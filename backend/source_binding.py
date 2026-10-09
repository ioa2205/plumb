"""Private local folder associations. Snapshot evidence never reads this live tree."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from analysis.snapshot import SnapshotStore, capture_snapshot
from backend.case_reads import bounded
from backend.contracts.runs import Condition, ConditionKind
from backend.contracts.setup_view import SourceCheck
from backend.jobs import WorkerLock
from backend.review import write_json
from backend.run_store import RunStore
from backend.settings import Settings


def association(root: Path) -> dict[str, object]:
    info = root.stat()
    return {"folder": str(root), "device": info.st_dev, "inode": info.st_ino}


def bind(settings: Settings, root: Path, snapshot_id: str) -> str:
    identifier = "inspect-" + uuid4().hex
    directory = settings.cache_dir / "inspections"
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / f"{identifier}.json", {**association(root), "snapshot_id": snapshot_id})
    return identifier


def read_json(path: Path, *, max_bytes: int = 16 * 1024) -> dict[str, object]:
    if path.stat().st_size > max_bytes:
        raise ValueError("source association exceeds its bound")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("source association is unavailable")
    return value


def root_for(settings: Settings, value: object) -> Path:
    from backend.setup_reads import authorized_root

    if not isinstance(value, dict) or not isinstance(value.get("folder"), str):
        raise ValueError("source association is unavailable")
    root = authorized_root(value["folder"], settings)
    if association(root) != {k: value.get(k) for k in ("folder", "device", "inode")}:
        raise ValueError("original folder identity changed")
    return root


def inspection(settings: Settings, identifier: str) -> tuple[Path, str]:
    if re.fullmatch(r"inspect-[0-9a-f]{32}", identifier) is None:
        raise ValueError("invalid inspection ID")
    value = read_json(settings.cache_dir / "inspections" / f"{identifier}.json")
    snapshot = value.get("snapshot_id")
    if not isinstance(snapshot, str) or re.fullmatch(r"[0-9a-f]{64}", snapshot) is None:
        raise ValueError("invalid inspection snapshot")
    return root_for(settings, value), snapshot


def check_source(settings: Settings, run_id: str) -> SourceCheck:
    if re.fullmatch(r"review-[0-9a-f]{32}", run_id) is None:
        raise ValueError("invalid review ID")
    run = RunStore(settings.cache_dir / "runs.sqlite").run(run_id)
    if run is None:
        raise ValueError("unknown review")
    base: dict[str, Any] = {
        "run_id": run_id,
        "snapshot_id": run.snapshot_id,
        "checked_at": datetime.now(UTC),
        "limitations": [
            "This observation compares included source hashes and excluded scope only. "
            "It is not a new security verdict; original findings and citations stay frozen.",
            "Counts refer to included files, not every file on disk. "
            "A later edit may change this observation.",
        ],
    }
    with WorkerLock(settings.cache_dir / "review.lock"):
        try:
            # Full frozen provenance grew beyond the small inspection association budget.
            config = read_json(
                settings.data_dir / "reviews" / run_id / "context.json", max_bytes=64 * 1024
            )
            if config.get("snapshot_id") != run.snapshot_id:
                raise ValueError("source context disagrees with run")
            if "source" not in config:
                return SourceCheck(**base, state="unassociated")
            root = root_for(settings, config["source"])
            store = SnapshotStore(settings.cache_dir / "snapshots")
            old = store.load(run.snapshot_id)
            current = capture_snapshot(root, store)
            before = {f.path: f.sha256 for f in old.files}
            after = {f.path: f.sha256 for f in current.files}
            changed = sum(before[p] != after[p] for p in before.keys() & after.keys())
            added, removed = len(after.keys() - before.keys()), len(before.keys() - after.keys())
            scope_changed = old.excluded != current.excluded
            stale = bool(changed or added or removed or scope_changed)
            return bounded(
                SourceCheck(
                    **base,
                    state="changed" if stale else "current",
                    current_snapshot_id=current.id,
                    changed_files=changed,
                    added_files=added,
                    removed_files=removed,
                    excluded_scope_changed=scope_changed,
                    conditions=[
                        Condition(
                            kind=ConditionKind.STALE_SOURCE,
                            message=f"Since the frozen review: {changed} included files changed, "
                            f"{added} added, {removed} removed. "
                            + ("Excluded scope also changed. " if scope_changed else "")
                            + "Saved findings still describe the original snapshot.",
                            action="Inspect the current folder and start a new review.",
                        )
                    ]
                    if stale
                    else [],
                )
            )
        except (OSError, ValueError, RuntimeError):
            return SourceCheck(
                **base,
                state="unavailable",
                conditions=[
                    Condition(
                        kind=ConditionKind.STALE_SOURCE,
                        message="The original folder cannot be checked safely. "
                        "Its current source state is unknown; saved evidence is preserved.",
                        action="Inspect an authorized local folder to start a current review.",
                    )
                ],
            )
