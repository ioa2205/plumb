"""Observed source support and historical acceptance remain separate."""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.common import Contract, RelPath, Sha256

SourceLevel = Literal["observed", "partial", "unverified", "not_applicable"]


class CapabilityEvidence(Contract):
    record: RelPath
    sha256: Sha256
    scope: str = Field(min_length=1, max_length=1000)
    current_engine_acceptance: Literal[False] = False


class CapabilityRow(Contract):
    category: Literal["language", "framework", "family"]
    name: str = Field(min_length=1, max_length=100)
    units: int | None = Field(default=None, ge=0)
    parsed_units: int | None = Field(default=None, ge=0)
    indexed_units: int | None = Field(default=None, ge=0)
    parsed: SourceLevel
    indexed: SourceLevel
    workflow_implemented: bool
    investigated: Literal[False] = False
    runtime_testable: Literal[False] = False
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _counts(self) -> Self:
        for level, count in ((self.parsed, self.parsed_units), (self.indexed, self.indexed_units)):
            if self.units is None:
                if count is not None or level not in {"unverified", "not_applicable"}:
                    raise ValueError("unobserved support cannot claim source counts")
            elif (
                count is None
                or count > self.units
                or level
                != (
                    "unverified"
                    if not self.units
                    else "observed"
                    if count == self.units
                    else "partial"
                )
            ):
                raise ValueError("source level must preserve its observed denominator")
        return self


class CapabilityTable(Contract):
    schema_version: Literal[1] = 1
    registry_sha256: Sha256
    snapshot_id: Sha256 | None = None
    rows: list[CapabilityRow] = Field(max_length=10)
    evidence: list[CapabilityEvidence] = Field(max_length=10)
    runtime_note: str
    quality_note: str

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if len({(r.category, r.name) for r in self.rows}) != len(self.rows):
            raise ValueError("capability rows must be unique")
        if self.snapshot_id is None and any(r.units is not None for r in self.rows):
            raise ValueError("source observations require their snapshot")
        return self
