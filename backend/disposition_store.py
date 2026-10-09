"""Bounded append-only reviewer audit. Reads never create a database or change evidence."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from analysis.paths import is_link
from backend.contracts.investigation import DispositionDecision, DispositionUpdate, Finding
from backend.policy_store import PolicyStore

if TYPE_CHECKING:
    from backend.reports import ReportBundle

MAX_DECISION_BYTES = 8192
MAX_RUN_DECISIONS = 2000


class DispositionConflict(ValueError):
    """The saved finding or expected state differs. Refresh before another decision."""


def fingerprint(finding: Finding) -> str:
    return hashlib.sha256(finding.model_dump_json().encode()).hexdigest()


def validate_history(
    finding: Finding, history: list[DispositionDecision], *, projected: bool = False
) -> None:
    state = history[0].previous_disposition if projected and history else finding.disposition
    previous_time = None
    for version, decision in enumerate(history, 1):
        if (
            decision.run_id != finding.run_id
            or decision.finding_id != finding.id
            or decision.snapshot_id != finding.snapshot_id
            or decision.version != version
            or decision.previous_disposition != state
            or (previous_time is not None and decision.recorded_at < previous_time)
            or decision.original_finding_sha256 != history[0].original_finding_sha256
            or (not projected and decision.original_finding_sha256 != fingerprint(finding))
        ):
            raise ValueError("Reviewer history differs from its saved finding or prior state")
        state = decision.disposition
        previous_time = decision.recorded_at
    if (
        projected
        and history
        and (finding.disposition != state or finding.disposition_reason != history[-1].reason)
    ):
        raise ValueError("Current disposition differs from its reviewer history")


class DispositionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _path(self) -> None:
        for path in (self.path, *self.path.parents):
            try:
                status = path.lstat()
            except FileNotFoundError:
                continue
            if is_link(status):
                raise ValueError("Linked reviewer storage is unavailable")

    @staticmethod
    def _history(db: sqlite3.Connection, finding: Finding) -> list[DispositionDecision]:
        rows = db.execute(
            "SELECT version, CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload "
            "ELSE NULL END, digest FROM decisions WHERE run_id=? AND finding_id=? "
            "ORDER BY version LIMIT 101",
            (MAX_DECISION_BYTES, finding.run_id, finding.id),
        ).fetchall()
        if len(rows) > 100:
            raise ValueError("Reviewer history exceeds its read budget")
        history = []
        for version, payload, digest in rows:
            if payload is None or hashlib.sha256(payload.encode()).hexdigest() != digest:
                raise ValueError("Reviewer history integrity check failed")
            record = DispositionDecision.model_validate_json(payload)
            if version != record.version:
                raise ValueError("Reviewer history version key changed")
            history.append(record)
        validate_history(finding, history)
        return history

    def history(self, finding: Finding) -> list[DispositionDecision]:
        self._path()
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            return self._history(db, finding)

    def append(self, finding: Finding, intent: DispositionUpdate) -> DispositionDecision:
        finding = Finding.model_validate(finding.model_dump())
        intent = DispositionUpdate.model_validate(intent.model_dump())
        if intent.snapshot_id != finding.snapshot_id:
            raise DispositionConflict("The finding snapshot changed")
        self._path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=5)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            PolicyStore._wal(db)
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS decisions (run_id TEXT NOT NULL, "
                "finding_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, "
                "digest TEXT NOT NULL, PRIMARY KEY(run_id, finding_id, version))"
            )
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS refuse_{action.lower()} BEFORE {action} "
                    "ON decisions BEGIN SELECT RAISE(ABORT, "
                    "'reviewer decisions are append-only'); END"
                )
            db.execute("BEGIN IMMEDIATE")
            try:
                history = self._history(db, finding)
                current = history[-1].disposition if history else finding.disposition
                if (
                    intent.expected_version != len(history)
                    or intent.previous_disposition != current
                ):
                    raise DispositionConflict("The reviewer state changed")
                if (
                    len(history) >= 100
                    or db.execute(
                        "SELECT count(*) FROM decisions WHERE run_id=?", (finding.run_id,)
                    ).fetchone()[0]
                    >= MAX_RUN_DECISIONS
                ):
                    raise DispositionConflict("Reviewer history storage budget exhausted")
                record = DispositionDecision(
                    **intent.model_dump(),
                    run_id=finding.run_id,
                    finding_id=finding.id,
                    original_finding_sha256=fingerprint(finding),
                    version=len(history) + 1,
                    recorded_at=datetime.now(UTC),
                )
                validate_history(finding, [*history, record])
                payload = record.model_dump_json()
                if len(payload.encode()) > MAX_DECISION_BYTES:
                    raise ValueError("Reviewer decision exceeds its storage budget")
                db.execute(
                    "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
                    (
                        finding.run_id,
                        finding.id,
                        record.version,
                        payload,
                        hashlib.sha256(payload.encode()).hexdigest(),
                    ),
                )
                db.execute("COMMIT")
                return record
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def project(self, original: "ReportBundle", effective: "ReportBundle") -> "ReportBundle":
        from backend.reports import ReportBundle

        self._path()
        if not self.path.exists():
            return effective
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("BEGIN")
            count = db.execute(
                "SELECT count(*) FROM decisions WHERE run_id=?", (original.run.id,)
            ).fetchone()[0]
            if count > MAX_RUN_DECISIONS:
                raise ValueError("Reviewer history exceeds its read budget")
            histories = [decision for f in original.findings for decision in self._history(db, f)]
            if len(histories) != count:
                raise ValueError("Reviewer history contains an unrelated finding")
        by_id = {d.finding_id: d for d in histories}
        return ReportBundle.model_validate(
            {
                **effective.model_dump(),
                "disposition_history": histories,
                "findings": [
                    {
                        **f.model_dump(),
                        "disposition": by_id[f.id].disposition,
                        "disposition_reason": by_id[f.id].reason,
                    }
                    if f.id in by_id
                    else f.model_dump()
                    for f in effective.findings
                ],
            }
        )
