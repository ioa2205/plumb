"""Validated saved-case reads. No inference, live target reads, writes or execution."""

import sqlite3
from threading import Lock
from typing import Literal

from agent.validator import Validator
from analysis.snapshot import SnapshotStore
from backend.contracts.cases import (
    CaseDetail,
    CitedExcerpt,
    FindingPage,
    PeerExcerpt,
    SnapshotCodePage,
)
from backend.contracts.code import SnapshotFile, SourceSpan
from backend.contracts.common import Contract
from backend.contracts.investigation import (
    DispositionDecision,
    DispositionUpdate,
    ExhibitRole,
    Finding,
)
from backend.contracts.review_view import FindingList, FindingRow
from backend.disposition_store import DispositionConflict, DispositionStore
from backend.redaction import Redactor
from backend.reports import Format, ReportBundle, render
from backend.saved_reports import load
from backend.settings import Settings

MAX_CASE_BYTES = 512 * 1024


class CaseUnavailable(ValueError):
    """A generic refusal; no report, source or filesystem detail crosses the boundary."""


class CaseMissing(CaseUnavailable):
    """The requested saved report, finding or citation is absent."""


def bounded[T: Contract](record: T) -> T:
    if len(record.model_dump_json().encode("utf-8")) > MAX_CASE_BYTES:
        raise CaseUnavailable("Saved case is too large")
    return record


