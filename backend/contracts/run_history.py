"""Recorded run navigation and conservative comparisons, never a fresh review."""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.code import GuardKind
from backend.contracts.common import Contract, Id
from backend.contracts.project_view import ProjectCitation
from backend.contracts.review_view import FindingRow
from backend.contracts.runs import ReviewRun

ComparisonGroup = Literal["new", "still_present", "no_longer_observed", "not_reviewed"]
GROUPS: tuple[ComparisonGroup, ...] = ("new", "still_present", "no_longer_observed", "not_reviewed")


class RunHistory(Contract):
    runs: list[ReviewRun] = Field(max_length=20)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_offset: int | None

    @model_validator(mode="after")
    def _page(self) -> Self:
        end = self.offset + len(self.runs)
        if (
            (self.runs and end > self.total)
            or self.next_offset != (end if end < self.total else None)
            or len({r.id for r in self.runs}) != len(self.runs)
        ):
            raise ValueError("history pages must preserve unique runs and their total")
        return self


class ComparisonRow(Contract):
    id: Id
    group: ComparisonGroup
    before: FindingRow | None
    after: FindingRow | None
    reason: str

    @model_validator(mode="after")
    def _sides(self) -> Self:
        if (
            (self.group == "new" and (self.before is not None or self.after is None))
            or (self.group != "new" and self.before is None)
            or (self.group in ("still_present", "no_longer_observed") and self.after is None)
        ):
            raise ValueError("comparison groups must retain the appropriate finding records")
        if self.group == "no_longer_observed" and (
            self.after is None or self.after.conclusion != "rejected"
        ):
            raise ValueError("absence needs an explicit later rejected finding")
        if self.group in ("new", "still_present") and (
            self.after is None or self.after.conclusion == "rejected"
        ):
            raise ValueError("a rejected finding is not an observed concern")
        return self


class GuardCount(Contract):
    applying: int = Field(ge=0)
    total: int = Field(ge=1)
    citations: list[ProjectCitation] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _count(self) -> Self:
        if self.applying > self.total:
            raise ValueError("guard count must fit its recorded cohort")
        return self


class PolicyDrift(Contract):
    resource: str
    kind: GuardKind
    before: GuardCount | None
    after: GuardCount | None
    cohort_changed: bool
    reason: str


class RunComparison(Contract):
    before: ReviewRun
    after: ReviewRun
    group: ComparisonGroup
    rows: list[ComparisonRow] = Field(max_length=20)
    counts: dict[ComparisonGroup, int]
    offset: int = Field(ge=0)
    next_offset: int | None
    policies: list[PolicyDrift] = Field(max_length=20)
    policies_total: int = Field(ge=0)
    policy_offset: int = Field(ge=0)
    policy_next_offset: int | None
    limitations: list[str]

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if self.before.id == self.after.id or self.after.created_at < self.before.created_at:
            raise ValueError("comparison needs distinct runs in chronological order")
        if set(self.counts) != set(GROUPS) or any(n < 0 for n in self.counts.values()):
            raise ValueError("comparison counts must include each group")
        for rows, total, offset, following in (
            (self.rows, self.counts[self.group], self.offset, self.next_offset),
            (self.policies, self.policies_total, self.policy_offset, self.policy_next_offset),
        ):
            end = offset + len(rows)
            if (rows and end > total) or following != (end if end < total else None):
                raise ValueError("comparison pages must preserve their full counts")
        if len({r.id for r in self.rows}) != len(self.rows) or any(
            r.group != self.group for r in self.rows
        ):
            raise ValueError("comparison rows must retain unique group identities")
        for row in self.rows:
            for finding, run in ((row.before, self.before), (row.after, self.after)):
                if finding and (
                    finding.id not in run.finding_ids
                    or (finding.location and finding.location.snapshot_id != run.snapshot_id)
                ):
                    raise ValueError("comparison findings must belong to their recorded run")
        for policy in self.policies:
            for count, run in ((policy.before, self.before), (policy.after, self.after)):
                if count and any(c.span.snapshot_id != run.snapshot_id for c in count.citations):
                    raise ValueError("policy observations must retain their snapshot citations")
        return self
