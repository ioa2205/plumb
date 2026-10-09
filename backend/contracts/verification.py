"""Differential proof: probe runs and suggested changes (PROJECT_PLAN §3.4)."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.contracts.code import SourceSpan
from backend.contracts.common import Contract, Id, RelPath, Sha256


class RunnerKind(StrEnum):
    BUNDLED_LAB = "bundled_lab"
    WINDOWS_SANDBOX = "windows_sandbox"
    DOCKER = "docker"


class StepRole(StrEnum):
    SETUP = "setup"
    ATTACK = "attack"
    CONTROL = "control"


class Access(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class HTTPProbeRequest(Contract):
    role: StepRole
    principal: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    method: Literal["GET", "POST"]
    path: str = Field(min_length=1, max_length=512)
    body: dict[str, JsonValue] | None = None
    capture: dict[str, str] = Field(default_factory=dict, max_length=3)
    expected_if_safe: Access

    @field_validator("path")
    @classmethod
    def _relative_http_path(cls, path: str) -> str:
        if (
            not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or "#" in path
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
        ):
            raise ValueError("probe paths must be relative HTTP paths without controls")
        parsed = urlsplit(path)
        if parsed.netloc or parsed.scheme:
            raise ValueError("probe paths cannot choose a host")
        return path


class ProbeSpec(Contract):
    """Data for a trusted transport; never a script or a model-written command."""

    id: Id
    finding_id: Id
    marker: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,128}$")]
    requests: list[HTTPProbeRequest] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _attack_and_control(self) -> Self:
        if not any(r.role is StepRole.ATTACK for r in self.requests) or not any(
            r.role is StepRole.CONTROL for r in self.requests
        ):
            raise ValueError("a probe requires attack and control requests")
        seen = False
        for r in self.requests:
            if r.role is not StepRole.SETUP:
                seen = True
            elif seen:
                raise ValueError("setup must precede attack and control")
            if (r.role is StepRole.ATTACK and r.expected_if_safe is not Access.DENIED) or (
                r.role is StepRole.CONTROL and r.expected_if_safe is not Access.ALLOWED
            ):
                raise ValueError("attack expects denial and control expects allowance")
        return self


DENIAL_STATUSES = frozenset({401, 403, 404})


class ProbeStep(Contract):
    """One request made by the trusted runner and what came back.

    ``marker_present`` says whether the victim's marker (data or effect) was observed.
    """

    role: StepRole
    principal: str
    method: str
    path: str
    expected_if_safe: Access
    status: int | None = Field(default=None, ge=100, le=599)  # None: timeout or transport error
    marker_present: bool | None = None
    error: str | None = None

    @property
    def observed(self) -> Access | None:
        """ALLOWED, DENIED, or None when the response proves neither (5xx, timeout, odd 4xx)."""
        if self.status is None or self.marker_present is None:
            return None
        if 200 <= self.status < 300:
            return Access.ALLOWED if self.marker_present else Access.DENIED
        if self.status in DENIAL_STATUSES and not self.marker_present:
            return Access.DENIED
        return None


class SnapshotRole(StrEnum):
    VULNERABLE = "vulnerable"
    PATCHED = "patched"


class ProbeOutcome(StrEnum):
    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    FIXED = "fixed"
    NOT_FIXED = "not_fixed"
    INCONCLUSIVE = "inconclusive"


def derive_outcome(snapshot_role: SnapshotRole, steps: list[ProbeStep]) -> ProbeOutcome:
    """The outcome is a function of the observations, never a claim.

    Without at least one attack and one control, or if any control is not
    clearly allowed (a vacuous probe or a broken server), the result is
    inconclusive. A timeout or a 500 is never a fix.
    """
    attacks = [s for s in steps if s.role is StepRole.ATTACK]
    controls = [s for s in steps if s.role is StepRole.CONTROL]
    if not attacks or not controls:
        return ProbeOutcome.INCONCLUSIVE
    if any(c.observed is not Access.ALLOWED for c in controls):
        return ProbeOutcome.INCONCLUSIVE
    if any(a.observed is None for a in attacks):
        return ProbeOutcome.INCONCLUSIVE
    exposed = any(a.observed is Access.ALLOWED for a in attacks)
    if snapshot_role is SnapshotRole.VULNERABLE:
        return ProbeOutcome.REPRODUCED if exposed else ProbeOutcome.NOT_REPRODUCED
    return ProbeOutcome.NOT_FIXED if exposed else ProbeOutcome.FIXED


class ProbeRun(Contract):
    id: Id
    finding_id: Id
    runner: RunnerKind
    runner_manifest_sha256: Sha256
    snapshot_id: Sha256
    snapshot_role: SnapshotRole
    steps: list[ProbeStep]
    outcome: ProbeOutcome
    started_at: AwareDatetime
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def _outcome_follows_from_steps(self) -> Self:
        derived = derive_outcome(self.snapshot_role, self.steps)
        if self.outcome is not derived:
            raise ValueError(f"outcome {self.outcome} contradicts the observed steps ({derived})")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at comes before started_at")
        return self


class ChangeStatus(StrEnum):
    PROPOSED = "proposed"  # never applied to the user's repository
    REPLAYED_FIXED = "replayed_fixed"
    REPLAYED_NOT_FIXED = "replayed_not_fixed"
    REPLAY_FAILED = "replay_failed"


class SourceEdit(Contract):
    source: SourceSpan
    file_sha256: Sha256
    action: Literal["replace", "insert_before", "insert_after", "delete"]
    code: str = Field(max_length=4000)

    @model_validator(mode="after")
    def _one_line(self) -> Self:
        if self.source.start_line != self.source.end_line:
            raise ValueError("each edit anchors one frozen line")
        if (self.action == "delete" and self.code != "") or (
            self.action != "delete" and not self.code.strip()
        ):
            raise ValueError("deletes are empty; other edits require code")
        return self


class SuggestedChange(Contract):
    """A minimal diff, applied only to a disposable copy for fix replay."""

    id: Id
    finding_id: Id
    intent: str  # one sentence
    diff: str
    files: list[RelPath] = Field(min_length=1)
    status: ChangeStatus = ChangeStatus.PROPOSED
    replay_probe_run_ids: list[Id] = []
    snapshot_id: Sha256 | None = None
    source_scope: SourceSpan | None = None
    source_edits: list[SourceEdit] = Field(default=[], max_length=4)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.source_edits:
            scope = self.source_scope
            if (
                scope is None
                or self.snapshot_id != scope.snapshot_id
                or any(
                    e.source.snapshot_id != self.snapshot_id
                    or e.source.path != scope.path
                    or not scope.start_line <= e.source.start_line <= scope.end_line
                    for e in self.source_edits
                )
                or self.files != [scope.path]
            ):
                raise ValueError("frozen edits must stay within one source scope")
            if len({e.source.start_line for e in self.source_edits}) != len(self.source_edits):
                raise ValueError("multiple edits of one line are ambiguous")
        elif self.snapshot_id is not None or self.source_scope is not None:
            raise ValueError("frozen-source provenance requires its exact edits")
        if "\n--- " not in f"\n{self.diff}" or "\n+++ " not in self.diff:
            raise ValueError("diff must be a unified diff")
        replayed = self.status is not ChangeStatus.PROPOSED
        if replayed and not self.replay_probe_run_ids:
            raise ValueError("a replay result requires its probe runs")
        return self


class FixProposal(Contract):
    id: Id
    finding_id: Id
    snapshot_id: Sha256
    status: Literal["proposed", "refused", "unavailable"]
    reason: str = Field(min_length=1, max_length=600)
    change: SuggestedChange | None = None
    probe_status: Literal["available", "unavailable"] = "unavailable"
    probe_reason: str = Field(min_length=1, max_length=600)
    probe_spec: ProbeSpec | None = None
    adapter_manifest_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _links(self) -> Self:
        if (self.status == "proposed") != (self.change is not None):
            raise ValueError("only valid proposed output has a change")
        if self.change and (
            self.change.finding_id != self.finding_id or self.change.snapshot_id != self.snapshot_id
        ):
            raise ValueError("proposal change binds its finding and frozen snapshot")
        if (self.probe_status == "available") != (self.probe_spec is not None):
            raise ValueError("available regression probes require a declarative spec")
        if self.probe_spec and (
            self.status != "proposed"
            or self.probe_spec.finding_id != self.finding_id
            or not self.adapter_manifest_sha256
        ):
            raise ValueError("probe must bind a valid proposal and trusted adapter manifest")
        return self
