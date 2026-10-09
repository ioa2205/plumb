"""Bounded Next.js boundary questions; uncertain helper policies stay visible."""

import hashlib
import json
import random
from dataclasses import replace

from pydantic import Field

from agent.challenge import CHECKLISTS
from agent.evidence import Cut, EvidencePacket
from agent.guard_syntax import checks
from agent.guards import Ask, Classifier, Summary
from agent.llm import Spend
from agent.questions import (
    ClientExposure,
    ExceptionReason,
    GuardSummary,
    IntentionalException,
    client_exposure,
    guard_summary,
    intentional_exception,
)
from agent.ts_paths import bind_authentication, bind_query_guard
from agent.validator import check_answer
from analysis.access import AccessMap, AccessPath
from analysis.index import Index
from analysis.nextjs import NextJSMap, SerializedField
from analysis.platform_calls import non_authorizing
from analysis.resolution import CallGraph
from analysis.serialization import crossings, exposed, minimized
from analysis.snapshot import SnapshotStore
from analysis.syntax import code_only, span_sha256
from backend.contracts.code import (
    EntryPointKind,
    Guard,
    GuardKind,
    GuardMechanism,
    ProjectSnapshot,
    SourceSpan,
    SymbolKind,
)
from backend.contracts.common import Contract, Family
from backend.contracts.investigation import (
    ChallengeCheck,
    Conclusion,
    EvidenceStrength,
    Exhibit,
    ExhibitRole,
    Finding,
    Severity,
)
from backend.contracts.policies import BoundPolicy, FrozenPolicies


class BoundarySample(Contract):
    seed: int
    answer: ClientExposure | GuardSummary | IntentionalException
    violations: list[str] = Field(default_factory=list)


class BoundaryResult(Contract):
    entry_id: str
    conclusion: Conclusion
    rationale: str
    samples: list[BoundarySample]
    guards: list[Guard]
    issues: list[str]
    policies: list[BoundPolicy] = Field(default=[])
    field_flows: list[SerializedField] = Field(default=[])
    flow_unknowns: list[str] = Field(default=[])


