"""Explicit private-local web assessment commands; imports are inert data."""

import argparse
from pathlib import Path

from backend.assessment import AssessmentStore, build_checklist, observed_map
from backend.contracts.assessment import (
    AccessExpectation,
    AttachmentReview,
    ComparisonRequest,
    ScopeCreate,
    TaskResolveRequest,
)
from backend.contracts.common import Contract
from backend.contracts.website import WebsiteScopeCreate
from backend.settings import Settings


def add_assessment_arguments(commands: argparse._SubParsersAction) -> None:
    assess = commands.add_parser(
        "assess", help="Private web observations; external access disabled"
    )
    assess.add_argument("assessment_id", nargs="?")
    assess.add_argument("--create", type=Path, help="ScopeCreate JSON with explicit authority")
    assess.add_argument(
        "--website",
        type=Path,
        help="WebsiteScopeCreate JSON: approved owned URL and explicit scope",
    )
    assess.add_argument("--import-records", type=Path, help="Reviewed bounded JSON or selected HAR")
    assess.add_argument("--review", type=Path, help="AttachmentReview JSON after human preview")
    assess.add_argument("--expectation", type=Path, help="Declared AccessExpectation JSON")
    assess.add_argument("--compare", type=Path, help="ComparisonRequest JSON of existing artifacts")
    assess.add_argument("--prompt", help="Resolve a bounded typed task; grants no authority")
    assess.add_argument("--map", action="store_true")
    assess.add_argument("--checklist", action="store_true")
    assess.add_argument("--report", action="store_true", help="Private report preview")
    assess.add_argument("--export-report", action="store_true", help="Export after --review")
    assess.add_argument("--preview-sha256", help="Exact private report draft hash after preview")
    assess.add_argument("--analyze", help="Comparison ID; explicit local three-judgment analysis")
    assess.add_argument(
        "--lab-preview", choices=["receipt", "invoice", "pair"], help="No execution"
    )
    assess.add_argument("--lab-run", type=Path, help="Approved LabActionRunRequest JSON")
    assess.add_argument(
        "--collection-status", help="Read saved proposal/attempts/missing evidence by preview hash"
    )
    assess.add_argument(
        "--import-collection", type=Path, help="LabCollectionImportRequest JSON after trace review"
    )
    assess.add_argument("--profile", default="auto")
    assess.add_argument(
        "--approach", choices=["baseline", "facts", "decomposed"], default="baseline"
    )
    assess.add_argument("--guidance-card", help="Explicit experimental local methodology card ID")
    assess.add_argument("--model", help="Pinned model ID; explicit choice, no automatic download")


def read_bounded(path: Path, *, max_bytes: int = 2 * 1024**2) -> bytes:
    if path.stat().st_size > max_bytes:
        raise ValueError("Input exceeds the import bound")
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Input exceeded its bound during reading")
    return data


def execute_assessment(settings: Settings, args: argparse.Namespace) -> int:
    try:
        selected = sum(
            bool(getattr(args, name))
            for name in (
                "create",
                "website",
                "import_records",
                "expectation",
                "compare",
                "prompt",
                "map",
                "checklist",
                "report",
                "export_report",
                "analyze",
                "lab_preview",
                "lab_run",
                "collection_status",
                "import_collection",
            )
        )
        if selected > 1:
            raise ValueError("Select exactly one action per invocation")
        if (args.approach != "baseline" or args.guidance_card) and not args.analyze:
            raise ValueError("Experimental reasoning options require an explicit analysis action")
        if selected and not args.create and not args.website and not args.assessment_id:
            raise ValueError("Select a saved assessment ID for this action")
        store = AssessmentStore(settings)
        result: Contract
        if args.website:
            from backend.website_workflow import create_website_scope

            website = WebsiteScopeCreate.model_validate_json(read_bounded(args.website))
            if args.assessment_id and args.assessment_id != website.scope.assessment_id:
                raise ValueError("Website scope differs from the selected assessment ID")
            result = create_website_scope(store, website)
        elif args.create:
            request = ScopeCreate.model_validate_json(read_bounded(args.create))
            if args.assessment_id and args.assessment_id != request.scope.assessment_id:
                raise ValueError("Scope differs from the selected assessment ID")
            result = store.create(request.scope)
        elif not args.assessment_id:
            result = store.list_scopes()
        elif args.import_records:
            if not args.review:
                raise ValueError("Human review is required")
            review = AttachmentReview.model_validate_json(read_bounded(args.review))
            result = store.import_records(
                args.assessment_id, read_bounded(args.import_records), review
            )
        elif args.expectation:
            result = store.add_expectation(
                args.assessment_id,
                AccessExpectation.model_validate_json(read_bounded(args.expectation)),
            )
        elif args.compare:
            result = store.add_comparison(
                args.assessment_id,
                ComparisonRequest.model_validate_json(read_bounded(args.compare)),
            )
        elif args.prompt:
            result = store.resolve_task(args.assessment_id, TaskResolveRequest(prompt=args.prompt))
        elif args.map:
            result = observed_map(store.load(args.assessment_id))
        elif args.checklist:
            result = build_checklist(store.load(args.assessment_id))
        elif args.report:
            result = store.report(args.assessment_id)
        elif args.export_report:
            if not args.review or not args.preview_sha256:
                raise ValueError("Preview the report and supply human review")
            result = store.export_report(
                args.assessment_id,
                AttachmentReview.model_validate_json(read_bounded(args.review)),
                args.preview_sha256,
            )
        elif args.analyze:
            from backend.assessment_jobs import analyze_saved

            result = analyze_saved(
                settings,
                args.assessment_id,
                args.analyze,
                profile=args.profile,
                approach=args.approach,
                guidance_card_id=args.guidance_card,
            )
        elif args.lab_preview:
            from backend.assessment_jobs import lab_preview

            result = lab_preview(
                settings,
                args.assessment_id,
                invoice=args.lab_preview == "invoice",
                paired=args.lab_preview == "pair",
            )
        elif args.lab_run:
            from backend.assessment_jobs import collect_saved
            from backend.contracts.assessment_jobs import LabActionRunRequest

            result = collect_saved(
                settings,
                args.assessment_id,
                LabActionRunRequest.model_validate_json(read_bounded(args.lab_run)),
            )
        elif args.collection_status:
            from backend.assessment_jobs import collection_checkpoint

            result = collection_checkpoint(settings, args.assessment_id, args.collection_status)
        elif args.import_collection:
            from backend.assessment_jobs import import_collection
            from backend.contracts.assessment_jobs import LabCollectionImportRequest

            result = import_collection(
                settings,
                args.assessment_id,
                LabCollectionImportRequest.model_validate_json(
                    read_bounded(args.import_collection)
                ),
            )
        else:
            result = store.load(args.assessment_id)
        print(result.model_dump_json(indent=2))
        return 0
    except (OSError, ValueError, RuntimeError):
        print(
            "Assessment refused. Check scope/expiry, IDs, action and bounded input. "
            "Review sanitized data before import/export; external interaction remains disabled."
        )
        return 1
