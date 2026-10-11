"""Predeclared Task 2 development exercises, never final accuracy or external tests.

prepare: inert synthetic packets, no model/target execution.
run: two fixed local-model comparisons, at most six judgments and 600 seconds.
collect: explicitly reviewed fixed owned-lab actions, no inference or auto import.
"""

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.assessment import AssessmentStore, sanitize_http_record
from backend.assessment_jobs import analyze_saved, collect_saved, lab_preview
from backend.contracts.assessment import (
    AccessExpectation,
    AssessmentBudget,
    AssessmentScope,
    AssessmentView,
    AttachmentReview,
    ComparisonRequest,
    ScopeAuthority,
    SyntheticObject,
)
from backend.contracts.assessment import TestAccount as DesignatedAccount
from backend.contracts.assessment_engine import ControlledHTTPPermission
from backend.contracts.assessment_jobs import LabActionRunRequest
from backend.redaction import Redactor
from backend.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
MAX_JUDGMENTS = 6
MAX_SECONDS = 600
MARKER = "PLUMB-TASK2-SYNTHETIC-ORDER"
QUESTION = (
    "Can the pinned local model interpret exact synthetic comparisons "
    "and retain controls/unknowns without source code?"
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def identity() -> dict[str, str]:
    paths = [
        "eval/task2_development.py",
        "agent/web_assessment.py",
        "agent/llm.py",
        "verification/web_assessment.py",
        "verification/lab.py",
        "verification/probes.py",
        "backend/assessment_jobs.py",
        "backend/contracts/assessment.py",
        "backend/contracts/assessment_engine.py",
        "backend/contracts/assessment_jobs.py",
        "backend/profiles.py",
        "backend/preflight.py",
        "backend/redaction.py",
        "backend/llama_server.py",
        "eval/bench/machine.py",
        "verification/pins/tandir-api.json",
    ]
    paths.extend(
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in sorted((ROOT / "backend/assessment").glob("*.py"))
    )
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}


def _write_new(output: Path, result: object) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _scope(assessment_id: str, *, collection: bool = False) -> AssessmentScope:
    now = datetime.now(UTC)
    return AssessmentScope(
        scope_id="scope-" + uuid4().hex,
        assessment_id=assessment_id,
        application_id="owned-tandir",
        application_name="Owned synthetic Tandir development exercise",
        origin="http://127.0.0.1:8701",
        allowed_paths=["/health", "/orders", "/auth/login"] if collection else ["/orders"],
        allowed_actions=["read", "collect", "authenticate", "create_synthetic"]
        if collection
        else ["read", "compare", "plan", "report", "analyze"],
        accounts=[
            DesignatedAccount(account_id=account, role="customer", label="Synthetic " + account)
            for account in ("alice", "bob")
        ],
        synthetic_objects=[
            SyntheticObject(
                object_id="synthetic-order",
                owner_account_id="alice",
                kind="synthetic order",
                synthetic_marker=MARKER,
            )
        ],
        authority=ScopeAuthority(
            granted_by="Repository owner implementation task",
            reference="Task 2 implementation and owned synthetic checks; no external permission",
            granted_at=now,
        ),
        expires_at=now + timedelta(hours=4),
        budget=AssessmentBudget(
            max_requests=12 if collection else 3, max_seconds=180 if collection else 300
        ),
        stop_conditions=[
            "Cancel",
            "Budget exhaustion",
            "Unexpected personal or credential material",
        ],
    )


def _fixture_records(scope: AssessmentScope, *, protected: bool) -> list[dict[str, object]]:
    path = "invoice" if protected else "receipt"
    records: list[dict[str, object]] = []
    for identity, account, endpoint, status, body in (
        ("E01", "alice", path, 200, json.dumps({"order_id": 1000, "delivery_address": MARKER})),
        (
            "E02",
            "bob",
            path,
            403 if protected else 200,
            json.dumps({"detail": "Denied"})
            if protected
            else json.dumps({"order_id": 1000, "delivery_address": MARKER}),
        ),
        ("E03", "bob", "invoice", 403, json.dumps({"detail": "Denied"})),
    ):
        records.append(
            {
                "artifact_id": identity,
                "collected_at": datetime.now(UTC).isoformat(),
                "provenance": "Inert owned Tandir fixture; no live request or runtime proof",
                "context": {
                    "account_id": account,
                    "object_id": "synthetic-order",
                    "session_context_id": "fixture-session:" + account,
                    "request_context_id": "fixture-request:order-1000",
                },
                "request": {
                    "method": "GET",
                    "url": scope.origin + "/orders/1000/" + endpoint,
                    "headers": {},
                },
                "response": {
                    "status": status,
                    "headers": {"content-type": "application/json"},
                    "body": body,
                },
            }
        )
    return records


