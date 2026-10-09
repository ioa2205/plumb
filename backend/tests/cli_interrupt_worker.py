"""Trusted stand-in workflow for the real Windows console-signal integration test."""

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.snapshot import SnapshotStore, take_snapshot
from backend import cli
from backend.contracts.application_map import ApplicationMap
from backend.contracts.investigation import Question
from backend.contracts.policies import FrozenPolicies
from backend.contracts.runs import Coverage, ReviewRun
from backend.profiles import Profile
from backend.review import implementation_identity, write_json
from backend.run_store import RunStore
from backend.settings import Settings

RUN = "review-" + "d" * 32


def main(root: Path, phase: str) -> int:
    os.environ["PLUMB_DATA_DIR"] = str(root / "data")
    settings = Settings()
    source = root / "source"
    source.mkdir(parents=True)
    (source / "example.py").write_text("value = 1\n", encoding="utf-8")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(source, store)
    now = datetime.now(UTC)
    run = ReviewRun(
        id=RUN,
        snapshot_id=snapshot.id,
        run_type="live",
        lifecycle="running",
        stage="investigating",
        created_at=now,
        started_at=now,
        coverage=Coverage(total=1, pending=1),
    )
    question = Question(
        id="question:fixture",
        run_id=RUN,
        type="guard_summary",
        family="authorization",
        stage="challenge",
        status="running",
        subject_ids=[],
        evidence=[],
    )
    RunStore(settings.cache_dir / "runs.sqlite").create(run, [question])
    directory = settings.data_dir / "reviews" / RUN
    directory.mkdir(parents=True)
    write_json(
        directory / "context.json",
        {
            "snapshot_id": snapshot.id,
            "implementation": implementation_identity(),
            "profile": Profile().identity(),
            "guard_cache": str(root / "guard-cache.json"),
        },
    )

    def mark(name: str) -> None:
        (root / name).write_text("done", encoding="utf-8")

    def wait_for_break() -> None:
        print("READY_FOR_BREAK", flush=True)
        # Python dispatches SIGBREAK at bytecode boundaries; a single long native
        # wait need not wake immediately, just like a bounded in-flight request.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(0.05)
        raise RuntimeError("Test did not deliver a console break")

    def workflow(*args: object) -> object:
        if phase == "construction":
            wait_for_break()
        return SimpleNamespace(run=wait_for_break, _challenge=None)

    context = SimpleNamespace(
        snapshot=snapshot,
        store=store,
        scheduling_limits=[],
        close=lambda: mark("context-closed"),
        map=ApplicationMap(
            snapshot_id=snapshot.id,
            entries=[],
            symbols=[],
            guards=[],
            access_sites=[],
            unknown_targets=[],
            links=[],
        ),
        preparation=None,
        policies=FrozenPolicies(snapshot_id=snapshot.id),
    )
    server = SimpleNamespace(
        config=SimpleNamespace(argv=lambda *a: ["trusted-test-stand-in"]),
        preflight=lambda: None,
        stop=lambda: mark("model-stopped"),
        memory_abort=None,
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "Review", lambda *a: context)
        patch.setattr(cli, "select", lambda *a: Profile())
        patch.setattr(cli, "validate_resume", lambda *a: None)
        patch.setattr(cli, "create", lambda *a: server)
        patch.setattr(cli, "machine_state", lambda: {"stand_in": True, "real_model": False})
        patch.setattr(cli, "Workflow", workflow)
        patch.setattr(
            cli,
            "ModelAdapter",
            lambda *a, **kw: SimpleNamespace(close=lambda: mark("adapter-closed")),
        )
        code = cli.main(["resume", RUN, "--limit", "1"])
    mark("returned")
    return code


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), sys.argv[2]))
