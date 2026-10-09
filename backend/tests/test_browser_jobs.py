"""Protected browser dispatch of the real workflow with labeled software judgments."""

import argparse
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from agent.llm import JsonAnswer, ModelRequest, Spend
from analysis.snapshot import SnapshotStore, take_snapshot
from backend import cli
from backend.app import create_app
from backend.contracts.runs import ReviewRun, RunLifecycle, RunStage, RunType
from backend.contracts.setup_view import LaunchRequest, SourceCheck
from backend.jobs import WorkerLock
from backend.profiles import Profile
from backend.run_store import RunStore
from backend.settings import Settings
from backend.source_binding import association, bind, check_source
from backend.tests.support import ORIGIN, PORT, signed_in, visitor
from backend.tests.test_review import ROUTES, Model

ROOT = Path(__file__).resolve().parents[2]


def joined(app: FastAPI) -> None:
    thread = app.state.worker._thread
    assert thread is not None
    thread.join(timeout=30)
    assert not thread.is_alive(), "owned software worker did not stop"


def test_protected_launch_pause_resume_cancel_and_saved_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    entered, release = threading.Event(), threading.Event()
    closed: list[str] = []

    class Adapter(Model):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__()

        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            if not release.is_set():
                entered.set()
                assert release.wait(20)
            return super().ask(request, spend)

        def close(self) -> None:
            closed.append("adapter")

    monkeypatch.setattr(cli, "select", lambda *args: Profile())
    monkeypatch.setattr(
        cli,
        "create",
        lambda *args: SimpleNamespace(
            config=SimpleNamespace(argv=lambda *args: ["software-test-no-model"]),
            stop=lambda: closed.append("server"),
            memory_abort=False,
        ),
    )
    monkeypatch.setattr(cli, "ModelAdapter", Adapter)
    monkeypatch.setattr(cli, "machine_state", lambda: {"software_test": True})
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    client.headers["Origin"] = ORIGIN
    inspected = client.post(
        "/api/projects/inspect",
        json={
            "folder": str(ROOT / "labs/tandir"),
            "authorized": True,
        },
    )
    assert inspected.status_code == 200
    body = {
        "inspection_id": inspected.json()["inspection_id"],
        "authorized": True,
        "resources": ["Order"],
        "routes": ROUTES,
        "limit": 1,
    }
    assert (
        visitor(app).post("/api/projects/review", json=body, headers={"Origin": ORIGIN}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/projects/review", json=body, headers={"Origin": "http://foreign.invalid"}
        ).status_code
        == 403
    )
    for invalid in (False, 1, "true", None):
        assert (
            client.post("/api/projects/review", json={**body, "authorized": invalid}).status_code
            == 422
        )
    response = client.post("/api/projects/review", json=body)
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert response.json()["snapshot_id"] == inspected.json()["snapshot_id"]
    try:
        assert entered.wait(10)
        assert client.post("/api/projects/review", json=body).status_code == 409
        assert client.post(f"/api/runs/{run_id}/source-check").status_code == 409
        assert client.post(f"/api/runs/{run_id}/pause").status_code == 202
    finally:
        release.set()
    joined(app)
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    paused = runs.run(run_id)
    assert paused is not None and paused.lifecycle is RunLifecycle.PAUSED
    assert (settings.data_dir / "reviews" / run_id / "report.html").is_file()
    source = client.post(f"/api/runs/{run_id}/source-check")
    assert source.status_code == 200 and source.json()["state"] == "current"
    # Resume dispatch retains original model/profile/source identity and question checkpoint.
    entered.clear()
    release.clear()
    response = client.post(f"/api/runs/{run_id}/resume", json={"limit": 1})
    assert response.status_code == 202 and response.json()["id"] == run_id
    try:
        assert entered.wait(10)
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    finally:
        release.set()
    joined(app)
    canceled = runs.run(run_id)
    assert canceled is not None and canceled.lifecycle is RunLifecycle.CANCELED
    assert client.post(f"/api/runs/{run_id}/resume", json={}).status_code == 503
    assert closed.count("adapter") == 2 and closed.count("server") == 2
    app.state.worker.close()


