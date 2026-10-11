"""Session-protected local assessment routes. No imported URL is fetched here."""

from fastapi import APIRouter, HTTPException

from backend.assessment import AssessmentStore, build_checklist, observed_map
from backend.assessment_jobs import (
    AssessmentJobs,
    analyze_saved,
    collect_saved,
    collection_checkpoint,
    import_collection,
    lab_preview,
)
from backend.contracts.assessment import (
    AccessExpectation,
    AssessmentAnswer,
    AssessmentChecklist,
    AssessmentList,
    AssessmentView,
    ComparisonRequest,
    EvidenceImportRequest,
    ObservationComparison,
    ObservedMap,
    PrivateReportRequest,
    ReportPreview,
    ScopeCreate,
    TaskResolveRequest,
)
from backend.contracts.assessment_jobs import (
    AssessmentJob,
    LabActionPreview,
    LabActionPreviewRequest,
    LabActionRunRequest,
    LabCollectionCheckpoint,
    LabCollectionImportRequest,
    ObservationAnalysisRequest,
)
from backend.contracts.common import Id, Sha256
from backend.contracts.website import WebsiteScopeCreate
from backend.jobs import WorkerBusy
from backend.settings import Settings
from backend.website_workflow import create_website_scope


def assessment_router(settings: Settings, jobs: AssessmentJobs) -> APIRouter:
    router = APIRouter(prefix="/api/assessments")
    store = AssessmentStore(settings)

    def failure(error: Exception) -> HTTPException:
        # Imported data may contain credentials or PII; errors never echo parser input.
        return HTTPException(
            status_code=409,
            detail="Assessment action refused. Check the saved scope, expiry, review, "
            "artifact IDs and privacy stop. Imported observations remain private local data.",
        )

    @router.get("", response_model=AssessmentList)
    def listing() -> AssessmentList:
        return store.list_scopes()

    @router.post("", response_model=AssessmentView, status_code=201)
    def create(request: ScopeCreate) -> AssessmentView:
        try:
            return store.create(request.scope)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/website", response_model=AssessmentView, status_code=201)
    def website_scope(request: WebsiteScopeCreate) -> AssessmentView:
        try:
            return create_website_scope(store, request)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.get("/{assessment_id}", response_model=AssessmentView)
    def read(assessment_id: Id) -> AssessmentView:
        try:
            return store.load(assessment_id)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/imports", response_model=AssessmentView)
    def import_evidence(assessment_id: Id, request: EvidenceImportRequest) -> AssessmentView:
        try:
            return store.import_records(assessment_id, request.payload, request.review)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/expectations", response_model=AssessmentView)
    def expectation(assessment_id: Id, request: AccessExpectation) -> AssessmentView:
        try:
            return store.add_expectation(assessment_id, request)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/prompt", response_model=AssessmentAnswer)
    def prompt(assessment_id: Id, request: TaskResolveRequest) -> AssessmentAnswer:
        try:
            return store.resolve_task(assessment_id, request)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.get("/{assessment_id}/map", response_model=ObservedMap)
    def mapping(assessment_id: Id) -> ObservedMap:
        try:
            return observed_map(store.load(assessment_id))
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.get("/{assessment_id}/checklist", response_model=AssessmentChecklist)
    def checklist(assessment_id: Id) -> AssessmentChecklist:
        try:
            return build_checklist(store.load(assessment_id))
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/comparisons", response_model=ObservationComparison)
    def comparison(assessment_id: Id, request: ComparisonRequest) -> ObservationComparison:
        try:
            return store.add_comparison(assessment_id, request)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.get("/{assessment_id}/report", response_model=ReportPreview)
    def report_preview(assessment_id: Id) -> ReportPreview:
        try:
            return store.report(assessment_id)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/report", response_model=ReportPreview)
    def report_export(assessment_id: Id, request: PrivateReportRequest) -> ReportPreview:
        try:
            return store.export_report(assessment_id, request.review, request.preview_sha256)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/analyze", response_model=AssessmentJob, status_code=202)
    def analyze(assessment_id: Id, request: ObservationAnalysisRequest) -> AssessmentJob:
        try:
            store.load(assessment_id)
            return jobs.start(
                assessment_id,
                "analyze",
                lambda cancel: analyze_saved(
                    settings,
                    assessment_id,
                    request.comparison_id,
                    profile=request.profile,
                    approach=request.approach,
                    guidance_card_id=request.guidance_card_id,
                    cancel=cancel,
                ),
            )
        except (ValueError, OSError, WorkerBusy) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/actions/preview", response_model=LabActionPreview)
    def preview_action(assessment_id: Id, request: LabActionPreviewRequest) -> LabActionPreview:
        try:
            return lab_preview(
                settings, assessment_id, invoice=request.invoice, paired=request.paired
            )
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/actions/run", response_model=AssessmentJob, status_code=202)
    def run_action(assessment_id: Id, request: LabActionRunRequest) -> AssessmentJob:
        try:
            store.load(assessment_id)
            return jobs.start(
                assessment_id,
                "collect",
                lambda cancel: collect_saved(settings, assessment_id, request, cancel=cancel),
            )
        except (ValueError, OSError, WorkerBusy) as error:
            raise failure(error) from error

    @router.post("/{assessment_id}/collections/import", response_model=AssessmentView)
    def reviewed_collection(
        assessment_id: Id, request: LabCollectionImportRequest
    ) -> AssessmentView:
        try:
            return import_collection(settings, assessment_id, request)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    @router.get(
        "/{assessment_id}/collections/{preview_sha256}", response_model=LabCollectionCheckpoint
    )
    def saved_collection(assessment_id: Id, preview_sha256: Sha256) -> LabCollectionCheckpoint:
        try:
            return collection_checkpoint(settings, assessment_id, preview_sha256)
        except (ValueError, OSError) as error:
            raise failure(error) from error

    return router


def assessment_job_router(jobs: AssessmentJobs) -> APIRouter:
    router = APIRouter(prefix="/api/assessment-jobs")

    @router.get("/{job_id}", response_model=AssessmentJob)
    def read_job(job_id: Id) -> AssessmentJob:
        try:
            return jobs.read(job_id)
        except (ValueError, OSError) as error:
            raise HTTPException(
                status_code=404, detail="No readable owned assessment job"
            ) from error

    @router.post("/{job_id}/cancel", response_model=AssessmentJob)
    def cancel_job(job_id: Id) -> AssessmentJob:
        try:
            return jobs.cancel(job_id)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=409, detail="This job is not active") from error

    return router
