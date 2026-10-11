"""Finite proposals and resumable attempted evidence; no runner or inference launch."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from backend import assessment_jobs as jobs
from backend import cli
from backend.app import create_app
from backend.assessment import AssessmentStore
from backend.contracts.assessment_engine import ControlledHTTPResult, HTTPActionProgress
from backend.contracts.assessment_jobs import (
    LabActionPreviewRequest,
    LabCollectionCheckpoint,
    ObservationAnalysisRequest,
)
from backend.settings import Settings

from .support import PORT, signed_in, visitor
from .test_assessment_jobs import collection_setup


@pytest.mark.parametrize("permanent", [False, True])
def test_atomic_checkpoint_windows_read_lock_is_bounded_and_never_exposes_partial_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permanent: bool
) -> None:
    path = tmp_path / "checkpoint.json"
    jobs._atomic_json(path, {"old_complete": True})
    original_replace = Path.replace
    attempts: list[Path] = []
    pauses: list[float] = []
    monkeypatch.setattr(jobs.sys, "platform", "win32")
    monkeypatch.setattr(jobs.time, "sleep", pauses.append)

    def locked(self: Path, target: Path) -> Path:
        attempts.append(target)
        assert path.read_text(encoding="utf-8").strip() == '{\n  "old_complete": true\n}'
        if permanent or len(attempts) <= 2:
            error = PermissionError("Synthetic transient Windows read lock")
            error.winerror = 5
            raise error
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", locked)
    if permanent:
        with pytest.raises(PermissionError):
            jobs._atomic_json(path, {"new_complete": True})
        assert '"old_complete"' in path.read_text(encoding="utf-8")
        assert len(attempts) == 8 and pauses == [0.01] * 7
    else:
        jobs._atomic_json(path, {"new_complete": True})
        assert '"new_complete"' in path.read_text(encoding="utf-8")
        assert len(attempts) == 3 and pauses == [0.01] * 2
    assert list(tmp_path.glob(".*.tmp")) == []


def test_saved_proposal_has_no_permission_or_execution_and_is_same_cli_api_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, _ = collection_setup(settings, monkeypatch)
    saved = jobs.collection_checkpoint(settings, identity, request.preview_sha256)
    assert saved.phase == "proposed" and saved.permission is None and saved.result is None
    assert not saved.automatic_replay_allowed and saved.evidence_review_required
    app = create_app(settings, port=PORT)
    route = f"/api/assessments/{identity}/collections/{request.preview_sha256}"
    assert visitor(app).get(route).status_code == 401
    response = signed_in(app).get(route)
    assert response.status_code == 200
    assert LabCollectionCheckpoint.model_validate(response.json()) == saved
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    assert cli.main(["assess", identity, "--collection-status", request.preview_sha256]) == 0
    assert LabCollectionCheckpoint.model_validate_json(capsys.readouterr().out) == saved


def test_final_checkpoint_retains_exact_permission_and_pending_human_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, trace = collection_setup(settings, monkeypatch)
    jobs.collect_saved(settings, identity, request)
    saved = jobs.collection_checkpoint(settings, identity, request.preview_sha256)
    assert saved.phase == "completed" and saved.permission == request.permission
    assert saved.result == trace and saved.evidence_review_required
    assert not AssessmentStore(settings).load(identity).artifacts
    assert not list((AssessmentStore(settings).directory / identity).rglob("*.tmp"))


def test_interrupted_action_has_durable_attempt_before_execution_and_cannot_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, trace = collection_setup(settings, monkeypatch)
    progress = HTTPActionProgress(
        action_id="probe:0",
        attempts=1,
        missing_evidence=["Synthetic creation completion unknown; never replay"],
    )
    partial = trace.model_copy(
        update={"records": [], "requests_used": 1, "action_progress": [progress]}
    )

    def interrupted(*args: object, **kwargs: object) -> ControlledHTTPResult:
        callback = kwargs["checkpoint"]
        assert callable(callback)
        callback(partial)
        checkpoint = jobs.collection_checkpoint(settings, identity, request.preview_sha256)
        assert checkpoint.phase == "executing" and checkpoint.result == partial
        raise RuntimeError("fixture process stopped after uncertain synthetic creation")

    monkeypatch.setattr(jobs, "run_controlled_http", interrupted)
    with pytest.raises(RuntimeError):
        jobs.collect_saved(settings, identity, request)
    saved = jobs.collection_checkpoint(settings, identity, request.preview_sha256)
    assert saved.phase == "interrupted" and saved.result == partial
    assert saved.result.action_progress[0].missing_evidence and not saved.automatic_replay_allowed
    assert AssessmentStore(settings).load(identity).spent_requests == 12
    with pytest.raises(ValueError, match="unconsumed"):
        jobs.collect_saved(settings, identity, request)


def test_recovered_executing_checkpoint_reads_interrupted_without_changing_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, trace = collection_setup(settings, monkeypatch)
    checkpoint = jobs.collection_checkpoint(settings, identity, request.preview_sha256).model_copy(
        update={"phase": "executing", "permission": request.permission, "result": trace}
    )
    store = AssessmentStore(settings)
    jobs._save_collection_checkpoint(store, checkpoint)
    path = jobs._collection_checkpoint_path(store, identity, request.preview_sha256)
    original = path.read_bytes()
    result = jobs.collection_checkpoint(settings, identity, request.preview_sha256)
    assert result.phase == "interrupted" and not result.automatic_replay_allowed
    assert path.read_bytes() == original


def test_prior_cancel_does_not_consume_permission_or_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, _ = collection_setup(settings, monkeypatch)
    with pytest.raises(ValueError):
        jobs.collect_saved(settings, identity, request, cancel=lambda: True)
    assert (
        jobs.collection_checkpoint(settings, identity, request.preview_sha256).phase == "proposed"
    )
    assert AssessmentStore(settings).load(identity).spent_requests == 0


def test_authorizer_private_material_is_refused_before_consume_or_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", redaction_secrets=(SecretStr("private-reviewer-sentinel"),)
    )
    identity, request, _ = collection_setup(settings, monkeypatch)
    request = request.model_copy(
        update={
            "permission": request.permission.model_copy(
                update={"approved_by": "private-reviewer-sentinel"}
            )
        }
    )
    with pytest.raises(ValueError, match="credential material"):
        jobs.collect_saved(settings, identity, request)
    assert (
        jobs.collection_checkpoint(settings, identity, request.preview_sha256).phase == "proposed"
    )
    assert AssessmentStore(settings).load(identity).spent_requests == 0
    assert all(
        b"private-reviewer-sentinel" not in path.read_bytes()
        for path in (AssessmentStore(settings).directory / identity).rglob("*.json")
    )


@pytest.mark.parametrize("value", ["true", 1, "receipt", None])
def test_finite_preview_operations_require_typed_boolean(value: object) -> None:
    with pytest.raises(ValidationError):
        LabActionPreviewRequest.model_validate({"paired": value})


def test_checkpoint_cannot_claim_approval_or_completion_without_exact_action_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, _ = collection_setup(settings, monkeypatch)
    checkpoint = jobs.collection_checkpoint(settings, identity, request.preview_sha256)
    with pytest.raises(ValidationError, match="permission"):
        LabCollectionCheckpoint.model_validate({**checkpoint.model_dump(), "phase": "completed"})
    with pytest.raises(ValidationError, match="exact scoped"):
        LabCollectionCheckpoint.model_validate(
            {**checkpoint.model_dump(), "preview_sha256": "f" * 64}
        )


def test_invalid_analysis_approach_and_extra_tool_commands_refused() -> None:
    with pytest.raises(ValidationError):
        ObservationAnalysisRequest.model_validate({"comparison_id": "C1", "approach": "shell"})
    with pytest.raises(ValidationError):
        LabActionPreviewRequest.model_validate({"command": "curl outside.invalid"})
    assert ObservationAnalysisRequest(comparison_id="C1").approach == "baseline"


def test_accounting_cannot_claim_completed_artifact_that_was_not_collected() -> None:
    with pytest.raises(ValidationError, match="sanitized checkpoint"):
        ControlledHTTPResult(
            preview_id="preview",
            preview_sha256="a" * 64,
            runner_manifest_sha256="b" * 64,
            requests_used=1,
            seconds=0,
            stopped=True,
            action_progress=[
                HTTPActionProgress(
                    action_id="probe:0", attempts=1, completed=True, artifact_ids=["nonexistent"]
                )
            ],
        )
    with pytest.raises(ValidationError, match="attempt"):
        HTTPActionProgress(action_id="probe:0", completed=True)


def test_long_owner_data_root_preserves_exact_checkpoint_hash_without_windows_path_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / ("owner-data-" + "x" * 70))
    identity, request, trace = collection_setup(settings, monkeypatch)
    jobs.collect_saved(settings, identity, request)
    checkpoint = jobs.collection_checkpoint(settings, identity, request.preview_sha256)
    assert checkpoint.phase == "completed" and checkpoint.result == trace
    assert checkpoint.preview_sha256 == request.preview_sha256


def test_scope_stopping_is_observed_by_existing_worker_cancel_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, trace = collection_setup(settings, monkeypatch)

    def stopped(*args: object, **kwargs: object) -> ControlledHTTPResult:
        canceled = kwargs["cancel"]
        assert callable(canceled) and not canceled()
        AssessmentStore(settings).stop(identity, "Owner revoked the collection")
        assert canceled()
        return trace.model_copy(update={"stopped": True, "stop_reason": "canceled"})

    monkeypatch.setattr(jobs, "run_controlled_http", stopped)
    result = jobs.collect_saved(settings, identity, request)
    assert result.stopped
    assert jobs.collection_checkpoint(settings, identity, request.preview_sha256).phase == "stopped"
