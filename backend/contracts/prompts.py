"""Local source prompt resolution; a prompt supplies no authority."""

from typing import Literal

from pydantic import Field

from backend.contracts.common import Contract, Family, Id
from backend.contracts.investigation import Finding


class SourcePromptRequest(Contract):
    inspection_id: str = Field(pattern=r"^inspect-[0-9a-f]{32}$")
    prompt: str = Field(min_length=1, max_length=4096)
    limit: int = Field(default=5, ge=1, le=20)


class SourcePromptResolution(Contract):
    target_id: Id
    task_id: Id
    prompt: str = Field(min_length=1, max_length=4096)
    families: list[Family]
    resources: list[str]
    routes: list[str]
    limit: int = Field(ge=1, le=20)
    status: Literal["resolved", "clarification_required", "refused"]
    clarification: str | None = None
    authorization_granted: Literal[False] = False
    network_activity: Literal[False] = False


class SavedAnswerRequest(Contract):
    prompt: str = Field(min_length=1, max_length=4096)


class SavedFindingAnswer(Contract):
    run_id: Id
    prompt: str
    finding: Finding
    report_path: str
    limitations: list[str]
    generated_by: Literal["saved_evidence"] = "saved_evidence"
    network_activity: Literal[False] = False
    authorization_granted: Literal[False] = False
