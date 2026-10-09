"""Browser setup and source-only inspection, separate from recorded review runs."""

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from backend.contracts.capabilities import CapabilityTable
from backend.contracts.code import EntryPoint
from backend.contracts.common import Contract, Family, Id, Sha256
from backend.contracts.runs import Condition


class SetupReadiness(Contract):
    capabilities: CapabilityTable | None = None
    checked_at: AwareDatetime
    ready: bool
    inspect_ready: bool
    profile_id: str
    model_id: str
    model_size_bytes: int = Field(ge=1)
    model_verified: bool
    runtime_verified: bool
    measured_host: bool
    memory_fit: bool
    available_ram_bytes: int = Field(ge=0)
    required_ram_bytes: int = Field(ge=1)
    available_vram_bytes: int | None = Field(ge=0)
    # Zero when the profile uses no graphics card.
    required_vram_bytes: int = Field(ge=0)
    missing_download_bytes: int = Field(ge=0)
    requires_large_download_approval: bool
    conditions: list[Condition]
    limitations: list[str]
    model_loaded: Literal[False] = False

    @model_validator(mode="after")
    def _capability_scope(self) -> Self:
        if self.capabilities and self.capabilities.snapshot_id is not None:
            raise ValueError("setup readiness has no inspected source")
        return self

    downloads_started: Literal[False] = False

    @model_validator(mode="after")
    def _readiness(self) -> Self:
        fit = self.available_ram_bytes >= self.required_ram_bytes and (
            self.required_vram_bytes == 0
            or (
                self.available_vram_bytes is not None
                and self.available_vram_bytes >= self.required_vram_bytes
            )
        )
        if self.memory_fit != fit or self.requires_large_download_approval != (
            self.missing_download_bytes > 500_000_000
        ):
            raise ValueError("readiness must retain measured memory and download bounds")
        if self.ready and not all(
            (
                self.inspect_ready,
                self.measured_host,
                self.model_verified,
                self.runtime_verified,
                fit,
            )
        ):
            raise ValueError("readiness cannot override missing prerequisites")
        return self


class InspectRequest(Contract):
    folder: str = Field(min_length=1, max_length=4096)
    authorized: Literal[True]

    @field_validator("authorized", mode="before")
    @classmethod
    def _explicit_authorization(cls, value: object) -> object:
        if value is not True:
            raise ValueError("explicit authorization must be true")
        return value


class InspectionView(Contract):
    capabilities: CapabilityTable | None = None
    inspection_id: str | None = Field(default=None, pattern=r"^inspect-[0-9a-f]{32}$")
    snapshot_id: Sha256
    name: str
    captured_at: AwareDatetime
    languages: dict[str, int]
    frameworks: dict[str, int]
    resources: dict[str, int]
    included_files: int = Field(ge=0)
    excluded_files: int = Field(ge=0)
    exclusion_reasons: dict[str, int]
    entries: list[EntryPoint] = Field(max_length=12)
    entries_total: int = Field(ge=0)
    unresolved_links: int = Field(ge=0)
    conditions: list[Condition]
    limitations: list[str]
    model_loaded: Literal[False] = False
    target_executed: Literal[False] = False

    @model_validator(mode="after")
    def _source(self) -> Self:
        if self.capabilities and self.capabilities.snapshot_id != self.snapshot_id:
            raise ValueError("capabilities must describe this inspected snapshot")
        if (
            self.entries_total < len(self.entries)
            or len({e.id for e in self.entries}) != len(self.entries)
            or any(
                e.snapshot_id != self.snapshot_id or e.span.snapshot_id != self.snapshot_id
                for e in self.entries
            )
            or any(
                n < 0
                for counts in (
                    self.languages,
                    self.frameworks,
                    self.resources,
                    self.exclusion_reasons,
                )
                for n in counts.values()
            )
            or sum(self.exclusion_reasons.values()) != self.excluded_files
            or sum(self.frameworks.values()) != self.entries_total
        ):
            raise ValueError("inspection inventory must preserve counts and frozen citations")
        return self


class LaunchRequest(Contract):
    inspection_id: str = Field(pattern=r"^inspect-[0-9a-f]{32}$")
    authorized: Literal[True]
    limit: int = Field(default=5, ge=1, le=20)
    families: list[Family] = Field(default=[Family.AUTHORIZATION], min_length=1, max_length=4)
    resources: list[str] = Field(default=[], max_length=20)
    routes: list[str] = Field(default=[], max_length=20)

    @field_validator("authorized", mode="before")
    @classmethod
    def _authorization(cls, value: object) -> object:
        return InspectRequest._explicit_authorization(value)

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if len(set(self.families)) != len(self.families) or any(
            not 0 < len(s) <= 256 or any(ord(c) < 32 for c in s)
            for s in [*self.resources, *self.routes]
        ):
            raise ValueError("select distinct families and bounded scope")
        if self.resources and self.families != [Family.AUTHORIZATION]:
            raise ValueError("resource scope applies to authorization only")
        return self


class ResumeRequest(Contract):
    limit: int = Field(default=5, ge=1, le=20)


class SourceCheck(Contract):
    run_id: Id
    snapshot_id: Sha256
    checked_at: AwareDatetime
    state: Literal["current", "changed", "unavailable", "unassociated"]
    current_snapshot_id: Sha256 | None = None
    changed_files: int | None = Field(default=None, ge=0)
    added_files: int | None = Field(default=None, ge=0)
    removed_files: int | None = Field(default=None, ge=0)
    excluded_scope_changed: bool | None = None
    conditions: list[Condition] = []
    limitations: list[str]
    model_loaded: Literal[False] = False
    target_executed: Literal[False] = False

    @model_validator(mode="after")
    def _observed(self) -> Self:
        counts = (self.changed_files, self.added_files, self.removed_files)
        measured = self.state in {"current", "changed"}
        if measured != all(v is not None for v in counts) or measured != (
            self.current_snapshot_id is not None and self.excluded_scope_changed is not None
        ):
            raise ValueError("missing source must not fabricate counts")
        if not measured and any(
            v is not None for v in (*counts, self.current_snapshot_id, self.excluded_scope_changed)
        ):
            raise ValueError("unknown counts must stay unknown")
        if measured and (self.state == "changed") != (any(counts) or self.excluded_scope_changed):
            raise ValueError("source state must agree with measured changes")
        if self.state == "current" and self.current_snapshot_id != self.snapshot_id:
            raise ValueError("unchanged source must retain its content identity")
        return self
