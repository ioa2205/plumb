"""Read saved history and compare exact review units without inference or target execution."""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from typing import Protocol

from agent.validator import Validator
from analysis.snapshot import SnapshotStore
from backend.case_reads import CaseReads, CaseUnavailable, bounded
from backend.contracts.application_map import ApplicationMap
from backend.contracts.code import AccessSite, EntryPoint
from backend.contracts.investigation import Conclusion, Finding, Question, QuestionStatus
from backend.contracts.peers import KINDS, PeerComparison
from backend.contracts.review_view import FindingRow
from backend.contracts.run_history import (
    GROUPS,
    ComparisonGroup,
    ComparisonRow,
    GuardCount,
    PolicyDrift,
    RunComparison,
    RunHistory,
)
from backend.contracts.runs import ReviewRun
from backend.project_reads import ProjectMissing, ProjectReads, citation
from backend.reports import ReportBundle
from backend.settings import Settings

MAX_RECORD_BYTES = 512 * 1024


class RunReadUnavailable(ValueError):
    """A generic saved-record refusal; private storage details do not reach the UI."""


def finding_row(finding: Finding) -> FindingRow:
    return FindingRow(
        id=finding.id,
        display_id=finding.display_id,
        title=finding.title,
        family=finding.family,
        conclusion=finding.conclusion,
        severity=finding.severity,
        runtime_verification=finding.runtime_verification,
        disposition=finding.disposition,
        location=finding.exhibits[0].span if finding.exhibits else None,
    )


def entry_key(entry: EntryPoint) -> tuple:
    return (
        entry.framework.value,
        entry.kind.value,
        entry.method or "",
        entry.route or "",
        entry.span.path,
    )


def site_key(site: AccessSite, entry: EntryPoint) -> tuple:
    return (
        "access",
        *entry_key(entry),
        site.resource,
        site.operation.value,
        site.data_layer.value,
        site.span.path,
    )


