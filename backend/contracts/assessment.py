"""Separate, source-free assessment contracts; observations never become source proof."""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, JsonValue, field_validator, model_validator

from backend.contracts.common import Contract, Id, Sha256

Text = Annotated[str, Field(min_length=1, max_length=4096)]
PortableId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")]


def normalized_path(value: str) -> str:
    decoded = value
    for _ in range(4):
        updated = unquote(decoded)
        if updated == decoded:
            break
        decoded = updated
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(char) < 32 for char in decoded)
        or any(part in {".", ".."} for part in decoded.split("/"))
        or "?" in decoded
        or "#" in decoded
        or "%" in decoded
    ):
        raise ValueError("scope path must be absolute, canonical and contain no escapes")
    return decoded


class AssessmentBudget(Contract):
    max_requests: int = Field(default=3, ge=1, le=30)
    max_seconds: int = Field(default=180, ge=1, le=3600)


class ScopeAuthority(Contract):
    granted_by: Text
    reference: Text
    granted_at: datetime

    @field_validator("granted_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("authority time requires an explicit timezone")
        return value


class TestAccount(Contract):
    account_id: Id
    role: Text
    label: Text


class SyntheticObject(Contract):
    object_id: Id
    owner_account_id: Id
    kind: Text
    synthetic: Literal[True] = True
    synthetic_marker: str | None = Field(default=None, min_length=1, max_length=256)


class AssessmentScope(Contract):
    scope_id: PortableId
    assessment_id: PortableId
    application_id: Id
    application_name: Text
    origin: Text
    allowed_paths: list[Text] = Field(min_length=1, max_length=100)
    allowed_actions: list[
        Literal[
            "read",
            "compare",
            "plan",
            "report",
            "analyze",
            "collect",
            "authenticate",
            "create_synthetic",
        ]
    ] = Field(min_length=1, max_length=8)
    accounts: list[TestAccount] = Field(min_length=1, max_length=20)
    synthetic_objects: list[SyntheticObject] = Field(default_factory=list, max_length=100)
    authority: ScopeAuthority
    expires_at: datetime
    budget: AssessmentBudget = Field(default_factory=AssessmentBudget)
    stop_conditions: list[Text] = Field(min_length=1, max_length=20)
    external_access_enabled: Literal[False] = False

    @field_validator("scope_id", "assessment_id")
    @classmethod
    def portable(cls, value: str) -> str:
        if value.upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *[f"COM{i}" for i in range(1, 10)],
            *[f"LPT{i}" for i in range(1, 10)],
        }:
            raise ValueError("scope identifiers must not be Windows device names")
        return value

    @field_validator("origin")
    @classmethod
    def origin_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(ord(char) < 33 for char in value)
        ):
            raise ValueError(
                "application origin must be an explicit HTTP origin without credentials"
            )
        # Validate the port even when it is not consumed yet.
        _ = parsed.port
        return value.rstrip("/")

    @field_validator("allowed_paths")
    @classmethod
    def paths(cls, values: list[str]) -> list[str]:
        return [normalized_path(value) for value in values]

    @model_validator(mode="after")
    def relationships(self) -> "AssessmentScope":
        if self.expires_at.tzinfo is None or self.expires_at <= self.authority.granted_at:
            raise ValueError("scope expiry must follow authority and include a timezone")
        ids = [item.account_id for item in self.accounts]
        object_ids = [item.object_id for item in self.synthetic_objects]
        if len(ids) != len(set(ids)) or len(object_ids) != len(set(object_ids)):
            raise ValueError("designated account and synthetic object IDs must be unique")
        if any(item.owner_account_id not in ids for item in self.synthetic_objects):
            raise ValueError("synthetic object owner must be a designated account")
        return self


class AttachmentReview(Contract):
    reviewed_by: Text
    confirmed_sanitized: Literal[True]
    reviewed_at: datetime

    @field_validator("confirmed_sanitized", mode="before")
    @classmethod
    def confirmed(cls, value: object) -> object:
        if value is not True:
            raise ValueError("human review requires the explicit boolean true")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("human review time requires a timezone")
        return value


class ObservationContext(Contract):
    account_id: Id
    object_id: Id
    session_context_id: Id
    request_context_id: Id


class LabCollectionBinding(Contract):
    manifest_sha256: Sha256
    scope_origin: Text
    runner_origin: Text
    preview_sha256: Sha256


class EvidenceArtifact(Contract):
    artifact_id: Id
    assessment_id: Id
    kind: Literal["request_response", "note", "screenshot"]
    sha256: Sha256
    collected_at: datetime
    imported_at: datetime
    provenance: Text
    review: AttachmentReview
    fields: dict[str, str] = Field(min_length=1, max_length=200)
    context: ObservationContext | None = None
    execution_status: Literal["imported"] = "imported"
    attachment_path: str | None = None
    trusted_lab_collection: LabCollectionBinding | None = None

    @model_validator(mode="after")
    def coherent(self) -> "EvidenceArtifact":
        if self.collected_at.tzinfo is None or self.imported_at.tzinfo is None:
            raise ValueError("artifact times require a timezone")
        if self.kind == "request_response" and self.context is None:
            raise ValueError("request observations require designated context")
        if self.kind != "screenshot" and self.attachment_path is not None:
            raise ValueError("only reviewed screenshots have an attachment")
        if (
            sum(len(key.encode()) + len(value.encode()) for key, value in self.fields.items())
            > 262144
        ):
            raise ValueError("artifact field budget exceeded")
        return self


class EvidenceCitation(Contract):
    artifact_id: Id
    field: Text
    sha256: Sha256


