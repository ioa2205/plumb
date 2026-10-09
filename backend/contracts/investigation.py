"""The investigation: typed questions, tool observations, and findings (PROJECT_PLAN §3, §6)."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, JsonValue, StringConstraints, model_validator

from backend.contracts.code import SourceSpan
from backend.contracts.common import Contract, Family, Id, Sha256
from backend.contracts.policies import BoundPolicy


class QuestionType(StrEnum):
    GUARD_SUMMARY = "guard_summary"
    GUARD_EQUIVALENT = "guard_equivalent"
    INPUT_ORIGIN = "input_origin"
    SINK_SAFETY = "sink_safety"
    INTENTIONAL_EXCEPTION = "intentional_exception"
    CLIENT_EXPOSURE = "client_exposure"
    FIX_SKETCH = "fix_sketch"


class QuestionStage(StrEnum):
    """FRAME -> GATHER -> HYPOTHESIZE -> CHALLENGE -> DECIDE -> [VERIFY] -> RECORD."""

    FRAME = "frame"
    GATHER = "gather"
    HYPOTHESIZE = "hypothesize"
    CHALLENGE = "challenge"
    DECIDE = "decide"
    VERIFY = "verify"
    RECORD = "record"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    EXCLUDED = "excluded"  # owner narrowed the queue before this question started
    RUNNING = "running"
    ANSWERED = "answered"
    REJECTED_BY_VALIDATOR = "rejected_by_validator"
    INCONCLUSIVE = "inconclusive"  # self-consistency samples disagreed
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELED = "canceled"
    FAILED = "failed"


class Budget(Contract):
    max_looks: int = Field(default=4, ge=0)
    max_prompt_tokens: int = Field(default=3000, gt=0)
    max_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


class Question(Contract):
    """One narrow judgment asked of the model, with its evidence and budget."""

    id: Id
    run_id: Id
    type: QuestionType
    family: Family
    stage: QuestionStage
    status: QuestionStatus
    subject_ids: list[Id]  # access sites, guards, or entry points the question is about
    evidence: list[SourceSpan]
    budget: Budget = Budget()
    priority_reasons: list[str] = []
    exploration: bool = False  # drawn from the 20% share reserved for lower-ranked items
    answer: dict[str, JsonValue] | None = None
    observation_ids: list[Id] = []

    @model_validator(mode="after")
    def _answer_matches_status(self) -> Self:
        if (self.status is QuestionStatus.ANSWERED) != (self.answer is not None):
            raise ValueError("an answer is present exactly when the question is answered")
        return self


class ObservationStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    REFUSED = "refused"  # blocked by policy, for example a path outside the root


class ToolObservation(Contract):
    """One tool call: its inputs, tool and version, timing, output reference, and status."""

    id: Id
    run_id: Id
    question_id: Id | None = None
    tool: str
    tool_version: str
    inputs: dict[str, JsonValue]
    started_at: AwareDatetime
    finished_at: AwareDatetime
    output_sha256: Sha256 | None = None
    status: ObservationStatus

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at comes before started_at")
        return self


class Conclusion(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class RuntimeVerification(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    UNAVAILABLE = "unavailable"
    INCONCLUSIVE = "inconclusive"
    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"  # "not reproduced under tested conditions"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class EvidenceStrength(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    THIN = "thin"


class Disposition(StrEnum):
    OPEN = "open"
    DISMISSED = "dismissed"
    ACCEPTED_RISK = "accepted_risk"
    RESOLVED = "resolved"


ReviewerText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
CommitHash = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40)
]


class DispositionUpdate(Contract):
    """Compare-and-append intent; no evidence or runtime fields are writable."""

    snapshot_id: Sha256
    expected_version: int = Field(ge=0, le=100, strict=True)
    previous_disposition: Disposition
    disposition: Disposition
    reason: ReviewerText
    actor: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    resolution_commit: CommitHash | None = None

    @model_validator(mode="after")
    def _transition(self) -> Self:
        if self.disposition == self.previous_disposition:
            raise ValueError("a reviewer decision changes the disposition")
        if (
            self.disposition is not Disposition.OPEN
            and self.previous_disposition is not Disposition.OPEN
        ):
            raise ValueError("reopen before making a different closing decision")
        if (self.disposition is Disposition.RESOLVED) != (self.resolution_commit is not None):
            raise ValueError("resolution requires a linked commit; other decisions omit it")
        if any(ord(c) < 32 for c in self.reason + self.actor):
            raise ValueError("reviewer text must be one line without control characters")
        return self


class DispositionDecision(DispositionUpdate):
    run_id: Id
    finding_id: Id
    original_finding_sha256: Sha256
    version: int = Field(ge=1, le=100, strict=True)
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def _version(self) -> Self:
        if self.version != self.expected_version + 1:
            raise ValueError("a decision advances exactly one version")
        return self


class ExhibitRole(StrEnum):
    EVIDENCE = "evidence"
    SOURCE = "source"
    SINK = "sink"
    GUARD = "guard"
    DEVIANT = "deviant"
    DEVELOPER_NOTE = "developer_note"  # comments: shown, never evidence


ExhibitTag = Annotated[str, StringConstraints(pattern=r"^E\d{2,3}$")]


class Exhibit(Contract):
    tag: ExhibitTag
    span: SourceSpan
    role: ExhibitRole
    gloss: str  # one sentence: why this exhibit matters


class ChallengeCheck(Contract):
    """One acquittal checklist item and what the search found (negative evidence)."""

    item: str  # "A query filter scoped to the principal"
    searched: str  # where it looked, for example "services/orders.py:12-30"
    found: bool
    exhibit_tag: ExhibitTag | None = None

    @model_validator(mode="after")
    def _found_cites_code(self) -> Self:
        if self.found and self.exhibit_tag is None:
            raise ValueError(f"check {self.item!r} was found, so it must cite an exhibit")
        return self


class FlowStep(Contract):
    label: str  # "request query parameter `sort`", "f-string into ORDER BY"
    exhibit_tag: ExhibitTag


class Finding(Contract):
    """A case file. The five evidence-contract fields are independent (PROJECT_PLAN §6)."""

    id: Id
    display_id: Annotated[str, StringConstraints(pattern=r"^F-\d{2,}$")]
    run_id: Id
    snapshot_id: Sha256
    family: Family
    cwe: list[Annotated[int, Field(gt=0)]] = Field(min_length=1)
    title: str
    lede: str
    conclusion: Conclusion
    runtime_verification: RuntimeVerification = RuntimeVerification.NOT_ATTEMPTED
    severity: Severity
    severity_rationale: str = Field(min_length=1)
    strength: EvidenceStrength
    gaps: list[str] = []
    disposition: Disposition = Disposition.OPEN
    disposition_reason: str | None = None
    exhibits: list[Exhibit]
    checks: list[ChallengeCheck] = []
    flow: list[FlowStep] = []
    peer_group_id: Id | None = None
    unknowns: list[str] = []
    question_ids: list[Id] = []
    probe_run_ids: list[Id] = []
    suggested_change_id: Id | None = None
    policy_basis: list[BoundPolicy] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _evidence_rules(self) -> Self:
        if any(p.snapshot_id != self.snapshot_id for p in self.policy_basis):
            raise ValueError("finding requirements belong to its snapshot")
        by_tag = {e.tag: e for e in self.exhibits}
        if len(by_tag) != len(self.exhibits):
            raise ValueError("exhibit tags are unique within a finding")
        if any(e.span.snapshot_id != self.snapshot_id for e in self.exhibits):
            raise ValueError("every exhibit cites the finding's snapshot")
        cited = [c.exhibit_tag for c in self.checks if c.exhibit_tag] + [
            s.exhibit_tag for s in self.flow
        ]
        if missing := sorted(set(cited) - set(by_tag)):
            raise ValueError(f"unknown exhibit tags: {missing}")
        found_roles = [
            by_tag[c.exhibit_tag].role for c in self.checks if c.found and c.exhibit_tag is not None
        ]
        if ExhibitRole.DEVELOPER_NOTE in found_roles:
            raise ValueError("a comment is never evidence that a check was found")
        if self.conclusion is Conclusion.REJECTED and ExhibitRole.GUARD not in found_roles:
            raise ValueError("a rejection must cite a guard found in code")
        if self.runtime_verification is RuntimeVerification.REPRODUCED and not self.probe_run_ids:
            raise ValueError("'reproduced' requires the probe run on record")
        if self.strength is not EvidenceStrength.COMPLETE and not self.gaps:
            raise ValueError("partial or thin evidence must name its gaps")
        if self.disposition is Disposition.DISMISSED and not self.disposition_reason:
            raise ValueError("a dismissal records its reason")
        return self
