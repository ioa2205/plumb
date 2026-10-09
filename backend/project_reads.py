"""Project navigation from frozen maps and saved peer evidence. No target execution."""

import hashlib
import sqlite3
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from agent.validator import Validator
from analysis.snapshot import SnapshotStore
from backend.capabilities import table
from backend.case_reads import CaseMissing, CaseReads, bounded
from backend.contracts.application_map import ApplicationMap
from backend.contracts.code import (
    GuardKind,
    PolicyAssertion,
    PolicyStatus,
    ProjectSnapshot,
    SourceSpan,
    SymbolKind,
)
from backend.contracts.common import LinkStatus
from backend.contracts.policies import BoundPolicy, PolicyInput
from backend.contracts.project_view import (
    ProjectCitation,
    ProjectEdge,
    ProjectExcerpt,
    ProjectFlow,
    ProjectNode,
    ProjectPage,
    ProjectRule,
)
from backend.map_store import MapStore, MapUnavailable
from backend.policy_store import PolicyConflict, PolicyStore
from backend.redaction import Redactor
from backend.run_store import RunStore
from backend.settings import Settings


class ProjectUnavailable(ValueError):
    """Frozen project records cannot be validated. No private details reach the API."""


class ProjectMissing(ProjectUnavailable):
    """A map, snapshot or proposal was not recorded."""


def citation(span: SourceSpan) -> ProjectCitation:
    return ProjectCitation(
        id="cite:" + hashlib.sha256(span.model_dump_json().encode()).hexdigest(), span=span
    )