def question_keys(questions: list[Question], graph: ApplicationMap | None) -> dict[str, str | None]:
    # Names/routes are navigation identities only, never security evidence. Repeated
    # operations need an unchanged unique code hash; otherwise correspondence is unknown.
    bases: dict[str, tuple] = {}
    spans = {}
    if graph:
        entries = {e.id: e for e in graph.entries}
        for e in graph.entries:
            bases[e.id] = ("entry", *entry_key(e))
            spans[e.id] = e.span
        for site in graph.access_sites:
            bases[site.id] = site_key(site, entries[site.entry_point_id])
            spans[site.id] = site.span
    counts = Counter(bases.values())
    refined = {
        identity: base if counts[base] == 1 else (*base, spans[identity].content_sha256)
        for identity, base in bases.items()
    }
    unique = Counter(refined.values())
    result = {}
    for q in questions:
        subjects = [refined.get(identity) for identity in q.subject_ids]
        if not subjects or any(s is None or unique[s] != 1 for s in subjects):
            # Legacy/sink packets can correspond only when their complete cited code is unchanged.
            subjects = [("code", s.path, s.content_sha256) for s in q.evidence]
        result[q.id] = (
            hashlib.sha256(
                json.dumps(
                    [q.family.value, q.type.value, sorted(json.dumps(s) for s in subjects)],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            if subjects
            else None
        )
    return result


def compare_rows(
    before: ReportBundle,
    after: ReportBundle,
    before_questions: list[Question],
    after_questions: list[Question],
    before_map: ApplicationMap | None,
    after_map: ApplicationMap | None,
) -> list[ComparisonRow]:
    left_keys = question_keys(before_questions, before_map)
    right_keys = question_keys(after_questions, after_map)
    left_q = {q.id: q for q in before_questions}
    right_q = {q.id: q for q in after_questions}

    def key(f: Finding, keys: dict[str, str | None], qs: dict[str, Question]) -> str | None:
        found = {keys.get(i) for i in f.question_ids}
        if (
            len(found) != 1
            or None in found
            or any(qs[i].family != f.family for i in f.question_ids)
        ):
            return None
        return found.pop()

    left = {f.id: key(f, left_keys, left_q) for f in before.findings}
    right = {f.id: key(f, right_keys, right_q) for f in after.findings}
    left_counts = Counter(left.values())
    right_counts = Counter(right.values())
    q_counts = Counter(right_keys.values())
    right_by_key = {right[f.id]: f for f in after.findings if right[f.id] is not None}
    matched = set()
    rows = []

    def add(group: ComparisonGroup, old: Finding | None, new: Finding | None, reason: str) -> None:
        identity = f"{before.run.id}:{after.run.id}:{old.id if old else ''}:{new.id if new else ''}"
        rows.append(
            ComparisonRow(
                id="compare:" + hashlib.sha256(identity.encode()).hexdigest(),
                group=group,
                before=finding_row(old) if old else None,
                after=finding_row(new) if new else None,
                reason=reason,
            )
        )

    for old in before.findings:
        if old.conclusion is Conclusion.REJECTED:
            continue
        anchor = left[old.id]
        new = right_by_key.get(anchor) if anchor is not None else None
        certain = anchor is not None and left_counts[anchor] == 1 and right_counts[anchor] == 1
        if certain and new and new.conclusion is not Conclusion.REJECTED:
            matched.add(new.id)
            add(
                "still_present",
                old,
                new,
                "Both reports record a concern on the same unique review unit.",
            )
        elif (
            certain
            and new
            and q_counts[anchor] == 1
            and all(right_q[i].status is QuestionStatus.ANSWERED for i in new.question_ids)
        ):
            add(
                "no_longer_observed",
                old,
                new,
                "The later matched check explicitly rejected the concern "
                "with validated guard evidence. "
                "This is a source observation, not proof of a runtime fix.",
            )
        else:
            add(
                "not_reviewed",
                old,
                None,
                "No unique, explicitly answered later rejection matches this review unit. "
                "Missing, excluded, failed, ambiguous or changed packets remain unknown.",
            )
    for new in after.findings:
        if new.conclusion is not Conclusion.REJECTED and new.id not in matched:
            add(
                "new",
                None,
                new,
                "Newly recorded in this comparison; it may have existed outside earlier coverage.",
            )
    return rows


class PeerSource(Protocol):
    @property
    def peer_comparisons(self) -> list[PeerComparison]: ...


def policy_drift(before: PeerSource, after: PeerSource) -> list[PolicyDrift]:
    def observations(bundle: PeerSource) -> dict[tuple[str, str], tuple[GuardCount, tuple]]:
        variants = defaultdict(dict)
        for peer in bundle.peer_comparisons:
            voters = [row for row in peer.rows if row.exclusion is None]
            if not voters:
                continue
            cohort = tuple(sorted(site_key(row.site, row.entry) for row in voters))
            if len(set(cohort)) != len(cohort):
                continue  # repeated data units cannot silently inflate a peer denominator
            for kind in KINDS:
                guards = [g for row in voters for g in row.guards if g.kind is kind]
                count = sum(any(g.kind is kind for g in row.guards) for row in voters)
                spans = [g.span for g in guards] or [row.site.span for row in voters]
                citations = {citation(s).id: citation(s) for s in spans}
                record = GuardCount(
                    applying=count,
                    total=len(voters),
                    citations=[citations[k] for k in sorted(citations)][:20],
                )
                variants[(peer.group.resource, kind.value)][(cohort, count)] = (record, cohort)
        # Distinct or conflicting cohorts are not silently merged into a consensus.
        return {
            key: next(iter(values.values())) for key, values in variants.items() if len(values) == 1
        }

    left, right = observations(before), observations(after)
    return [
        PolicyDrift(
            resource=resource,
            kind=kind,
            before=left[(resource, kind)][0] if (resource, kind) in left else None,
            after=right[(resource, kind)][0] if (resource, kind) in right else None,
            cohort_changed=(resource, kind) not in left
            or (resource, kind) not in right
            or left[(resource, kind)][1] != right[(resource, kind)][1],
            reason="Saved source-validated guard observations. "
            "Changed or missing cohorts cannot establish "
            "a like-for-like policy change; human rules and permissions are unchanged.",
        )
        for resource, kind in sorted(set(left) | set(right))
    ]


class RunReads:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.cache_dir / "runs.sqlite"
        self.cases = CaseReads(settings)
        self.projects = ProjectReads(settings)

    def _read(self, query: str, parameters: tuple = ()) -> list[tuple]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            return db.execute(query, parameters).fetchall()

    def history(self, offset: int = 0) -> RunHistory:
        try:
            counts = self._read("SELECT count(*) FROM runs")
            total = counts[0][0] if counts else 0
            rows = self._read(
                "SELECT id, CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload ELSE NULL END "
                "FROM runs ORDER BY julianday(json_extract(payload,'$.created_at')) DESC, id "
                "LIMIT 20 OFFSET ?",
                (MAX_RECORD_BYTES, offset),
            )
            runs = [ReviewRun.model_validate_json(payload) for _, payload in rows]
            if any(identity != run.id for (identity, _), run in zip(rows, runs, strict=True)):
                raise RunReadUnavailable("Run identities differ from their storage keys.")
            end = offset + len(runs)
            return bounded(
                RunHistory(
                    runs=runs, total=total, offset=offset, next_offset=end if end < total else None
                )
            )
        except (OSError, ValueError, sqlite3.Error, TypeError) as error:
            raise RunReadUnavailable("Recorded history cannot be read safely.") from error

    def _context(self, run_id: str) -> tuple[ReportBundle, list[Question], ApplicationMap | None]:
        bundle = self.cases._bundle(run_id)
        if self.projects.runs.run(run_id) != bundle.run:
            raise RunReadUnavailable(
                "Saved report and current checkpoint differ. Wait for a fresh report."
            )
        rows = self._read(
            "SELECT id, CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload ELSE NULL END "
            "FROM questions WHERE run_id=? ORDER BY position LIMIT 10001",
            (MAX_RECORD_BYTES, run_id),
        )
        if len(rows) > 10000:
            raise RunReadUnavailable("Comparison exceeds its saved-question read budget.")
        questions = [Question.model_validate_json(payload) for _, payload in rows]
        if any(
            q.run_id != run_id or identity != q.id
            for (identity, _), q in zip(rows, questions, strict=True)
        ):
            raise RunReadUnavailable("Question identities differ from the selected run.")
        graph = None
        try:
            _, graph, store = self.projects._context(run_id)
        except ProjectMissing:
            store = SnapshotStore(self.settings.cache_dir / "snapshots")
            try:
                store.load(bundle.snapshot.id)
            except FileNotFoundError:
                store = SnapshotStore(self.settings.cache_dir)
        validator = Validator(bundle.snapshot, store)
        if any(validator.span(s) for q in questions for s in q.evidence):
            raise RunReadUnavailable("A saved review question differs from its frozen source.")
        return bundle, questions, graph

    def comparison(
        self,
        before_id: str,
        after_id: str,
        group: ComparisonGroup = "new",
        offset: int = 0,
        policy_offset: int = 0,
    ) -> RunComparison:
        try:
            before, left, left_map = self._context(before_id)
            after, right, right_map = self._context(after_id)
            if before.snapshot.root_name != after.snapshot.root_name:
                raise RunReadUnavailable("Select reviews with the same recorded project name.")
            rows = compare_rows(before, after, left, right, left_map, right_map)
            policies = policy_drift(before, after)
            selected = [r for r in rows if r.group == group]
            end = offset + len(selected[offset : offset + 20])
            policy_end = policy_offset + len(policies[policy_offset : policy_offset + 20])
            return bounded(
                RunComparison(
                    before=before.run,
                    after=after.run,
                    group=group,
                    rows=selected[offset : offset + 20],
                    counts={g: sum(r.group == g for r in rows) for g in GROUPS},
                    offset=offset,
                    next_offset=end if end < len(selected) else None,
                    policies=policies[policy_offset : policy_offset + 20],
                    policies_total=len(policies),
                    policy_offset=policy_offset,
                    policy_next_offset=policy_end if policy_end < len(policies) else None,
                    limitations=[
                        "Saved reports only; no new model judgment, probe or analysis starts here.",
                        "Correspondence uses unique frozen request/data identities, "
                        "or unchanged cited code. Ambiguous, renamed or missing units "
                        "remain not reviewed. Matching project names "
                        "alone does not establish that two folders are the same project.",
                        "No longer observed needs an explicitly answered, "
                        "source-validated later rejection. "
                        "It does not mean fixed, safe, or runtime verified.",
                        "New means newly recorded, not necessarily introduced by a code change. "
                        "Absence, incomplete coverage and validator rejection "
                        "cannot establish safety.",
                        *before.limitations,
                        *after.limitations,
                    ],
                )
            )
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError, CaseUnavailable) as error:
            raise RunReadUnavailable(
                "These saved runs cannot be compared safely. Their reports are preserved."
            ) from error
