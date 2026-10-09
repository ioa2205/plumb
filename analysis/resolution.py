"""Snapshot call graph shared by language resolvers. Unknown edges stay visible."""

import sqlite3
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.code import SourceSpan
from backend.contracts.common import Contract, Id, Sha256
from backend.contracts.common import LinkStatus as LinkStatus


class CallEdge(Contract):
    caller_id: Id
    target_id: Id | None
    callee: str
    span: SourceSpan
    reference_line: int = Field(ge=1)
    column: int = Field(ge=0)  # zero-based UTF-16 position of the callee's final identifier
    status: LinkStatus
    via: str
    reason: str
    kind: Literal["call", "reference"] = "call"
    platform_operation: Literal["number_conversion", "form_data_read"] | None = None

    @model_validator(mode="after")
    def _target_status(self) -> Self:
        if (self.target_id is None) != (self.status is LinkStatus.UNRESOLVED):
            raise ValueError("only unresolved edges have no target")
        if not self.span.start_line <= self.reference_line <= self.span.end_line:
            raise ValueError("reference position must lie in the cited span")
        if self.platform_operation is not None and (
            self.via != "typescript" or self.target_id is not None or self.kind != "call"
        ):
            raise ValueError("platform provenance belongs only to external TypeScript calls")
        return self


class CallGraph(Contract):
    snapshot_id: Sha256
    language: str
    resolver_version: str
    platform_sha256: Sha256 | None = None
    edges: list[CallEdge]
    issues: list[str] = Field(default_factory=list)
    peak_rss_bytes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _same_snapshot(self) -> Self:
        if any(e.span.snapshot_id != self.snapshot_id for e in self.edges):
            raise ValueError("call edges must cite this snapshot")
        return self

    def callers(self, target_id: str) -> list[CallEdge]:
        return [edge for edge in self.edges if edge.target_id == target_id]

    def calls(self, caller_id: str) -> list[CallEdge]:
        return [edge for edge in self.edges if edge.caller_id == caller_id]

    def save(self, path: Path) -> None:
        """One graph per snapshot and language, in its own SQLite cache file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS graph (id INTEGER PRIMARY KEY, payload TEXT)")
            db.execute("INSERT OR REPLACE INTO graph VALUES (1, ?)", (self.model_dump_json(),))

    @classmethod
    def open(cls, path: Path) -> Self:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = db.execute("SELECT payload FROM graph WHERE id = 1").fetchone()
            if row is None:
                raise ValueError("call graph is empty")
            return cls.model_validate_json(row[0])
        finally:
            db.close()


def graph_path(cache: Path, snapshot_id: str, language: str) -> Path:
    if len(snapshot_id) != 64 or any(c not in "0123456789abcdef" for c in snapshot_id):
        raise ValueError("invalid snapshot hash")
    if language not in {"python", "typescript"}:
        raise ValueError("unsupported resolver language")
    return cache / "resolution" / f"{snapshot_id}.{language}.sqlite"