class ProjectReads:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runs = RunStore(settings.cache_dir / "runs.sqlite")
        self.maps = MapStore(settings.cache_dir / "application_maps.sqlite")
        self.policies = PolicyStore(settings.cache_dir / "policies.sqlite")
        self.cases = CaseReads(settings)
        self.redactor = Redactor.configured(settings)
        self.lock = RLock()

    def _context(self, run_id: str) -> tuple[ProjectSnapshot, ApplicationMap, SnapshotStore]:
        run = self.runs.run(run_id)
        if run is None:
            raise ProjectMissing("No recorded run.")
        graph = self.maps.load(run.snapshot_id)
        if graph is None:
            raise ProjectMissing("No application map was recorded for this snapshot.")
        store = SnapshotStore(self.settings.cache_dir / "snapshots")
        try:
            snapshot = store.load(run.snapshot_id)
        except FileNotFoundError:
            store = SnapshotStore(self.settings.cache_dir)
            snapshot = store.load(run.snapshot_id)
        validator = Validator(snapshot, store)
        files = {f.path: f for f in snapshot.files}
        for item in [
            *graph.entries,
            *graph.guards,
            *graph.access_sites,
            *graph.unknown_targets,
            *graph.links,
            *graph.symbols,
        ]:
            # Empty package modules have a synthetic line-1 span. Never publish that citation.
            if getattr(item, "kind", None) is SymbolKind.MODULE and files[item.span.path].size == 0:
                continue
            if validator.span(item.span):
                raise ProjectUnavailable("An application-map citation cannot be validated.")
        return snapshot, graph, store

    def _proposals(self, run_id: str) -> list[ProjectRule]:
        try:
            bundle = self.cases._bundle(run_id)
        except CaseMissing:
            return []  # live/legacy records need not have saved peer judgments
        proposals: dict[str, ProjectRule] = {}
        for peer in bundle.peer_comparisons:
            voters = [row for row in peer.rows if row.exclusion is None]
            observed: dict[str, dict[str, list[SourceSpan]]] = defaultdict(dict)
            forms: dict[str, set[str]] = defaultdict(set)
            for row in voters:
                for guard in row.guards:
                    forms[guard.kind.value].add(guard.canonical)
                    observed[guard.kind.value].setdefault(row.site.id, []).append(guard.span)
            for kind, sites in sorted(observed.items()):
                if len(sites) < max(3, peer.group.min_peers) or len(sites) / len(voters) < max(
                    0.75, peer.group.min_share
                ):
                    continue
                spans = {s.model_dump_json(): s for group in sites.values() for s in group}
                evidence = [spans[key] for key in sorted(spans)][:100]
                canonical = f"{kind.upper()}({peer.group.resource})"
                # The ID binds this observation to the run, snapshot, exact checks and voter set.
                identity = "|".join(
                    [
                        run_id,
                        peer.group.snapshot_id,
                        peer.group.resource,
                        kind,
                        canonical,
                        *sorted(forms[kind]),
                        *sorted(sites),
                        *sorted(row.site.id for row in voters),
                        *[span.model_dump_json() for span in evidence],
                        str(peer.group.min_peers),
                        str(peer.group.min_share),
                    ]
                )
                assertion = PolicyAssertion(
                    id="policy:" + hashlib.sha256(identity.encode()).hexdigest(),
                    statement=(
                        f"{peer.group.resource}: {kind} checks are observed at "
                        f"{len(sites)} of {len(voters)} eligible access sites. "
                        "Treat this as the expected access rule?"
                    ),
                    resource=peer.group.resource,
                    kind=kind,
                    canonical=canonical,
                    status=PolicyStatus.INFERRED,
                    author="Plumb · saved peer evidence",
                    created_at=bundle.run.finished_at or bundle.run.created_at,
                    evidence=evidence,
                )
                digest = hashlib.sha256(assertion.model_dump_json().encode()).hexdigest()
                proposals[assertion.id] = ProjectRule(
                    assertion=assertion,
                    source_run_id=run_id,
                    sites_applying=len(sites),
                    sites_total=len(voters),
                    guard_forms=sorted(forms[kind])[:100],
                    proposal_sha256=digest,
                    citations=[citation(s) for s in evidence],
                )
        return [proposals[key] for key in sorted(proposals)]

    def _node(
        self, identity: str, label: str, detail: str, span: SourceSpan, optimistic: bool = False
    ) -> ProjectNode:
        return ProjectNode(
            id=identity,
            label=self.redactor.text(label),
            detail=self.redactor.text(detail),
            citation=citation(span),
            optimistic=optimistic,
        )

    def _flows(self, graph: ApplicationMap) -> list[ProjectFlow]:
        outgoing = defaultdict(list)
        for link in graph.links:
            outgoing[link.source].append(link)
        guard_by_id = {g.id: g for g in graph.guards}
        access_by_id = {a.id: a for a in graph.access_sites}
        result = []
        # High-connectivity entry units first, then source order; no security importance claim.
        entries = sorted(
            graph.entries,
            key=lambda e: (
                -sum(a.entry_point_id == e.id for a in graph.access_sites),
                e.span.path,
                e.span.start_line,
                e.id,
            ),
        )
        for entry in entries:
            sites = [a for a in graph.access_sites if a.entry_point_id == entry.id]
            own = {a.id for a in sites}
            pending = deque([entry.id, entry.handler_symbol_id])
            pending.extend(
                link.source
                for link in graph.links
                if link.target in own and link.kind == "may_check"
            )
            seen: set[str] = set()
            links = {}
            while pending:
                identity = pending.popleft()
                if identity in seen:
                    continue
                seen.add(identity)
                for link in outgoing[identity]:
                    if link.target in access_by_id and link.target not in own:
                        continue
                    links[link.id] = link
                    pending.append(link.target)
            guards = sorted(
                (guard_by_id[i] for i in seen if i in guard_by_id),
                key=lambda g: (g.span.path, g.span.start_line, g.id),
            )
            shown_ids = {entry.id, *[g.id for g in guards[:5]], *[a.id for a in sites[:6]]}
            result.append(
                ProjectFlow(
                    entry=self._node(
                        entry.id,
                        f"{entry.method or entry.kind.value} {entry.route or entry.span.path}",
                        entry.framework.value,
                        entry.span,
                    ),
                    guards=[
                        self._node(
                            g.id,
                            "Optimistic routing candidate"
                            if g.optimistic
                            else "Unclassified guard candidate",
                            g.mechanism.value.replace("_", " "),
                            g.span,
                            g.optimistic,
                        )
                        for g in guards[:5]
                    ],
                    data=[
                        self._node(
                            a.id,
                            a.resource,
                            f"{a.operation.value} · {a.key_origin.value} key · "
                            f"{a.data_layer.value}",
                            a.span,
                        )
                        for a in sites[:6]
                    ],
                    links=[
                        ProjectEdge(
                            id=e.id,
                            source=e.source,
                            target=e.target,
                            status=e.status,
                            kind=e.kind,
                            reason=self.redactor.text(e.reason),
                            optimistic=e.optimistic,
                        )
                        for e in graph.links
                        if e.source in shown_ids and e.target in shown_ids
                    ][:100],
                    guards_total=len(guards),
                    data_total=len(sites),
                    unresolved_links=sum(
                        link.status is LinkStatus.UNRESOLVED for link in links.values()
                    ),
                    optimistic_links=sum(link.optimistic for link in links.values()),
                )
            )
        return result

    def page(
        self, run_id: str, offset: int = 0, scope_offset: int = 0, policy_offset: int = 0
    ) -> ProjectPage:
        try:
            with self.lock:
                snapshot, graph, store = self._context(run_id)
                frozen = self.policies.freeze(snapshot, graph.access_sites)
                flows = self._flows(graph)
                proposals = self._proposals(run_id)
                rules = [
                    self.policies.load(p) for p in proposals[policy_offset : policy_offset + 20]
                ]

                def next_page(start: int, count: int, total: int) -> int | None:
                    return start + count if start + count < total else None

                return bounded(
                    ProjectPage(
                        capabilities=table(snapshot, graph, store),
                        bound_policies=frozen.policies,
                        policy_conflicts=list(
                            dict.fromkeys(
                                issue
                                for site in graph.access_sites
                                for issue in frozen.conflicts(site)
                            )
                        ),
                        run_id=run_id,
                        snapshot_id=snapshot.id,
                        name=self.redactor.text(snapshot.root_name),
                        captured_at=snapshot.created_at,
                        languages=dict(
                            sorted(
                                Counter(
                                    f.language.value for f in snapshot.files if f.language
                                ).items()
                            )
                        ),
                        frameworks=dict(
                            sorted(Counter(e.framework.value for e in graph.entries).items())
                        ),
                        resources=dict(
                            sorted(
                                Counter(
                                    self.redactor.text(a.resource) for a in graph.access_sites
                                ).items()
                            )
                        ),
                        included_files=len(snapshot.files),
                        excluded_files=len(snapshot.excluded),
                        exclusion_reasons=dict(
                            sorted(Counter(f.reason.value for f in snapshot.excluded).items())
                        ),
                        unresolved_links=sum(
                            link.status is LinkStatus.UNRESOLVED for link in graph.links
                        ),
                        optimistic_links=sum(link.optimistic for link in graph.links),
                        flows=flows[offset : offset + 12],
                        flows_total=len(flows),
                        offset=offset,
                        next_offset=next_page(offset, len(flows[offset : offset + 12]), len(flows)),
                        exclusions=snapshot.excluded[scope_offset : scope_offset + 20],
                        scope_offset=scope_offset,
                        scope_next_offset=next_page(
                            scope_offset,
                            len(snapshot.excluded[scope_offset : scope_offset + 20]),
                            len(snapshot.excluded),
                        ),
                        rules=rules,
                        rules_total=len(proposals),
                        policy_offset=policy_offset,
                        policy_next_offset=next_page(policy_offset, len(rules), len(proposals)),
                        limitations=[
                            "Possible static flows, not runtime traces. Guard candidates do not "
                            "establish protection; resource names do not establish "
                            "business intent.",
                            "Unresolved links can hide cross-file protections. No mapped guard "
                            "or data access does not mean none exists.",
                            "Included files without discovered entries may contain unsupported "
                            "flows. Exclusions count recorded paths or ignored directories, "
                            "not the files within ignored directories.",
                            "Rules use saved validated peer judgments; no new model judgment "
                            "runs when reading or confirming them. Confirmation records a local "
                            "review decision and never changes agent permissions.",
                            *[self.redactor.text(s) for s in graph.limitations],
                        ],
                    )
                )
        except ProjectMissing:
            raise
        except (OSError, ValueError, sqlite3.Error, MapUnavailable, KeyError) as error:
            raise ProjectUnavailable("Project records cannot be read safely.") from error

    def confirm(self, run_id: str, policy_id: str, expected: str) -> ProjectRule:
        try:
            with self.lock:
                _, graph, _ = self._context(run_id)
                proposal = next(
                    (p for p in self._proposals(run_id) if p.assertion.id == policy_id), None
                )
                if proposal is None:
                    raise ProjectMissing("No source-bound rule has this ID.")
                return self.policies.confirm(
                    proposal,
                    expected,
                    [s for s in graph.access_sites if s.resource == proposal.assertion.resource],
                )
        except (PolicyConflict, ProjectMissing):
            raise
        except (OSError, ValueError, sqlite3.Error, MapUnavailable, KeyError) as error:
            raise ProjectUnavailable("Rule confirmation cannot be saved safely.") from error

    def declare(self, run_id: str, request: PolicyInput) -> BoundPolicy:
        try:
            with self.lock:
                request = PolicyInput.model_validate(request.model_dump())
                snapshot, graph, store = self._context(run_id)
                if snapshot.id != request.snapshot_id:
                    raise PolicyConflict(
                        "Source changed; revalidate the requirement on the new snapshot."
                    )
                by_id = {s.id: s for s in graph.access_sites}
                if any(i not in by_id for i in request.site_ids):
                    raise PolicyConflict("Requirement contains an unrelated access identity.")
                sites = [by_id[i] for i in sorted(request.site_ids)]
                if len({s.resource for s in sites}) != 1:
                    raise PolicyConflict(
                        "A requirement binds one exact resource, not matching names."
                    )
                for site in sites:
                    if Validator(snapshot, store).evidence(site.span):
                        raise PolicyConflict("Requirement access source cannot be validated.")
                kind = request.required_guard or GuardKind.UNKNOWN
                assertion = PolicyAssertion(
                    id="policy:" + uuid4().hex,
                    statement=request.statement,
                    resource=sites[0].resource,
                    kind=kind,
                    canonical=(
                        f"ROLE({request.required_role})"
                        if request.required_role
                        else f"{kind.value.upper()}({sites[0].resource})"
                    ),
                    status=PolicyStatus.DECLARED,
                    author=request.author,
                    created_at=datetime.now(UTC),
                )
                return self.policies.save(
                    BoundPolicy(
                        assertion=assertion,
                        snapshot_id=snapshot.id,
                        source_run_id=run_id,
                        sites=sites,
                        forbidden_fields=request.forbidden_fields,
                        required_role=request.required_role,
                        provenance="Local reviewer declaration against frozen access citations",
                    )
                )
        except (PolicyConflict, ProjectMissing):
            raise
        except (OSError, ValueError, sqlite3.Error, MapUnavailable, KeyError) as error:
            raise ProjectUnavailable("Declared rule cannot be saved safely.") from error

    def excerpt(self, run_id: str, citation_id: str, offset: int = 0) -> ProjectExcerpt:
        try:
            with self.lock:
                snapshot, graph, store = self._context(run_id)
                nodes = [*graph.entries, *graph.guards, *graph.access_sites]
                spans = [n.span for n in nodes] + [
                    s for p in self._proposals(run_id) for s in p.assertion.evidence
                ]
                selected = next((citation(s) for s in spans if citation(s).id == citation_id), None)
                if selected is None:
                    raise ProjectMissing("No project citation has this ID.")
                span = selected.span
                if offset < 0 or span.start_line + offset > span.end_line:
                    raise ProjectMissing("No citation page at this offset.")
                if Validator(snapshot, store).span(span):
                    raise ProjectUnavailable("Source citation cannot be validated.")
                text = store.read(snapshot, span.path).decode("utf-8")
                lines = self.redactor.text(text, preserve_lines=True).split("\n")
                start = span.start_line + offset
                end = min(span.end_line, start + 79)
                return bounded(
                    ProjectExcerpt(
                        run_id=run_id,
                        citation=selected,
                        offset=offset,
                        start_line=start,
                        end_line=end,
                        lines=lines[start - 1 : end],
                        next_offset=offset + end - start + 1 if end < span.end_line else None,
                    )
                )
        except ProjectMissing:
            raise
        except (OSError, ValueError, sqlite3.Error, MapUnavailable, KeyError) as error:
            raise ProjectUnavailable("Project source cannot be read safely.") from error
