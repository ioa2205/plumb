"""One local heavy worker shared with source review, with durable private results."""

import hashlib
import json
import re
import sys
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from agent.llm import JsonAnswer, ModelAdapter, ModelRequest, Spend
from agent.web_assessment import ObservationAnalysis, analyze_observations
from backend.assessment import AssessmentStore
from backend.contracts.assessment import AssessmentView
from backend.contracts.assessment_jobs import (
    AssessmentJob,
    LabActionPreview,
    LabActionRunRequest,
    LabCollectionCheckpoint,
    LabCollectionImportRequest,
)
from backend.contracts.common import Contract
from backend.contracts.investigation import Budget
from backend.jobs import WorkerBusy, WorkerLock
from backend.preflight import PreflightResult
from backend.profiles import create, first_use_pending, select
from backend.redaction import Redactor
from backend.review import write_json
from backend.settings import Settings
from eval.bench.machine import machine_state
from verification.web_assessment import (
    ControlledHTTPPreview,
    ControlledHTTPResult,
    preview_lab_assessment,
    run_controlled_http,
)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    """Polling readers see an entire old or new job, never a half-written record."""
    # Keep the sibling filename short on hosts without long-path support.
    target = _long_io_path(path)
    temporary = target.with_name("." + uuid4().hex + ".tmp")
    try:
        write_json(temporary, value)
        # A Windows polling reader can briefly deny deletion of the old file.
        # Keep the complete old record visible and retry only that transient
        # replacement boundary. Retry waits total at most 70 ms; I/O still varies.
        for attempt in range(8):
            try:
                temporary.replace(target)
                break
            except PermissionError as error:
                if (
                    sys.platform != "win32"
                    or getattr(error, "winerror", None) not in {5, 32, 33}
                    or attempt == 7
                ):
                    raise
                time.sleep(0.01)
    finally:
        temporary.unlink(missing_ok=True)


def _long_io_path(path: Path) -> Path:
    """Native Windows extended paths after callers have checked storage boundaries."""
    if sys.platform == "win32" and len(str(path.absolute())) > 240:
        absolute = str(path.absolute())
        if not absolute.startswith("\\\\?\\"):
            return Path(
                "\\\\?\\UNC\\" + absolute[2:]
                if absolute.startswith("\\\\")
                else "\\\\?\\" + absolute
            )
    return path


