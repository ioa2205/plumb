"""Assessment jobs share the production lock and preserve private bounded outcomes."""

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr

from agent.llm import JsonAnswer, ModelRequest, ModelUnavailable, Spend
from backend import assessment_jobs as jobs
from backend.assessment import AssessmentStore
from backend.contracts.assessment import AssessmentView, AttachmentReview
from backend.contracts.assessment_engine import ControlledHTTPPermission, ControlledHTTPResult
from backend.contracts.assessment_jobs import LabActionRunRequest, LabCollectionImportRequest
from backend.jobs import WorkerBusy, WorkerLock
from backend.redaction import Redactor
from backend.settings import Settings
from eval import task2_development as development


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Settings, AssessmentStore, dict[str, Any]]:
    settings = Settings(
        data_dir=tmp_path / "data", redaction_secrets=(SecretStr("configured-private-secret"),)
    )
    result = development.prepare(settings, tmp_path / "preparation.json")
    return settings, AssessmentStore(settings), result["cases"][0]


def manifests(settings: Settings, identity: str) -> list[dict[str, Any]]:
    directory = AssessmentStore(settings).directory / identity / "model-runs"
    return [json.loads(path.read_text()) for path in sorted(directory.glob("analysis-*.json"))]


def fake_model(
    monkeypatch: pytest.MonkeyPatch,
    view: AssessmentView,
    *,
    failure: bool = False,
    after_ask: Callable[[], object] = lambda: None,
    after_start: Callable[[float], object] = lambda timeout: None,
    before_ask: Callable[[Spend], object] = lambda spend: None,
) -> list[str]:
    calls: list[str] = []
    selected = SimpleNamespace(
        id="fixture-profile",
        backend="cpu",
        model_id="fixture-model",
        model_sha256="a" * 64,
        identity=lambda: {"id": "fixture-profile", "model_sha256": "a" * 64},
    )
    monkeypatch.setattr(jobs, "machine_state", lambda: {"fixture": True})
    monkeypatch.setattr(jobs, "select", lambda *args: selected)
    monkeypatch.setattr(jobs, "first_use_pending", lambda *args: False)

    def create(*args: object) -> object:
        calls.append("create")
        return SimpleNamespace(
            config=SimpleNamespace(argv=lambda *args: ["fixture-local-server"]),
            startup_timeout=300,
            stop=lambda: calls.append("server-stop"),
        )

    class Adapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            calls.append("adapter")
            assert kwargs.get("attempt_seconds") is None
            self.server = cast(SimpleNamespace, args[0])
            self.started = False
            redactor = cast(Redactor, kwargs["redactor"])
            assert redactor.text("configured-private-secret") != "configured-private-secret"

        def start(self) -> None:
            if not self.started:
                self.started = True
                calls.append("start")
                after_start(self.server.startup_timeout)

        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            calls.append("ask")
            before_ask(spend)
            after_ask()
            if failure:
                raise ModelUnavailable("configured-private-secret")
            spend.requests += 1
            spend.seconds += 1
            payload = json.loads(
                request.user.removeprefix("OBSERVATION_DATA\n").removesuffix(
                    "\nEND_OBSERVATION_DATA"
                )
            )
            answer = {
                "verdict": "supported",
                "evidence_refs": [
                    observation["fields"][field]["ref"]
                    for observation in payload["observations"]
                    for field in ("response.status", "response.body")
                ],
                "rationale": "The synthetic observations match the declared owner policy.",
                "alternative_explanations": ["Account identity was supplied by the reviewer."],
                "missing_evidence": ["Independent runtime reproduction was not attempted."],
                "mitigation": "Enforce object ownership.",
            }
            return JsonAnswer(answer, json.dumps(answer), 100, 50, 1)

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(jobs, "create", create)
    monkeypatch.setattr(jobs, "ModelAdapter", Adapter)
    return calls


