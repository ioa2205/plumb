"""One shared software journey; model and runtime answers are labeled fixtures."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend import cli
from backend.app import create_app
from backend.contracts.cases import CaseDetail
from backend.mcp import SavedReviews
from backend.profiles import Profile
from backend.reports import ReportBundle
from backend.saved_reports import load
from backend.source_binding import read_json
from backend.tests.support import ORIGIN, PORT, signed_in
from backend.tests.test_browser_jobs import ROOT, joined
from backend.tests.test_review import ROUTES, Model
from verification.tests.test_report_replay import SavedReceipt
from verification.tests.test_report_replay import saved_receipt as saved_receipt


def test_inspect_browser_pause_cli_resume_export_case_decision_and_replay_links(
    saved_receipt: SavedReceipt,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _, _, probe_calls = saved_receipt
    closed: list[str] = []

    class Adapter(Model):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__()

        def close(self) -> None:
            closed.append("adapter")

    monkeypatch.setattr(cli, "select", lambda *args: Profile())
    monkeypatch.setattr(
        cli,
        "create",
        lambda *args: SimpleNamespace(
            config=SimpleNamespace(argv=lambda *args: ["software-fixture-no-model"]),
            stop=lambda: closed.append("server"),
            memory_abort=False,
        ),
    )
    monkeypatch.setattr(cli, "ModelAdapter", Adapter)
    monkeypatch.setattr(cli, "machine_state", lambda: {"software_fixture": True})
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    client.headers["Origin"] = ORIGIN
    try:
        inspected = client.post(
            "/api/projects/inspect", json={"folder": str(ROOT / "labs/tandir"), "authorized": True}
        )
        assert inspected.status_code == 200, inspected.text
        inspection = inspected.json()
        assert not any(r["investigated"] for r in inspection["capabilities"]["rows"])
        launched = client.post(
            "/api/projects/review",
            json={
                "inspection_id": inspection["inspection_id"],
                "authorized": True,
                "resources": ["Order"],
                "routes": ROUTES,
                "limit": 1,
            },
        )
        assert launched.status_code == 202, launched.text
        run_id = launched.json()["id"]
        joined(app)
        original_dir = settings.data_dir / "reviews" / run_id
        partial = ReportBundle.model_validate_json((original_dir / "report.json").read_bytes())
        assert partial.run.lifecycle.value == "paused" and partial.run.coverage.pending == 1
        # Browser dispatch and terminal resume use the same frozen inputs and identities.
        frozen = {
            name: (original_dir / name).read_bytes()
            for name in ("context.json", "policies.json", "scheduling.json")
        }
        assert cli.main(["resume", run_id, "--limit", "1"]) == 0
        bundle, _ = load(settings, run_id)
        assert bundle.run.lifecycle.value == "completed" and bundle.run.coverage.completed == 2
        assert bundle.snapshot.id == inspection["snapshot_id"]
        assert {name: (original_dir / name).read_bytes() for name in frozen} == frozen
        assert bundle.supplementary is not None and bundle.proposals
        assert bundle.capabilities is not None and not any(
            r.runtime_testable for r in bundle.capabilities.rows
        )
        assert [r.model_dump(mode="json") for r in bundle.capabilities.rows] == inspection[
            "capabilities"
        ]["rows"]
        finding = next(f for f in bundle.findings if f.conclusion.value == "supported")
        endpoint = f"/api/runs/{run_id}/findings/{finding.id}"
        detail = client.get(endpoint)
        assert detail.status_code == 200 and detail.json()["proposal"] is not None
        originals = {p.name: p.read_bytes() for p in original_dir.glob("report.*")}
        decision = client.post(
            endpoint + "/disposition",
            json={
                "snapshot_id": bundle.snapshot.id,
                "expected_version": 0,
                "previous_disposition": "open",
                "disposition": "accepted_risk",
                "reason": "Software journey decision",
                "actor": "Fixture reviewer",
            },
        )
        assert decision.status_code == 200, decision.text
        # The bundled replay uses fixture probe answers; it launches no target process.
        assert cli.main(["replay", run_id, "--finding", finding.id]) == 0
        assert probe_calls == ["vulnerable", "receipt_fixed"]
        case = client.get(endpoint).json()
        CaseDetail.model_validate(case)
        for bad in (
            {**case["proposal"], "finding_id": "other"},
            {**case["proposal"], "snapshot_id": "a" * 64},
        ):
            with pytest.raises(ValidationError):
                CaseDetail.model_validate({**case, "proposal": bad})
        assert case["finding"]["disposition"] == "accepted_risk"
        assert case["finding"]["runtime_verification"] == "reproduced"
        assert case["suggested_change"]["status"] == "replayed_fixed"
        assert case["suggested_change"]["replay_probe_run_ids"] == [case["probe_runs"][1]["id"]]
        assert case["finding"]["probe_run_ids"] == [case["probe_runs"][0]["id"]]
        for suffix in ("json", "markdown", "html", "sarif"):
            exported = client.get(f"/api/runs/{run_id}/current-report?format={suffix}")
            state = "accepted\\_risk" if suffix == "markdown" else "accepted_risk"
            assert exported.status_code == 200 and state in exported.text

        # Disable constructors after processing: saved API/MCP reads must stay offline.
        def forbidden(*args: object, **kwargs: object) -> None:
            pytest.fail("saved read tried to start inference")

        monkeypatch.setattr(cli, "create", forbidden)
        monkeypatch.setattr(cli, "ModelAdapter", forbidden)
        mcp = SavedReviews(settings).read("finding", run_id, finding_id=finding.id)
        assert mcp["finding"] == case["finding"]
        assert client.get(endpoint + "/exhibits/E01").status_code == 200
        assert {p.name: p.read_bytes() for p in original_dir.glob("report.*")} == originals
        assert closed == ["adapter", "server", "adapter", "server"]
    finally:
        app.state.worker.close()


def test_provenance_context_budget_keeps_small_associations_and_large_contexts_bounded(
    tmp_path: Path,
) -> None:
    path = tmp_path / "context.json"
    value = {"implementation": "a" * (20 * 1024)}
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="bound"):
        read_json(path)
    assert read_json(path, max_bytes=64 * 1024) == value
    path.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(ValueError, match="bound"):
        read_json(path, max_bytes=64 * 1024)