def analyze_saved(
    settings: Settings,
    assessment_id: str,
    comparison_id: str,
    *,
    profile: str = "auto",
    approach: Literal["baseline", "facts", "decomposed"] = "baseline",
    guidance_card_id: str | None = None,
    max_seconds: float | None = None,
    cancel: Callable[[], bool] = lambda: False,
) -> ObservationAnalysis:
    deadline = None if max_seconds is None else time.perf_counter() + max_seconds
    if max_seconds is not None and (not 0 < max_seconds <= 3600):
        raise ValueError("Analysis deadline must be positive and bounded")
    if approach not in {"baseline", "facts", "decomposed"}:
        raise ValueError("Unknown observation approach")
    guidance_card = None
    if guidance_card_id is not None:
        from knowledge.cards import load_cards

        guidance_card = next((card for card in load_cards() if card.id == guidance_card_id), None)
        if guidance_card is None:
            raise ValueError("Unknown reviewed local guidance card")
    store = AssessmentStore(settings)
    view = store.load(assessment_id)
    if view.stopped or datetime.now(UTC) >= view.scope.expires_at:
        raise ValueError("Assessment stopped or expired")
    directory = store._safe_path(store.directory / assessment_id / "model-runs")
    directory.mkdir(parents=True, exist_ok=True)
    identifier = "analysis-" + uuid4().hex
    manifest: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "assessment_id": assessment_id,
        "comparison_id": comparison_id,
        "input_sha256": _digest(view.model_dump(mode="json")),
        "scope": view.scope.model_dump(mode="json"),
        "preflights": [],
        "requests": [],
        "outcome": "not_started",
        "approach": approach,
        "guidance_card": guidance_card.model_dump(mode="json") if guidance_card else None,
        "outer_max_seconds": max_seconds,
    }
    adapter: ModelAdapter | None = None
    server = None
    spend: Spend | None = None
    cleanup_errors: list[Exception] = []
    cleanup_attempted = False
    budget_started = 0.0
    seconds_available = 0.0

    def stop_owned_model() -> None:
        nonlocal cleanup_attempted
        if cleanup_attempted:
            return
        cleanup_attempted = True
        if adapter is not None:
            try:
                adapter.close()
            except (OSError, RuntimeError) as error:
                cleanup_errors.append(error)
        # Adapter.start may fail after server creation but before its started
        # flag is set. Stop the created server independently, under the lock.
        if server is not None:
            try:
                server.stop()
            except (OSError, RuntimeError) as error:
                cleanup_errors.append(error)

    try:
        with ExitStack() as cleanup:
            cleanup.enter_context(WorkerLock(settings.cache_dir / "review.lock"))
            if cancel():
                raise ValueError("Canceled before loading")
            view = store.load(assessment_id)
            if view.stopped or datetime.now(UTC) >= view.scope.expires_at:
                raise ValueError("Assessment stopped or expired")
            if not any(item.comparison_id == comparison_id for item in view.comparisons):
                raise ValueError("Unknown saved comparison")
            manifest["machine_start"] = machine_state()
            selected = select(settings, profile)
            if first_use_pending(settings, selected):
                raise ValueError("Run plumb calibrate before this profile's first analysis")
            seconds_available = view.scope.budget.max_seconds - view.spent_seconds
            if deadline is not None:
                seconds_available = min(seconds_available, deadline - time.perf_counter())
            if seconds_available <= 0:
                raise ValueError("Assessment time budget exhausted")
            view = store.charge_budget(assessment_id, requests=3)
            budget_started = time.perf_counter()

            def finish_budget() -> None:
                elapsed = time.perf_counter() - budget_started
                store.charge_budget(assessment_id, seconds=min(elapsed, seconds_available))
                manifest["elapsed_budget_seconds"] = elapsed

            # Charge elapsed time before releasing the shared heavy-worker lock,
            # including cancellation/failure after this assessment expires/stops.
            cleanup.callback(finish_budget)
            manifest["reserved_judgment_attempts"] = 3
            manifest["seconds_available"] = seconds_available
            server = create(settings, identifier, selected)
            cleanup.callback(stop_owned_model)
            manifest.update(
                profile=selected.identity(),
                server_argv=server.config.argv(0, "<per-launch key>"),
                implementation={
                    str(path.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in (
                        Path(__file__),
                        Path(__file__).with_name("assessment_api.py"),
                        Path(__file__).resolve().parents[1] / "agent/web_assessment.py",
                        Path(__file__).resolve().parents[1] / "agent/observation_facts.py",
                        Path(__file__).resolve().parents[1] / "knowledge/cards.py",
                        Path(__file__).resolve().parents[1] / "eval/bench/machine.py",
                        Path(__file__).resolve().parents[1] / "backend/contracts/assessment.py",
                        Path(__file__).resolve().parents[1]
                        / "backend/contracts/assessment_engine.py",
                    )
                },
            )
            manifest["implementation"].update(
                {
                    str(path.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in (Path(__file__).with_name("assessment")).glob("*.py")
                }
            )

            def preflight() -> PreflightResult:
                result = server.preflight()
                manifest["preflights"].append(asdict(result))
                return result

            adapter = ModelAdapter(
                server,
                preflight=preflight,
                redactor=Redactor.configured(settings),
            )
            spend = Spend(
                Budget(
                    max_looks=0,
                    max_prompt_tokens=18000,
                    max_seconds=max(
                        0.01, seconds_available - (time.perf_counter() - budget_started)
                    ),
                    max_retries=0,
                )
            )

            class Recorder:
                def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
                    if cancel():
                        raise ValueError("Canceled")
                    if datetime.now(UTC) >= view.scope.expires_at:
                        raise ValueError("Assessment scope expired")
                    if time.perf_counter() - budget_started >= seconds_available:
                        raise ValueError("Assessment time budget exhausted")
                    # Model loading is part of this assessment's wall-clock budget.
                    # The shared adapter's request spend excludes server startup.
                    server.startup_timeout = min(
                        server.startup_timeout,
                        seconds_available - (time.perf_counter() - budget_started),
                    )
                    adapter.start()
                    remaining = seconds_available - (time.perf_counter() - budget_started)
                    if cancel() or remaining <= 0 or datetime.now(UTC) >= view.scope.expires_at:
                        raise ValueError(
                            "Canceled, expired or time budget exhausted during loading"
                        )
                    spend.budget = spend.budget.model_copy(
                        update={"max_seconds": spend.seconds + min(spend.seconds_left, remaining)}
                    )
                    row: dict[str, Any] = {
                        "request": request.body(),
                        "started_at": datetime.now(UTC).isoformat(),
                    }
                    manifest["requests"].append(row)
                    try:
                        answer = adapter.ask(request, spend)
                    except (ValueError, OSError, RuntimeError) as error:
                        row["error"] = type(error).__name__
                        raise
                    row["answer"] = asdict(answer)
                    return answer

            result = analyze_observations(
                view,
                comparison_id,
                Recorder(),
                spend,
                cancel=cancel,
                approach=approach,
                guidance_card=guidance_card,
            )
            result = ObservationAnalysis.model_validate(
                {
                    **result.model_dump(),
                    "model_provenance": [
                        f"Model {selected.model_id}; SHA-256 {selected.model_sha256}",
                        f"Profile {selected.id}; backend {selected.backend}; "
                        "pinned local llama.cpp",
                        f"Exact private invocation manifest: {directory / (identifier + '.json')}",
                        f"Observation approach: {approach}; "
                        + (
                            f"methodology card {guidance_card.id} version {guidance_card.version}; "
                            f"SHA-256 {guidance_card.content_sha256}"
                            if guidance_card
                            else "no guidance card"
                        ),
                    ],
                }
            )
            manifest.update(
                outcome=result.conclusion,
                result=result.model_dump(mode="json"),
                spend={**asdict(spend), "budget": spend.budget.model_dump(mode="json")},
            )
            current = store.load(assessment_id)
            if current.scope != view.scope or current.stopped:
                raise ValueError("Scope changed or stopped during analysis")
            store.save(
                current.model_copy(
                    update={"analyses": [*current.analyses, result.model_dump(mode="json")]}
                )
            )
            return result
    except (ValueError, OSError, RuntimeError) as error:
        manifest.update(outcome="refused_or_failed", error=type(error).__name__)
        raise
    finally:
        stop_owned_model()
        if spend is not None:
            manifest["spend"] = {**asdict(spend), "budget": spend.budget.model_dump(mode="json")}
        if cleanup_errors:
            manifest["cleanup_errors"] = [type(error).__name__ for error in cleanup_errors]
        if server is not None:
            sampler = getattr(server, "sampler", None)
            manifest["model_memory"] = {
                "peak_working_set_bytes": sampler.peak_working_set if sampler else None,
                "peak_private_commit_bytes": sampler.peak_private if sampler else None,
                "samples": sampler.samples if sampler else 0,
                "unavailable_reason": None if sampler else "Model process sampler did not start",
            }
            manifest["load_seconds"] = getattr(server, "load_seconds", None)
            log_path = getattr(server, "log_path", None)
            manifest["runtime_log"] = str(log_path) if log_path else None
        manifest["ended_at"] = datetime.now(UTC).isoformat()
        manifest["model_stopped"] = not cleanup_errors
        write_json(
            directory / f"{identifier}.json", Redactor.configured(settings).strings(manifest)
        )
        if cleanup_errors:
            raise cleanup_errors[0]


def lab_preview(
    settings: Settings, assessment_id: str, *, invoice: bool = False, paired: bool = False
) -> LabActionPreview:
    view = AssessmentStore(settings).load(assessment_id)
    if view.stopped:
        raise ValueError("Assessment stopped")
    preview = preview_lab_assessment(view.scope, invoice=invoice, paired=paired)
    directory = _long_io_path(settings.cache_dir / "assessment-previews")
    directory.mkdir(parents=True, exist_ok=True)
    write_json(_long_io_path(directory / f"{preview.sha256}.json"), preview.model_dump(mode="json"))
    checkpoint = LabCollectionCheckpoint(
        assessment_id=assessment_id,
        preview_sha256=preview.sha256,
        preview=preview,
        phase="proposed",
        updated_at=datetime.now(UTC),
        message="Finite scoped proposal. Review and approve every exact action before execution.",
    )
    _save_collection_checkpoint(AssessmentStore(settings), checkpoint)
    return LabActionPreview(preview=preview, preview_sha256=preview.sha256)


def _collection_checkpoint_path(
    store: AssessmentStore, assessment_id: str, preview_sha256: str
) -> Path:
    # Resolve the assessment through the same validated private store before
    # using either identity in a filename supplied by the CLI/API.
    store.load(assessment_id)
    if re.fullmatch(r"[0-9a-f]{64}", preview_sha256) is None:
        raise ValueError("Unknown exact preview hash")
    path = store._safe_path(
        store.directory / assessment_id / "collections" / (preview_sha256 + ".checkpoint.json")
    )
    return _long_io_path(path)


def _save_collection_checkpoint(
    store: AssessmentStore, checkpoint: LabCollectionCheckpoint
) -> None:
    value = checkpoint.model_dump(mode="json")
    if store.redactor.strings(value) != value:
        raise ValueError("collection checkpoint refuses private credential material")
    path = _collection_checkpoint_path(store, checkpoint.assessment_id, checkpoint.preview_sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, value)


def collection_checkpoint(
    settings: Settings, assessment_id: str, preview_sha256: str
) -> LabCollectionCheckpoint:
    """Resume by reading saved attempts/evidence; never replay a state change."""
    store = AssessmentStore(settings)
    path = _collection_checkpoint_path(store, assessment_id, preview_sha256)
    if path.stat().st_size > 2 * 1024**2:
        raise ValueError("Collection checkpoint exceeds its read bound")
    result = LabCollectionCheckpoint.model_validate_json(path.read_bytes())
    if (
        result.assessment_id != assessment_id
        or result.preview_sha256 != preview_sha256
        or result.preview.sha256 != preview_sha256
        or result.preview.assessment_id != assessment_id
    ):
        raise ValueError("Collection checkpoint belongs to another exact proposal")
    if result.phase in {"approved", "executing"}:
        try:
            with WorkerLock(settings.cache_dir / "review.lock"):
                # An interrupted write is conservatively uncertain even if no
                # action yet appears completed. A fresh preview and separate
                # approval are needed for a new disposable collection.
                return result.model_copy(
                    update={
                        "phase": "interrupted",
                        "message": "Saved partial collection; no active worker. Attempts may "
                        "have changed synthetic state. Review saved missing evidence and "
                        "obtain a fresh preview/approval for a new disposable collection.",
                    }
                )
        except WorkerBusy:
            pass
    return result


def collect_saved(
    settings: Settings,
    assessment_id: str,
    request: LabActionRunRequest,
    *,
    cancel: Callable[[], bool] = lambda: False,
) -> ControlledHTTPResult:
    store = AssessmentStore(settings)
    with WorkerLock(settings.cache_dir / "review.lock"):
        view = store.load(assessment_id)
        if view.stopped or cancel():
            raise ValueError("Assessment stopped")
        path = _long_io_path(
            settings.cache_dir / "assessment-previews" / f"{request.preview_sha256}.json"
        )
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("No current unconsumed preview")
        preview = ControlledHTTPPreview.model_validate_json(path.read_bytes())
        if preview.assessment_id != assessment_id or preview.sha256 != request.preview_sha256:
            raise ValueError("Preview belongs to another scope")
        from verification.web_assessment import validate_permission

        validate_permission(view.scope, preview, request.permission)
        seconds_available = view.scope.budget.max_seconds - view.spent_seconds
        if seconds_available <= 0:
            raise ValueError("Assessment time budget exhausted")
        checkpoint = LabCollectionCheckpoint(
            assessment_id=assessment_id,
            preview_sha256=preview.sha256,
            preview=preview,
            phase="approved",
            permission=request.permission,
            updated_at=datetime.now(UTC),
            message="Exact proposal approved; permission is one use and cannot be replayed.",
        )
        _save_collection_checkpoint(store, checkpoint)
        store.charge_budget(assessment_id, requests=preview.max_requests)
        # Consume before launch under the shared lock. Even failed/canceled permission
        # cannot be replayed into another state change; a new preview is required.
        path.rename(path.with_suffix(".consumed"))
        started = time.perf_counter()

        def saved_progress(partial: ControlledHTTPResult) -> None:
            nonlocal checkpoint
            partial = ControlledHTTPResult.model_validate(partial.model_dump())
            if (
                partial.preview_sha256 != preview.sha256
                or partial.preview_id != preview.preview_id
                or partial.runner_manifest_sha256 != preview.runner_manifest_sha256
            ):
                raise ValueError("partial collection differs from the exact approved proposal")
            checkpoint = checkpoint.model_copy(
                update={
                    "phase": "stopped" if partial.stopped else "executing",
                    "result": partial,
                    "updated_at": datetime.now(UTC),
                    "message": "Attempt checkpoint saved; sanitized collected evidence "
                    "requires separate human review. Missing actions cannot be replayed.",
                }
            )
            _save_collection_checkpoint(store, checkpoint)

        def canceled_or_changed() -> bool:
            if cancel() or time.perf_counter() - started >= seconds_available:
                return True
            current = store.load(assessment_id)
            return current.stopped or current.scope != view.scope

        try:
            result = run_controlled_http(
                view.scope,
                preview,
                request.permission,
                settings=settings,
                cancel=canceled_or_changed,
                checkpoint=saved_progress,
            )
        except BaseException:
            checkpoint = checkpoint.model_copy(
                update={
                    "phase": "interrupted",
                    "updated_at": datetime.now(UTC),
                    "message": "Collection interrupted; retain attempted actions and missing "
                    "evidence. No automatic continuation or reuse of permission.",
                }
            )
            _save_collection_checkpoint(store, checkpoint)
            raise
        finally:
            store.charge_budget(
                assessment_id, seconds=min(time.perf_counter() - started, seconds_available)
            )
        directory = store._safe_path(store.directory / assessment_id / "collections")
        _long_io_path(directory).mkdir(parents=True, exist_ok=True)
        saved_progress(result)
        _atomic_json(directory / f"{request.preview_sha256}.json", result.model_dump(mode="json"))
        checkpoint = checkpoint.model_copy(
            update={
                "phase": "stopped" if result.stopped else "completed",
                "result": result,
                "updated_at": datetime.now(UTC),
                "message": "Saved owned collection; review sanitized evidence before import. "
                "A stopped or interrupted collection cannot silently resume.",
            }
        )
        _save_collection_checkpoint(store, checkpoint)
        if result.stopped:
            store.stop(assessment_id, result.stop_reason or "Owned collection stopped")
        return result


def import_collection(
    settings: Settings, assessment_id: str, request: LabCollectionImportRequest
) -> AssessmentView:
    store = AssessmentStore(settings)
    view = store.load(assessment_id)
    path = _long_io_path(
        store._safe_path(
            store.directory / assessment_id / "collections" / f"{request.preview_sha256}.json"
        )
    )
    if path.stat().st_size > 2 * 1024**2:
        raise ValueError("Collected trace exceeds its read bound")
    result = ControlledHTTPResult.model_validate_json(path.read_bytes())
    if result.preview_sha256 != request.preview_sha256 or result.stopped or view.stopped:
        raise ValueError("Collected trace is stopped or belongs to another preview")
    return store.import_lab_records(
        assessment_id,
        result,
        request.review,
        prepare_website=request.prepare_website_comparisons,
    )


class AssessmentJobs:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._closing = False
        self._current: str | None = None

    def _path(self, job_id: str) -> Path:
        if re.fullmatch(r"assessment-job-[0-9a-f]{32}", job_id) is None:
            raise ValueError("Unknown assessment job")
        return self.settings.cache_dir / "assessment-jobs" / f"{job_id}.json"

    def read(self, job_id: str) -> AssessmentJob:
        path = self._path(job_id)
        if path.stat().st_size > 2 * 1024**2:
            raise ValueError("Job record exceeds read bound")
        return AssessmentJob.model_validate_json(path.read_bytes())

    def start(
        self,
        assessment_id: str,
        action: Literal["analyze", "collect"],
        work: Callable[[Callable[[], bool]], Contract],
    ) -> AssessmentJob:
        with self._lock:
            if self._closing or (self._thread is not None and self._thread.is_alive()):
                raise WorkerBusy("A local assessment worker is already active")
            self._cancel.clear()
            job = AssessmentJob(
                job_id="assessment-job-" + uuid4().hex,
                assessment_id=assessment_id,
                action=action,
                state="queued",
                created_at=datetime.now(UTC),
                message="Queued explicit local action",
            )
            path = self._path(job.job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_json(path, job.model_dump(mode="json"))
            self._current = job.job_id

            def execute() -> None:
                running = job.model_copy(
                    update={"state": "running", "message": "Local action in progress"}
                )
                _atomic_json(path, running.model_dump(mode="json"))
                try:
                    result = work(self._cancel.is_set)
                    ended = running.model_copy(
                        update={
                            "state": "canceled" if self._cancel.is_set() else "completed",
                            "result": result.model_dump(mode="json"),
                            "ended_at": datetime.now(UTC),
                            "message": "Local action stopped"
                            if self._cancel.is_set()
                            else "Saved local result",
                        }
                    )
                except (ValueError, OSError, RuntimeError):
                    ended = running.model_copy(
                        update={
                            "state": "canceled" if self._cancel.is_set() else "failed",
                            "ended_at": datetime.now(UTC),
                            "message": "Action refused or stopped; inspect scope and local "
                            "prerequisites. No external access.",
                        }
                    )
                _atomic_json(
                    path, Redactor.configured(self.settings).strings(ended.model_dump(mode="json"))
                )

            self._thread = threading.Thread(target=execute, name="plumb-assessment", daemon=False)
            self._thread.start()
            return job

    def cancel(self, job_id: str) -> AssessmentJob:
        with self._lock:
            if job_id != self._current:
                raise ValueError("Job is not the current owned worker")
            self._cancel.set()
        return self.read(job_id)

    def close(self) -> None:
        with self._lock:
            self._closing = True
            self._cancel.set()
            thread = self._thread
        if thread is not None:
            thread.join()