def prepare(settings: Settings, output: Path) -> dict[str, Any]:
    """Create two explicit software fixtures; all model/collection actions are unrun."""
    if output.exists():
        raise ValueError("preparation output already exists")
    store = AssessmentStore(settings)
    cases: list[dict[str, Any]] = []
    for name, protected in (("receipt-issue", False), ("invoice-protected", True)):
        assessment_id = "task2-dev-" + uuid4().hex
        scope = _scope(assessment_id)
        store.create(scope)
        records = _fixture_records(scope, protected=protected)
        # A fixture-only parser exercise. This label deliberately makes no claim
        # of a human reviewing observations, or an executed application test.
        review = AttachmentReview(
            reviewed_by="Automated inert synthetic fixture validation; not human acceptance",
            confirmed_sanitized=True,
            reviewed_at=datetime.now(UTC),
        )
        store.import_records(assessment_id, json.dumps({"records": records}), review)
        expectation = AccessExpectation(
            expectation_id="expected-owner",
            path="/orders/1000/" + ("invoice" if protected else "receipt"),
            object_id="synthetic-order",
            allowed_account_ids=["alice"],
            statement="Only the designated synthetic owner is allowed to read this order",
            declared_by="Owned development fixture",
            basis="Fixed synthetic owner-policy exercise",
        )
        store.add_expectation(assessment_id, expectation)
        comparison = store.add_comparison(
            assessment_id,
            ComparisonRequest(
                left_artifact_id="E01",
                right_artifact_id="E02",
                control_artifact_id="E03",
                expectation_id=expectation.expectation_id,
            ),
        )
        view = store.load(assessment_id)
        cases.append(
            {
                "case_id": name,
                "assessment_id": assessment_id,
                "comparison_id": comparison.comparison_id,
                "input_sha256": _hash(view.model_dump(mode="json")),
                "expected_interpretation": "rejected" if protected else "supported",
                "evidence_kind": "inert_synthetic_fixture",
            }
        )
    result = {
        "kind": "task2_development_preparation",
        "created_at": datetime.now(UTC).isoformat(),
        "hypothesis": QUESTION,
        "max_judgment_attempts": MAX_JUDGMENTS,
        "max_seconds": MAX_SECONDS,
        "stop_condition": "Two cases/six attempts/600s; failure/cancel stops; no retries",
        "driver": identity(),
        "cases": cases,
        "model_loaded": False,
        "target_executed": False,
        "final_evaluation": False,
        "fresh_accuracy_evidence": False,
    }
    _write_new(output, result)
    return result