class AccessExpectation(Contract):
    expectation_id: Id
    path: Text
    object_id: Id
    allowed_account_ids: list[Id] = Field(min_length=1, max_length=20)
    statement: Text
    declared_by: Text
    basis: Text

    @field_validator("path")
    @classmethod
    def path_valid(cls, value: str) -> str:
        return normalized_path(value)


class ComparisonRequest(Contract):
    left_artifact_id: Id
    right_artifact_id: Id
    control_artifact_id: Id | None = None
    expectation_id: Id | None = None


class ObservationComparison(Contract):
    comparison_id: Id
    request: ComparisonRequest
    conclusion: Literal["candidate", "rejected", "inconclusive"]
    summary: Text
    citations: list[EvidenceCitation] = Field(default_factory=list, max_length=100)
    missing_evidence: list[Text] = Field(default_factory=list, max_length=30)
    alternative_explanations: list[Text] = Field(default_factory=list, max_length=30)
    execution_status: Literal["imported"] = "imported"


class AssessmentTask(Contract):
    task_id: Id
    target_id: Id
    action: Literal["compare", "explain", "missing", "plan", "report", "analyze", "source_review"]
    prompt: Text
    evidence_ids: list[Id] = Field(default_factory=list, max_length=3)
    focus: str = Field(default="", max_length=256)
    budget: AssessmentBudget = Field(default_factory=AssessmentBudget)
    status: Literal["resolved", "clarification_required", "refused"] = "resolved"
    clarification: str | None = Field(default=None, max_length=4096)
    authorization_granted: Literal[False] = False
    network_activity: Literal[False] = False


class AssessmentAnswer(Contract):
    answer_id: Id
    task: AssessmentTask
    text: Text
    citations: list[EvidenceCitation] = Field(default_factory=list, max_length=100)
    unknowns: list[Text] = Field(default_factory=list, max_length=30)
    generated_by: Literal["deterministic", "local_model"] = "deterministic"


class ObservedEndpoint(Contract):
    endpoint_id: Id
    method: Text
    path: Text
    account_ids: list[Id]
    object_ids: list[Id]
    artifact_ids: list[Id]
    citations: list[EvidenceCitation]
    coverage: Literal["observed_import"] = "observed_import"


class ObservedMap(Contract):
    assessment_id: Id
    endpoints: list[ObservedEndpoint] = Field(default_factory=list, max_length=100)
    declared_roles: list[TestAccount]
    unknowns: list[Text]
    collection_performed: Literal[False] = False


class ChecklistItem(Contract):
    check_id: Id
    path: Text
    action: Literal["read"] = "read"
    account_ids: list[Id]
    object_ids: list[Id]
    expectation_id: Id | None = None
    status: Literal["planned", "observations_available", "compared"] = "planned"
    instructions: Text
    artifact_ids: list[Id] = Field(default_factory=list)
    limitations: list[Text] = Field(default_factory=list)


class AssessmentChecklist(Contract):
    assessment_id: Id
    items: list[ChecklistItem]
    untested_paths: list[Text]
    execution_status: Literal["plan_only"] = "plan_only"


class ReportClaim(Contract):
    text: Text
    citations: list[EvidenceCitation] = Field(min_length=1, max_length=100)


class AssessmentReport(Contract):
    assessment_id: Id
    title: Text
    description: Text
    affected_endpoints: list[str]
    safe_reproduction: list[Text]
    impact: Text
    claims: list[ReportClaim]
    evidence: list[EvidenceArtifact]
    expected_behavior: list[AccessExpectation]
    comparisons: list[ObservationComparison]
    mitigation: list[Text]
    tools_and_models: list[Text]
    methodology: list[Text]
    limitations: list[Text]
    dismissed_leads: list[Text]
    tested_coverage: list[str]
    untested_coverage: list[str]
    confidentiality: Literal["private_local"] = "private_local"
    runtime_verification: Literal["not_attempted"] = "not_attempted"
    human_preview_required: Literal[True] = True


class AssessmentView(Contract):
    scope: AssessmentScope
    artifacts: list[EvidenceArtifact] = Field(default_factory=list, max_length=100)
    expectations: list[AccessExpectation] = Field(default_factory=list, max_length=100)
    comparisons: list[ObservationComparison] = Field(default_factory=list, max_length=100)
    answers: list[AssessmentAnswer] = Field(default_factory=list, max_length=100)
    analyses: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=100)
    stopped: bool = False
    stop_reason: str | None = Field(default=None, max_length=4096)
    spent_requests: int = Field(default=0, ge=0)
    spent_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)


class ScopeCreate(Contract):
    scope: AssessmentScope
    confirmed_authority: Literal[True]

    @field_validator("confirmed_authority", mode="before")
    @classmethod
    def confirmed(cls, value: object) -> object:
        if value is not True:
            raise ValueError("authority confirmation requires the explicit boolean true")
        return value


class EvidenceImportRequest(Contract):
    payload: str = Field(min_length=1, max_length=2097152)
    review: AttachmentReview


class TaskResolveRequest(Contract):
    prompt: Text
    evidence_ids: list[Id] = Field(default_factory=list, max_length=3)
    budget: AssessmentBudget = Field(default_factory=AssessmentBudget)


class AssessmentList(Contract):
    assessments: list[AssessmentScope]


class ReportPreview(Contract):
    report: AssessmentReport
    markdown: str = Field(max_length=1048576)
    preview_sha256: Sha256
    export_path: str | None = None
    submitted: Literal[False] = False


class PrivateReportRequest(Contract):
    review: AttachmentReview
    preview_sha256: Sha256


ResolvedTask = AssessmentTask
