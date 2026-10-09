"""Supplementary observations, separate from investigated findings and coverage."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.code import SourceSpan
from backend.contracts.common import Contract, Id, Sha256


class SecuritySignal(Contract):
    id: Id
    category: Literal["secret", "configuration", "dependency"]
    status: Literal["observed", "unknown"]
    source: SourceSpan
    rule_id: Id
    rule_version: str = Field(max_length=100)
    summary: str = Field(max_length=600)
    # No source snippets or credential values are transported.
    fingerprint: Sha256 | None = None
    ecosystem: Literal["npm", "PyPI"] | None = None
    package: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=100)
    advisory_id: Id | None = None
    limitations: list[str] = Field(max_length=8)


class SignalSet(Contract):
    run_id: Id
    snapshot_id: Sha256
    tool_version: str
    status: Literal["ok", "partial", "not_run"]
    signals: list[SecuritySignal] = Field(default=[], max_length=100)
    pack_sha256: Sha256 | None = None
    pack_date: date | None = None
    pack_source: str | None = None
    limitations: list[str] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _same_snapshot(self) -> Self:
        if len({s.id for s in self.signals}) != len(self.signals) or any(
            s.source.snapshot_id != self.snapshot_id for s in self.signals
        ):
            raise ValueError("signals require unique identities on their frozen snapshot")
        if (self.pack_sha256 is None) != (self.pack_date is None):
            raise ValueError("advisory provenance requires both hash and date")
        if self.status == "not_run" and self.signals:
            raise ValueError("an unrun signal check cannot publish observations")
        return self