def test_changed_source_replaced_folder_unknown_counts_and_snapshot_preservation(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    root = tmp_path / "target"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
    (root / "old.py").write_text("x = 2\n", encoding="utf-8")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    original = take_snapshot(root, store)
    inspection_id = bind(settings, root, original.id)
    run_id = "review-" + "b" * 32
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    runs.create(
        ReviewRun(
            id=run_id,
            snapshot_id=original.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.PAUSED,
            stage=RunStage.INVESTIGATING,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        ),
        [],
    )
    directory = settings.data_dir / "reviews" / run_id
    directory.mkdir(parents=True)
    config = {"snapshot_id": original.id, "source": association(root)}
    (directory / "context.json").write_text(json.dumps(config), encoding="utf-8")
    (root / ".env").write_text("SECRET=not-read", encoding="utf-8")
    scope_only = check_source(settings, run_id)
    assert scope_only.state == "changed" and scope_only.current_snapshot_id == original.id
    assert scope_only.excluded_scope_changed and scope_only.changed_files == 0
    assert store.load(original.id) == original, "freshness check changed a frozen manifest"
    (root / "app.py").write_text("x = 3\n", encoding="utf-8")
    (root / "old.py").unlink()
    (root / "new.py").write_text("x = 4\n", encoding="utf-8")
    checked = check_source(settings, run_id)
    assert checked.state == "changed"
    assert (checked.changed_files, checked.added_files, checked.removed_files) == (1, 1, 1)
    assert checked.excluded_scope_changed and checked.conditions[0].kind.value == "stale_source"
    assert store.read(original, "app.py") == b"x = 1\n"
    frozen = runs.run(run_id)
    assert frozen is not None and frozen.snapshot_id == original.id
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    client.headers["Origin"] = ORIGIN
    body = {"inspection_id": inspection_id, "authorized": True}
    # Changed inspected bytes refuse before model setup or run creation.
    assert client.post("/api/projects/review", json=body).status_code == 503
    joined(app)
    root.rename(tmp_path / "old-target")
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert client.post("/api/projects/review", json=body).status_code == 503
    unknown = check_source(settings, run_id)
    assert unknown.state == "unavailable" and unknown.changed_files is None
    assert str(tmp_path) not in unknown.model_dump_json()
    config.pop("source")
    (directory / "context.json").write_text(json.dumps(config), encoding="utf-8")
    assert check_source(settings, run_id).state == "unassociated"
    for updates in (
        {"changed_files": 0},
        {"current_snapshot_id": original.id},
        {"excluded_scope_changed": False},
    ):
        with pytest.raises(ValidationError):
            SourceCheck.model_validate({**unknown.model_dump(), **updates})
    app.state.worker.close()


def test_memory_profile_and_process_lock_refusal_never_loads_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    root = ROOT / "labs/tandir"
    snap = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
    body = {
        "inspection_id": bind(settings, root, snap.id),
        "authorized": True,
        "routes": ROUTES,
        "resources": ["Order"],
    }
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    client.headers["Origin"] = ORIGIN

    def refused(*args: object) -> None:
        raise ValueError("memory/profile not ready")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("refused review attempted model setup")

    monkeypatch.setattr(cli, "select", refused)
    monkeypatch.setattr(cli, "create", forbidden)
    monkeypatch.setattr(cli, "machine_state", lambda: {})
    with WorkerLock(settings.cache_dir / "review.lock"):
        assert client.post("/api/projects/review", json=body).status_code == 409
    joined(app)
    assert client.post("/api/projects/review", json=body).status_code == 503
    joined(app)
    assert client.get("/api/runs").json()["total"] == 0
    for updates in (
        {"families": ["authorization", "authorization"]},
        {"limit": 0},
        {"resources": ["Order"], "families": ["injection"]},
    ):
        with pytest.raises(ValidationError):
            LaunchRequest.model_validate({**body, **updates})
    app.state.worker.close()


def test_shutdown_joins_owned_worker_and_pauses_at_its_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.browser_jobs import BrowserJobs

    settings = Settings(data_dir=tmp_path / "data")
    root = tmp_path / "target"
    root.mkdir()
    snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
    token = bind(settings, root, snapshot.id)
    reached, released = threading.Event(), threading.Event()
    cleaned: list[bool] = []

    def execute(
        args: argparse.Namespace,
        settings: Settings,
        *,
        requested_id: str,
        ready: Callable[[str], None],
        **kwargs: object,
    ) -> int:
        runs = RunStore(settings.cache_dir / "runs.sqlite")
        run = ReviewRun(
            id=requested_id,
            snapshot_id=snapshot.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.QUEUED,
            created_at=datetime.now(UTC),
        )
        runs.create(run, [])
        ready(requested_id)
        reached.set()
        assert released.wait(10)
        assert runs.requested(requested_id) == "pause"
        cleaned.append(True)
        return 0

    monkeypatch.setattr("backend.browser_jobs.execute_review", execute)
    worker = BrowserJobs(settings)
    worker.launch(LaunchRequest(inspection_id=token, authorized=True))
    assert reached.wait(10)
    closing = threading.Thread(target=worker.close)
    closing.start()
    try:
        closing.join(0.05)
        assert closing.is_alive(), "shutdown returned while its worker still ran"
    finally:
        released.set()
        closing.join(10)
    assert not closing.is_alive() and cleaned == [True]
    with pytest.raises(RuntimeError):
        worker.launch(LaunchRequest(inspection_id=token, authorized=True))
