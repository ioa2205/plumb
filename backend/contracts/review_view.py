"""Bounded workbench projections; never transport model answers or working state."""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.code import SourceSpan
from backend.contracts.common import Contract, Family, Id
from backend.contracts.investigation import (
    Conclusion,
    Disposition,
    QuestionStage,
    QuestionStatus,
    QuestionType,
    RuntimeVerification,
    Severity,
)
from backend.contracts.runs import ReviewRun, RunEvent
from backend.contracts.signals import SignalSet


class QueueRow(Contract):
    id: Id
    position: int = Field(ge=1)
    original_position: int | None = Field(default=None, ge=1)
    type: QuestionType
    family: Family
    stage: QuestionStage
    status: QuestionStatus
    location: SourceSpan | None
    priority_reasons: list[str]
    exploration: bool


class ReviewPage(Contract):
    run: ReviewRun
    questions: list[QueueRow] = Field(max_length=20)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(ge=0)
    events: list[RunEvent] = Field(max_length=100)
    cursor: int = Field(ge=0)
    requested: Literal["pause", "cancel"] | None
    queue_excluded: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        end = self.offset + len(self.questions)
        if (
            self.total
            != self.run.coverage.completed + self.run.coverage.pending + self.queue_excluded
        ):
            raise ValueError("queue total must match included checks")
        if self.questions and end > self.total:
            raise ValueError("queue page cannot exceed the total")
        if self.queue_excluded > self.run.coverage.excluded:
            raise ValueError("user exclusions must fit recorded scope")
        originals = [q.original_position for q in self.questions if q.original_position is not None]
        if len(set(originals)) != len(originals) or any(n > self.total for n in originals):
            raise ValueError("original positions must be unique within the queue")
        if self.next_offset != (end if end < self.total else None):
            raise ValueError("queue continuation must follow the page")
        if [q.position for q in self.questions] != list(range(self.offset + 1, end + 1)):
            raise ValueError("queue positions must preserve their recorded order")
        if len({q.id for q in self.questions}) != len(self.questions) or any(
            q.location and q.location.snapshot_id != self.run.snapshot_id for q in self.questions
        ):
            raise ValueError("queue must belong to its snapshot with unique question IDs")
        if [e.seq for e in self.events] != list(
            range(max(1, self.cursor - 99), self.cursor + 1)
        ) or any(e.run_id != self.run.id for e in self.events):
            raise ValueError("activity must be the contiguous tail of this run")
        return self


class QueueEdit(Contract):
    question_id: Id
    action: Literal["up", "down", "exclude", "include"]
    expected_cursor: int = Field(ge=0)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class FindingRow(Contract):
    id: Id
    display_id: str
    title: str
    family: Family
    conclusion: Conclusion
    severity: Severity
    runtime_verification: RuntimeVerification
    disposition: Disposition
    location: SourceSpan | None


class FindingList(Contract):
    supplementary: SignalSet | None = None
    run: ReviewRun
    findings: list[FindingRow] = Field(max_length=20)
    limitations: list[str]
    counts: dict[Conclusion, int]
    total: int = Field(ge=0)  # matches the selected filters across the entire saved report
    offset: int = Field(ge=0)
    next_offset: int | None = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.supplementary and (
            self.supplementary.run_id != self.run.id
            or self.supplementary.snapshot_id != self.run.snapshot_id
        ):
            raise ValueError("signals must belong to the saved run")
        end = self.offset + len(self.findings)
        if self.findings and end > self.total:
            raise ValueError("finding page cannot exceed the total")
        if set(self.counts) != set(Conclusion) or any(n < 0 for n in self.counts.values()):
            raise ValueError("all conclusion counts must be present and nonnegative")
        if sum(self.counts.values()) != self.total or self.total > len(self.run.finding_ids):
            raise ValueError("filtered counts must add up within the saved run")
        if self.next_offset != (end if end < self.total else None):
            raise ValueError("finding continuation must follow the page")
        if len({f.id for f in self.findings}) != len(self.findings) or any(
            f.id not in self.run.finding_ids
            or (f.location and f.location.snapshot_id != self.run.snapshot_id)
            for f in self.findings
        ):
            raise ValueError("findings must belong to their saved run")
        return self
