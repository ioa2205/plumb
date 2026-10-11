"""The owned URL journey preserves explicit authority, controls and private review."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agent.llm import JsonAnswer, ModelRequest, Spend
from backend import assessment_jobs as jobs
from backend import cli
from backend.app import create_app
from backend.assessment import AssessmentStore
from backend.assessment.evidence import digest
from backend.contracts.assessment import AssessmentBudget, AttachmentReview
from backend.contracts.assessment_engine import ControlledHTTPResult
from backend.contracts.website import WebsiteScopeCreate
from backend.settings import Settings
from backend.website_workflow import create_website_scope, prepared_website_comparisons
from eval import task2_development as development
from verification import lab

from .support import ORIGIN, PORT, signed_in, visitor


def request(identity: str = "website-fixture") -> WebsiteScopeCreate:
    scope = development._scope(identity, collection=True).model_copy(
        update={
            "allowed_actions": [
                "read",
                "compare",
                "plan",
                "report",
                "analyze",
                "collect",
                "authenticate",
                "create_synthetic",
            ],
            "budget": AssessmentBudget(max_requests=30, max_seconds=600),
        }
    )
    return WebsiteScopeCreate(
        url="http://127.0.0.1:8701/orders",
        scope=scope,
        confirmed_authority=True,
        expected_owner_only=True,
        expectation_basis="Explicit synthetic owner policy; independent of observed HTTP responses",
    )


def paired_trace(website: WebsiteScopeCreate) -> ControlledHTTPResult:
    runtime_scope = website.scope.model_copy(update={"origin": "http://127.0.0.1:19999"})
    owner, other, control = cast(
        list[dict[str, Any]], development._fixture_records(runtime_scope, protected=False)
    )
    setup = copy.deepcopy(owner)
    setup["artifact_id"] = "W-setup"
    setup["request"] = {
        "method": "POST",
        "url": runtime_scope.origin + "/orders",
        "headers": {},
    }
    setup["response"] = {"status": 200, "headers": {}, "body": '{"id":1000}'}
    invoice_owner = copy.deepcopy(owner)
    invoice_owner["artifact_id"] = "W-invoice-owner"
    invoice_owner["request"]["url"] = runtime_scope.origin + "/orders/1000/invoice"
    invoice_control = copy.deepcopy(control)
    invoice_control["artifact_id"] = "W-invoice-control"
    return ControlledHTTPResult.model_validate(
        {
            "preview_id": "paired-synthetic",
            "preview_sha256": "a" * 64,
            "runner_manifest_sha256": digest(lab.PIN.read_bytes()),
            "runner_origin": runtime_scope.origin,
            "records": [setup, other, owner, control, invoice_owner, invoice_control],
            "requests_used": 9,
            "seconds": 0.01,
            "stopped": False,
        }
    )


def human_review() -> AttachmentReview:
    return AttachmentReview(
        reviewed_by="Synthetic evidence reviewer",
        confirmed_sanitized=True,
        reviewed_at=datetime.now(UTC),
    )


def test_owned_url_starts_with_prior_explicit_policy_and_no_network(tmp_path: Path) -> None:
    store = AssessmentStore(Settings(data_dir=tmp_path / "private"))
    website = request()
    view = create_website_scope(store, website)
    assert not view.artifacts and not view.comparisons and not view.analyses
    assert view.spent_requests == view.spent_seconds == 0
    assert {item.path for item in view.expectations} == {
        "/orders/{order_id}/receipt",
        "/orders/{order_id}/invoice",
    }
    assert all(item.allowed_account_ids == ["alice"] for item in view.expectations)
    assert all(item.basis == website.expectation_basis for item in view.expectations)


def test_private_expectation_validation_cannot_leave_a_partial_website_scope(
    tmp_path: Path,
) -> None:
    from pydantic import SecretStr

    store = AssessmentStore(
        Settings(data_dir=tmp_path / "private", redaction_secrets=(SecretStr("private-basis"),))
    )
    website = request().model_copy(update={"expectation_basis": "private-basis"})
    with pytest.raises(ValueError, match="unsanitized"):
        create_website_scope(store, website)
    assert not store.list_scopes().assessments


@pytest.mark.parametrize(
    "url",
    [
        "https://external.invalid",
        "http://localhost:8701",
        "http://127.0.0.1:8702",
        "http://127.0.0.1:8701@external.invalid",
        "http://127.0.0.1:8701/orders?next=https://external.invalid",
        "http://127.0.0.1:8701/orders#fragment",
        "http://127.0.0.1:8701/%6frders",
        "http://127.0.0.1:8701/orders/../auth/login",
        "http://127.0.0.1:8701\\orders",
        "http://127.0.0.1:8701/orders/1042/receipt",
    ],
)
def test_unapproved_or_noncanonical_url_never_creates_scope(tmp_path: Path, url: str) -> None:
    store = AssessmentStore(Settings(data_dir=tmp_path / "private"))
    website = request().model_copy(update={"url": url})
    with pytest.raises(ValueError):
        create_website_scope(store, website)
    assert not store.list_scopes().assessments


@pytest.mark.parametrize(
    "changed", ["authority", "expectation", "actions", "accounts", "paths", "budget"]
)
def test_scope_requires_separate_authority_expectation_and_full_approved_boundary(
    tmp_path: Path, changed: str
) -> None:
    raw = request().model_dump(mode="json")
    if changed == "authority":
        raw["confirmed_authority"] = False
    elif changed == "expectation":
        raw["expected_owner_only"] = False
    elif changed == "actions":
        raw["scope"]["allowed_actions"].remove("authenticate")
    elif changed == "accounts":
        raw["scope"]["accounts"] = raw["scope"]["accounts"][:1]
    elif changed == "paths":
        raw["scope"]["allowed_paths"] = ["/orders"]
    else:
        raw["scope"]["budget"]["max_requests"] = 17
    store = AssessmentStore(Settings(data_dir=tmp_path / "private"))
    with pytest.raises(ValueError):
        create_website_scope(store, WebsiteScopeCreate.model_validate(raw))
    assert not store.list_scopes().assessments


def test_reviewed_pair_prepares_exact_controls_and_private_report_without_inference(
    tmp_path: Path,
) -> None:
    store = AssessmentStore(Settings(data_dir=tmp_path / "private"))
    website = request()
    create_website_scope(store, website)
    trace = paired_trace(website)
    view = store.import_lab_records(
        website.scope.assessment_id, trace, human_review(), prepare_website=True
    )
    assert len(view.artifacts) == 6 and len(view.comparisons) == 2
    assert [item.conclusion for item in view.comparisons] == ["candidate", "rejected"]
    assert all(item.request.control_artifact_id for item in view.comparisons)
    assert all(not item.missing_evidence for item in view.comparisons)
    assert prepared_website_comparisons(view, trace.preview_sha256) == view
    assert all(item.execution_status == "imported" for item in view.artifacts)
    draft = store.report(website.scope.assessment_id)
    assert draft.report.confidentiality == "private_local"
    assert draft.report.runtime_verification == "not_attempted"
    saved = store.export_report(website.scope.assessment_id, human_review(), draft.preview_sha256)
    assert saved.export_path is not None and Path(saved.export_path).is_file()
    assert not saved.submitted


def test_complete_website_journey_with_fixture_model_preserves_three_judgments_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "private")
    store = AssessmentStore(settings)
    website = request("website-journey")
    create_website_scope(store, website)
    preview = jobs.lab_preview(settings, website.scope.assessment_id, paired=True)
    from backend.contracts.assessment_engine import ControlledHTTPPermission
    from backend.contracts.assessment_jobs import LabActionRunRequest, LabCollectionImportRequest

    permission = ControlledHTTPPermission(
        preview_sha256=preview.preview_sha256,
        approved_action_ids=[item.action_id for item in preview.preview.actions],
        approved_by="Synthetic action approver",
        granted_at=datetime.now(UTC),
        expires_at=website.scope.expires_at,
        reviewed_preview=True,
    )
    trace = paired_trace(website).model_copy(
        update={"preview_id": preview.preview.preview_id, "preview_sha256": preview.preview_sha256}
    )
    monkeypatch.setattr(jobs, "run_controlled_http", lambda *args, **kwargs: trace)
    collected = jobs.collect_saved(
        settings,
        website.scope.assessment_id,
        LabActionRunRequest(preview_sha256=preview.preview_sha256, permission=permission),
    )
    assert collected == trace and not store.load(website.scope.assessment_id).artifacts
    view = jobs.import_collection(
        settings,
        website.scope.assessment_id,
        LabCollectionImportRequest(
            preview_sha256=preview.preview_sha256,
            review=human_review(),
            prepare_website_comparisons=True,
        ),
    )
    lifecycle: list[str] = []
    seeds: list[int | None] = []
    selected = SimpleNamespace(
        id="fixture-profile",
        backend="cpu",
        model_id="fixture-model",
        model_sha256="b" * 64,
        identity=lambda: {"id": "fixture-profile", "model_sha256": "b" * 64},
    )
    monkeypatch.setattr(jobs, "machine_state", lambda: {"fixture": True})
    monkeypatch.setattr(jobs, "select", lambda *args: selected)
    monkeypatch.setattr(jobs, "first_use_pending", lambda *args: False)
    monkeypatch.setattr(
        jobs,
        "create",
        lambda *args: SimpleNamespace(
            config=SimpleNamespace(argv=lambda *args: ["fixture-only-no-process"]),
            startup_timeout=300,
            stop=lambda: lifecycle.append("server-stopped"),
        ),
    )

    class FixtureAdapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            lifecycle.append("created")

        def start(self) -> None:
            lifecycle.append("fixture-start")

        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            payload = json.loads(
                request.user.removeprefix("OBSERVATION_DATA\n").removesuffix(
                    "\nEND_OBSERVATION_DATA"
                )
            )
            observations = payload["observations"]
            other = next(item for item in observations if item["role"] == "other")
            answer = {
                "verdict": "rejected"
                if other["fields"]["response.status"]["value"] == "403"
                else "supported",
                "evidence_refs": [
                    item["fields"][field]["ref"]
                    for item in observations
                    for field in ("response.status", "response.body")
                ],
                "rationale": "Synthetic fixture interpretation; not real model acceptance.",
                "alternative_explanations": ["Accounts remain declared fixture context."],
                "missing_evidence": ["Independent runtime reproduction remains unclaimed."],
                "mitigation": "Enforce the declared owner policy.",
            }
            seeds.append(request.seed)
            spend.requests += 1
            spend.seconds += 0.1
            return JsonAnswer(answer, json.dumps(answer), 10, 10, 0.1)

        def close(self) -> None:
            lifecycle.append("closed")

    monkeypatch.setattr(jobs, "ModelAdapter", FixtureAdapter)
    outcomes = [
        jobs.analyze_saved(settings, website.scope.assessment_id, item.comparison_id)
        for item in view.comparisons
    ]
    assert [item.conclusion for item in outcomes] == ["supported", "rejected"]
    assert all(item.requests_used == 3 for item in outcomes)
    assert seeds == [42, 43, 44, 42, 43, 44] and lifecycle.count("closed") >= 2
    assert lifecycle.count("server-stopped") == 2
    assert store.load(website.scope.assessment_id).spent_requests == 18
    draft = store.report(website.scope.assessment_id)
    assert draft.report.runtime_verification == "not_attempted"
    assert any("fixture-model" in item for item in draft.report.tools_and_models)
    exported = store.export_report(
        website.scope.assessment_id, human_review(), draft.preview_sha256
    )
    assert (
        exported.export_path
        and Path(exported.export_path).read_text(encoding="utf-8") == draft.markdown
    )
    assert not exported.submitted


@pytest.mark.parametrize(
    "failure", ["missing_control", "missing_declaration", "wrong_account", "unreviewed"]
)
def test_preparation_refuses_partial_or_undeclared_pair_atomically(
    tmp_path: Path, failure: str
) -> None:
    store = AssessmentStore(Settings(data_dir=tmp_path / "private"))
    website = request()
    if failure == "missing_declaration":
        store.create(website.scope)
    else:
        create_website_scope(store, website)
    trace = paired_trace(website)
    raw: dict[str, Any] = trace.model_dump(mode="json")
    if failure == "missing_control":
        raw["records"].pop()
    elif failure == "wrong_account":
        raw["records"][1]["context"]["account_id"] = "alice"
    elif failure == "unreviewed":
        with pytest.raises(ValueError, match="completed reviewed"):
            prepared_website_comparisons(
                store.load(website.scope.assessment_id), trace.preview_sha256
            )
        return
    with pytest.raises(ValueError):
        store.import_lab_records(
            website.scope.assessment_id,
            ControlledHTTPResult.model_validate(raw),
            human_review(),
            prepare_website=True,
        )
    unchanged = store.load(website.scope.assessment_id)
    assert not unchanged.artifacts and not unchanged.comparisons and not unchanged.analyses


def test_website_scope_requires_session_and_origin(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "private")
    app = create_app(settings, port=PORT)
    assert (
        visitor(app)
        .post("/api/assessments/website", headers={"origin": ORIGIN}, json={})
        .status_code
        == 401
    )
    assert signed_in(app).post("/api/assessments/website", json={}).status_code == 403
    assert not AssessmentStore(settings).list_scopes().assessments


def test_website_scope_missing_lab_environment_refuses_without_partial_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise lab.LabUnavailable("Trusted lab interpreter differs from its local release manifest")

    monkeypatch.setattr(lab, "verified_files", unavailable)
    settings = Settings(data_dir=tmp_path / "private")
    app = create_app(settings, port=PORT)
    response = signed_in(app).post(
        "/api/assessments/website",
        headers={"origin": ORIGIN},
        json=request("website-unavailable").model_dump(mode="json"),
    )
    assert response.status_code == 409
    assert not AssessmentStore(settings).list_scopes().assessments


def test_url_scope_api_cli_equivalence_and_protected_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Public copies have no prepared lab interpreter. Check the real prerequisite
    # before the API turns that refusal into HTTP 409; conftest reports its exact
    # absence as a skip. Authentication/refusal checks above always run.
    lab.verified_files()
    settings = Settings(data_dir=tmp_path / "private")
    app = create_app(settings, port=PORT)
    assert (
        visitor(app)
        .post("/api/assessments/website", headers={"origin": ORIGIN}, json={})
        .status_code
        == 401
    )
    client = signed_in(app)
    website = request("website-api")
    assert client.post("/api/assessments/website", json={}).status_code == 403
    response = client.post(
        "/api/assessments/website",
        headers={"origin": ORIGIN},
        json=website.model_dump(mode="json"),
    )
    assert response.status_code == 201
    assert not response.json()["artifacts"]
    bad = website.model_copy(update={"url": "https://external.invalid"})
    assert (
        client.post(
            "/api/assessments/website", headers={"origin": ORIGIN}, json=bad.model_dump(mode="json")
        ).status_code
        == 409
    )
    other = request("website-cli")
    file = tmp_path / "website.json"
    file.write_text(other.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    assert cli.main(["assess", "--website", str(file)]) == 0
    terminal = json.loads(capsys.readouterr().out)
    assert terminal["scope"] == other.scope.model_dump(mode="json")
    assert len(terminal["expectations"]) == 2 and not terminal["artifacts"]
