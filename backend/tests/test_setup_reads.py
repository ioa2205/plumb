"""Actual static inspection and negative browser setup boundaries. No model."""

import json
from pathlib import Path

import pytest

from backend.app import create_app
from backend.contracts.setup_view import InspectionView, SetupReadiness
from backend.jobs import WorkerLock
from backend.settings import Settings
from backend.setup_reads import authorized_root, readiness
from backend.tests.support import ORIGIN, PORT, signed_in, visitor

ROOT = Path(__file__).resolve().parents[2]


def test_authorized_source_inspection_never_imports_or_runs_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "target"
    source.mkdir()
    marker = tmp_path / "target-executed"
    (source / "app.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('EXECUTED')\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/items/{item_id}')\n"
        "def item(item_id: int):\n"
        "    return {'id': item_id}\n",
        encoding="utf-8",
    )
    (source / ".env").write_text("PRIVATE_SECRET=never-read", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Browser inspection attempted model loading or installation")

    monkeypatch.setattr("backend.llama_server.LlamaServer.start", forbidden)
    monkeypatch.setattr("backend.setup.__main__.install", forbidden)
    client = signed_in(create_app(settings, port=PORT))
    client.headers["Origin"] = ORIGIN
    response = client.post(
        "/api/projects/inspect", json={"folder": str(source), "authorized": True}
    )
    assert response.status_code == 200, response.text
    view = InspectionView.model_validate(response.json())
    assert not view.model_loaded and not view.target_executed and not marker.exists()
    assert view.entries_total == 1 and view.entries[0].route == "/items/{item_id}"
    assert view.exclusion_reasons["secret"] == 1 and "PRIVATE_SECRET" not in response.text
    assert view.frameworks == {"fastapi": 1}
    assert view.entries[0].snapshot_id == view.snapshot_id
    assert (settings.cache_dir / "application_maps.sqlite").is_file()
    assert not (settings.data_dir / "models").exists()


def test_inspection_requires_authorization_origin_local_path_and_separate_storage(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "target"
    source.mkdir()
    app = create_app(settings, port=PORT)
    body = {"folder": str(source), "authorized": True}
    assert (
        visitor(app)
        .post("/api/projects/inspect", headers={"Origin": ORIGIN}, json=body)
        .status_code
        == 401
    )
    client = signed_in(app)
    client.headers["Origin"] = ORIGIN
    for invalid in (1, "true", None):
        assert (
            client.post("/api/projects/inspect", json={**body, "authorized": invalid}).status_code
            == 422
        )
    assert (
        client.post("/api/projects/inspect", json={**body, "authorized": False}).status_code == 422
    )
    assert client.post("/api/projects/inspect", json={"folder": str(source)}).status_code == 422
    assert (
        client.post(
            "/api/projects/inspect", headers={"Origin": "http://foreign.invalid"}, json=body
        ).status_code
        == 403
    )
    for folder in (
        "relative",
        "\\\\remote.invalid\\share",
        "//remote.invalid/share",
        "\\\\?\\C:\\",
        str(tmp_path.anchor),
        str(tmp_path),
        str(settings.data_dir),
        "bad\npath",
    ):
        response = client.post("/api/projects/inspect", json={"folder": folder, "authorized": True})
        assert response.status_code == 503 and str(tmp_path) not in response.text
    with WorkerLock(settings.cache_dir / "review.lock"):
        assert client.post("/api/projects/inspect", json=body).status_code == 409
        assert client.get("/api/setup").status_code == 409


def test_root_symlink_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "target"
    source.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit directory symlinks")
    with pytest.raises(ValueError):
        authorized_root(str(link), Settings(data_dir=tmp_path / "data"))


def test_saved_actual_readiness_retains_memory_gate_and_missing_asset_conditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.loads((ROOT / "frontend/scripts/fixtures/setup-views.json").read_text())
    plan = raw["setup_preview"]
    monkeypatch.setattr("backend.setup_reads.preview", lambda settings: plan)
    view = readiness(Settings(data_dir=tmp_path / "data"))
    assert view.model_loaded is False and view.downloads_started is False
    assert view.required_ram_bytes == plan["doctor"]["profiles"][0]["host_required_bytes"]
    altered = json.loads(json.dumps(plan))
    profile = altered["doctor"]["profiles"][0]
    profile.update(
        {
            "model_verified": False,
            "runtime_verified": False,
            "estimated_memory_fit": False,
            "ready": False,
        }
    )
    altered["doctor"]["model_candidates"][0]["verified_installed"] = False
    # The selected candidate is located by identity rather than its position.
    for candidate in altered["doctor"]["model_candidates"]:
        if candidate["id"] == profile["model_id"]:
            candidate["verified_installed"] = False
    altered["doctor"]["inventory"]["memory"]["available_bytes"] = 0
    altered.update(
        {
            "ready": False,
            "missing_download_bytes": view.model_size_bytes,
            "requires_large_download_approval": True,
        }
    )
    monkeypatch.setattr("backend.setup_reads.preview", lambda settings: altered)
    unavailable = readiness(Settings(data_dir=tmp_path / "data"))
    assert not unavailable.ready and unavailable.requires_large_download_approval
    assert {c.kind.value for c in unavailable.conditions} >= {
        "setup_required",
        "model_too_large",
        "runner_unavailable",
    }
    with pytest.raises(ValueError):
        SetupReadiness.model_validate({**unavailable.model_dump(), "ready": True})


def test_setup_errors_do_not_echo_private_machine_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(settings: Settings) -> None:
        raise ValueError("private-machine-secret")

    monkeypatch.setattr("backend.app.readiness", bad)
    client = signed_in(create_app(Settings(data_dir=tmp_path / "data"), port=PORT))
    response = client.get("/api/setup")
    assert response.status_code == 503 and "private-machine-secret" not in response.text


def test_inspection_contract_refuses_foreign_source_and_changed_scope() -> None:
    view = json.loads((ROOT / "frontend/scripts/fixtures/setup-views.json").read_text())[
        "inspection"
    ]
    foreign = json.loads(json.dumps(view))
    foreign["entries"][0]["span"]["snapshot_id"] = "0" * 64
    for changes in (foreign, {**view, "excluded_files": view["excluded_files"] + 1}):
        with pytest.raises(ValueError):
            InspectionView.model_validate(changes)
