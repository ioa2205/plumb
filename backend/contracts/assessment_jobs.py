"""Explicit local analysis and reviewed lab collection transport."""

from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from backend.contracts.assessment import AttachmentReview
from backend.contracts.assessment_engine import (
    ControlledHTTPPermission,
    ControlledHTTPPreview,
    ControlledHTTPResult,
)
from backend.contracts.common import Contract, Id, Sha256


class ObservationAnalysisRequest(Contract):
    comparison_id: Id
    profile: str = Field(default="auto", max_length=128)
    approach: Literal["baseline", "facts", "decomposed"] = "baseline"
    guidance_card_id: str | None = Field(default=None, min_length=1, max_length=96)


class LabActionPreviewRequest(Contract):
    invoice: bool = Field(default=False, strict=True)
    paired: bool = Field(default=False, strict=True)


class LabActionPreview(Contract):
    preview: ControlledHTTPPreview
    preview_sha256: Sha256


class LabActionRunRequest(Contract):
    preview_sha256: Sha256
    permission: ControlledHTTPPermission


class LabCollectionImportRequest(Contract):
    preview_sha256: Sha256
    review: AttachmentReview
    prepare_website_comparisons: bool = False


class LabCollectionCheckpoint(Contract):
    assessment_id: Id
    preview_sha256: Sha256
    preview: ControlledHTTPPreview
    phase: Literal["proposed", "approved", "executing", "completed", "stopped", "interrupted"]
    permission: ControlledHTTPPermission | None = None
    result: ControlledHTTPResult | None = None
    updated_at: AwareDatetime
    message: str = Field(min_length=1, max_length=4096)
    automatic_replay_allowed: Literal[False] = False
    evidence_review_required: Literal[True] = True

    @model_validator(mode="after")
    def exact_binding(self) -> "LabCollectionCheckpoint":
        if (
            self.preview.assessment_id != self.assessment_id
            or self.preview.sha256 != self.preview_sha256
            or (self.permission and self.permission.preview_sha256 != self.preview_sha256)
            or (self.result and self.result.preview_sha256 != self.preview_sha256)
        ):
            raise ValueError("checkpoint requires one exact scoped proposal")
        if self.phase != "proposed" and self.permission is None:
            raise ValueError("execution checkpoint requires explicit separate action permission")
        return self


class AssessmentJob(Contract):
    job_id: Id
    assessment_id: Id
    action: Literal["analyze", "collect"]
    state: Literal["queued", "running", "completed", "canceled", "failed"]
    created_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    result: dict[str, JsonValue] | None = None
    message: str
