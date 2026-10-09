"""Read-only projections for saved case files; the report validator remains authoritative."""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.code import SourceSpan
from backend.contracts.common import Contract, Id, Language, Line, Sha256
from backend.contracts.investigation import Conclusion, DispositionDecision, Exhibit, Finding
from backend.contracts.peers import PeerComparison
from backend.contracts.runs import ReviewRun
from backend.contracts.signals import SignalSet
from backend.contracts.verification import FixProposal, ProbeRun, SuggestedChange


class FindingPage(Contract):
    supplementary: SignalSet | None = None
    run: ReviewRun
    findings: list[Finding] = Field(max_length=20)
    limitations: list[str]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _page(self) -> Self:
        if self.supplementary and (
            self.supplementary.run_id != self.run.id
            or self.supplementary.snapshot_id != self.run.snapshot_id
        ):
            raise ValueError("signals must belong to the saved run")
        if self.total != len(self.run.finding_ids) or any(
            f.run_id != self.run.id or f.snapshot_id != self.run.snapshot_id for f in self.findings
        ):
            raise ValueError("page must belong to its recorded run")
        end = self.offset + len(self.findings)
        if [f.id for f in self.findings] != self.run.finding_ids[self.offset : end]:
            raise ValueError("page must preserve the recorded finding order")
        if self.next_offset != (end if end < self.total else None):
            raise ValueError("continuation must follow the returned page")
        return self


class CaseDetail(Contract):
    disposition_history: list[DispositionDecision] = Field(default=[], max_length=100)
    proposal: FixProposal | None = None
    run: ReviewRun
    finding: Finding
    probe_runs: list[ProbeRun]
    suggested_change: SuggestedChange | None = None
    limitations: list[str]
    # Legacy report bundles do not persist peer rows. Never reconstruct counts from a title.
    peer_comparison: PeerComparison | Literal["not_recorded"] = "not_recorded"

    @model_validator(mode="after")
    def _identity(self) -> Self:
        finding = self.finding
        from backend.disposition_store import validate_history

        validate_history(finding, self.disposition_history, projected=True)
        if self.proposal and (
            self.proposal.finding_id != finding.id
            or self.proposal.snapshot_id != finding.snapshot_id
            or finding.conclusion is not Conclusion.SUPPORTED
            # A refused general proposal does not own a separate bundled replay change.
            or (self.proposal.change is not None and self.proposal.change != self.suggested_change)
        ):
            raise ValueError("proposal must bind the saved case and change")
        if (
            finding.run_id != self.run.id
            or finding.snapshot_id != self.run.snapshot_id
            or finding.id not in self.run.finding_ids
        ):
            raise ValueError("case must belong to its recorded run")
        peer = self.peer_comparison
        if isinstance(peer, PeerComparison) and (
            peer.finding_id != finding.id
            or peer.question_id not in finding.question_ids
            or peer.group.id != finding.peer_group_id
            or peer.group.snapshot_id != finding.snapshot_id
        ):
            raise ValueError("case must include only its recorded peer comparison")
        change = self.suggested_change
        if (change is None) != (finding.suggested_change_id is None) or (
            change and (change.finding_id != finding.id or change.id != finding.suggested_change_id)
        ):
            raise ValueError("case must include exactly its cited change")
        expected = set(finding.probe_run_ids) | set(change.replay_probe_run_ids if change else [])
        if (
            len({p.id for p in self.probe_runs}) != len(self.probe_runs)
            or {p.id for p in self.probe_runs} != expected
            or any(p.finding_id != finding.id for p in self.probe_runs)
        ):
            raise ValueError("case must include exactly its cited proof records")
        return self


class PeerExcerpt(Contract):
    """A numbered page of a recorded peer citation, never an arbitrary source path."""

    run_id: Id
    finding_id: Id
    site_id: Id
    citation: int = Field(ge=0, le=201)
    span: SourceSpan
    start_line: Line
    end_line: Line
    lines: list[str] = Field(min_length=1, max_length=80)
    next_offset: int | None = Field(default=None, ge=1)
    text_is_redacted: Literal[True] = True
    comments_are_not_evidence: Literal[True] = True

    @model_validator(mode="after")
    def _range(self) -> Self:
        if (
            not self.span.start_line <= self.start_line <= self.end_line <= self.span.end_line
            or len(self.lines) != self.end_line - self.start_line + 1
            or self.next_offset
            != (
                self.end_line - self.span.start_line + 1
                if self.end_line < self.span.end_line
                else None
            )
        ):
            raise ValueError("peer excerpt must be a numbered page of its original citation")
        return self


class SnapshotCodePage(Contract):
    """Display context from a cited frozen file; only citation is evidence."""

    run_id: Id
    finding_id: Id
    citation: SourceSpan
    file_sha256: Sha256
    file_line_count: int = Field(ge=1)
    language: Language | None = None
    mode: Literal["context", "file"]
    before: int = Field(ge=0, le=80)
    after: int = Field(ge=0, le=80)
    range_start: Line
    range_end: Line
    offset: int = Field(ge=0, le=1_000_000)
    start_line: Line
    end_line: Line
    lines: list[str] = Field(min_length=1, max_length=80)
    next_offset: int | None = Field(default=None, ge=1)
    text_is_redacted: Literal[True] = True
    comments_are_not_evidence: Literal[True] = True
    context_is_not_evidence: Literal[True] = True

    @model_validator(mode="after")
    def _range(self) -> Self:
        expected = (
            (
                max(1, self.citation.start_line - self.before),
                min(self.file_line_count, self.citation.end_line + self.after),
            )
            if self.mode == "context"
            else (1, self.file_line_count)
        )
        if (
            self.citation.end_line > self.file_line_count
            or (self.range_start, self.range_end) != expected
            or (self.mode == "file" and (self.before or self.after))
            or self.start_line != self.range_start + self.offset
            or not self.range_start <= self.start_line <= self.end_line <= self.range_end
            or len(self.lines) != self.end_line - self.start_line + 1
            or self.next_offset
            != (self.end_line - self.range_start + 1 if self.end_line < self.range_end else None)
        ):
            raise ValueError("code page must stay in its frozen file and declared display range")
        return self


class CitedExcerpt(Contract):
    run_id: Id
    finding_id: Id
    snapshot_id: Sha256
    exhibit: Exhibit
    start_line: Line
    end_line: Line
    lines: list[str] = Field(min_length=1, max_length=80)
    next_offset: int | None = Field(default=None, ge=1)
    text_is_redacted: Literal[True] = True
    comments_are_not_evidence: Literal[True] = True

    @model_validator(mode="after")
    def _range(self) -> Self:
        span = self.exhibit.span
        if (
            self.snapshot_id != span.snapshot_id
            or not span.start_line <= self.start_line <= self.end_line <= span.end_line
            or len(self.lines) != self.end_line - self.start_line + 1
            or self.next_offset
            != (self.end_line - span.start_line + 1 if self.end_line < span.end_line else None)
        ):
            raise ValueError("excerpt must be a numbered page of its original citation")
        return self