class BoundaryInvestigator:
    def __init__(
        self,
        snapshot: ProjectSnapshot,
        store: SnapshotStore,
        index: Index,
        graph: CallGraph,
        nextjs: NextJSMap,
        classifier: Classifier,
        *,
        policies: FrozenPolicies | None = None,
        access: AccessMap | None = None,
    ) -> None:
        self.snapshot, self.store, self.graph, self.nextjs, self.classifier = (
            snapshot,
            store,
            graph,
            nextjs,
            classifier,
        )
        self.symbols = {
            s.id: s for s in (index.to_contract(r, snapshot.id) for r in index.symbols())
        }
        self.entries = {e.entry.id: e.entry for e in nextjs.entries}
        self.policies = policies or FrozenPolicies(snapshot_id=snapshot.id)
        if self.policies.snapshot_id != snapshot.id:
            raise ValueError("Boundary requirements belong to a different snapshot")
        self.paths = {p.site.id: p for p in access.accesses} if access else {}
        if access and access.snapshot_id != snapshot.id:
            raise ValueError("Boundary accesses belong to a different snapshot")
        for policy in self.policies.policies:
            for site in policy.sites:
                if site.entry_point_id in self.entries and (
                    site.id not in self.paths or self.paths[site.id].site != site
                ):
                    raise ValueError("Boundary policy does not match the current exact access")

    def cuts(self, entry_id: str) -> list[Cut]:
        entry = self.entries[entry_id]
        selected = [entry.handler_symbol_id]
        frontier = list(selected)
        for _ in range(2):
            frontier = list(
                dict.fromkeys(
                    e.target_id
                    for ident in frontier
                    for e in self.graph.calls(ident)
                    if e.target_id and e.target_id not in selected
                )
            )
            selected.extend(frontier)
        cuts = []
        for ident in selected:
            symbol = self.symbols[ident]
            if any(
                c.path == symbol.span.path
                and c.start <= symbol.span.start_line
                and c.end >= symbol.span.end_line
                for c in cuts
            ):
                continue
            cuts.append(
                Cut(
                    f"part {len(cuts) + 1}",
                    symbol.span.path,
                    symbol.language,
                    self.store.read(self.snapshot, symbol.span.path),
                    symbol.span.start_line,
                    symbol.span.end_line,
                )
            )
        # A resolved factory alone does not expose the predicate implementation.
        # Include every source fragment used by guard confirmation in the challenge
        # and in the exported exhibits, even when the call graph omits that method.
        handler = self.symbols[entry.handler_symbol_id]
        for candidate in checks(
            handler.language,
            cuts[0].source,
            handler.span.start_line,
            handler.span.end_line,
            path=handler.span.path,
            read=self.classifier.validator.source_if_present,
        ):
            for context in candidate.context:
                if any(
                    c.path == context.path and c.start <= context.start and c.end >= context.end
                    for c in cuts
                ):
                    continue
                cuts = [
                    c
                    for c in cuts
                    if not (
                        c.path == context.path and context.start <= c.start and context.end >= c.end
                    )
                ]
                cuts.append(context)
        for crossing in crossings(self.nextjs, entry.handler_symbol_id):
            for span in [
                crossing.span,
                *crossing.boundary_evidence,
                *[s for f in crossing.fields for s in [f.source, *f.evidence]],
            ]:
                if self.classifier.validator.evidence(span):
                    raise ValueError("Serialization citation cannot be validated")
                if any(
                    c.path == span.path and c.start <= span.start_line and c.end >= span.end_line
                    for c in cuts
                ):
                    continue
                language = next(f.language for f in self.snapshot.files if f.path == span.path)
                if language is None:
                    raise ValueError("Serialization language unavailable")
                cuts.append(
                    Cut(
                        f"part {len(cuts) + 1}",
                        span.path,
                        language,
                        self.store.read(self.snapshot, span.path),
                        span.start_line,
                        span.end_line,
                    )
                )
        return [replace(c, label=f"part {n + 1}") for n, c in enumerate(cuts)]

    def field_cuts(self, entry_id: str, path: AccessPath, names: list[str]) -> list[Cut]:
        """Complete source chains without source-derived answers or unrelated guard helpers."""
        if self.paths.get(path.site.id) != path or path.site.entry_point_id != entry_id:
            raise ValueError("Field focus does not match the current exact access")
        full = self.cuts(entry_id)
        entry = self.entries[entry_id]
        flows = crossings(self.nextjs, entry.handler_symbol_id)
        if (
            not names
            or not flows
            or any(c.unknowns for c in flows)
            or self.policies.conflicts(path.site)
        ):
            return full
        fields = [f for c in flows for f in c.fields]
        chosen = [f for f in fields if f.field in names] or fields
        required = {path.owner_symbol_id, *(f.source_owner_symbol_id for f in chosen)}
        if not required.issubset(self.symbols):
            raise ValueError("Field source callable is outside the frozen index")
        reachable = {entry.handler_symbol_id}
        frontier = set(reachable)
        for _ in range(6):
            frontier = {
                e.target_id
                for ident in frontier
                for e in self.graph.calls(ident)
                if e.kind == "call" and e.target_id is not None and e.target_id in self.symbols
            } - reachable
            reachable.update(frontier)
            if len(reachable) > 64:
                return full
            if not frontier:
                break
        if not required.issubset(reachable):
            return full  # indirect callbacks/unknown links retain their whole context
        selected = set(required)
        for _ in range(6):
            parents = {
                e.caller_id
                for e in self.graph.edges
                if e.kind == "call" and e.target_id in selected and e.caller_id in reachable
            } - selected
            selected.update(parents)
            if not parents:
                break
        if entry.handler_symbol_id not in selected:
            return full
        # A projection's return line alone omits its parameter binding. Preserve
        # the smallest indexed callable containing every source-flow fragment.
        for field in chosen:
            for fragment in field.evidence:
                owners = [
                    s
                    for s in self.symbols.values()
                    if s.kind in {SymbolKind.FUNCTION, SymbolKind.COMPONENT}
                    and s.span.path == fragment.path
                    and s.span.start_line <= fragment.start_line
                    and s.span.end_line >= fragment.end_line
                ]
                if owners:
                    selected.add(min(owners, key=lambda s: s.span.end_line - s.span.start_line).id)
        spans = [
            path.site.span,
            *(self.symbols[ident].span for ident in selected),
            *(c.span for c in flows),
            *(s for c in flows for s in c.boundary_evidence),
            *(s for f in chosen for s in [f.source, *f.evidence]),
        ]
        ranges: dict[str, list[tuple[int, int]]] = {}
        for span in spans:
            if self.classifier.validator.evidence(span):
                raise ValueError("Focused field citation cannot be validated")
            ranges.setdefault(span.path, []).append((span.start_line, span.end_line))
        cuts: list[Cut] = []
        for filename in sorted(ranges):
            merged: list[tuple[int, int]] = []
            for start, end in sorted(ranges[filename]):
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            language = next(f.language for f in self.snapshot.files if f.path == filename)
            if language is None:
                raise ValueError("Focused field language unavailable")
            for start, end in merged:
                cuts.append(
                    Cut(
                        f"part {len(cuts) + 1}",
                        filename,
                        language,
                        self.store.read(self.snapshot, filename),
                        start,
                        end,
                    )
                )
        EvidencePacket.build(*cuts)  # unchanged source budget, never truncate
        return cuts

    def investigate(
        self, entry_id: str, model: Ask, spend: Spend, *, judgments: int = 3
    ) -> BoundaryResult:
        if isinstance(judgments, bool) or judgments not in (1, 3):
            raise ValueError("Only production three or experimental one judgment is supported")
        applicable = [
            p for p in self.policies.policies if any(s.entry_point_id == entry_id for s in p.sites)
        ]
        if applicable:
            return self._policy_investigate(entry_id, applicable, model, spend, judgments=judgments)
        entry = self.entries[entry_id]
        cuts = self.cuts(entry_id)
        # Refuse an oversized packet instead of silently hiding helper code.
        EvidencePacket.build(*cuts)
        page = entry.kind is EntryPointKind.PAGE
        symbol = self.symbols[entry.handler_symbol_id]
        candidates = checks(
            symbol.language,
            cuts[0].source,
            symbol.span.start_line,
            symbol.span.end_line,
            path=symbol.span.path,
            read=self.classifier.validator.source_if_present,
        )
        guards = self.classifier.classify(symbol, spend).guards if candidates and not page else []
        role = next((g for g in guards if g.kind is GuardKind.ROLE and g.role == "admin"), None)
        helper_checks = any(
            checks(
                c.language,
                c.source,
                c.start,
                c.end,
                path=c.path,
                read=self.classifier.validator.source_if_present,
            )
            for c in cuts[1:]
        )
        issues = (
            ["Helper authorization has not been proven to apply to this exact resource binding"]
            if helper_checks and role is None and not page
            else []
        )
        applicable = [
            p for p in self.policies.policies if any(s.entry_point_id == entry_id for s in p.sites)
        ]
        # Step 05 establishes field/output flow and exact boundary guard bindings.
        # Carry requirements now, retaining the concrete missing validation gate.
        if applicable:
            issues.append(
                "Declared boundary requirements need exact guard/serialization flow validation"
            )
        samples = []
        for number in range(judgments):
            order = list(cuts)
            random.Random(42 + number).shuffle(order)  # noqa: S311 - reproducible order
            packet = EvidencePacket.build(*order)
            if page:
                prompt = client_exposure(packet)
            elif role:
                candidate = next(
                    c
                    for c in candidates
                    if c.start == role.span.start_line and c.end == role.span.end_line
                )
                focus = next(
                    line
                    for line in packet.line_ids
                    if packet.location(line)[0] == role.span.path
                    and packet.location(line)[1] == candidate.focus
                )
                prompt = guard_summary(packet, at=focus, subjects=(), objects=())
            else:
                prompt = intentional_exception(packet, missing=GuardKind.ROLE, resource="data")
            answer = prompt.parse(model.ask(prompt.request(seed=42 + number), spend).data)
            if not isinstance(answer, ClientExposure | GuardSummary | IntentionalException):
                raise TypeError("boundary answer required")
            errors = [v.message for v in check_answer(prompt, answer)]
            if isinstance(answer, GuardSummary):
                if len(answer.guards) != 1 or answer.guards[0].kind is not GuardKind.ROLE:
                    errors.append("judgment does not confirm the source-bound admin guard")
                elif role is not None:
                    ids = answer.guards[0].line_ids
                    matching = [
                        line
                        for line in ids
                        if line in packet.line_ids
                        and packet.location(line)[0] == role.span.path
                        and role.span.start_line <= packet.location(line)[1] <= role.span.end_line
                    ]
                    code = "\n".join(packet.line(line).text for line in matching)
                    if '"admin"' not in code and "'admin'" not in code:
                        errors.append("judgment does not cite the actual admin condition")
            elif (
                isinstance(answer, IntentionalException)
                and answer.reason is not ExceptionReason.NONE_FOUND
            ):
                errors.append("an equivalent path-bound policy was not confirmed")
            samples.append(BoundarySample(seed=42 + number, answer=answer, violations=errors))
        issues.extend(dict.fromkeys(error for sample in samples for error in sample.violations))
        if page:
            conclusion = Conclusion.INCONCLUSIVE
            issues.append(
                "Field sensitivity alone does not prove excess disclosure; "
                "DTO intent and complete serialization flow need validation"
            )
        elif (
            issues
            or any(s.violations for s in samples)
            or (
                len({s.answer.model_dump_json() for s in samples}) > 1
                and not all(isinstance(s.answer, GuardSummary) for s in samples)
            )
        ):
            conclusion = Conclusion.INCONCLUSIVE
        elif role:
            conclusion = Conclusion.REJECTED
        else:
            code = (
                code_only(symbol.language, cuts[0].source)
                .decode()
                .splitlines()[symbol.span.start_line - 1 : symbol.span.end_line]
            )
            # Only concrete database operations or writes in the callable itself establish a lead.
            import re

            operation = bool(re.search(r"\b(?:SELECT|UPDATE|DELETE|INSERT)\b", "\n".join(code)))
            conclusion = Conclusion.INCONCLUSIVE
            issues.append(
                "A database operation alone does not establish its required authorization policy"
                if operation
                else "No concrete sensitive operation established in the callable"
            )
        return BoundaryResult(
            entry_id=entry_id,
            conclusion=conclusion,
            rationale="Source-bound boundary judgment; "
            "optimistic proxies do not authorize this callable",
            samples=samples,
            guards=guards,
            issues=issues,
            policies=applicable,
        )

    def _policy_investigate(
        self,
        entry_id: str,
        policies: list[BoundPolicy],
        model: Ask,
        spend: Spend,
        *,
        judgments: int = 3,
    ) -> BoundaryResult:
        entry = self.entries[entry_id]
        cuts = self.cuts(entry_id)
        EvidencePacket.build(*cuts)
        samples: list[BoundarySample] = []
        guards: list[Guard] = []
        issues: list[str] = []
        outcomes: list[Conclusion] = []
        boundary_flows = crossings(self.nextjs, entry.handler_symbol_id)
        unknowns = list(dict.fromkeys(s for c in boundary_flows for s in c.unknowns))
        summaries: dict[tuple[str, str, GuardKind], Summary] = {}

        def summary(identity: str, resource: str, required_kind: GuardKind) -> Summary:
            key = (identity, resource, required_kind)
            if key not in summaries:
                summaries[key] = self.classifier.classify(
                    self.symbols[identity], spend, resource=resource, required_kind=required_kind
                )
            return summaries[key]

        def authentication_summary(identity: str, resource: str) -> Summary:
            # Both path binders inspect the returned null-checked principal separately
            # from the local owner/tenant/role predicate they are binding.
            return summary(identity, resource, GuardKind.AUTHENTICATED)

        for site_id in sorted(
            {s.id for p in policies for s in p.sites if s.entry_point_id == entry_id}
        ):
            path = self.paths[site_id]
            conflicts = self.policies.conflicts(path.site)
            issues.extend(conflicts)
            for policy in self.policies.for_site(path.site):
                required = policy.assertion.kind
                names = policy.forbidden_fields
                tasks = (
                    ["guard"] if required not in {GuardKind.NONE, GuardKind.UNKNOWN} else []
                ) + (["fields"] if names else [])
                for task in tasks:
                    relevant = []
                    local_issues = list(conflicts)
                    if task == "guard":
                        if path.status.value == "unresolved":
                            local_issues.append("Exact caller/resource access path is unresolved")
                        local = summary(path.owner_symbol_id, path.site.resource, required)
                        local_issues.extend(local.issues)
                        owner = self.symbols[path.owner_symbol_id]
                        recognized = checks(
                            owner.language,
                            self.store.read(self.snapshot, owner.span.path),
                            owner.span.start_line,
                            owner.span.end_line,
                            path=owner.span.path,
                            read=self.classifier.validator.source_if_present,
                        )
                        if any(
                            e.target_id is None
                            and e.reference_line < path.site.span.start_line
                            and not non_authorizing(e, self.graph, self.snapshot, self.store)
                            and not any(c.start <= e.reference_line <= c.end for c in recognized)
                            for e in self.graph.calls(owner.id)
                        ):
                            local_issues.append(
                                "An unresolved pre-access helper could enforce authorization"
                            )
                        for guard in local.guards:
                            if (
                                guard.kind is required
                                and (
                                    policy.required_role is None
                                    or guard.role == policy.required_role
                                )
                                and bind_query_guard(
                                    path,
                                    guard,
                                    self.classifier,
                                    self.symbols,
                                    self.graph,
                                    authentication_summary,
                                )
                            ):
                                relevant.append(guard)
                        if required is GuardKind.AUTHENTICATED:
                            bound_auth = bind_authentication(
                                path,
                                self.classifier,
                                self.symbols,
                                self.graph,
                                authentication_summary,
                            )
                            if bound_auth:
                                relevant.append(bound_auth[0])
                            elif any(
                                checks(
                                    c.language,
                                    c.source,
                                    c.start,
                                    c.end,
                                    path=c.path,
                                    read=self.classifier.validator.source_if_present,
                                )
                                for c in cuts[1:]
                            ):
                                local_issues.append(
                                    "Shown authentication helper has no proven "
                                    "awaited access binding"
                                )
                        if (
                            any(
                                g.kind is required
                                and (policy.required_role is None or g.role == policy.required_role)
                                for g in local.guards
                            )
                            and not relevant
                        ):
                            local_issues.append(
                                "Shown guard has no proven binding to this exact access"
                            )
                    witnesses = (
                        exposed(
                            self.nextjs,
                            entry.handler_symbol_id,
                            path.owner_symbol_id,
                            path.site.span,
                            names,
                        )
                        if task == "fields"
                        else []
                    )
                    omitted = task == "fields" and minimized(
                        self.nextjs,
                        entry.handler_symbol_id,
                        path.owner_symbol_id,
                        path.site.span,
                        names,
                    )
                    batch = []
                    task_cuts = self.field_cuts(entry_id, path, names) if task == "fields" else cuts
                    for number in range(judgments):
                        order = list(task_cuts)
                        random.Random(42 + number).shuffle(order)  # noqa: S311
                        packet = EvidencePacket.build(*order)
                        if task == "fields":
                            focus = next(
                                line
                                for line in packet.line_ids
                                if packet.location(line)
                                == (path.site.span.path, path.site.span.start_line)
                            )
                            prompt = client_exposure(
                                packet, fields=tuple(names), at=focus, resource=path.site.resource
                            )
                        elif relevant:
                            guard = relevant[0]
                            focus = next(
                                line
                                for line in packet.line_ids
                                if packet.location(line)[0] == guard.span.path
                                and guard.span.start_line
                                <= packet.location(line)[1]
                                <= guard.span.end_line
                            )
                            prompt = guard_summary(
                                packet,
                                at=focus,
                                kinds=(required,),
                                subjects=(guard.subject,) if guard.subject else (),
                                objects=(guard.object,) if guard.object else (),
                            )
                        else:
                            prompt = intentional_exception(
                                packet, missing=required, resource=path.site.resource
                            )
                        request = replace(
                            prompt.request(seed=42 + number),
                            user=prompt.user
                            + "\nHuman-declared requirement (not guard evidence): "
                            + json.dumps(policy.assertion.statement, ensure_ascii=True),
                        )
                        if policy.required_role is not None:
                            request = replace(
                                request,
                                user=request.user
                                + "\nQualified required role (not guard evidence): "
                                + json.dumps(policy.required_role, ensure_ascii=True),
                            )
                        answer = prompt.parse(model.ask(request, spend).data)
                        if not isinstance(
                            answer, ClientExposure | GuardSummary | IntentionalException
                        ):
                            raise TypeError("boundary answer required")
                        errors = [v.message for v in check_answer(prompt, answer)]
                        if isinstance(answer, ClientExposure):
                            expected = {name for _, _, name in witnesses}
                            if {f.name for f in answer.fields} != expected:
                                errors.append(
                                    "Judgment disagrees with exact source-field crossing facts"
                                )
                            for item in answer.fields:
                                eligible = [(c, f) for c, f, name in witnesses if name == item.name]
                                cited = [
                                    packet.location(line)
                                    for line in item.line_ids
                                    if line in packet.line_ids
                                ]
                                if not any(
                                    any(
                                        p == c.span.path
                                        and c.span.start_line <= n <= c.span.end_line
                                        for p, n in cited
                                    )
                                    and any(
                                        p == s.path and s.start_line <= n <= s.end_line
                                        for p, n in cited
                                        for s in f.evidence
                                    )
                                    for c, f in eligible
                                ):
                                    errors.append(
                                        "Field judgment does not cite its exact "
                                        "client/response crossing"
                                    )
                        elif isinstance(answer, GuardSummary):
                            if len(answer.guards) != 1 or answer.guards[0].kind is not required:
                                errors.append("Judgment does not confirm the required guard kind")
                            elif not any(
                                any(
                                    packet.location(line)[0] == g.span.path
                                    and g.span.start_line
                                    <= packet.location(line)[1]
                                    <= g.span.end_line
                                    for line in answer.guards[0].line_ids
                                    if line in packet.line_ids
                                )
                                for g in relevant
                            ):
                                errors.append(
                                    "Guard judgment does not cite the exact confirmed predicate"
                                )
                        elif answer.reason is not ExceptionReason.NONE_FOUND:
                            errors.append("No equivalent exact-access guard was source-confirmed")
                        sample = BoundarySample(seed=42 + number, answer=answer, violations=errors)
                        batch.append(sample)
                        samples.append(sample)
                    if local_issues or any(s.violations for s in batch):
                        outcomes.append(Conclusion.INCONCLUSIVE)
                    elif task == "guard":
                        outcomes.append(Conclusion.REJECTED if relevant else Conclusion.SUPPORTED)
                        guards.extend(relevant)
                    elif witnesses:
                        outcomes.append(Conclusion.SUPPORTED)
                    elif omitted:
                        guard = Guard(
                            id="guard:minimized:"
                            + hashlib.sha256(f"{site_id}:{names}".encode()).hexdigest()[:20],
                            snapshot_id=self.snapshot.id,
                            kind=GuardKind.MINIMIZED,
                            canonical=f"MINIMIZED({path.site.resource}: {', '.join(names)})",
                            mechanism=GuardMechanism.DATA_ACCESS_LAYER,
                            via_symbol_id=entry.handler_symbol_id,
                            object=path.owner_symbol_id,
                            role=json.dumps(names),
                            span=path.site.span,
                        )
                        guards.append(self.classifier.validator.confirm(guard))
                        outcomes.append(Conclusion.REJECTED)
                    else:
                        outcomes.append(Conclusion.INCONCLUSIVE)
                        local_issues.extend(
                            unknowns
                            or ["Complete source-field serialization/omission was not established"]
                        )
                    issues.extend(local_issues)
        issues.extend(v for sample in samples for v in sample.violations)
        conclusion = (
            Conclusion.INCONCLUSIVE
            if not outcomes or Conclusion.INCONCLUSIVE in outcomes
            else Conclusion.SUPPORTED
            if Conclusion.SUPPORTED in outcomes
            else Conclusion.REJECTED
        )
        return BoundaryResult(
            entry_id=entry_id,
            conclusion=conclusion,
            rationale="Exact declared access/minimization requirements checked against "
            "source-bound guards and crossings; proxy routing does not authorize "
            "the callable",
            samples=samples,
            guards=list({g.id: g for g in guards}.values()),
            issues=list(dict.fromkeys(issues)),
            policies=policies,
            field_flows=[f for c in boundary_flows for f in c.fields],
            flow_unknowns=unknowns,
        )


