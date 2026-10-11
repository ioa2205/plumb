"""Read-only local conversation; answers never grant action authority."""

from typing import Literal

from pydantic import Field, model_validator

from backend.contracts.assessment import EvidenceCitation
from backend.contracts.code import SourceSpan
from backend.contracts.common import Contract, Sha256


class ConversationCreate(Contract):
    target_kind: Literal["inspection", "review", "assessment"]
    target_id: str = Field(min_length=1, max_length=96)


class ConversationAsk(Contract):
    prompt: str = Field(min_length=1, max_length=4096)
    profile: str = Field(default="auto", min_length=1, max_length=96)
    max_seconds: int = Field(default=300, ge=1, le=300)


class ConversationEvidence(Contract):
    reference_id: str = Field(pattern=r"^R[0-9]{3}$")
    label: str = Field(min_length=1, max_length=512)
    quote: str = Field(min_length=1, max_length=4096)
    source: SourceSpan | None = None
    observation: EvidenceCitation | None = None
    model_quote: str | None = Field(default=None, exclude=True, max_length=4096)

    @model_validator(mode="after")
    def _one_kind(self) -> "ConversationEvidence":
        if (self.source is None) == (self.observation is None):
            raise ValueError("conversation evidence requires exactly one citation kind")
        return self


class ConversationTurn(Contract):
    prompt: str = Field(min_length=1, max_length=4096)
    answer: str = Field(min_length=1, max_length=8192)
    evidence: list[ConversationEvidence] = Field(max_length=8)
    unknowns: list[str] = Field(max_length=30)
    generated_by: Literal["local_model", "unresolved"]
    evidence_sha256: Sha256
    authorization_granted: Literal[False] = False
    actions_executed: Literal[False] = False
    verdict_changed: Literal[False] = False


class ConversationView(ConversationCreate):
    conversation_id: str = Field(pattern=r"^conversation-[0-9a-f]{32}$")
    state: Literal["idle", "running", "completed", "failed", "canceled"] = "idle"
    turns: list[ConversationTurn] = Field(default_factory=list, max_length=20)
    message: str = Field(default="Ready for a local evidence question.", max_length=512)
    confidentiality: Literal["private_local"] = "private_local"
