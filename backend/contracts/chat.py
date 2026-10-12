"""Plain-language chat (ADR-0028): general answers, cited answers and proposed tasks.

A general answer is uncited and says so. It is never a finding, a permission or
a statement about a particular website or codebase. Anything said about a
selected target carries the exact evidence the ADR-0026 validator accepted.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.common import Contract
from backend.contracts.conversation import ConversationEvidence

Intent = Literal[
    "general_question",
    "creative_writing",
    "explain_result",
    "general_and_result",
    "review_folder",
    "test_website",
    "about_plumb",
    "unclear",
]
Rung = Literal["code", "model", "model_reordered", "user", "stop"]
TargetKind = Literal["inspection", "review", "assessment", "website"]


class ChatCreate(Contract):
    """A chat may start with nothing selected; a target is optional."""

    target_kind: TargetKind | None = None
    target_id: str | None = Field(default=None, min_length=1, max_length=96)

    @model_validator(mode="after")
    def _both_or_neither(self) -> Self:
        if (self.target_kind is None) != (self.target_id is None):
            raise ValueError("a selected target needs both its kind and its identifier")
        return self


class ChatAsk(Contract):
    prompt: str = Field(min_length=1, max_length=4096)
    profile: str = Field(default="auto", min_length=1, max_length=96)
    max_seconds: int = Field(default=300, ge=1, le=600)
    # The user's own pick after the chat asked what the message is about.
    choice: Intent | None = None


class ChatChoice(Contract):
    intent: Intent
    label: str = Field(min_length=1, max_length=160)


class ChatTask(Contract):
    """Something the user asked to have done, as a proposal. Chat never runs it."""

    kind: Literal["inspect_folder", "website_setup", "choose_result"]
    summary: str = Field(min_length=1, max_length=1024)
    ready: bool
    missing: list[str] = Field(default_factory=list, max_length=12)
    steps: list[str] = Field(default_factory=list, max_length=12)
    folder: str | None = Field(default=None, max_length=1024)
    url: str | None = Field(default=None, max_length=2048)
    authorization_granted: Literal[False] = False
    started: Literal[False] = False


class ChatPart(Contract):
    kind: Literal["general", "guidance", "cited", "notice"]
    text: str = Field(min_length=1, max_length=8192)
    # Where the text comes from, in words a newcomer can read.
    basis: str = Field(min_length=1, max_length=512)
    complete: bool = True
    evidence: list[ConversationEvidence] = Field(default_factory=list, max_length=8)
    unknowns: list[str] = Field(default_factory=list, max_length=30)
    guidance_card: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _kinds(self) -> Self:
        if self.kind != "cited" and self.evidence:
            raise ValueError("only a cited part carries evidence")
        if self.kind == "cited" and not self.evidence:
            raise ValueError("a cited part needs the exact evidence it rests on")
        if (self.kind == "guidance") != (self.guidance_card is not None):
            raise ValueError("a guidance part names its reviewed card, and only it does")
        return self


class ChatTurn(Contract):
    prompt: str = Field(min_length=1, max_length=4096)
    intent: Intent
    intent_rung: Rung
    interpretation: str = Field(min_length=1, max_length=512)
    parts: list[ChatPart] = Field(default_factory=list, max_length=4)
    task: ChatTask | None = None
    choices: list[ChatChoice] = Field(default_factory=list, max_length=8)
    limits: str = Field(min_length=1, max_length=256)
    model_requests: int = Field(default=0, ge=0, le=8)
    model_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    authorization_granted: Literal[False] = False
    actions_executed: Literal[False] = False
    finding_created: Literal[False] = False


class ChatView(ChatCreate):
    chat_id: str = Field(pattern=r"^chat-[0-9a-f]{32}$")
    state: Literal["idle", "running", "completed", "failed", "canceled"] = "idle"
    target_label: str | None = Field(default=None, max_length=256)
    turns: list[ChatTurn] = Field(default_factory=list, max_length=40)
    message: str = Field(default="Ask anything in your own words.", max_length=512)
    progress: str | None = Field(default=None, max_length=256)
    limits: str = Field(default="", max_length=256)
    confidentiality: Literal["private_local"] = "private_local"


class ChatSelect(ChatCreate):
    """Explicit selection of what follow-ups are about; made by a control, not by a message."""


class SavedResult(Contract):
    target_kind: TargetKind
    target_id: str = Field(min_length=1, max_length=96)
    label: str = Field(min_length=1, max_length=256)


class SavedResults(Contract):
    results: list[SavedResult] = Field(max_length=20)