def _validate_case(case: object, name: str, view: AssessmentView) -> None:
    """Hashes bind bytes; these checks also bind the declared two-case exercise."""
    protected = name == "invoice-protected"
    if not isinstance(case, dict) or (
        case.get("case_id") != name
        or case.get("expected_interpretation") != ("rejected" if protected else "supported")
        or case.get("evidence_kind") != "inert_synthetic_fixture"
        or case.get("assessment_id") != view.scope.assessment_id
    ):
        raise ValueError("preparation differs from the exact issue/protected exercise")
    scope = view.scope
    template = _scope(scope.assessment_id)
    variable_fields = {"scope_id", "authority", "expires_at"}
    if scope.model_dump(exclude=variable_fields) != template.model_dump(exclude=variable_fields):
        raise ValueError("prepared fixture scope differs from the fixed exercise")
    if (
        view.spent_requests
        or view.spent_seconds
        or view.stopped
        or view.answers
        or view.analyses
        or len(view.artifacts) != 3
        or len(view.expectations) != 1
        or len(view.comparisons) != 1
    ):
        raise ValueError("prepared fixture must be pristine and contain the exact comparison")
    expectation = AccessExpectation(
        expectation_id="expected-owner",
        path="/orders/1000/" + ("invoice" if protected else "receipt"),
        object_id="synthetic-order",
        allowed_account_ids=["alice"],
        statement="Only the designated synthetic owner is allowed to read this order",
        declared_by="Owned development fixture",
        basis="Fixed synthetic owner-policy exercise",
    )
    expected_request = ComparisonRequest(
        left_artifact_id="E01",
        right_artifact_id="E02",
        control_artifact_id="E03",
        expectation_id="expected-owner",
    )
    comparison = view.comparisons[0]
    if (
        view.expectations != [expectation]
        or comparison.request != expected_request
        or comparison.comparison_id != case.get("comparison_id")
        or comparison.conclusion != ("rejected" if protected else "candidate")
    ):
        raise ValueError("prepared comparison differs from the fixed issue/protected exercise")
    artifacts = {artifact.artifact_id: artifact for artifact in view.artifacts}
    if set(artifacts) != {"E01", "E02", "E03"}:
        raise ValueError("prepared fixture artifact identities changed")
    for record in _fixture_records(scope, protected=protected):
        actual = artifacts[str(record["artifact_id"])]
        record["collected_at"] = actual.collected_at.isoformat()
        expected = sanitize_http_record(scope, record, actual.review)
        if (
            actual.fields != expected.fields
            or actual.context != expected.context
            or actual.provenance != expected.provenance
            or actual.review.reviewed_by
            != "Automated inert synthetic fixture validation; not human acceptance"
        ):
            raise ValueError("prepared observation differs from the exact inert fixture")


