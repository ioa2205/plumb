"""CLI/API equivalence, protected private boundaries and owned job shutdown."""

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend import cli
from backend.app import create_app
from backend.assessment_jobs import AssessmentJobs
from backend.assessment_security import MAX_REQUEST_BYTES
from backend.contracts.assessment import AssessmentAnswer, AssessmentScope, TaskResolveRequest
from backend.contracts.assessment_jobs import AssessmentJob
from backend.settings import Settings

from .support import ORIGIN, PORT, signed_in, visitor


def scope() -> AssessmentScope:
    now = datetime.now(UTC)
    return AssessmentScope.model_validate(
        {
            "assessment_id": "test-assessment",
            "scope_id": "test-scope",
            "application_id": "owned-tandir",
            "application_name": "Owned lab",
            "origin": "http://127.0.0.1:8701",
            "allowed_paths": ["/orders"],
            "allowed_actions": ["read", "compare", "plan", "report", "analyze"],
            "accounts": [{"account_id": "alice", "role": "customer", "label": "synthetic"}],
            "synthetic_objects": [
                {"object_id": "O1", "owner_account_id": "alice", "kind": "order"}
            ],
            "authority": {
                "granted_by": "owner",
                "reference": "synthetic fixture",
                "granted_at": (now - timedelta(minutes=1)).isoformat(),
            },
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "stop_conditions": ["unexpected private information"],
        }
    )


def test_api_and_cli_resolve_same_private_plan_without_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    created = client.post(
        "/api/assessments",
        headers={"origin": ORIGIN},
        json={"scope": scope().model_dump(mode="json"), "confirmed_authority": True},
    )
    assert created.status_code == 201
    request = TaskResolveRequest(prompt="Prepare a manual checklist")
    answer = client.post(
        "/api/assessments/test-assessment/prompt",
        headers={"origin": ORIGIN},
        json=request.model_dump(mode="json"),
    )
    assert answer.status_code == 200
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    assert cli.main(["assess", "test-assessment", "--prompt", request.prompt]) == 0
    terminal = AssessmentAnswer.model_validate_json(capsys.readouterr().out)
    assert terminal == AssessmentAnswer.model_validate(answer.json())
    assert not terminal.task.network_activity and not terminal.task.authorization_granted
    assert client.get("/api/assessments/test-assessment/map").json()["endpoints"] == []
    assert client.get("/api/assessments/test-assessment/checklist").json()["execution_status"] == (
        "plan_only"
    )
    assert client.get("/api/assessments/test-assessment/report").json()["submitted"] is False


def test_assessment_routes_require_session_and_same_origin(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path), port=PORT)
    assert visitor(app).get("/api/assessments").status_code == 401
    client = signed_in(app)
    assert client.post("/api/assessments", json={}).status_code == 403
    assert (
        client.post(
            "/api/assessments", headers={"origin": "https://attacker.invalid"}, json={}
        ).status_code
        == 403
    )


def test_private_report_export_requires_review_of_exact_current_draft(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path), port=PORT)
    client = signed_in(app)
    client.headers["origin"] = ORIGIN
    assert (
        client.post(
            "/api/assessments",
            json={"scope": scope().model_dump(mode="json"), "confirmed_authority": True},
        ).status_code
        == 201
    )
    route = "/api/assessments/test-assessment/report"
    preview = client.get(route).json()
    review = {
        "reviewed_by": "Synthetic fixture reviewer",
        "reviewed_at": datetime.now(UTC).isoformat(),
        "confirmed_sanitized": True,
    }
    assert client.post(route, json={"review": review}).status_code == 422
    assert (
        client.post(route, json={"review": review, "preview_sha256": "0" * 64}).status_code == 409
    )
    result = client.post(
        route, json={"review": review, "preview_sha256": preview["preview_sha256"]}
    )
    assert result.status_code == 200 and not result.json()["submitted"]
    assert Path(result.json()["export_path"]).is_file()


def test_rejected_private_input_does_not_echo_secrets_and_raw_stream_is_bounded(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(data_dir=tmp_path), port=PORT)
    client = signed_in(app)
    private_value = "private-string-that-does-not-match-a-credential-regex"
    rejected = client.post(
        "/api/assessments", headers={"origin": ORIGIN}, json={"unknown": private_value}
    )
    assert rejected.status_code == 422 and private_value not in rejected.text
    rejected_launch = client.post(
        "/api/projects/review", headers={"origin": ORIGIN}, json={"unknown": private_value}
    )
    assert rejected_launch.status_code == 422 and private_value not in rejected_launch.text
    oversized = client.post(
        "/api/assessments",
        headers={"origin": ORIGIN, "content-type": "application/json"},
        content=b" " * (MAX_REQUEST_BYTES + 1),
    )
    assert oversized.status_code == 413
    assert not (tmp_path / "assessments/assessments.sqlite").exists()


def test_cli_import_does_not_fetch_embedded_url_and_requires_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.assessment import AssessmentStore

    settings = Settings(data_dir=tmp_path)
    AssessmentStore(settings).create(scope())
    payload = tmp_path / "observations.json"
    payload.write_text(json.dumps({"records": []}), encoding="utf-8")
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    assert cli.main(["assess", "--prompt", "Prepare a checklist"]) == 1
    assert cli.main(["assess", "test-assessment", "--import-records", str(payload)]) == 1


def test_worker_saves_cancellation_and_stops_owned_thread(tmp_path: Path) -> None:
    from backend.contracts.assessment import AssessmentList

    jobs = AssessmentJobs(Settings(data_dir=tmp_path))
    running = threading.Event()

    def work(cancel: object) -> AssessmentList:
        running.set()
        assert callable(cancel)
        assert threading.Event().wait(0.01) is False
        while not cancel():
            threading.Event().wait(0.01)
        return AssessmentList(assessments=[])

    job = jobs.start("test-assessment", "analyze", work)
    assert running.wait(2)
    jobs.cancel(job.job_id)
    jobs.close()
    ended = jobs.read(job.job_id)
    assert ended.state == "canceled" and ended.ended_at is not None
    assert AssessmentJob.model_validate_json(ended.model_dump_json()) == ended
    with pytest.raises(ValueError):
        jobs.read("assessment-job-" + "../outside" * 4)
