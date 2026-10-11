"""Typed local observation judgments and explicitly reviewed owned-lab collection."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from backend.contracts.assessment import EvidenceCitation
from backend.contracts.common import Contract, Id, Sha256
from backend.contracts.verification import ProbeSpec


class ObservationClaim(Contract):
    citation: EvidenceCitation
    value: str = Field(max_length=16384)


class ObservationJudgment(Contract):
    verdict: Literal["supported", "rejected", "inconclusive"]
    claims: list[ObservationClaim] = Field(min_length=1, max_length=30)
    rationale: str = Field(min_length=1, max_length=2048)
    alternative_explanations: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(
        min_length=1, max_length=10
    )
    missing_evidence: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(
        min_length=1, max_length=10
    )
    mitigation: str = Field(min_length=1, max_length=2048)


class ValidatedObservationJudgment(Contract):
    seed: int
    evidence_order: list[str] = Field(max_length=100)
    answer: ObservationJudgment | None = None
    raw_answer: str | None = Field(default=None, max_length=65536)
    violations: list[str] = Field(default_factory=list)
    error: str | None = None


class ObservationAnalysis(Contract):
    comparison_id: Id
    conclusion: Literal["supported", "rejected", "inconclusive"]
    judgments: list[ValidatedObservationJudgment]
    citations: list[EvidenceCitation]
    alternative_explanations: list[str]
    missing_evidence: list[str]
    requests_used: int = Field(ge=0, le=30)
    seconds: float = Field(ge=0)
    stop_reason: str | None = None
    packet_sha256: Sha256
    generated_by: Literal["local_model"] = "local_model"
    runtime_verification: Literal["not_attempted"] = "not_attempted"
    model_provenance: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(
        default_factory=list, max_length=20
    )


class ControlledHTTPAction(Contract):
    action_id: Id
    account_id: Literal["alice", "bob"] | None
    method: Literal["GET", "POST"]
    path: str
    purpose: Literal["readiness", "authenticate", "create_synthetic", "read"]
    max_attempts: int = Field(default=1, ge=1, le=4)
    body_preview: dict[str, JsonValue] | None = None
    state_change: bool


class ControlledHTTPPreview(Contract):
    preview_id: Id
    assessment_id: Id
    scope_sha256: Sha256
    runner_manifest_sha256: Sha256
    synthetic_object_id: Id
    spec: ProbeSpec
    control_spec: ProbeSpec | None = None
    actions: list[ControlledHTTPAction] = Field(min_length=6, max_length=9)
    created_at: AwareDatetime
    expires_at: AwareDatetime
    max_requests: int = Field(ge=1, le=30)
    max_seconds: int = Field(ge=1, le=3600)
    max_response_bytes: int = Field(default=65536, ge=1, le=65536)
    max_total_bytes: int = Field(default=786432, ge=1, le=786432)
    runner: Literal["hash_pinned_owned_tandir"] = "hash_pinned_owned_tandir"
    external_access_enabled: Literal[False] = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


class ControlledHTTPPermission(Contract):
    preview_sha256: Sha256
    approved_action_ids: list[Id] = Field(min_length=1, max_length=9)
    approved_by: str = Field(min_length=1, max_length=256)
    granted_at: AwareDatetime
    expires_at: AwareDatetime
    reviewed_preview: Literal[True]

    @field_validator("reviewed_preview", mode="before")
    @classmethod
    def explicit_review(cls, value: object) -> object:
        if value is not True:
            raise ValueError("explicit reviewed-preview confirmation must be boolean true")
        return value


class HTTPActionProgress(Contract):
    action_id: Id
    attempts: int = Field(default=0, ge=0, le=4)
    completed: bool = False
    artifact_ids: list[Id] = Field(default_factory=list, max_length=1)
    missing_evidence: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(
        default_factory=list, max_length=4
    )

    @model_validator(mode="after")
    def coherent(self) -> "HTTPActionProgress":
        if self.completed and (self.attempts == 0 or self.missing_evidence):
            raise ValueError("completed action requires an attempt and no missing action evidence")
        if self.artifact_ids and not self.completed:
            raise ValueError("only completed sanitized actions may bind evidence")
        return self


class ControlledHTTPResult(Contract):
    preview_id: Id
    preview_sha256: Sha256
    runner_manifest_sha256: Sha256
    runner_origin: str | None = None
    records: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=6)
    requests_used: int = Field(ge=0, le=30)
    bytes_received: int = Field(
        default=0,
        ge=0,
        le=917504,
        description="Counted decoded body and normalized header bytes; excludes HTTP wire framing.",
    )
    action_progress: list[HTTPActionProgress] = Field(default_factory=list, max_length=9)
    seconds: float = Field(ge=0)
    stopped: bool
    stop_reason: str | None = None
    execution_status: Literal["collected_owned_lab"] = "collected_owned_lab"
    runtime_verification: Literal["not_attempted"] = "not_attempted"

    @model_validator(mode="after")
    def coherent_progress(self) -> "ControlledHTTPResult":
        if self.action_progress:
            ids = [row.action_id for row in self.action_progress]
            artifacts = {
                record["artifact_id"]
                for record in self.records
                if isinstance(record.get("artifact_id"), str)
            }
            if (
                len(ids) != len(set(ids))
                or sum(row.attempts for row in self.action_progress) != self.requests_used
            ):
                raise ValueError("action checkpoint identities and attempts must match accounting")
            if any(
                identity not in artifacts
                for row in self.action_progress
                for identity in row.artifact_ids
            ):
                raise ValueError("completed evidence must exist in the sanitized checkpoint")
        return self