def run(
    settings: Settings,
    preparation: Path,
    output: Path,
    *,
    profile: str = "auto",
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Run exactly the prepared local judgments, retaining every failed/unmet gate."""
    if output.exists():
        raise ValueError("execution output already exists")
    if preparation.stat().st_size > 2 * 1024**2:
        raise ValueError("preparation exceeds the read bound")
    prepared = json.loads(preparation.read_text(encoding="utf-8"))
    if (
        prepared.get("kind") != "task2_development_preparation"
        or prepared.get("driver") != identity()
    ):
        raise ValueError("preparation source pins changed; execution refused")
    if (
        prepared.get("max_judgment_attempts") != MAX_JUDGMENTS
        or prepared.get("max_seconds") != MAX_SECONDS
    ):
        raise ValueError("preparation differs from the fixed development budget")
    cases = prepared.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise ValueError("preparation must contain exactly the issue/protected pair")
    store = AssessmentStore(settings)
    for case, name in zip(cases, ("receipt-issue", "invoice-protected"), strict=True):
        if not isinstance(case, dict) or not isinstance(case.get("assessment_id"), str):
            raise ValueError("preparation cases require exact saved assessment identifiers")
        view = store.load(case["assessment_id"])
        if _hash(view.model_dump(mode="json")) != case["input_sha256"] or view.analyses:
            raise ValueError("prepared synthetic evidence changed or was already analyzed")
        _validate_case(case, name, view)
    started = clock()
    result: dict[str, Any] = {
        "kind": "task2_development_execution",
        "started_at": datetime.now(UTC).isoformat(),
        "preparation_sha256": hashlib.sha256(preparation.read_bytes()).hexdigest(),
        "driver": identity(),
        "hypothesis": prepared["hypothesis"],
        "max_judgment_attempts": MAX_JUDGMENTS,
        "max_seconds": MAX_SECONDS,
        "case_results": [],
        "state": "unrun",
        "evidence_kind": "fresh_local_judgments_over_inert_fixtures",
        "runtime_verification": "not_attempted",
        "final_evaluation": False,
    }
    attempted = 0
    try:
        for case in cases:
            if clock() - started >= MAX_SECONDS or attempted >= MAX_JUDGMENTS:
                result["state"] = "budget_stopped"
                break
            analysis = analyze_saved(
                settings,
                case["assessment_id"],
                case["comparison_id"],
                profile=profile,
                cancel=lambda: clock() - started >= MAX_SECONDS,
            )
            attempted += len(analysis.judgments)
            valid = [
                sample
                for sample in analysis.judgments
                if sample.answer is not None and not sample.error and not sample.violations
            ]
            expected = case["expected_interpretation"]
            passed = (
                analysis.stop_reason is None
                and len(analysis.judgments) == 3
                and len(valid) == 3
                and len({sample.seed for sample in valid}) == 3
                and {sample.answer.verdict for sample in valid if sample.answer is not None}
                == {expected}
                and analysis.conclusion == expected
            )
            result["case_results"].append(
                {
                    **case,
                    "analysis": analysis.model_dump(mode="json"),
                    "judgment_attempts": len(analysis.judgments),
                    "successful_completion_count": analysis.requests_used,
                    "matches_predeclared_interpretation": analysis.conclusion
                    == case["expected_interpretation"],
                    "acceptance_passed": passed,
                }
            )
            if not passed:
                result["state"] = "failed"
                break
        else:
            result["state"] = "completed"
    except (ValueError, OSError, RuntimeError) as error:
        result.update(state="refused_or_failed", error=type(error).__name__)
    finally:
        result.update(
            finished_at=datetime.now(UTC).isoformat(),
            seconds=max(0.0, clock() - started),
            judgment_attempts=attempted,
            local_model_manifests=[
                str(path)
                for case in cases
                for path in sorted(
                    (store.directory / case["assessment_id"] / "model-runs").glob("analysis-*.json")
                )
            ],
        )
        _write_new(output, Redactor.configured(settings).strings(result))
    return result


def collect(settings: Settings, output: Path) -> dict[str, Any]:
    """Exercise the exact developer-reviewed owned template; human import stays pending."""
    if output.exists():
        raise ValueError("collection output already exists")
    store = AssessmentStore(settings)
    assessment_id = "task2-collect-" + uuid4().hex
    store.create(_scope(assessment_id, collection=True))
    result: dict[str, Any] = {
        "kind": "task2_owned_collection_development",
        "assessment_id": assessment_id,
        "started_at": datetime.now(UTC).isoformat(),
        "driver": identity(),
        "model_loaded": False,
        "human_attachment_review": "pending",
        "automatic_import": False,
        "external_access_enabled": False,
        "runtime_verification": "not_attempted",
        "state": "unrun",
    }
    try:
        preview = lab_preview(settings, assessment_id, paired=True)
        result["preview"] = preview.model_dump(mode="json")
        consent = ControlledHTTPPermission(
            preview_sha256=preview.preview_sha256,
            approved_action_ids=[action.action_id for action in preview.preview.actions],
            approved_by="Fixed owned synthetic development exercise under implementation task",
            granted_at=datetime.now(UTC),
            expires_at=preview.preview.expires_at,
            reviewed_preview=True,
        )
        result["developer_test_permission"] = consent.model_dump(mode="json")
        trace = collect_saved(
            settings,
            assessment_id,
            LabActionRunRequest(
                preview_sha256=preview.preview_sha256,
                permission=consent,
            ),
        )
        result.update(
            trace=trace.model_dump(mode="json"),
            state="stopped" if trace.stopped else "completed_pending_human_review",
        )
    except (ValueError, OSError, RuntimeError) as error:
        result.update(state="refused_or_failed", error=type(error).__name__)
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        _write_new(output, Redactor.configured(settings).strings(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    for name in ("prepare", "run", "collect"):
        command = sub.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name == "run":
            command.add_argument("preparation", type=Path)
            command.add_argument("--profile", default="auto")
    arguments = parser.parse_args()
    settings = Settings()
    if arguments.stage == "prepare":
        result = prepare(settings, arguments.output)
    elif arguments.stage == "collect":
        result = collect(settings, arguments.output)
    else:
        result = run(settings, arguments.preparation, arguments.output, profile=arguments.profile)
    print(
        json.dumps(
            {"output": str(arguments.output.resolve()), "state": result.get("state", "prepared")},
            sort_keys=True,
        )
    )
    return 0 if result.get("state") in {None, "completed", "completed_pending_human_review"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