def test_first_cleanup_failure_cannot_be_hidden_by_adapter_second_close(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    calls = fake_model(monkeypatch, store.load(case["assessment_id"]))
    original = jobs.ModelAdapter

    class FailedClose(original):  # type: ignore[misc]
        def close(self) -> None:
            if self.started:
                self.started = False
                calls.append("failed-close")
                raise OSError("Private cleanup details")

    monkeypatch.setattr(jobs, "ModelAdapter", FailedClose)
    with pytest.raises(OSError):
        jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    manifest = manifests(settings, case["assessment_id"])[0]
    assert manifest["model_stopped"] is False
    assert manifest["cleanup_errors"] == ["OSError"]
    assert calls.count("failed-close") == 1 and calls.count("server-stop") == 1
    assert "Private cleanup details" not in json.dumps(manifest)


def test_start_failure_still_stops_created_server_and_preserves_spend(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    calls = fake_model(monkeypatch, store.load(case["assessment_id"]))
    original = jobs.ModelAdapter

    class FailedStart(original):  # type: ignore[misc]
        def start(self) -> None:
            calls.append("failed-start")
            raise OSError("Private startup details")

    monkeypatch.setattr(jobs, "ModelAdapter", FailedStart)
    with pytest.raises(OSError):
        jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    manifest = manifests(settings, case["assessment_id"])[0]
    assert manifest["outcome"] == "refused_or_failed" and manifest["model_stopped"]
    assert calls.count("server-stop") == 1
    assert manifest["spend"]["requests"] == 0


def test_model_loading_reduces_request_budget_and_caps_startup_timeout(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    elapsed = [0.0]
    monkeypatch.setattr(jobs, "time", SimpleNamespace(perf_counter=lambda: elapsed[0]))
    startup_limits: list[float] = []
    request_limits: list[float] = []

    def load(timeout: float) -> None:
        startup_limits.append(timeout)
        elapsed[0] += 40

    calls = fake_model(
        monkeypatch,
        store.load(case["assessment_id"]),
        after_start=load,
        before_ask=lambda spend: request_limits.append(spend.seconds_left),
    )
    result = jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    assert result.conclusion == "supported"
    assert startup_limits == [300] and calls.count("start") == 1
    assert request_limits == [260, 259, 258]
    assert store.load(case["assessment_id"]).spent_seconds == 40


@pytest.mark.parametrize("stop", ["cancel", "time"])
def test_stop_during_loading_prevents_first_judgment_and_charges_loading_time(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
) -> None:
    settings, store, case = prepared
    elapsed = [0.0]
    canceled = [False]
    monkeypatch.setattr(jobs, "time", SimpleNamespace(perf_counter=lambda: elapsed[0]))

    def load(timeout: float) -> None:
        assert timeout == 300
        elapsed[0] = 40 if stop == "cancel" else 301
        canceled[0] = stop == "cancel"

    calls = fake_model(monkeypatch, store.load(case["assessment_id"]), after_start=load)
    result = jobs.analyze_saved(
        settings, case["assessment_id"], case["comparison_id"], cancel=lambda: canceled[0]
    )
    assert result.conclusion == "inconclusive" and result.requests_used == 0
    assert calls.count("start") == 1 and "ask" not in calls and "close" in calls
    saved = store.load(case["assessment_id"])
    assert saved.spent_requests == 3
    assert saved.spent_seconds == (40 if stop == "cancel" else 300)
    assert manifests(settings, case["assessment_id"])[0]["requests"] == []


def test_outer_deadline_bounds_loading_after_machine_diagnostics(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    elapsed = [0.0]
    monkeypatch.setattr(jobs, "time", SimpleNamespace(perf_counter=lambda: elapsed[0]))
    limits: list[float] = []
    fake_model(monkeypatch, store.load(case["assessment_id"]), after_start=limits.append)

    def diagnostics() -> dict[str, object]:
        elapsed[0] = 80.0
        return {"fixture": True}

    monkeypatch.setattr(jobs, "machine_state", diagnostics)
    result = jobs.analyze_saved(
        settings, case["assessment_id"], case["comparison_id"], max_seconds=90
    )
    assert limits == [10.0] and result.conclusion == "supported"


def test_source_review_lock_refuses_assessment_before_model_selection(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    calls = fake_model(monkeypatch, store.load(case["assessment_id"]))
    with WorkerLock(settings.cache_dir / "review.lock"), pytest.raises(WorkerBusy):
        jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    assert not calls and store.load(case["assessment_id"]).spent_requests == 0
    assert manifests(settings, case["assessment_id"])[0]["outcome"] == "refused_or_failed"


@pytest.mark.parametrize("blocked", ["first_use", "cancel"])
def test_first_use_and_prior_cancel_never_launch_or_reserve(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    blocked: str,
) -> None:
    settings, store, case = prepared
    calls = fake_model(monkeypatch, store.load(case["assessment_id"]))
    monkeypatch.setattr(jobs, "first_use_pending", lambda *args: blocked == "first_use")
    with pytest.raises(ValueError):
        jobs.analyze_saved(
            settings,
            case["assessment_id"],
            case["comparison_id"],
            cancel=lambda: blocked == "cancel",
        )
    assert not calls and store.load(case["assessment_id"]).spent_requests == 0
    manifest = manifests(settings, case["assessment_id"])[0]
    assert manifest["model_stopped"] and manifest["requests"] == []


def test_three_lifetime_attempts_and_elapsed_time_are_charged_before_lock_release(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    calls = fake_model(monkeypatch, store.load(case["assessment_id"]))
    original_charge = AssessmentStore.charge_budget
    charges: list[tuple[int, float]] = []

    def charge(
        self: AssessmentStore, identity: str, *, requests: int = 0, seconds: float = 0
    ) -> AssessmentView:
        with pytest.raises(WorkerBusy), WorkerLock(settings.cache_dir / "review.lock"):
            pytest.fail("both reservation and completion must hold the shared worker lock")
        charges.append((requests, seconds))
        return original_charge(self, identity, requests=requests, seconds=seconds)

    monkeypatch.setattr(AssessmentStore, "charge_budget", charge)
    result = jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    saved = store.load(case["assessment_id"])
    assert result.conclusion == "supported" and result.requests_used == 3
    assert saved.spent_requests == 3 and saved.spent_seconds > 0
    assert charges[0] == (3, 0) and charges[-1][0] == 0 and charges[-1][1] > 0
    assert calls.count("ask") == 3 and calls.count("close") >= 1
    with pytest.raises(ValueError, match="budget"):
        jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    assert calls.count("create") == 1


def test_stopped_midrun_still_charges_elapsed_time_and_keeps_failed_manifest(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    calls = fake_model(
        monkeypatch,
        store.load(case["assessment_id"]),
        after_ask=lambda: store.stop(case["assessment_id"], "Owner stopped"),
    )
    with pytest.raises(ValueError, match="stopped"):
        jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    saved = store.load(case["assessment_id"])
    assert saved.stopped and saved.spent_requests == 3 and saved.spent_seconds > 0
    assert "close" in calls
    manifest = manifests(settings, case["assessment_id"])[0]
    assert manifest["outcome"] == "refused_or_failed" and manifest["elapsed_budget_seconds"] > 0
    assert manifest["result"]["judgments"] and not saved.analyses


def test_scope_expired_midrun_still_charges_elapsed_seconds(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    view = store.load(case["assessment_id"])

    class FutureDatetime:
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return view.scope.expires_at + timedelta(seconds=1)

    fake_model(
        monkeypatch, view, after_ask=lambda: monkeypatch.setattr(jobs, "datetime", FutureDatetime)
    )
    jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    saved = store.load(case["assessment_id"])
    assert saved.spent_requests == 3 and saved.spent_seconds > 0
    assert saved.analyses[0]["conclusion"] == "inconclusive"


def test_failed_judgment_retains_class_only_raw_failure_and_configured_secret_stays_private(
    prepared: tuple[Settings, AssessmentStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, case = prepared
    calls = fake_model(monkeypatch, store.load(case["assessment_id"]), failure=True)
    result = jobs.analyze_saved(settings, case["assessment_id"], case["comparison_id"])
    assert result.conclusion == "inconclusive" and result.requests_used == 0
    assert calls.count("ask") == 1 and result.judgments[0].error == "ModelUnavailable"
    manifest = manifests(settings, case["assessment_id"])[0]
    assert manifest["requests"][0]["error"] == "ModelUnavailable"
    assert "configured-private-secret" not in json.dumps(manifest)
    assert store.load(case["assessment_id"]).spent_requests == 3


def collection_setup(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, LabActionRunRequest, ControlledHTTPResult]:
    identity = "owned-collection-job"
    store = AssessmentStore(settings)
    scope = development._scope(identity, collection=True)
    store.create(scope)
    preview = jobs.lab_preview(settings, identity, paired=True)
    consent = ControlledHTTPPermission(
        preview_sha256=preview.preview_sha256,
        approved_action_ids=[action.action_id for action in preview.preview.actions],
        approved_by="Owned synthetic test fixture",
        granted_at=datetime.now(UTC),
        expires_at=scope.expires_at,
        reviewed_preview=True,
    )
    runtime_scope = scope.model_copy(update={"origin": "http://127.0.0.1:19999"})
    records = development._fixture_records(runtime_scope, protected=False)
    trace = ControlledHTTPResult.model_validate(
        {
            "preview_id": preview.preview.preview_id,
            "preview_sha256": preview.preview_sha256,
            "runner_manifest_sha256": preview.preview.runner_manifest_sha256,
            "runner_origin": runtime_scope.origin,
            "records": records,
            "requests_used": 9,
            "seconds": 0.01,
            "stopped": False,
        }
    )
    monkeypatch.setattr(jobs, "run_controlled_http", lambda *args, **kwargs: trace)
    return (
        identity,
        LabActionRunRequest(preview_sha256=preview.preview_sha256, permission=consent),
        trace,
    )


def test_collection_consumes_once_reserves_health_cap_and_stages_without_auto_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, trace = collection_setup(settings, monkeypatch)
    assert jobs.collect_saved(settings, identity, request) == trace
    store = AssessmentStore(settings)
    saved = store.load(identity)
    assert saved.spent_requests == 12 and saved.spent_seconds > 0
    assert not saved.artifacts and not saved.analyses
    path = store.directory / identity / "collections" / f"{request.preview_sha256}.json"
    assert ControlledHTTPResult.model_validate_json(path.read_bytes()) == trace
    with pytest.raises(ValueError, match="unconsumed"):
        jobs.collect_saved(settings, identity, request)


def test_collection_import_requires_explicit_human_review_and_preserves_actual_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    identity, request, trace = collection_setup(settings, monkeypatch)
    jobs.collect_saved(settings, identity, request)
    with pytest.raises(ValueError):
        LabCollectionImportRequest.model_validate({"preview_sha256": request.preview_sha256})
    review = AttachmentReview(
        reviewed_by="Named synthetic test reviewer",
        confirmed_sanitized=True,
        reviewed_at=datetime.now(UTC),
    )
    result = jobs.import_collection(
        settings,
        identity,
        LabCollectionImportRequest(preview_sha256=request.preview_sha256, review=review),
    )
    assert len(result.artifacts) == 3
    assert all(artifact.review == review for artifact in result.artifacts)
    assert all(
        artifact.fields["request.url"].startswith(trace.runner_origin or "invalid")
        for artifact in result.artifacts
    )
    assert all(artifact.trusted_lab_collection is not None for artifact in result.artifacts)


def test_job_polling_sees_entire_records_busy_and_cancellation_are_bounded(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    worker = jobs.AssessmentJobs(settings)
    started, release = threading.Event(), threading.Event()

    def work(cancel: Callable[[], bool]) -> ControlledHTTPResult:
        started.set()
        assert release.wait(5)
        assert cancel()
        return ControlledHTTPResult(
            preview_id="fixture",
            preview_sha256="a" * 64,
            runner_manifest_sha256="b" * 64,
            requests_used=0,
            seconds=0,
            stopped=True,
            stop_reason="canceled",
        )

    try:
        job = worker.start("owned-job", "collect", work)
        assert started.wait(5)
        with pytest.raises(WorkerBusy):
            worker.start("second-job", "collect", work)
        assert all(worker.read(job.job_id).state == "running" for _ in range(20))
        worker.cancel(job.job_id)
        release.set()
        worker.close()
        ended = worker.read(job.job_id)
        assert ended.state == "canceled" and ended.result is not None
        assert not list((settings.cache_dir / "assessment-jobs").glob("*.tmp"))
    finally:
        release.set()
        worker.close()


def test_atomic_job_write_preserves_old_valid_record_until_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "job.json"
    path.write_text('{"state":"old"}')
    original = jobs.write_json
    observed: list[object] = []

    def write(temporary: Path, value: object) -> None:
        observed.append(json.loads(path.read_text()))
        assert temporary != path
        original(temporary, value)
        observed.append(json.loads(path.read_text()))

    monkeypatch.setattr(jobs, "write_json", write)
    jobs._atomic_json(path, {"state": "new"})
    assert observed == [{"state": "old"}, {"state": "old"}]
    assert json.loads(path.read_text()) == {"state": "new"}
    assert not list(tmp_path.glob("*.tmp"))
