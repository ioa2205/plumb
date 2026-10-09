"""The local API. Every request passes the checks in ``backend.security``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from subprocess import SubprocessError
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi import Path as PathParameter
from fastapi.responses import StreamingResponse

from backend.browser_jobs import BrowserJobs, LaunchRefused
from backend.case_reads import CaseMissing, CaseReads, CaseUnavailable
from backend.contracts.application_map import ApplicationMap
from backend.contracts.cases import (
    CaseDetail,
    CitedExcerpt,
    FindingPage,
    PeerExcerpt,
    SnapshotCodePage,
)
from backend.contracts.common import Family, Id, Sha256
from backend.contracts.investigation import (
    Disposition,
    DispositionDecision,
    DispositionUpdate,
    ExhibitTag,
    Question,
    RuntimeVerification,
    Severity,
)
from backend.contracts.policies import BoundPolicy, PolicyInput
from backend.contracts.project_view import PolicyConfirm, ProjectExcerpt, ProjectPage, ProjectRule
from backend.contracts.review_view import FindingList, QueueEdit, ReviewPage
from backend.contracts.run_history import ComparisonGroup, RunComparison, RunHistory
from backend.contracts.runs import ReviewRun
from backend.contracts.setup_view import (
    InspectionView,
    InspectRequest,
    LaunchRequest,
    ResumeRequest,
    SetupReadiness,
    SourceCheck,
)
from backend.disposition_store import DispositionConflict
from backend.jobs import WorkerBusy
from backend.map_store import MapStore, MapUnavailable
from backend.policy_store import PolicyConflict
from backend.project_reads import ProjectMissing, ProjectReads, ProjectUnavailable
from backend.queue_controls import QueueConflict, edit_queue
from backend.redaction import Redactor
from backend.review_reads import review_page
from backend.run_reads import RunReads, RunReadUnavailable
from backend.run_store import RunStore
from backend.security import BOOTSTRAP_PATH, Gate, Guarded, bootstrap
from backend.settings import Settings
from backend.setup_reads import inspect_folder, readiness
from backend.source_binding import check_source
from backend.sse import last_seen, stream
from backend.workbench import DEFAULT_DIRECTORY, Workbench


def create_app(
    settings: Settings | None = None,
    *,
    port: int | None = None,
    workbench_dir: Path | None = None,
) -> FastAPI:
    """The app for a server bound to ``port`` on loopback (default: the configured port).

    ``app.state.gate`` holds this launch's one-time bootstrap link.
    """
    settings = settings or Settings()
    redactor = Redactor.configured(settings)
    gate = Gate(settings.port if port is None else port, redactor=redactor)
    store = MapStore(settings.cache_dir / "application_maps.sqlite")
    runs = RunStore(settings.cache_dir / "runs.sqlite", redactor=redactor)
    cases = CaseReads(settings)
    projects = ProjectReads(settings)
    history = RunReads(settings)
    worker = BrowserJobs(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Closing the terminal pauses at a saved checkpoint and joins the owned worker.
            # Existing request budgets bound in-flight inference; its model is stopped by CLI.
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(worker.close)

    app = FastAPI(title="Plumb", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.worker = worker
    app.state.gate = gate
    app.add_middleware(Guarded, gate=gate)
    workbench = Workbench(workbench_dir if workbench_dir is not None else DEFAULT_DIRECTORY)

    @app.get(BOOTSTRAP_PATH, include_in_schema=False)
    def open_session(request: Request, token: str | None = None) -> Response:
        return bootstrap(gate, token, request.headers.get("cookie"))

    @app.get("/api/snapshots/{snapshot_id}/map", response_model=ApplicationMap)
    def application_map(snapshot_id: Sha256) -> ApplicationMap:
        try:
            result = store.load(snapshot_id)
        except MapUnavailable as error:
            raise HTTPException(
                status_code=503, detail="This map cannot be read. Rebuild the snapshot map."
            ) from error
        if result is None:
            raise HTTPException(
                status_code=404, detail="No application map exists for this snapshot."
            )
        return result

    def known(run_id: str) -> ReviewRun:
        run = runs.run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="No run has this ID.")
        return run

    def launch_error(error: Exception) -> HTTPException:
        return HTTPException(
            status_code=409 if isinstance(error, WorkerBusy) else 503,
            detail="Review could not start. Check readiness, inspect the current local folder "
            "and read the terminal. Saved results are preserved.",
        )

    @app.post("/api/projects/review", response_model=ReviewRun, status_code=202)
    def start_review(request: LaunchRequest) -> ReviewRun:
        try:
            return worker.launch(request)
        except (OSError, ValueError, WorkerBusy, LaunchRefused) as error:
            raise launch_error(error) from error

    @app.post("/api/runs/{run_id}/resume", response_model=ReviewRun, status_code=202)
    def resume_review(run_id: Id, request: ResumeRequest) -> ReviewRun:
        known(run_id)
        try:
            return worker.resume(run_id, request)
        except (OSError, ValueError, WorkerBusy, LaunchRefused) as error:
            raise launch_error(error) from error

    @app.post("/api/runs/{run_id}/source-check", response_model=SourceCheck)
    def current_source(run_id: Id) -> SourceCheck:
        known(run_id)
        try:
            return check_source(settings, run_id)
        except (OSError, ValueError, WorkerBusy) as error:
            raise launch_error(error) from error

    @app.get("/api/setup", response_model=SetupReadiness)
    def setup_readiness() -> SetupReadiness:
        try:
            return readiness(settings)
        except WorkerBusy as error:
            raise HTTPException(
                status_code=409,
                detail="A review is running. Read its saved results; "
                "check readiness after it stops.",
            ) from error
        except (OSError, ValueError, KeyError) as error:
            raise HTTPException(
                status_code=503,
                detail="Readiness cannot be established. Run plumb setup in the terminal; "
                "no download or model has started.",
            ) from error

    @app.post("/api/projects/inspect", response_model=InspectionView)
    def open_project(request: InspectRequest) -> InspectionView:
        try:
            return inspect_folder(settings, request.folder)
        except WorkerBusy as error:
            raise HTTPException(
                status_code=409,
                detail="A review is running. Inspect after it stops; "
                "saved results remain available.",
            ) from error
        except (OSError, ValueError, RuntimeError, SubprocessError, CaseUnavailable) as error:
            raise HTTPException(
                status_code=503,
                detail="This folder cannot be inspected safely. Check its absolute local path, "
                "separate data storage and plumb setup. No target code was executed.",
            ) from error

    @app.get("/api/runs", response_model=RunHistory)
    def run_history(offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0) -> RunHistory:
        try:
            return history.history(offset)
        except RunReadUnavailable as error:
            raise HTTPException(
                status_code=503, detail="Recorded history cannot be read safely."
            ) from error

    @app.get("/api/runs/{run_id}/compare", response_model=RunComparison)
    def run_comparison(
        run_id: Id,
        before: Id,
        group: ComparisonGroup = "new",
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        policy_offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> RunComparison:
        try:
            return history.comparison(before, run_id, group, offset, policy_offset)
        except RunReadUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="These saved reviews cannot be compared safely. "
                "Check their order and saved reports; incomplete coverage remains unknown.",
            ) from error

    @app.get("/api/runs/{run_id}", response_model=ReviewRun)
    def review_run(run_id: Id) -> ReviewRun:
        return known(run_id)

    def saved_error(error: CaseUnavailable) -> HTTPException:
        return HTTPException(
            status_code=404 if isinstance(error, CaseMissing) else 503,
            detail="No saved case matches this request."
            if isinstance(error, CaseMissing)
            else "This saved case cannot be read safely. Its report is preserved.",
        )

    def project_error(error: Exception) -> HTTPException:
        return HTTPException(
            status_code=404 if isinstance(error, ProjectMissing) else 503,
            detail="This project's frozen map or source is unavailable. "
            "Its saved report is preserved.",
        )

    @app.get("/api/runs/{run_id}/project", response_model=ProjectPage)
    def project_page(
        run_id: Id,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        scope_offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        policy_offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> ProjectPage:
        known(run_id)
        try:
            return projects.page(run_id, offset, scope_offset, policy_offset)
        except ProjectUnavailable as error:
            raise project_error(error) from error

    @app.get("/api/runs/{run_id}/project/citations/{citation_id}", response_model=ProjectExcerpt)
    def project_source(
        run_id: Id,
        citation_id: Id,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> ProjectExcerpt:
        known(run_id)
        try:
            return projects.excerpt(run_id, citation_id, offset)
        except ProjectUnavailable as error:
            raise project_error(error) from error

    @app.post("/api/runs/{run_id}/project/rules", response_model=BoundPolicy, status_code=201)
    def declare_rule(run_id: Id, request: PolicyInput) -> BoundPolicy:
        known(run_id)
        try:
            return projects.declare(run_id, request)
        except PolicyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ProjectUnavailable as error:
            raise HTTPException(
                status_code=503, detail="Declared rule could not be saved."
            ) from error

    @app.post("/api/runs/{run_id}/project/rules/{policy_id}/confirm", response_model=ProjectRule)
    def confirm_rule(run_id: Id, policy_id: Id, request: PolicyConfirm) -> ProjectRule:
        known(run_id)
        try:
            return projects.confirm(run_id, policy_id, request.proposal_sha256)
        except PolicyConflict as error:
            raise HTTPException(
                status_code=409, detail="This rule changed. Refresh before confirming."
            ) from error
        except (ProjectUnavailable, CaseUnavailable, MapUnavailable, OSError, ValueError) as error:
            raise project_error(error) from error

    @app.get("/api/runs/{run_id}/findings", response_model=FindingPage)
    def finding_page(
        run_id: Id,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        limit: Annotated[int, Query(ge=1, le=20)] = 20,
    ) -> FindingPage:
        try:
            return cases.page(run_id, offset, limit)
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.get("/api/runs/{run_id}/findings/{finding_id}", response_model=CaseDetail)
    def finding_case(run_id: Id, finding_id: Id) -> CaseDetail:
        try:
            return cases.case(run_id, finding_id)
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.post(
        "/api/runs/{run_id}/findings/{finding_id}/disposition", response_model=DispositionDecision
    )
    def decide_disposition(
        run_id: Id, finding_id: Id, request: DispositionUpdate
    ) -> DispositionDecision:
        try:
            return cases.update_disposition(run_id, finding_id, request)
        except DispositionConflict as error:
            raise HTTPException(
                status_code=409,
                detail="Reviewer state changed or its history is full. "
                "Refresh the case before another decision.",
            ) from error
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.get("/api/runs/{run_id}/current-report")
    def current_report(
        run_id: Id, format: Literal["json", "markdown", "html", "sarif"] = "json"
    ) -> Response:
        try:
            content = cases.export(run_id, format)
        except CaseUnavailable as error:
            raise saved_error(error) from error
        suffix, media = {
            "json": ("json", "application/json"),
            "markdown": ("md", "text/markdown"),
            "html": ("html", "text/html"),
            "sarif": ("sarif", "application/sarif+json"),
        }[format]
        return Response(
            content,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{run_id}-current.{suffix}"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/runs/{run_id}/findings/{finding_id}/exhibits/{tag}", response_model=CitedExcerpt)
    def cited_excerpt(
        run_id: Id,
        finding_id: Id,
        tag: ExhibitTag,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        lines: Annotated[int, Query(ge=1, le=80)] = 80,
    ) -> CitedExcerpt:
        try:
            return cases.excerpt(run_id, finding_id, tag, offset, lines)
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.get(
        "/api/runs/{run_id}/findings/{finding_id}/peers/{site_id}/citations/{citation}",
        response_model=PeerExcerpt,
    )
    def peer_excerpt(
        run_id: Id,
        finding_id: Id,
        site_id: Id,
        citation: Annotated[int, PathParameter(ge=0, le=201)],
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        lines: Annotated[int, Query(ge=1, le=80)] = 80,
    ) -> PeerExcerpt:
        try:
            return cases.peer_excerpt(run_id, finding_id, site_id, citation, offset, lines)
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.get(
        "/api/runs/{run_id}/findings/{finding_id}/exhibits/{tag}/code",
        response_model=SnapshotCodePage,
    )
    def exhibit_code(
        run_id: Id,
        finding_id: Id,
        tag: ExhibitTag,
        mode: Literal["context", "file"] = "context",
        before: Annotated[int, Query(ge=0, le=80)] = 3,
        after: Annotated[int, Query(ge=0, le=80)] = 3,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        lines: Annotated[int, Query(ge=1, le=80)] = 80,
    ) -> SnapshotCodePage:
        try:
            return cases.code_page(
                run_id,
                finding_id,
                tag=tag,
                mode=mode,
                before=before,
                after=after,
                offset=offset,
                lines=lines,
            )
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.get(
        "/api/runs/{run_id}/findings/{finding_id}/peers/{site_id}/citations/{citation}/code",
        response_model=SnapshotCodePage,
    )
    def peer_code(
        run_id: Id,
        finding_id: Id,
        site_id: Id,
        citation: Annotated[int, PathParameter(ge=0, le=201)],
        mode: Literal["context", "file"] = "context",
        before: Annotated[int, Query(ge=0, le=80)] = 3,
        after: Annotated[int, Query(ge=0, le=80)] = 3,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        lines: Annotated[int, Query(ge=1, le=80)] = 80,
    ) -> SnapshotCodePage:
        try:
            return cases.code_page(
                run_id,
                finding_id,
                site_id=site_id,
                citation=citation,
                mode=mode,
                before=before,
                after=after,
                offset=offset,
                lines=lines,
            )
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.get("/api/runs/{run_id}/questions", response_model=list[Question])
    def run_questions(run_id: Id) -> list[Question]:
        """The queue in order, with whatever each question has reached so far."""
        known(run_id)
        return runs.questions(run_id)

    @app.get("/api/runs/{run_id}/review", response_model=ReviewPage)
    def review_view(
        run_id: Id, offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0
    ) -> ReviewPage:
        known(run_id)
        result = review_page(runs, run_id, offset)
        if result is None:
            raise HTTPException(status_code=404, detail="No run has this ID.")
        if len(result.model_dump_json().encode("utf-8")) > 512 * 1024:
            raise HTTPException(status_code=503, detail="This review page is too large to display.")
        return result

    @app.get("/api/runs/{run_id}/finding-list", response_model=FindingList)
    def grouped_findings(
        run_id: Id,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        family: Family | None = None,
        severity: Severity | None = None,
        runtime_verification: RuntimeVerification | None = None,
        disposition: Disposition | None = None,
    ) -> FindingList:
        try:
            return cases.finding_list(
                run_id,
                offset,
                family=family,
                severity=severity,
                runtime_verification=runtime_verification,
                disposition=disposition,
            )
        except CaseUnavailable as error:
            raise saved_error(error) from error

    @app.post("/api/runs/{run_id}/queue", response_model=ReviewPage)
    def change_queue(run_id: Id, edit: QueueEdit) -> ReviewPage:
        known(run_id)
        try:
            edit_queue(runs, run_id, edit)
        except WorkerBusy as error:
            raise HTTPException(
                status_code=409, detail="A worker is still active. Wait for its paused checkpoint."
            ) from error
        except QueueConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return review_view(run_id, edit.offset)

    @app.get("/api/runs/{run_id}/events", include_in_schema=False)
    def run_events(
        run_id: Id, last_event_id: Annotated[str | None, Header()] = None
    ) -> StreamingResponse:
        known(run_id)
        return StreamingResponse(
            stream(runs, run_id, last_seen(last_event_id)), media_type="text/event-stream"
        )

    def ask(run_id: str, action: Literal["cancel", "pause"]) -> dict[str, str]:
        known(run_id)
        if not runs.request(run_id, action):
            raise HTTPException(status_code=409, detail="This run has already ended.")
        return {"requested": action}

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: Id) -> dict[str, str]:
        """Takes effect at the worker's next checkpoint; finished questions are kept."""
        return ask(run_id, "cancel")

    @app.post("/api/runs/{run_id}/pause", status_code=202)
    def pause_run(run_id: Id) -> dict[str, str]:
        return ask(run_id, "pause")

    app.router.default = workbench
    return app
