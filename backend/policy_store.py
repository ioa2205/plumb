"""Human confirmations bound to an exact source-derived proposal; never permissions."""

import hashlib
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from backend.contracts.code import AccessSite, PolicyStatus, ProjectSnapshot
from backend.contracts.policies import BoundPolicy, FrozenPolicies
from backend.contracts.project_view import ProjectRule

MAX_POLICY_BYTES = 256 * 1024


class PolicyConflict(ValueError):
    """A changed proposal cannot inherit an old confirmation."""


class PolicyStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _wal(db: sqlite3.Connection) -> None:
        # journal_mode can return BUSY immediately during concurrent first-use setup,
        # even with a connection busy timeout. Retry only that bounded initialization.
        deadline = time.monotonic() + 5
        while True:
            try:
                db.execute("PRAGMA journal_mode=WAL")
                return
            except sqlite3.OperationalError as error:
                if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.025)

    @staticmethod
    def _read(payload: str, proposal: ProjectRule) -> ProjectRule:
        saved = ProjectRule.model_validate_json(payload)
        assertion = saved.assertion.model_copy(
            update={"status": PolicyStatus.INFERRED, "confirmed_by": None, "confirmed_at": None}
        )
        if (
            saved.assertion.status is not PolicyStatus.CONFIRMED
            or saved.model_copy(update={"assertion": assertion}) != proposal
        ):
            raise PolicyConflict("Policy confirmation differs from its source proposal.")
        return saved

    def load(self, proposal: ProjectRule) -> ProjectRule:
        if not self.path.exists():
            return proposal
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='policies'").fetchone():
                return proposal
            row = db.execute(
                "SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload ELSE NULL END "
                "FROM policies WHERE id=?",
                (MAX_POLICY_BYTES, proposal.assertion.id),
            ).fetchone()
            if row is None:
                return proposal
            if row[0] is None:
                raise PolicyConflict("Policy confirmation exceeds the read budget.")
            return self._read(row[0], proposal)

    def confirm(
        self, proposal: ProjectRule, expected: str, sites: list[AccessSite] | None = None
    ) -> ProjectRule:
        if expected != proposal.proposal_sha256:
            raise PolicyConflict("The proposed rule changed. Refresh before confirming it.")
        assertion = proposal.assertion.model_copy(
            update={
                "status": PolicyStatus.CONFIRMED,
                "confirmed_by": "Local reviewer",
                "confirmed_at": datetime.now(UTC),
            }
        )
        record = ProjectRule.model_validate(
            proposal.model_copy(update={"assertion": assertion}).model_dump()
        )
        payload = record.model_dump_json()
        if len(payload.encode()) > MAX_POLICY_BYTES:
            raise PolicyConflict("Policy confirmation exceeds the storage budget.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=30)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            self._wal(db)
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT OR IGNORE INTO policies VALUES (?, ?)", (assertion.id, payload))
                row = db.execute(
                    "SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload "
                    "ELSE NULL END FROM policies WHERE id=?",
                    (MAX_POLICY_BYTES, assertion.id),
                ).fetchone()
                if row[0] is None:
                    raise PolicyConflict("Policy confirmation exceeds the read budget.")
                result = self._read(row[0], proposal)
                if sites:
                    self._save_bound(
                        db,
                        BoundPolicy(
                            assertion=result.assertion,
                            snapshot_id=sites[0].snapshot_id,
                            source_run_id=result.source_run_id,
                            sites=sites,
                            provenance="Human confirmation of source-validated peer observation",
                        ),
                    )
                db.execute("COMMIT")
                return result
            except BaseException:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _save_bound(db: sqlite3.Connection, policy: BoundPolicy) -> None:
        policy = BoundPolicy.model_validate(policy.model_dump())
        payload = policy.model_dump_json()
        if len(payload.encode()) > MAX_POLICY_BYTES:
            raise PolicyConflict("Policy exceeds the storage budget.")
        db.execute(
            "CREATE TABLE IF NOT EXISTS bound_policies "
            "(id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, payload TEXT NOT NULL, "
            "digest TEXT NOT NULL)"
        )
        count = db.execute(
            "SELECT count(*) FROM bound_policies WHERE snapshot=?", (policy.snapshot_id,)
        ).fetchone()[0]
        prior = db.execute(
            "SELECT digest FROM bound_policies WHERE id=?", (policy.assertion.id,)
        ).fetchone()
        if prior is not None and prior[0] != policy.sha256:
            raise PolicyConflict("Saved policy identity changed.")
        if prior is None and count >= 100:
            raise PolicyConflict("Snapshot policy count exceeds the storage budget.")
        db.execute(
            "INSERT OR IGNORE INTO bound_policies VALUES (?, ?, ?, ?)",
            (policy.assertion.id, policy.snapshot_id, payload, policy.sha256),
        )

    def save(self, policy: BoundPolicy) -> BoundPolicy:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=30)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            self._wal(db)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                self._save_bound(db, policy)
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return policy

    def freeze(self, snapshot: ProjectSnapshot, sites: list[AccessSite]) -> FrozenPolicies:
        policies = []
        if self.path.exists():
            with closing(
                sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
            ) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='bound_policies'").fetchone():
                    rows = db.execute(
                        "SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload "
                        "ELSE NULL END, digest FROM bound_policies WHERE snapshot=? "
                        "ORDER BY id LIMIT 101",
                        (MAX_POLICY_BYTES, snapshot.id),
                    ).fetchall()
                    if len(rows) > 100:
                        raise PolicyConflict("Snapshot policy count exceeds the read budget.")
                    for payload, digest in rows:
                        if (
                            payload is None
                            or hashlib.sha256(payload.encode()).hexdigest() != digest
                        ):
                            raise PolicyConflict("Policy integrity check failed.")
                        policy = BoundPolicy.model_validate_json(payload)
                        if policy.snapshot_id != snapshot.id or any(
                            s not in sites for s in policy.sites
                        ):
                            raise PolicyConflict(
                                "Policy access binding changed; revalidate the rule."
                            )
                        policies.append(policy)
                # Confirmations saved before bound_policies existed remain usable only
                # on the exact snapshot that supplied their source evidence.
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='policies'").fetchone():
                    from backend.map_store import MapStore
                    from backend.run_store import RunStore

                    rows = db.execute(
                        "SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload "
                        "ELSE NULL END "
                        "FROM policies ORDER BY id LIMIT 1001",
                        (MAX_POLICY_BYTES,),
                    ).fetchall()
                    if len(rows) > 1000:
                        raise PolicyConflict("Confirmation inventory exceeds the read budget.")
                    for (payload,) in rows:
                        if payload is None:
                            raise PolicyConflict("Confirmation exceeds the read budget.")
                        rule = ProjectRule.model_validate_json(payload)
                        if rule.assertion.status is not PolicyStatus.CONFIRMED:
                            raise PolicyConflict("Invalid confirmation status.")
                        if rule.assertion.id in {p.assertion.id for p in policies}:
                            continue
                        if not rule.assertion.evidence or any(
                            s.snapshot_id != snapshot.id for s in rule.assertion.evidence
                        ):
                            continue
                        run = RunStore(self.path.parent / "runs.sqlite").run(rule.source_run_id)
                        if run is None or run.snapshot_id != snapshot.id:
                            raise PolicyConflict("Confirmation source run is unavailable.")
                        graph = MapStore(self.path.parent / "application_maps.sqlite").load(
                            snapshot.id
                        )
                        selected = [s for s in sites if s.resource == rule.assertion.resource]
                        if (
                            graph is None
                            or any(s not in graph.access_sites for s in selected)
                            or not selected
                        ):
                            raise PolicyConflict("Confirmation source accesses changed.")
                        policies.append(
                            BoundPolicy(
                                assertion=rule.assertion,
                                snapshot_id=snapshot.id,
                                source_run_id=rule.source_run_id,
                                sites=selected,
                                provenance=(
                                    "Human confirmation of source-validated peer observation"
                                ),
                            )
                        )
        return FrozenPolicies(snapshot_id=snapshot.id, policies=policies)
