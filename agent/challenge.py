"""Cited acquittal search and three independent judgments (PROJECT_PLAN §3.3)."""

import hashlib
import json
import random
from dataclasses import replace
from typing import Literal

from pydantic import Field

from agent.evidence import Cut, EvidencePacket
from agent.guards import Ask
from agent.llm import Spend
from agent.peers import PeerCheck, _dependencies
from agent.questions import (
    ExceptionReason,
    GuardSummary,
    IntentionalException,
    guard_summary,
    intentional_exception,
)
from agent.validator import Unconfirmed, check_answer, mentions
from analysis.access import REQUEST_ORIGINS, AccessMap
from analysis.fastapi import extract_fastapi
from backend.contracts.code import Guard, GuardKind, GuardMechanism, SourceSpan
from backend.contracts.common import Contract, Family
from backend.contracts.investigation import (
    ChallengeCheck,
    Conclusion,
    EvidenceStrength,
    Exhibit,
    ExhibitRole,
    Finding,
    QuestionType,
    Severity,
)
from backend.contracts.policies import BoundPolicy, FrozenPolicies

CHECKLISTS: dict[Family, tuple[str, ...]] = {
    Family.AUTHORIZATION: (
        "A query filter scoped to the principal",
        "An equivalent guard in the handler, router, dependency or DAL",
        "An admin-only entry point",
        "A resource public by executable policy",
        "An unreachable route",
    ),
    Family.INJECTION: (
        "Bound SQL parameters or a closed allowlist",
        "An argument array with shell execution disabled",
        "A request-independent sink value",
    ),
    Family.PATH_TRAVERSAL: (
        "Canonical path resolution followed by containment",
        "A closed allowlist of filenames",
        "A request-independent path",
    ),
    Family.NEXTJS_EXPOSURE: (
        "A minimal DTO excluding sensitive fields",
        "Authorization in the server entry or DAL",
        "The value remains server-side and is not serialized",
    ),
}


class Search(Contract):
    item: str
    status: Literal["found", "not_found", "unsupported"]
    searched: list[SourceSpan]
    guard_ids: list[str] = Field(default_factory=list)
    note: str


class Sample(Contract):
    seed: int
    evidence_order: list[str]
    question_type: QuestionType = QuestionType.INTENTIONAL_EXCEPTION
    answer: IntentionalException | GuardSummary
    interpretation: ExceptionReason
    violations: list[str] = Field(default_factory=list)


class ChallengeResult(Contract):
    snapshot_id: str
    site_id: str
    resource: str
    missing: GuardKind
    conclusion: Conclusion
    rationale: str
    searches: list[Search]
    samples: list[Sample]
    guards: list[Guard]
    evidence: list[SourceSpan]
    issues: list[str]
    peer_group_id: str | None
    policies: list[BoundPolicy] = Field(default=[])


