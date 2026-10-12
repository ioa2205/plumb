"""What a website journey remembers (ADR-0028): durable, compact and never rewritten.

The journey's memory is this record, not a transcript. Each model request is
built from a few lines of it. Permissions, identities and evidence are stored
once and referred to by identifier; nothing here is summarized by a model.
"""

from typing import Literal, Self

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from backend.contracts.common import Contract, Id, Sha256
from backend.contracts.web import (
    ActionClass,
    BlockedRequest,
    EvidenceRef,
    Line,
    PlanApproval,
    Rung,
    Text,
    WebEvidence,
    WebsitePlan,
    WebsiteScope,
)

Stage = Literal[
    "scope", "discover", "authenticate", "map", "select", "execute", "challenge", "record", "report"
]
StepState = Literal["planned", "attempted", "completed", "uncertain", "blocked", "skipped"]


class StepRecord(Contract):
    step_id: Id
    action: ActionClass
    state: StepState = "planned"
    note: str = Field(default="", max_length=600)
    requests: int = Field(default=0, ge=0)
    evidence_ids: list[Id] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def _explained(self) -> Self:
        if self.state in {"uncertain", "blocked", "skipped"} and not self.note:
            raise ValueError("a step that did not complete says why")
        return self


class AccountRecord(Contract):
    account_id: Id
    state: Literal[
        "not_tried", "signed_in", "created", "failed", "handoff", "uncertain", "needs_sign_in"
    ] = "not_tried"
    note: str = Field(default="", max_length=600)
    # Whether protected session state for this account is kept for a restart.
    session_kept: bool = False


class PageRecord(Contract):
    """One place in the page and action map."""

    path: str = Field(max_length=512)
    account_id: Id | None = None
    via: Literal["http", "browser"]
    status: int | None = None
    title: str = Field(default="", max_length=160)
    kind: str = Field(default="", max_length=40)
    kind_rung: Rung | None = None
    links: int = Field(default=0, ge=0)
    forms: list[str] = Field(default_factory=list, max_length=12)  # purpose or heading of each
    evidence_id: Id | None = None
    blocked: list[BlockedRequest] = Field(default_factory=list, max_length=40)
    note: str = Field(default="", max_length=300)


class DecisionRecord(Contract):
    """One decision and the rung of the ladder that made it. Raw answers are kept."""

    at: AwareDatetime
    stage: Stage
    question_type: str = Field(max_length=40)
    subject: str = Field(max_length=200)
    value: str | None = Field(default=None, max_length=120)
    rung: Rung
    reason: str | None = Field(default=None, max_length=600)
    attempts: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=6)


class CheckRecord(Contract):
    """One cross-account comparison on a known synthetic object, as code computed it."""

    check_id: Id
    rule_id: Id
    object_id: Id
    path: str = Field(max_length=512)
    owner_account_id: Id
    other_account_id: Id
    state: Literal["pending", "completed", "blocked"] = "pending"
    # Computed by code from the two responses; a lead until judged.
    comparison: Literal["candidate", "protected", "inconclusive", "not_run"] = "not_run"
    facts: dict[str, str] = Field(default_factory=dict, max_length=24)
    gaps: list[Line] = Field(default_factory=list, max_length=10)
    citations: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    # After three independent readings of the owner's rule; None until asked.
    judged: Literal["supported", "not_confirmed"] | None = None
    judgment: dict[str, JsonValue] | None = None
    note: str = Field(default="", max_length=600)


class Finding(Contract):
    finding_id: Id
    title: Line
    conclusion: Literal["supported", "candidate"]
    description: Text
    affected_application: Line
    affected_endpoint: Line
    safe_reproduction: list[Line] = Field(min_length=1, max_length=10)
    potential_impact: Text
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=20)
    mitigation: Text
    methodology: list[Line] = Field(min_length=1, max_length=10)
    tools_and_models: list[Line] = Field(min_length=1, max_length=10)
    limits: list[Line] = Field(min_length=1, max_length=10)
    explanation: Text
    explanation_source: Literal["model", "code"]
    # What Plumb's own runner did, never more: one live observation with its control.
    runtime: Literal["observed_once_by_plumb_runner"] = "observed_once_by_plumb_runner"
    check_id: Id


class Incident(Contract):
    """A privacy or production-risk stop. Kinds only; the content was discarded."""

    at: AwareDatetime
    step_id: Id
    path: str = Field(max_length=512)
    kinds: list[Line] = Field(min_length=1, max_length=6)
    content_kept: Literal[False] = False


class UserChoice(Contract):
    label: str = Field(min_length=1, max_length=200)
    meaning: str = Field(min_length=1, max_length=300)


class UserQuestion(Contract):
    """The ladder's last rung: a plain question only the user can answer."""

    subject: str = Field(max_length=200)
    question_type: str = Field(max_length=40)
    text: Line
    choices: list[UserChoice] = Field(min_length=1, max_length=12)


