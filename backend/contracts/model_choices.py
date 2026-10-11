"""Read-only pinned model choices with separate quality and hardware facts."""

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.common import Contract, Sha256


class ModelQualityRecord(Contract):
    path: str = Field(pattern=r"^docs/results/[a-zA-Z0-9._/-]+\.json$")
    sha256: Sha256


class ModelProfileChoice(Contract):
    profile_id: str = Field(min_length=1, max_length=128)
    backend: Literal["cpu", "vulkan"]
    hardware_compatible: bool
    memory_fit: bool
    required_ram_bytes: int = Field(ge=1)
    required_vram_bytes: int = Field(ge=0)
    available_vram_bytes: int | None = Field(ge=0)
    runtime_verified: bool
    runtime_compatible: bool | None
    first_use_check: Literal["not needed", "pending", "passed", "failed"]
    launch_available: bool
    automatic_eligible: bool
    quality_state: Literal["recorded_scoped", "untested"]
    quality_records: list[ModelQualityRecord] = Field(max_length=4)
    quality_note: str = Field(min_length=1, max_length=1024)
    conditions: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def _qualification(self) -> Self:
        if (self.quality_state == "recorded_scoped") != bool(self.quality_records):
            raise ValueError("recorded quality needs exact saved result references")
        if self.automatic_eligible != (self.quality_state == "recorded_scoped"):
            raise ValueError("untested quality cannot qualify automatic model selection")
        if self.launch_available and not all(
            (
                self.hardware_compatible,
                self.memory_fit,
                self.runtime_verified,
                self.runtime_compatible,
                self.first_use_check != "failed",
            )
        ):
            raise ValueError("model selection cannot override launch prerequisites")
        return self


class ModelChoice(Contract):
    model_id: str = Field(min_length=1, max_length=128)
    family: str = Field(min_length=1, max_length=128)
    quantization: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=1)
    verified_installed: bool
    requires_download_approval: bool
    profiles: list[ModelProfileChoice] = Field(max_length=8)
    unavailable_reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _bounds(self) -> Self:
        if self.requires_download_approval != (self.size_bytes > 500_000_000):
            raise ValueError("download approval threshold must remain unchanged")
        if not self.profiles and not self.unavailable_reason:
            raise ValueError("unavailable models need an explicit reason")
        if not self.verified_installed and any(p.launch_available for p in self.profiles):
            raise ValueError("an unverified model cannot launch")
        return self


class ModelCatalog(Contract):
    checked_at: AwareDatetime
    selected_profile: str | None
    recommended_profile: str | None
    selection_basis: str = Field(min_length=1, max_length=2048)
    available_ram_bytes: int = Field(ge=0)
    available_vram_bytes: int | None = Field(ge=0)
    models: list[ModelChoice] = Field(min_length=1, max_length=10)
    model_loaded: Literal[False] = False
    downloads_started: Literal[False] = False

    @model_validator(mode="after")
    def _identities(self) -> Self:
        profiles = [p for m in self.models for p in m.profiles]
        known = {p.profile_id for p in profiles}
        if len(known) != len(profiles) or len({m.model_id for m in self.models}) != len(
            self.models
        ):
            raise ValueError("model/profile choices must have distinct pinned identities")
        if any(
            p is not None and p not in known
            for p in (self.selected_profile, self.recommended_profile)
        ):
            raise ValueError("selected/recommended profiles must belong to the catalog")
        if (
            self.recommended_profile
            and not next(
                p for p in profiles if p.profile_id == self.recommended_profile
            ).automatic_eligible
        ):
            raise ValueError("automatic recommendations require recorded quality")
        if any(
            p.memory_fit
            != (
                self.available_ram_bytes >= p.required_ram_bytes
                and (
                    p.required_vram_bytes == 0
                    or (
                        p.available_vram_bytes is not None
                        and p.available_vram_bytes >= p.required_vram_bytes
                    )
                )
            )
            for p in profiles
        ):
            raise ValueError(
                "profile memory fit must preserve current RAM and dedicated VRAM gates"
            )
        return self