class AuthorizationChallenge:
    """Facts are rebuilt from the snapshot; callers cannot supply an exemption."""

    def __init__(
        self,
        peers: PeerCheck,
        access: AccessMap,
        model: Ask,
        *,
        policies: FrozenPolicies | None = None,
    ) -> None:
        self.peers, self.access, self.model = peers, access, model
        self.result = peers.build(access)
        self.facts = {f.site_id: f for f in self.result.checks}
        self.paths = {p.site.id: p for p in access.accesses}
        self.policies = policies or FrozenPolicies(snapshot_id=peers.snapshot.id)
        if self.policies.snapshot_id != peers.snapshot.id:
            raise ValueError("Policy requirements belong to a different snapshot")
        for policy in self.policies.policies:
            for site in policy.sites:
                if self.paths.get(site.id) is not None and self.paths[site.id].site != site:
                    raise ValueError("Policy access identity differs from source")
        self.routes = {
            r.entry.id: r for r in extract_fastapi(peers.snapshot, peers.store, peers.index).routes
        }

    def _cuts(self, site_id: str) -> list[Cut]:
        path = self.paths[site_id]
        route = self.routes[path.site.entry_point_id]
        symbols = list(dict.fromkeys([route.entry.handler_symbol_id, *path.via_symbol_ids]))
        symbols.extend(
            dep.target_symbol_id
            for dep in _dependencies(route.dependencies)
            if dep.target_symbol_id and dep.auth_signals
        )
        # Actual direct helper bodies, including serializers, are searched as counterevidence.
        for symbol_id in list(symbols):
            symbols.extend(e.target_id for e in self.peers.graph.calls(symbol_id) if e.target_id)
        spans = [self.peers.symbols[i].span for i in dict.fromkeys(symbols)]
        spans.extend(self.facts[site_id].evidence)
        unique = []
        for span in spans:
            if any(
                s.path == span.path
                and s.start_line <= span.start_line
                and s.end_line >= span.end_line
                for s in unique
            ):
                continue
            unique.append(span)
        cuts = []
        for n, span in enumerate(unique):
            if errors := self.peers.classifier.validator.evidence(span):
                raise Unconfirmed(errors)
            language = next(f.language for f in self.peers.snapshot.files if f.path == span.path)
            if language is None:
                raise ValueError("evidence language is unsupported")
            cuts.append(
                Cut(
                    f"part {n + 1}",
                    span.path,
                    language,
                    self.peers.store.read(self.peers.snapshot, span.path),
                    span.start_line,
                    span.end_line,
                )
            )
        return cuts

    def investigate(
        self,
        site_id: str,
        spend: Spend,
        *,
        missing: GuardKind = GuardKind.OWNER,
        judgments: int = 3,
    ) -> ChallengeResult:
        if isinstance(judgments, bool) or judgments not in (1, 3):
            raise ValueError("Only production three or experimental one judgment is supported")
        path, fact = self.paths[site_id], self.facts[site_id]
        applicable = self.policies.for_site(path.site)
        required = [p for p in applicable if p.assertion.kind is missing]
        required_roles = {p.required_role for p in required if p.required_role is not None}
        conflicts = self.policies.conflicts(path.site)
        if path.site.entry_point_id not in self.routes:
            raise ValueError("authorization challenge currently supports FastAPI paths only")
        cuts = self._cuts(site_id)
        # Enforce the packet budget before issuing any request; no hidden truncation.
        packet = EvidencePacket.build(*cuts)
        spans = [
            SourceSpan(
                snapshot_id=self.peers.snapshot.id,
                path=c.path,
                start_line=c.start,
                end_line=c.end,
                content_sha256=self._hash(c),
            )
            for c in cuts
        ]
        relevant = [
            g
            for g in fact.guards
            if g.kind is missing
            or (missing is GuardKind.OWNER and g.kind is GuardKind.TENANT and fact.exclusion)
        ]
        if required_roles:

            def matches_required_role(guard: Guard) -> bool:
                dependencies = [
                    dep
                    for dep in _dependencies(self.routes[path.site.entry_point_id].dependencies)
                    if dep.target_symbol_id == guard.via_symbol_id
                ]
                if dependencies:
                    bindings = [self.peers._binding(dep, guard) for dep in dependencies]
                    return all(
                        bound is not None and set(bound[0]) == required_roles for bound in bindings
                    )
                return all(guard.role == role for role in required_roles)

            relevant = [g for g in relevant if matches_required_role(g)]
        validator = self.peers.classifier.validator
        for guard in fact.guards:
            validator.confirm(guard, subject=guard.subject, object=guard.object)
        admin = bool(fact.exclusion and fact.exclusion.startswith("Admin-only"))
        if required_roles:
            admin = admin and any(g.kind is GuardKind.ROLE for g in relevant)
        searches = []
        for index, item in enumerate(CHECKLISTS[Family.AUTHORIZATION]):
            found = (
                [
                    g
                    for g in relevant
                    if (g.mechanism is GuardMechanism.QUERY_FILTER) == (index == 0)
                ]
                if index in (0, 1)
                else [g for g in fact.guards if g.kind is GuardKind.ROLE]
                if index == 2 and admin
                else []
            )
            searches.append(
                Search(
                    item=item,
                    status="found" if found else "unsupported" if index == 4 else "not_found",
                    searched=spans,
                    guard_ids=[g.id for g in found],
                    note="Executable protection found on this access path"
                    if found
                    else "Runtime reachability is not established by static mounting"
                    if index == 4
                    else "Not found in the cited code searched; this is bounded negative evidence",
                )
            )
        samples = []
        for number in range(judgments):
            shuffled = list(cuts)
            random.Random(42 + number).shuffle(shuffled)  # noqa: S311 - repeatable evidence order
            packet = EvidencePacket.build(*shuffled)
            prompt = intentional_exception(packet, missing=missing, resource=path.site.resource)
            # A known predicate needs a narrow classification, not a second cross-function
            # inference. Its path applicability was established independently from source.
            focused = relevant[0] if relevant else None
            if focused is not None:
                fields = tuple(f for f in (focused.subject, focused.object) if f is not None)
                ids = [
                    line
                    for line in packet.line_ids
                    if packet.location(line)[0] == focused.span.path
                    and focused.span.start_line <= packet.location(line)[1] <= focused.span.end_line
                ]
                at = next(
                    (
                        line
                        for line in ids
                        if all(mentions(packet.line(line).text, f) for f in fields)
                    ),
                    ids[0],
                )
                prompt = guard_summary(
                    packet,
                    at=at,
                    fields=fields or None,
                    subjects=(focused.subject,) if focused.subject else (),
                    objects=(focused.object,) if focused.object else (),
                    kinds=(GuardKind.ROLE, GuardKind.NONE, GuardKind.UNKNOWN)
                    if required_roles
                    else None,
                )
            request = prompt.request(seed=42 + number)
            if required:
                request = replace(
                    request,
                    user=request.user
                    + f"\nHuman requirement: this exact access requires {missing.value}. "
                    "This requirement supplies no evidence that a guard exists. Cite code only.",
                )
                if required_roles:
                    request = replace(
                        request,
                        user=request.user
                        + "\nQualified required roles: "
                        + json.dumps(sorted(required_roles)),
                    )
            answer = prompt.parse(self.model.ask(request, spend).data)
            errors = [v.message for v in check_answer(prompt, answer)]
            if isinstance(answer, GuardSummary) and focused is not None:
                matches = [
                    g
                    for g in answer.guards
                    if g.kind is focused.kind
                    and g.subject == focused.subject
                    and g.object == focused.object
                    and self._cites_guard(
                        packet,
                        IntentionalException(
                            reason=ExceptionReason.SCOPED_ELSEWHERE, line_ids=g.line_ids
                        ),
                        focused,
                    )
                ]
                reason = (
                    ExceptionReason.SCOPED_ELSEWHERE
                    if len(matches) == len(answer.guards) == 1
                    else ExceptionReason.NONE_FOUND
                )
                if len(matches) != 1 or len(answer.guards) != 1:
                    errors.append("predicate judgment does not confirm the applicable guard")
            elif isinstance(answer, IntentionalException):
                reason = answer.reason
            else:
                raise TypeError("challenge answer required")
            if isinstance(answer, GuardSummary):
                pass
            elif answer.reason is ExceptionReason.SCOPED_ELSEWHERE:
                if not any(self._cites_guard(packet, answer, g) for g in relevant):
                    errors.append(
                        "scoped-elsewhere answer lacks a cited, applicable confirmed guard"
                    )
            elif answer.reason is ExceptionReason.ADMIN_ONLY:
                roles = [g for g in fact.guards if g.kind is GuardKind.ROLE]
                code = "\n".join(
                    packet.line(line).text for line in answer.line_ids if line in packet.line_ids
                )
                if (
                    not admin
                    or not any(self._cites_guard(packet, answer, g) for g in roles)
                    or not ('"admin"' in code or "'admin'" in code)
                ):
                    errors.append("admin exception lacks the actual role check and literal binding")
            elif answer.reason is ExceptionReason.PUBLIC_RESOURCE:
                errors.append("public policy was not established by an executable guard")
            elif relevant or admin:
                errors.append("none-found answer contradicts confirmed protection on this path")
            samples.append(
                Sample(
                    seed=42 + number,
                    evidence_order=[c.label for c in shuffled],
                    question_type=prompt.type,
                    answer=answer,
                    interpretation=reason,
                    violations=errors,
                )
            )
        reasons = {s.interpretation for s in samples}
        issues = [*fact.issues, *conflicts]
        group = next((g for g in self.result.groups if site_id in g.site_ids), None)
        lead = bool(
            group
            and any(d.site_id == site_id and d.missing == missing.value for d in group.deviations)
        )
        if conflicts:
            conclusion, rationale = (
                Conclusion.INCONCLUSIVE,
                "Conflicting requirements need reviewer action",
            )
        elif len(reasons) != 1 or any(s.violations for s in samples):
            conclusion, rationale = (
                Conclusion.INCONCLUSIVE,
                "Independent judgments disagree or lack valid counterevidence",
            )
        elif next(iter(reasons)) is not ExceptionReason.NONE_FOUND:
            conclusion, rationale = (
                Conclusion.REJECTED,
                ("Three judgments" if judgments == 3 else "One experimental judgment")
                + " cite executable protection on the access path",
            )
        elif issues or path.site.key_origin not in REQUEST_ORIGINS:
            conclusion, rationale = (
                Conclusion.INCONCLUSIVE,
                "Unresolved path or input provenance limits the absence search",
            )
        elif lead or required:
            conclusion, rationale = (
                Conclusion.SUPPORTED,
                ("Declared/confirmed requirement" if required else "Peer deviation")
                + (
                    " persists after three independent acquittal searches"
                    if judgments == 3
                    else " persists after one experimental acquittal search"
                ),
            )
        else:
            conclusion, rationale = (
                Conclusion.CANDIDATE,
                "No protection found; no peer rule establishes the missing policy",
            )
        return ChallengeResult(
            snapshot_id=self.peers.snapshot.id,
            site_id=site_id,
            resource=path.site.resource,
            missing=missing,
            conclusion=conclusion,
            rationale=rationale,
            searches=searches,
            samples=samples,
            guards=fact.guards,
            evidence=spans,
            issues=issues,
            peer_group_id=group.id if group else None,
            policies=applicable,
        )

    @staticmethod
    def _hash(cut: Cut) -> str:
        from analysis.syntax import span_sha256

        return span_sha256(cut.source, cut.start, cut.end)

    @staticmethod
    def _cites_guard(packet: EvidencePacket, answer: IntentionalException, guard: Guard) -> bool:
        locations = [packet.location(line) for line in answer.line_ids if line in packet.line_ids]
        code = "\n".join(
            packet.line(line).text for line in answer.line_ids if line in packet.line_ids
        )
        return any(
            path == guard.span.path and guard.span.start_line <= number <= guard.span.end_line
            for path, number in locations
        ) and all(
            mentions(code, field) for field in (guard.subject, guard.object) if field is not None
        )