class Spent(Contract):
    requests: int = Field(default=0, ge=0)
    bytes: int = Field(default=0, ge=0)
    seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    model_questions: int = Field(default=0, ge=0)
    model_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)


class JourneyView(Contract):
    journey_id: str = Field(pattern=r"^journey-[0-9a-f]{32}$")
    scope: WebsiteScope
    plan: WebsitePlan
    # The identity of exactly this plan. An approval must send it back.
    plan_sha256: Sha256
    approval: PlanApproval | None = None
    approval_used_at: AwareDatetime | None = None
    approval_revoked_at: AwareDatetime | None = None
    status: Literal[
        "planned", "approved", "running", "paused", "stopped", "handoff", "done", "failed"
    ] = "planned"
    stage: Stage = "scope"
    activity: str = Field(default="Waiting for the plan to be approved.", max_length=300)
    stop_reason: str | None = Field(default=None, max_length=600)
    steps: list[StepRecord] = Field(default_factory=list, max_length=60)
    accounts: list[AccountRecord] = Field(default_factory=list, max_length=6)
    pages: list[PageRecord] = Field(default_factory=list, max_length=120)
    decisions: list[DecisionRecord] = Field(default_factory=list, max_length=200)
    checks: list[CheckRecord] = Field(default_factory=list, max_length=40)
    findings: list[Finding] = Field(default_factory=list, max_length=40)
    leads: list[Line] = Field(default_factory=list, max_length=40)
    evidence: list[WebEvidence] = Field(default_factory=list, max_length=300)
    blocked: list[BlockedRequest] = Field(default_factory=list, max_length=200)
    incidents: list[Incident] = Field(default_factory=list, max_length=20)
    handoffs: list[Line] = Field(default_factory=list, max_length=12)
    waiting: list[UserQuestion] = Field(default_factory=list, max_length=20)
    spent: Spent = Field(default_factory=Spent)
    browser: Literal["not_used", "used", "unavailable"] = "not_used"
    browser_note: str = Field(default="", max_length=600)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    report_path: str | None = Field(default=None, max_length=1024)
    confidentiality: Literal["private_local"] = "private_local"

    @model_validator(mode="after")
    def _plan_identity(self) -> Self:
        if self.plan_sha256 != self.plan.sha256 or self.plan.scope_sha256 != self.scope.sha256:
            raise ValueError("the plan does not belong to this scope or changed after it was made")
        return self


class JourneyList(Contract):
    journeys: list[JourneyView] = Field(max_length=20)


class JourneyCreate(Contract):
    scope: WebsiteScope
    confirmed_authority: Literal[True]


class JourneyApprove(Contract):
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: Line
    reviewed_plan: Literal[True]
    # Step identifiers the reviewer approves; all of the plan's steps when omitted.
    step_ids: list[Id] | None = Field(default=None, max_length=60)


class FixtureCreate(Contract):
    variant: Literal["open", "defended"] = "open"


class WebsiteReadiness(Contract):
    browser_ready: bool
    browser_note: str = Field(max_length=600)
    external_ready: bool
    external_note: str = Field(max_length=600)


class JourneyRun(Contract):
    profile: str = Field(default="auto", min_length=1, max_length=96)
    use_model: bool = True
    # Secret values by reference, entered by the reviewer for this run only.
    secrets: dict[str, str] = Field(default_factory=dict, max_length=12)
    # The user's answers to the journey's waiting questions: subject -> chosen label.
    answers: dict[str, str] = Field(default_factory=dict, max_length=20)


class HumanAuthView(Contract):
    """A private, transient view of one approved account's live challenge."""

    view_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    step_id: Id
    account_id: Id
    label: Line
    challenge: Literal["captcha", "one_time_code", "single_sign_on"]
    question: Line
    screenshot_png: str = Field(max_length=4 * 1024 * 1024)
    width: int = Field(default=1280, ge=1, le=1280)
    height: int = Field(default=900, ge=1, le=900)
    ready: Literal[True] = True


class HumanAuthInput(Contract):
    """Only a person supplies these events; text is never saved or reported."""

    view_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    kind: Literal["pointer", "text", "submit", "completed", "pause", "refresh"]
    x: int | None = Field(default=None, ge=0, lt=1280)
    y: int | None = Field(default=None, ge=0, lt=900)
    text: str | None = Field(default=None, min_length=1, max_length=1024, repr=False)

    @model_validator(mode="after")
    def _event(self) -> Self:
        if self.kind == "pointer":
            if self.x is None or self.y is None or self.text is not None:
                raise ValueError("a pointer event needs only viewport coordinates")
        elif self.kind == "text":
            if self.text is None or self.x is not None or self.y is not None:
                raise ValueError("a text event needs only private input text")
            if any(ord(char) < 32 for char in self.text):
                raise ValueError("private input text must be a single line")
        elif self.x is not None or self.y is not None or self.text is not None:
            raise ValueError("this human event has no extra payload")
        return self
