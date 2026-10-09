"""SQLite persistence for prebuilt application maps. Reads never start analysis."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from backend.contracts.application_map import ApplicationMap

MAX_MAP_BYTES = 32 * 1024 * 1024


class MapUnavailable(RuntimeError):
    """A cached map is corrupt, oversized, or not readable."""


class MapStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, application_map: ApplicationMap) -> None:
        # Revalidate even a model created using model_copy/model_construct.
        validated = ApplicationMap.model_validate(application_map.model_dump())
        payload = validated.model_dump_json()
        if len(payload.encode()) > MAX_MAP_BYTES:
            raise ValueError("application map exceeds the storage budget")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS maps "
                "(snapshot_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO maps VALUES (?, ?)", (validated.snapshot_id, payload)
            )

    def load(self, snapshot_id: str) -> ApplicationMap | None:
        if re.fullmatch(r"[0-9a-f]{64}", snapshot_id) is None:
            raise ValueError("invalid snapshot ID")
        if not self.path.exists():
            return None
        try:
            connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                connection.execute("PRAGMA trusted_schema=OFF")
                row = connection.execute(
                    "SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload "
                    "ELSE NULL END FROM maps WHERE snapshot_id=?",
                    (MAX_MAP_BYTES, snapshot_id),
                ).fetchone()
                if row is None:
                    return None
                if row[0] is None:
                    raise MapUnavailable("application map exceeds the read budget")
                result = ApplicationMap.model_validate_json(row[0])
                if result.snapshot_id != snapshot_id:
                    raise MapUnavailable("application map snapshot does not match its key")
                return result
            finally:
                connection.close()
        except (sqlite3.Error, OSError, ValidationError, TypeError) as error:
            raise MapUnavailable("application map cannot be read") from error