def finding(result: ChallengeResult, *, run_id: str, display_id: str) -> Finding:
    """Build an exportable static case without claiming runtime verification."""
    guard_spans = {g.span.model_dump_json(): g for g in result.guards}
    spans = list(
        dict.fromkeys(
            s.model_dump_json() for s in [*result.evidence, *(g.span for g in result.guards)]
        )
    )
    exhibits = [
        Exhibit(
            tag=f"E{i + 1:02d}",
            span=SourceSpan.model_validate_json(encoded),
            role=ExhibitRole.GUARD if encoded in guard_spans else ExhibitRole.EVIDENCE,
            gloss="Executable guard"
            if encoded in guard_spans
            else "Code inspected during the acquittal search",
        )
        for i, encoded in enumerate(spans)
    ]
    tags = {e.span.model_dump_json(): e.tag for e in exhibits}
    by_id = {g.id: g for g in result.guards}
    checklist = [
        ChallengeCheck(
            item=s.item,
            searched="; ".join(f"{p.path}:{p.start_line}-{p.end_line}" for p in s.searched)
            + f" ({s.status}: {s.note})",
            found=s.status == "found",
            exhibit_tag=tags[by_id[s.guard_ids[0]].span.model_dump_json()] if s.guard_ids else None,
        )
        for s in result.searches
    ]
    return Finding(
        id="finding:"
        + hashlib.sha256(f"{run_id}:{result.site_id}:{result.missing}".encode()).hexdigest()[:24],
        display_id=display_id,
        run_id=run_id,
        snapshot_id=result.snapshot_id,
        family=Family.AUTHORIZATION,
        cwe=[639, 862],
        title=f"{result.resource} access: {result.missing.value} check",
        lede=result.rationale,
        conclusion=result.conclusion,
        severity=Severity.UNKNOWN,
        severity_rationale="Data sensitivity and impact remain unassessed",
        strength=EvidenceStrength.PARTIAL,
        gaps=["Bounded static analysis; runtime verification not attempted", *result.issues],
        exhibits=exhibits,
        checks=checklist,
        peer_group_id=result.peer_group_id,
        unknowns=[s.note for s in result.searches if s.status == "unsupported"],
        policy_basis=result.policies,
    )