def finding(
    result: BoundaryResult, investigator: BoundaryInvestigator, *, run_id: str, display_id: str
) -> Finding:
    cuts = investigator.cuts(result.entry_id)
    exhibits = [
        Exhibit(
            tag=f"E{i:02d}",
            span=SourceSpan(
                snapshot_id=investigator.snapshot.id,
                path=c.path,
                start_line=c.start,
                end_line=c.end,
                content_sha256=span_sha256(c.source, c.start, c.end),
            ),
            role=ExhibitRole.SINK,
            gloss="Callable or resolved helper searched for boundary protection",
        )
        for i, c in enumerate(cuts, 1)
    ]
    for g in result.guards:
        exhibits.append(
            Exhibit(
                tag=f"E{len(exhibits) + 1:02d}",
                span=g.span,
                role=ExhibitRole.GUARD,
                gloss=g.canonical,
            )
        )
    for flow in result.field_flows:
        exhibits.append(
            Exhibit(
                tag=f"E{len(exhibits) + 1:02d}",
                span=flow.source,
                role=ExhibitRole.EVIDENCE,
                gloss=f"Source field {flow.source_resource + '.' if flow.source_resource else ''}"
                f"{flow.field} crosses as output {flow.output}",
            )
        )
    guard_tags = {
        g.kind: next(e.tag for e in exhibits if e.role is ExhibitRole.GUARD and e.span == g.span)
        for g in result.guards
    }
    return Finding(
        id="finding:" + hashlib.sha256(f"{run_id}:{result.entry_id}".encode()).hexdigest()[:24],
        display_id=display_id,
        run_id=run_id,
        snapshot_id=investigator.snapshot.id,
        family=Family.NEXTJS_EXPOSURE,
        cwe=[200] if any(p.forbidden_fields for p in result.policies) else [862],
        title="Next.js callable boundary",
        lede=result.rationale,
        conclusion=result.conclusion,
        severity=Severity.UNKNOWN,
        severity_rationale="Required policy and impact are not fully established",
        strength=EvidenceStrength.PARTIAL,
        gaps=["Bounded helper flow; runtime verification not attempted", *result.issues],
        exhibits=exhibits,
        checks=[
            ChallengeCheck(
                item=item,
                searched="; ".join(f"{c.path}:{c.start}-{c.end}" for c in cuts),
                found=bool(guard_tags)
                and (
                    (i == 0 and GuardKind.MINIMIZED in guard_tags)
                    or (i == 1 and any(k is not GuardKind.MINIMIZED for k in guard_tags))
                ),
                exhibit_tag=guard_tags.get(GuardKind.MINIMIZED)
                if i == 0
                else next(
                    (tag for kind, tag in guard_tags.items() if kind is not GuardKind.MINIMIZED),
                    None,
                )
                if i == 1
                else None,
            )
            for i, item in enumerate(CHECKLISTS[Family.NEXTJS_EXPOSURE])
        ],
        policy_basis=result.policies,
        unknowns=result.flow_unknowns,
    )