class CaseReads:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redactor = Redactor.configured(settings)
        self.lock = Lock()

    def _bundle(self, run_id: str) -> ReportBundle:
        try:
            return load(self.settings, run_id)[0]
        except FileNotFoundError as error:
            raise CaseMissing("Saved report unavailable") from error
        except (OSError, ValueError, sqlite3.Error) as error:
            raise CaseUnavailable("Saved report cannot be validated") from error

    @staticmethod
    def _finding(bundle: ReportBundle, finding_id: str) -> Finding:
        finding = next((f for f in bundle.findings if f.id == finding_id), None)
        if finding is None:
            raise CaseMissing("Finding unavailable")
        return finding

    def page(self, run_id: str, offset: int, limit: int) -> FindingPage:
        if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 20:
            raise CaseUnavailable("Invalid page")
        with self.lock:
            bundle = self._bundle(run_id)
            # ReportBundle validates membership, not sequence; use the run's canonical order.
            by_id = {f.id: f for f in bundle.findings}
            selected = [by_id[i] for i in bundle.run.finding_ids[offset : offset + limit]]
            end = offset + len(selected)
            return bounded(
                FindingPage(
                    supplementary=bundle.supplementary,
                    run=bundle.run,
                    findings=selected,
                    limitations=bundle.limitations,
                    total=len(bundle.findings),
                    offset=offset,
                    next_offset=end if end < len(bundle.findings) else None,
                )
            )

    def case(self, run_id: str, finding_id: str) -> CaseDetail:
        with self.lock:
            bundle = self._bundle(run_id)
            finding = self._finding(bundle, finding_id)
            change = next(
                (c for c in bundle.suggested_changes if c.id == finding.suggested_change_id), None
            )
            probe_ids = set(finding.probe_run_ids) | set(
                change.replay_probe_run_ids if change else []
            )
            return bounded(
                CaseDetail(
                    proposal=next(
                        (p for p in bundle.proposals if p.finding_id == finding.id), None
                    ),
                    run=bundle.run,
                    finding=finding,
                    disposition_history=[
                        d for d in bundle.disposition_history if d.finding_id == finding.id
                    ],
                    probe_runs=[p for p in bundle.probe_runs if p.id in probe_ids],
                    suggested_change=change,
                    limitations=bundle.limitations,
                    peer_comparison=next(
                        (p for p in bundle.peer_comparisons if p.finding_id == finding.id),
                        "not_recorded",
                    ),
                )
            )

    def update_disposition(
        self, run_id: str, finding_id: str, request: DispositionUpdate
    ) -> DispositionDecision:
        with self.lock:
            try:
                original = load(
                    self.settings, run_id, include_replay=False, include_dispositions=False
                )[0]
                finding = self._finding(original, finding_id)
                clean = DispositionUpdate.model_validate(
                    self.redactor.strings(request.model_dump(mode="json"))
                )
                if clean.snapshot_id != request.snapshot_id:
                    raise ValueError("Redaction changed the snapshot identity")
                return DispositionStore(self.settings.cache_dir / "dispositions.sqlite").append(
                    finding, clean
                )
            except DispositionConflict:
                raise
            except FileNotFoundError as error:
                raise CaseMissing("Saved report unavailable") from error
            except CaseMissing:
                raise
            except (OSError, ValueError, sqlite3.Error) as error:
                raise CaseUnavailable("Reviewer decision cannot be saved") from error

    def export(self, run_id: str, format: Format) -> str:
        with self.lock:
            bundle = self._bundle(run_id)
            store = SnapshotStore(self.settings.cache_dir / "snapshots")
            try:
                store.load(bundle.snapshot.id)
            except FileNotFoundError:
                store = SnapshotStore(self.settings.cache_dir)
            try:
                return render(bundle, store, format, secrets=self.redactor.secrets)
            except (OSError, ValueError) as error:
                raise CaseUnavailable("Current report cannot be exported") from error

    def finding_list(self, run_id: str, offset: int = 0, **filters: str | None) -> FindingList:
        if not 0 <= offset <= 1_000_000 or set(filters) - {
            "family",
            "severity",
            "runtime_verification",
            "disposition",
        }:
            raise CaseUnavailable("Invalid finding filters")
        from backend.contracts.investigation import Conclusion

        with self.lock:
            bundle = self._bundle(run_id)
            order = {
                value: i
                for i, value in enumerate(
                    (
                        Conclusion.SUPPORTED,
                        Conclusion.INCONCLUSIVE,
                        Conclusion.CANDIDATE,
                        Conclusion.REJECTED,
                    )
                )
            }
            matches = sorted(
                (
                    f
                    for f in bundle.findings
                    if all(
                        value is None or getattr(f, key) == value for key, value in filters.items()
                    )
                ),
                key=lambda f: order[f.conclusion],
            )
            end = offset + len(matches[offset : offset + 20])
            return bounded(
                FindingList(
                    supplementary=bundle.supplementary,
                    run=bundle.run,
                    findings=[
                        FindingRow(
                            id=f.id,
                            display_id=f.display_id,
                            title=f.title,
                            family=f.family,
                            conclusion=f.conclusion,
                            severity=f.severity,
                            runtime_verification=f.runtime_verification,
                            disposition=f.disposition,
                            location=f.exhibits[0].span if f.exhibits else None,
                        )
                        for f in matches[offset : offset + 20]
                    ],
                    limitations=bundle.limitations,
                    counts={c: sum(f.conclusion == c for f in matches) for c in Conclusion},
                    total=len(matches),
                    offset=offset,
                    next_offset=end if end < len(matches) else None,
                )
            )

    def excerpt(
        self, run_id: str, finding_id: str, tag: str, offset: int, lines: int
    ) -> CitedExcerpt:
        if not 0 <= offset <= 1_000_000 or not 1 <= lines <= 80:
            raise CaseUnavailable("Invalid excerpt page")
        with self.lock:
            bundle = self._bundle(run_id)
            finding = self._finding(bundle, finding_id)
            exhibit = next((e for e in finding.exhibits if e.tag == tag), None)
            if exhibit is None:
                raise CaseMissing("Citation unavailable")
            if exhibit.role is ExhibitRole.DEVELOPER_NOTE:
                raise CaseUnavailable("Developer notes are not security evidence")
            span = exhibit.span
            start = span.start_line + offset
            end = min(span.end_line, start + lines - 1)
            if start > span.end_line:
                raise CaseUnavailable("Offset leaves the citation")
            return bounded(
                CitedExcerpt(
                    run_id=run_id,
                    finding_id=finding.id,
                    snapshot_id=bundle.snapshot.id,
                    exhibit=exhibit,
                    start_line=start,
                    end_line=end,
                    lines=self._lines(bundle, span, start, end),
                    next_offset=end - span.start_line + 1 if end < span.end_line else None,
                )
            )

    def peer_excerpt(
        self, run_id: str, finding_id: str, site_id: str, citation: int, offset: int, lines: int
    ) -> PeerExcerpt:
        if not 0 <= offset <= 1_000_000 or not 1 <= lines <= 80 or not 0 <= citation <= 201:
            raise CaseUnavailable("Invalid peer excerpt page")
        with self.lock:
            bundle = self._bundle(run_id)
            finding = self._finding(bundle, finding_id)
            peer = next((p for p in bundle.peer_comparisons if p.finding_id == finding.id), None)
            row = next((r for r in peer.rows if r.site.id == site_id), None) if peer else None
            if row is None:
                raise CaseMissing("Peer citation unavailable")
            # Stable indices within this saved row: site, entry, guards, search/exclusion evidence.
            citations = [
                row.site.span,
                row.entry.span,
                *[g.span for g in row.guards],
                *row.evidence,
            ]
            if citation >= len(citations):
                raise CaseMissing("Peer citation unavailable")
            span = citations[citation]
            start = span.start_line + offset
            end = min(span.end_line, start + lines - 1)
            if start > span.end_line:
                raise CaseUnavailable("Offset leaves the citation")
            return bounded(
                PeerExcerpt(
                    run_id=run_id,
                    finding_id=finding.id,
                    site_id=site_id,
                    citation=citation,
                    span=span,
                    start_line=start,
                    end_line=end,
                    lines=self._lines(bundle, span, start, end),
                    next_offset=end - span.start_line + 1 if end < span.end_line else None,
                )
            )

    def code_page(
        self,
        run_id: str,
        finding_id: str,
        *,
        tag: str | None = None,
        site_id: str | None = None,
        citation: int | None = None,
        mode: Literal["context", "file"] = "context",
        before: int = 3,
        after: int = 3,
        offset: int = 0,
        lines: int = 80,
    ) -> SnapshotCodePage:
        if (
            mode not in {"context", "file"}
            or not 0 <= before <= 80
            or not 0 <= after <= 80
            or not 0 <= offset <= 1_000_000
            or not 1 <= lines <= 80
        ):
            raise CaseUnavailable("Invalid code page")
        if not (
            (tag is not None and site_id is None and citation is None)
            or (tag is None and site_id is not None and citation is not None)
        ):
            raise CaseUnavailable("Select exactly one recorded citation")
        with self.lock:
            bundle = self._bundle(run_id)
            finding = self._finding(bundle, finding_id)
            if tag is not None:
                exhibit = next((e for e in finding.exhibits if e.tag == tag), None)
                if exhibit is None:
                    raise CaseMissing("Citation unavailable")
                if exhibit.role is ExhibitRole.DEVELOPER_NOTE:
                    raise CaseUnavailable("Developer notes are not security evidence")
                span = exhibit.span
            else:
                peer = next(
                    (p for p in bundle.peer_comparisons if p.finding_id == finding.id), None
                )
                row = next((r for r in peer.rows if r.site.id == site_id), None) if peer else None
                if row is None:
                    raise CaseMissing("Peer citation unavailable")
                citations = [
                    row.site.span,
                    row.entry.span,
                    *[g.span for g in row.guards],
                    *row.evidence,
                ]
                if citation is None or not 0 <= citation <= 201 or citation >= len(citations):
                    raise CaseMissing("Peer citation unavailable")
                span = citations[citation]
            file, source = self._source_lines(bundle, span)
            if mode == "file":
                before = after = 0
            start_range = max(1, span.start_line - before) if mode == "context" else 1
            end_range = (
                min(len(source), span.end_line + after) if mode == "context" else len(source)
            )
            start = start_range + offset
            if start > end_range:
                raise CaseUnavailable("Offset leaves the display range")
            end = min(end_range, start + lines - 1)
            return bounded(
                SnapshotCodePage(
                    run_id=run_id,
                    finding_id=finding.id,
                    citation=span,
                    file_sha256=file.sha256,
                    file_line_count=len(source),
                    language=file.language,
                    mode=mode,
                    before=before,
                    after=after,
                    range_start=start_range,
                    range_end=end_range,
                    offset=offset,
                    start_line=start,
                    end_line=end,
                    lines=source[start - 1 : end],
                    next_offset=end - start_range + 1 if end < end_range else None,
                )
            )

    def _lines(self, bundle: ReportBundle, span: SourceSpan, start: int, end: int) -> list[str]:
        return self._source_lines(bundle, span)[1][start - 1 : end]

    def _source_lines(
        self, bundle: ReportBundle, span: SourceSpan
    ) -> tuple[SnapshotFile, list[str]]:
        try:
            store = SnapshotStore(self.settings.cache_dir / "snapshots")
            try:
                store.load(bundle.snapshot.id)
            except FileNotFoundError:
                store = SnapshotStore(self.settings.cache_dir)
            if Validator(bundle.snapshot, store).span(span):
                raise ValueError("Citation no longer validates")
            file = next(f for f in bundle.snapshot.files if f.path == span.path)
            source = store.read(bundle.snapshot, span.path).decode("utf-8")
            # Tree-sitter and citation hashes count LF, not Unicode separators or CR.
            total = source.count("\n") + (0 if source.endswith("\n") or not source else 1)
            # Redact the full file before slicing so multiline secrets cannot escape a page.
            redacted = self.redactor.text(source, preserve_lines=True).split("\n")[:total]
            return file, redacted
        except (OSError, ValueError, UnicodeError) as error:
            raise CaseUnavailable("Snapshot excerpt cannot be validated") from error
