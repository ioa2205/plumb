"""Owned synthetic observation fixtures exercise privacy, authority and evidence boundaries."""

import base64
import json
import sqlite3
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Self

import pytest
from pydantic import SecretStr, ValidationError

from backend.assessment import (
    AssessmentStore,
    answer_task,
    artifact_citation,
    build_checklist,
    check_scope,
    compare_observations,
    interpret_prompt,
    observed_map,
    resolve_citation,
    sanitize_http_record,
)
from backend.assessment.evidence import MAX_IMPORT_BYTES, SensitiveDiscovery, digest, parse_import
from backend.contracts.assessment import (
    AccessExpectation,
    AssessmentBudget,
    AssessmentScope,
    AssessmentView,
    AttachmentReview,
    ComparisonRequest,
    ScopeCreate,
    TaskResolveRequest,
)
from backend.redaction import TOKEN, Redactor
from backend.settings import Settings

TestData = dict[str, Any]


def scope(**changes: object) -> AssessmentScope:
    now = datetime.now(UTC)
    return AssessmentScope.model_validate(
        {
            "scope_id": "scope-1",
            "assessment_id": "assessment-1",
            "application_id": "owned-tandir",
            "application_name": "Owned synthetic Tandir",
            "origin": "http://127.0.0.1:8701",
            "allowed_paths": ["/orders", "/auth/login"],
            "allowed_actions": ["read", "compare", "plan", "report", "analyze", "collect"],
            "accounts": [
                {"account_id": "alice", "role": "customer", "label": "Synthetic owner"},
                {"account_id": "bob", "role": "customer", "label": "Synthetic other"},
            ],
            "synthetic_objects": [
                {
                    "object_id": "order-1",
                    "owner_account_id": "alice",
                    "kind": "order",
                    "synthetic_marker": "SYNTHETIC-ORDER-1",
                }
            ],
            "authority": {
                "granted_by": "Synthetic fixture owner",
                "reference": "Owned local lab development only",
                "granted_at": now - timedelta(days=1),
            },
            "expires_at": now + timedelta(days=1),
            "budget": {"max_requests": 9, "max_seconds": 180},
            "stop_conditions": ["Unexpected sensitive data", "Cancellation or exhausted budget"],
            **changes,
        }
    )


def review() -> AttachmentReview:
    return AttachmentReview(
        reviewed_by="Synthetic fixture reviewer",
        confirmed_sanitized=True,
        reviewed_at=datetime.now(UTC),
    )


def record(
    identity: str = "E01",
    *,
    account: str = "alice",
    path: str = "/orders/1/receipt",
    status: int = 200,
    body: str = '{"id":1,"marker":"SYNTHETIC-ORDER-1"}',
) -> TestData:
    return {
        "artifact_id": identity,
        "collected_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "provenance": "Owned synthetic fixture; not a fresh executed test",
        "context": {
            "account_id": account,
            "object_id": "order-1",
            "session_context_id": "session-" + account,
            "request_context_id": "request-1",
        },
        "request": {"method": "GET", "url": "http://127.0.0.1:8701" + path, "headers": {}},
        "response": {"status": status, "headers": {}, "body": body},
    }


def expectation(path: str = "/orders/1/receipt") -> AccessExpectation:
    return AccessExpectation(
        expectation_id="owner-rule",
        path=path,
        object_id="order-1",
        allowed_account_ids=["alice"],
        statement="Only the designated owner may read this synthetic order",
        declared_by="Synthetic fixture owner",
        basis="Explicit owned-lab development requirement",
    )


def comparison_view(*, denied: bool = False) -> AssessmentView:
    authority = scope()
    records = [
        record(),
        record(
            "E02",
            account="bob",
            status=403 if denied else 200,
            body='{"detail":"denied"}' if denied else '{"marker":"SYNTHETIC-ORDER-1"}',
        ),
        record(
            "E03", account="bob", path="/orders/1/invoice", status=403, body='{"detail":"denied"}'
        ),
    ]
    return AssessmentView(
        scope=authority,
        artifacts=[sanitize_http_record(authority, item, review()) for item in records],
        expectations=[expectation()],
    )


def request() -> ComparisonRequest:
    return ComparisonRequest(
        left_artifact_id="E01",
        right_artifact_id="E02",
        control_artifact_id="E03",
        expectation_id="owner-rule",
    )


def store(tmp_path: Path) -> AssessmentStore:
    return AssessmentStore(
        Settings(data_dir=tmp_path, redaction_secrets=(SecretStr("literal-supplied-secret"),))
    )


@pytest.mark.parametrize("value", [1, "true", False, None])
def test_review_and_scope_require_explicit_human_boolean(value: object) -> None:
    with pytest.raises(ValidationError):
        AttachmentReview.model_validate({**review().model_dump(), "confirmed_sanitized": value})
    with pytest.raises(ValidationError):
        ScopeCreate.model_validate({"scope": scope().model_dump(), "confirmed_authority": value})


@pytest.mark.parametrize("identity", ["../x", "x:y", "CON", "NUL", "LPT1", "C:folder", "has space"])
def test_scope_identifiers_are_safe_on_windows(identity: str) -> None:
    with pytest.raises(ValidationError):
        scope(assessment_id=identity)


@pytest.mark.parametrize(
    "path",
    [
        "/orders/../secret",
        "/orders/%2e%2e/secret",
        "/orders/%252e%252e/secret",
        "//host/path",
        "/orders\\x",
        "/orders?x=y",
        "/orders/%5cx",
    ],
)
def test_scope_paths_refuse_escapes(path: str) -> None:
    with pytest.raises(ValidationError):
        scope(allowed_paths=[path])


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/orders/1",
        "http://127.0.0.1:8702/orders/1",
        "http://user:pass@127.0.0.1:8701/orders/1",
        "http://127.0.0.1:8701/orders-escape/1",
        "http://127.0.0.1:8701/admin",
        "http://127.0.0.1:8701/orders/%252e%252e/admin",
        "http://127.0.0.1:8701/orders/1#secret",
    ],
)
def test_import_refuses_origin_and_path_escapes(url: str) -> None:
    item = record()
    item["request"]["url"] = url
    with pytest.raises(ValueError):
        sanitize_http_record(scope(), item, review())


def test_missing_expired_future_and_out_of_scope_authority() -> None:
    current = scope()
    expired = scope(expires_at=datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(ValueError, match="expired"):
        check_scope(expired)
    with pytest.raises(ValueError, match="outside"):
        check_scope(current, action="create_synthetic")
    with pytest.raises(ValidationError):
        AssessmentScope.model_validate(
            {key: value for key, value in current.model_dump().items() if key != "authority"}
        )
    with pytest.raises(ValidationError):
        scope(external_access_enabled=True)


def test_nested_json_form_headers_query_and_configured_secrets_are_redacted() -> None:
    item = record()
    item["request"]["url"] += "?token=url-secret&search=literal-supplied-secret"
    item["request"]["headers"] = {
        "Authorization": "Bearer opaque-token",
        "Cookie": "session=raw-cookie",
        "Referer": "http://localhost/?token=referer-secret",
    }
    item["request"]["body"] = "token=form-token&session=raw-session&safe=ok"
    item["response"]["headers"] = {"Set-Cookie": "secret-cookie"}
    item["response"]["body"] = (
        '{"secret":"json-secret","nested":{"access_token":"token-secret-private",'
        '"password":"password-secret-private"},"safe":"literal-supplied-secret"}'
    )
    result = sanitize_http_record(scope(), item, review(), Redactor(("literal-supplied-secret",)))
    serialized = result.model_dump_json()
    for secret in (
        "url-secret",
        "literal-supplied-secret",
        "opaque-token",
        "raw-cookie",
        "referer-secret",
        "form-token",
        "raw-session",
        "secret-cookie",
        "json-secret",
        "token-secret-private",
        "password-secret-private",
    ):
        assert secret not in serialized
    assert result.fields["request.headers.authorization"] == TOKEN
    assert result.fields["response.headers.set-cookie"] == TOKEN


@pytest.mark.parametrize(
    "body",
    [
        '{"email":"real@example.test"}',
        '{"phone":"+998900000000"}',
        '{"delivery_address":"Real residence"}',
        '{"nested":{"card_number":"4111111111111111"}}',
        "Real account real@example.test",
    ],
)
def test_unexpected_personal_information_stops_without_storing_original(
    tmp_path: Path, body: str
) -> None:
    persistence = store(tmp_path)
    persistence.create(scope())
    item = record(body=body)
    view = persistence.import_records("assessment-1", json.dumps({"records": [item]}), review())
    assert view.stopped and not view.artifacts
    assert "private incident" in (view.stop_reason or "")
    raw = persistence.path.read_bytes()
    assert body.encode() not in raw
    with pytest.raises(ValueError, match="stopped"):
        persistence.import_records("assessment-1", json.dumps({"records": [record()]}), review())
    preview = persistence.report("assessment-1")
    assert "Private incident draft" in preview.markdown


def test_exact_declared_synthetic_marker_is_permitted_in_personal_field() -> None:
    artifact = sanitize_http_record(
        scope(),
        record(body='{"delivery_address":"SYNTHETIC-ORDER-1","password":"SYNTHETIC-ORDER-1"}'),
        review(),
    )
    assert json.loads(artifact.fields["response.body"]) == {
        "delivery_address": "SYNTHETIC-ORDER-1",
        "password": TOKEN,
    }
    with pytest.raises(SensitiveDiscovery):
        sanitize_http_record(
            scope(),
            record(body='{"delivery_address":"SYNTHETIC-ORDER-1 plus private location"}'),
            review(),
        )


@pytest.mark.parametrize(
    ("location", "key", "private_value"),
    [
        ("query", "email", "unexpected-person@example.test"),
        ("query", "phone", "+998901234567"),
        ("query", "delivery_address", "UNEXPECTED-PRIVATE-RESIDENCE-487"),
        ("query", "payment_reference", "UNEXPECTED-PRIVATE-PAYMENT-487"),
        ("query", "search", "unexpected-person@example.test"),
        ("query", "address", "SYNTHETIC-ORDER-1 plus private location"),
        ("path", "", "unexpected-person@example.test"),
        ("path", "", "unexpected-person%40example.test"),
        ("path", "", "unexpected-person%2540example.test"),
        ("path", "", "unexpected-person%252540example.test"),
        ("request_header", "X-Email", "unexpected-person@example.test"),
        ("request_header", "X-Phone", "+998901234567"),
        ("request_header", "X-Comment", "unexpected-person@example.test"),
        ("response_header", "X-Address", "UNEXPECTED-PRIVATE-RESIDENCE-487"),
        ("response_header", "X-Card", "UNEXPECTED-PRIVATE-PAYMENT-487"),
        ("response_header", "X-Address", "SYNTHETIC-ORDER-1 plus private location"),
    ],
)
def test_personal_url_or_header_stops_and_discards_the_import_batch(
    tmp_path: Path, location: str, key: str, private_value: str
) -> None:
    from urllib.parse import urlencode

    persistence = store(tmp_path)
    persistence.create(scope())
    existing = persistence.import_records(
        "assessment-1", json.dumps({"records": [record()]}), review()
    )
    item = record("E03")
    if location == "query":
        item["request"]["url"] += "?" + urlencode({key: private_value})
    elif location == "path":
        item["request"]["url"] = "http://127.0.0.1:8701/orders/" + private_value + "/receipt"
    else:
        section = "request" if location == "request_header" else "response"
        item[section]["headers"] = {key: private_value}
    view = persistence.import_records(
        "assessment-1", json.dumps({"records": [record("E02"), item]}), review()
    )
    assert view.stopped and view.artifacts == existing.artifacts
    assert "private incident" in (view.stop_reason or "")
    for path in persistence.directory.glob("assessments.sqlite*"):
        assert private_value.encode() not in path.read_bytes()
    preview = persistence.report("assessment-1")
    assert "Private incident draft" in preview.markdown
    assert private_value not in preview.model_dump_json()
    with pytest.raises(ValueError, match="stopped"):
        persistence.import_records(
            "assessment-1", json.dumps({"records": [record("E04")]}), review()
        )


def test_credential_query_and_headers_redact_without_a_personal_stop(tmp_path: Path) -> None:
    from urllib.parse import parse_qs, urlsplit

    persistence = store(tmp_path)
    persistence.create(scope())
    item = record(path="/orders/SYNTHETIC-ORDER-1/receipt")
    item["request"]["url"] += "?password=private-credential@example.test"
    item["request"]["headers"] = {"Cookie": "session=private-credential@example.test"}
    item["response"]["headers"] = {"Authorization": "Bearer private-credential@example.test"}
    view = persistence.import_records("assessment-1", json.dumps({"records": [item]}), review())
    assert not view.stopped
    fields = view.artifacts[0].fields
    assert parse_qs(urlsplit(fields["request.url"]).query) == {"password": [TOKEN]}
    assert fields["request.headers.cookie"] == TOKEN
    assert fields["response.headers.authorization"] == TOKEN
    assert "private-credential@example.test" not in view.model_dump_json()


def test_only_exact_synthetic_metadata_is_retained_and_credentials_remain_redacted(
    tmp_path: Path,
) -> None:
    from urllib.parse import parse_qs, urlencode, urlsplit

    persistence = store(tmp_path)
    persistence.create(scope())
    item = record()
    item["request"]["url"] += "?" + urlencode(
        {"delivery_address": "SYNTHETIC-ORDER-1", "token": "SYNTHETIC-ORDER-1"}
    )
    item["request"]["headers"] = {"X-Address": "SYNTHETIC-ORDER-1"}
    item["response"]["headers"] = {
        "X-Email": "SYNTHETIC-ORDER-1",
        "Set-Cookie": "SYNTHETIC-ORDER-1",
    }
    view = persistence.import_records("assessment-1", json.dumps({"records": [item]}), review())
    assert not view.stopped
    fields = view.artifacts[0].fields
    assert parse_qs(urlsplit(fields["request.url"]).query) == {
        "delivery_address": ["SYNTHETIC-ORDER-1"],
        "token": [TOKEN],
    }
    assert fields["request.headers.x-address"] == "SYNTHETIC-ORDER-1"
    assert fields["response.headers.x-email"] == "SYNTHETIC-ORDER-1"
    assert fields["response.headers.set-cookie"] == TOKEN
    assert persistence.load("assessment-1") == view


def test_declared_synthetic_email_marker_is_allowed_only_as_exact_metadata(tmp_path: Path) -> None:
    from urllib.parse import quote

    persistence = store(tmp_path)
    authority = scope()
    object_item = authority.synthetic_objects[0].model_copy(
        update={"synthetic_marker": "synthetic-owner@example.test"}
    )
    authority = authority.model_copy(update={"synthetic_objects": [object_item]})
    persistence.create(authority)
    item = record(body="Synthetic fixture statement")
    marker = "synthetic-owner@example.test"
    item["request"]["url"] = "http://127.0.0.1:8701/orders/" + quote(marker) + "/receipt"
    item["request"]["url"] += "?email=" + quote(marker)
    item["response"]["headers"] = {"X-Email": marker}
    view = persistence.import_records("assessment-1", json.dumps({"records": [item]}), review())
    assert not view.stopped and view.artifacts[0].fields["response.headers.x-email"] == marker
    assert persistence.load("assessment-1") == view


def test_import_is_inert_bounded_and_requires_explicit_selection() -> None:
    authority = scope()
    with pytest.raises(ValueError, match="2 MiB"):
        parse_import(authority, b"x" * (MAX_IMPORT_BYTES + 1), review(), Redactor())
    with pytest.raises(ValueError, match="JSON"):
        parse_import(authority, "{broken", review(), Redactor())
    item = record(body='<script>fetch("https://external.test")</script>')
    artifacts, _ = parse_import(authority, json.dumps({"records": [item]}), review(), Redactor())
    assert "<script>" in artifacts[0].fields["response.body"]
    assert artifacts[0].execution_status == "imported"
    with pytest.raises(ValueError, match="selected"):
        parse_import(
            authority,
            json.dumps({"har": {"log": {"entries": []}}, "contexts": {}}),
            review(),
            Redactor(),
        )


def test_selected_har_does_not_store_cookies_or_nonselected_entries() -> None:
    authority = scope()
    item = record()
    entry = {
        "startedDateTime": item["collected_at"],
        "request": {
            "method": "GET",
            "url": item["request"]["url"],
            "headers": [{"name": "Cookie", "value": "raw-cookie"}],
            "cookies": [{"name": "raw", "value": "cookie-secret"}],
        },
        "response": {"status": 200, "headers": [], "content": {"text": item["response"]["body"]}},
    }
    payload = {
        "har": {"log": {"entries": [entry, {"secret": "not-selected"}]}},
        "selected_entries": [0],
        "contexts": {"0": item["context"]},
        "provenance": "Reviewed selected synthetic HAR",
    }
    artifacts, _ = parse_import(authority, json.dumps(payload), review(), Redactor())
    assert len(artifacts) == 1
    assert "raw-cookie" not in artifacts[0].model_dump_json()
    assert "cookie-secret" not in artifacts[0].model_dump_json()
    assert "not-selected" not in artifacts[0].model_dump_json()


def png(*, metadata: bool = False) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + (chunk(b"tEXt", b"Comment\x00secret metadata") if metadata else b"")
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def test_reviewed_png_metadata_removed_external_attachment_and_citations(tmp_path: Path) -> None:
    persistence = store(tmp_path)
    persistence.create(scope())
    payload = {
        "records": [
            {
                "artifact_id": "shot-1",
                "kind": "screenshot",
                "collected_at": record()["collected_at"],
                "provenance": "Human-reviewed synthetic screenshot",
                "description": "Synthetic red pixel",
                "content_base64": base64.b64encode(png(metadata=True)).decode(),
            }
        ]
    }
    view = persistence.import_records("assessment-1", json.dumps(payload), review())
    artifact = view.artifacts[0]
    assert artifact.kind == "screenshot"
    assert artifact.attachment_path is not None
    stored = Path(artifact.attachment_path).read_bytes()
    assert b"secret metadata" not in stored
    assert stored == png()
    assert "image understanding unavailable" in artifact.fields["screenshot.interpretation"]
    assert digest(stored) == artifact.fields["screenshot.sha256"]
    citation = artifact_citation(artifact, "screenshot.description")
    assert resolve_citation(view, citation) == "Synthetic red pixel"
    assert persistence.load("assessment-1") == view


@pytest.mark.parametrize(
    "content", [b"<svg onload='attack()'/>", png()[:-4], png() + b"trailing", b"\x89PNG\r\n\x1a\n"]
)
def test_malformed_or_active_screenshots_refused(content: bytes) -> None:
    payload = {
        "records": [
            {
                "kind": "screenshot",
                "collected_at": record()["collected_at"],
                "provenance": "Human reviewed",
                "description": "synthetic",
                "content_base64": base64.b64encode(content).decode(),
            }
        ]
    }
    with pytest.raises(ValueError):
        parse_import(scope(), json.dumps(payload), review(), Redactor())


def test_citations_bind_artifact_and_exact_sanitized_field_hash() -> None:
    view = comparison_view()
    citation = artifact_citation(view.artifacts[0], "response.body")
    assert resolve_citation(view, citation) == view.artifacts[0].fields["response.body"]
    for changes in ({"artifact_id": "missing"}, {"field": "missing"}, {"sha256": "f" * 64}):
        with pytest.raises(ValueError):
            resolve_citation(view, citation.model_copy(update=changes))
    changed = view.artifacts[0].model_copy(
        update={"fields": {**view.artifacts[0].fields, "response.body": "changed"}}
    )
    with pytest.raises(ValueError, match="hash"):
        resolve_citation(
            view.model_copy(update={"artifacts": [changed, *view.artifacts[1:]]}), citation
        )


def test_observed_map_and_manual_checklist_never_claim_unseen_execution() -> None:
    view = comparison_view()
    mapping = observed_map(view)
    assert {endpoint.path for endpoint in mapping.endpoints} == {
        "/orders/1/receipt",
        "/orders/1/invoice",
    }
    assert all(endpoint.coverage == "observed_import" for endpoint in mapping.endpoints)
    assert not mapping.collection_performed
    checklist = build_checklist(view)
    assert checklist.execution_status == "plan_only"
    assert "/auth/login" in checklist.untested_paths
    assert all(item.status != "executed" for item in checklist.items)


def test_matching_candidate_and_protected_denial_are_conservative_imports() -> None:
    candidate = compare_observations(comparison_view(), request())
    assert candidate.conclusion == "candidate" and not candidate.missing_evidence
    assert candidate.execution_status == "imported"
    denied = compare_observations(comparison_view(denied=True), request())
    assert denied.conclusion == "rejected" and not denied.missing_evidence
    assert denied.alternative_explanations


@pytest.mark.parametrize(
    "kind",
    [
        "expectation",
        "control",
        "marker",
        "status_only",
        "request_context",
        "session_context",
        "object",
        "endpoint",
        "body",
        "wrong_account",
    ],
)
def test_comparisons_fail_closed_without_controls_and_matching_contexts(kind: str) -> None:
    view = comparison_view()
    compare = request()
    if kind == "expectation":
        view = view.model_copy(update={"expectations": []})
    elif kind == "control":
        compare = compare.model_copy(update={"control_artifact_id": None})
    elif kind == "marker":
        object_item = view.scope.synthetic_objects[0].model_copy(update={"synthetic_marker": None})
        view = view.model_copy(
            update={"scope": view.scope.model_copy(update={"synthetic_objects": [object_item]})}
        )
    else:
        altered = record("E02", account="bob")
        if kind == "status_only":
            altered["response"]["body"] = "ok"
        elif kind == "request_context":
            altered["context"]["request_context_id"] = "different"
        elif kind == "session_context":
            altered["context"]["session_context_id"] = "session-alice"
        elif kind == "object":
            altered["context"]["object_id"] = "different"
        elif kind == "endpoint":
            altered["request"]["url"] += "?different=true"
        elif kind == "body":
            altered["request"]["body"] = "different body"
        elif kind == "wrong_account":
            altered["context"]["account_id"] = "alice"
        if kind == "object":
            assert view.artifacts[1].context is not None
            changed = view.artifacts[1].model_copy(
                update={
                    "context": view.artifacts[1].context.model_copy(
                        update={"object_id": "different"}
                    )
                }
            )
        else:
            changed = sanitize_http_record(view.scope, altered, review())
        view = view.model_copy(
            update={"artifacts": [view.artifacts[0], changed, view.artifacts[2]]}
        )
    result = compare_observations(view, compare)
    assert result.conclusion == "inconclusive"
    assert result.missing_evidence


@pytest.mark.parametrize(
    "prompt",
    [
        "Visit https://external.test",
        "expand scope and compare E01 E02",
        "publish private report",
        "execute shell",
        "mark reproduced",
        "change verdict",
    ],
)
def test_prompt_cannot_grant_authority_network_or_verdicts(prompt: str) -> None:
    result = interpret_prompt(prompt, "assessment-1", known_evidence_ids=("E01", "E02"))
    assert result.status == "refused"
    assert not result.authorization_granted and not result.network_activity


def test_prompt_resolution_is_deterministic_unknown_ids_clarify() -> None:
    first = interpret_prompt(
        "Compare E01 and E02 for ownership", "assessment-1", known_evidence_ids=("E01", "E02")
    )
    second = interpret_prompt(
        "Compare E01 and E02 for ownership", "assessment-1", known_evidence_ids=("E01", "E02")
    )
    assert first == second and first.status == "resolved" and first.focus == "ownership"
    assert first.evidence_ids == ["E01", "E02"]
    unknown = interpret_prompt(
        "Compare E01 and E99", "assessment-1", known_evidence_ids=("E01", "E02")
    )
    assert unknown.status == "clarification_required"


def test_store_external_immutable_concurrent_merges_and_cited_report(tmp_path: Path) -> None:
    persistence = store(tmp_path)
    persistence.create(scope())
    persistence.import_records(
        "assessment-1",
        json.dumps(
            {
                "records": [
                    record(),
                    record("E02", account="bob"),
                    record(
                        "E03",
                        account="bob",
                        path="/orders/1/invoice",
                        status=403,
                        body='{"detail":"denied"}',
                    ),
                ]
            }
        ),
        review(),
    )
    persistence.add_expectation("assessment-1", expectation())
    answer = persistence.resolve_task("assessment-1", TaskResolveRequest(prompt="Explain E01"))
    assert answer.citations and persistence.load("assessment-1").answers == [answer]
    result = persistence.add_comparison("assessment-1", request())
    assert result.conclusion == "candidate"
    preview = persistence.report("assessment-1")
    assert preview.report.runtime_verification == "not_attempted"
    assert (
        preview.report.confidentiality == "private_local" and preview.report.human_preview_required
    )
    assert not preview.submitted and preview.export_path is None
    export = persistence.export_report("assessment-1", review(), preview.preview_sha256)
    assert export.export_path is not None and Path(export.export_path).is_file()
    assert "runtime reproduction" in export.markdown
    current = persistence.load("assessment-1")
    updates = [
        current.model_copy(
            update={
                "answers": [
                    *current.answers,
                    answer_task(
                        current,
                        interpret_prompt(f"Explain E01 request {index}", "assessment-1", ("E01",)),
                    ),
                ]
            }
        )
        for index in range(3)
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(persistence.save, updates))
    assert len(persistence.load("assessment-1").answers) == 4
    stopped = persistence.stop("assessment-1", "Explicit cancellation")
    persistence.save(current)
    assert persistence.load("assessment-1").stopped
    with pytest.raises(ValueError, match="immutable"):
        persistence.save(
            stopped.model_copy(update={"scope": scope(application_name="Changed authority")})
        )
    with pytest.raises(ValueError, match="budget"):
        persistence.resolve_task(
            "assessment-1",
            TaskResolveRequest(prompt="Private report", budget=AssessmentBudget(max_requests=10)),
        )


def test_store_detects_tampering_duplicate_import_and_repository_data_dir(tmp_path: Path) -> None:
    persistence = store(tmp_path)
    persistence.create(scope())
    payload = json.dumps({"records": [record()]})
    persistence.import_records("assessment-1", payload, review())
    with pytest.raises(ValueError, match="already exists"):
        persistence.import_records("assessment-1", payload, review())
    with sqlite3.connect(persistence.path) as connection:
        raw = json.loads(connection.execute("SELECT payload FROM assessments").fetchone()[0])
        raw["artifacts"][0]["fields"]["response.body"] = "tampered"
        connection.execute("UPDATE assessments SET payload=?", (json.dumps(raw),))
    with pytest.raises(ValueError, match="hash"):
        persistence.load("assessment-1")
    with pytest.raises(ValueError, match="outside"):
        AssessmentStore(Settings(data_dir=Path(__file__).resolve().parents[2] / "tmp"))


def test_lifetime_accounting_is_atomic_persisted_and_never_reset_by_old_worker(
    tmp_path: Path,
) -> None:
    persistence = store(tmp_path)
    stale = persistence.create(scope())
    first = persistence.charge_budget("assessment-1", requests=3, seconds=25)
    assert first.spent_requests == 3 and first.spent_seconds == 25
    persistence.save(stale)
    assert persistence.load("assessment-1").spent_requests == 3
    with pytest.raises(ValueError, match="exhausted"):
        persistence.charge_budget("assessment-1", requests=7)
    with pytest.raises(ValueError, match="exhausted"):
        persistence.charge_budget("assessment-1", seconds=200)
    with pytest.raises(ValueError):
        persistence.charge_budget("assessment-1", requests=-1)
    with pytest.raises(ValueError):
        persistence.charge_budget("assessment-1", seconds=float("nan"))
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: persistence.charge_budget("assessment-1", requests=1), range(3)))
    assert persistence.load("assessment-1").spent_requests == 6
    persistence.stop("assessment-1", "Stopped while operation was running")
    ended = persistence.charge_budget("assessment-1", seconds=5)
    assert ended.spent_seconds == 30
    with pytest.raises(ValueError, match="stopped"):
        persistence.charge_budget("assessment-1", requests=1)


def test_private_report_auth_and_expired_or_stopped_incident_access(tmp_path: Path) -> None:
    persistence = store(tmp_path)
    persistence.create(scope(allowed_actions=["read", "plan"]))
    with pytest.raises(ValueError, match="reporting"):
        persistence.report("assessment-1")
    persistence.stop("assessment-1", "Unexpected discovery")
    assert "Private incident draft" in persistence.report("assessment-1").markdown


def test_private_export_requires_the_exact_current_human_preview(tmp_path: Path) -> None:
    persistence = store(tmp_path)
    persistence.create(scope())
    first = persistence.report("assessment-1")
    persistence.import_records("assessment-1", json.dumps({"records": [record()]}), review())
    with pytest.raises(ValueError, match="changed after human preview"):
        persistence.export_report("assessment-1", review(), first.preview_sha256)
    current = persistence.report("assessment-1")
    exported = persistence.export_report("assessment-1", review(), current.preview_sha256)
    assert exported.preview_sha256 == current.preview_sha256 and exported.export_path


def test_expired_scope_allows_elapsed_time_accounting_and_read_only_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.assessment.evidence as evidence

    persistence = store(tmp_path)
    view = persistence.create(scope())

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp((view.scope.expires_at + timedelta(seconds=1)).timestamp(), tz)

    monkeypatch.setattr(evidence, "datetime", ExpiredClock)
    with pytest.raises(ValueError, match="expired"):
        persistence.charge_budget("assessment-1", requests=1)
    assert persistence.charge_budget("assessment-1", seconds=5).spent_seconds == 5
    assert persistence.report("assessment-1").report.confidentiality == "private_local"


def test_saved_local_analysis_and_report_revalidate_three_judgments(tmp_path: Path) -> None:
    from agent.web_assessment import analysis_packet_hash
    from backend.contracts.assessment_engine import (
        ObservationAnalysis,
        ObservationClaim,
        ObservationJudgment,
        ValidatedObservationJudgment,
    )

    persistence = store(tmp_path)
    view = comparison_view()
    comparison = compare_observations(view, request())
    view = view.model_copy(update={"comparisons": [comparison]})
    persistence.create(view.scope)
    persistence.save(view)
    claims = [
        ObservationClaim(citation=artifact_citation(artifact, field), value=artifact.fields[field])
        for artifact in view.artifacts
        for field in ("response.status", "response.body")
    ]
    answer = ObservationJudgment(
        verdict="supported",
        claims=claims,
        rationale="Fixture interpretation: other account received the synthetic marker.",
        alternative_explanations=["Imported session identity remains a human declaration."],
        missing_evidence=["Fresh runtime acceptance is not established by fixture answers."],
        mitigation="Apply the declared owner constraint.",
    )
    analysis = ObservationAnalysis(
        comparison_id=comparison.comparison_id,
        conclusion="supported",
        judgments=[
            ValidatedObservationJudgment(
                seed=seed, evidence_order=[], answer=answer, raw_answer=answer.model_dump_json()
            )
            for seed in (42, 43, 44)
        ],
        citations=[claim.citation for claim in claims],
        alternative_explanations=answer.alternative_explanations,
        missing_evidence=answer.missing_evidence,
        requests_used=3,
        seconds=2,
        packet_sha256=analysis_packet_hash(view, comparison),
        model_provenance=["Fixture replay only; no model loaded"],
    )
    persistence.save(view.model_copy(update={"analyses": [analysis.model_dump(mode="json")]}))
    preview = persistence.report("assessment-1")
    assert any("supported" in claim.text for claim in preview.report.claims)
    assert answer.mitigation in preview.report.mitigation
    assert answer.missing_evidence[0] in preview.report.limitations
    assert "Fixture replay only" in " ".join(preview.report.tools_and_models)
    assert preview.report.evidence == view.artifacts
    assert "SYNTHETIC-ORDER-1" in preview.markdown
    for changes in (
        {"judgments": analysis.judgments[:2]},
        {"packet_sha256": "f" * 64},
        {"citations": []},
    ):
        with pytest.raises(ValueError):
            persistence._validate(
                view.model_copy(
                    update={
                        "analyses": [analysis.model_copy(update=changes).model_dump(mode="json")]
                    }
                )
            )
    tampered = view.comparisons[0].model_copy(update={"conclusion": "rejected"})
    with pytest.raises(ValueError, match="underlying evidence"):
        persistence._validate(view.model_copy(update={"comparisons": [tampered]}))


def test_large_report_preview_abbreviates_while_private_json_keeps_exact_evidence(
    tmp_path: Path,
) -> None:
    persistence = store(tmp_path)
    persistence.create(scope())
    body = json.dumps({"synthetic_text": "x" * 60000})
    view = persistence.import_records(
        "assessment-1", json.dumps({"records": [record(body=body)]}), review()
    )
    preview = persistence.report("assessment-1")
    assert "preview abbreviated" in preview.markdown
    assert preview.report.evidence[0].fields == view.artifacts[0].fields
    assert len(preview.markdown) < 10000


def test_rehashed_sensitive_saved_body_is_still_refused(tmp_path: Path) -> None:
    from backend.assessment.evidence import artifact_digest

    persistence = store(tmp_path)
    view = persistence.create(scope())
    artifact = sanitize_http_record(view.scope, record(), review())
    altered = artifact.model_copy(
        update={"fields": {**artifact.fields, "response.body": '{"phone":"real private number"}'}}
    )
    altered = altered.model_copy(update={"sha256": artifact_digest(altered)})
    with pytest.raises(SensitiveDiscovery):
        persistence.save(view.model_copy(update={"artifacts": [altered]}))


@pytest.mark.parametrize("location", ["query", "path", "request_header", "response_header"])
def test_rehashed_personal_saved_metadata_is_refused(tmp_path: Path, location: str) -> None:
    from backend.assessment.evidence import artifact_digest

    persistence = store(tmp_path)
    view = persistence.create(scope())
    artifact = sanitize_http_record(view.scope, record(), review())
    fields = artifact.fields.copy()
    if location == "query":
        fields["request.url"] += "?email=unexpected-person%40example.test"
    elif location == "path":
        fields["request.url"] = "http://127.0.0.1:8701/orders/unexpected-person%2540example.test"
    else:
        section = "request" if location == "request_header" else "response"
        fields[section + ".headers.x-email"] = "unexpected-person@example.test"
    altered = artifact.model_copy(update={"fields": fields})
    altered = altered.model_copy(update={"sha256": artifact_digest(altered)})
    with pytest.raises(SensitiveDiscovery):
        persistence.save(view.model_copy(update={"artifacts": [altered]}))
    assert not persistence.load("assessment-1").artifacts


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8701/orders/1?password=private-credential-value",
        "http://127.0.0.1:8701/orders/1?search=literal-supplied-secret",
        "http://127.0.0.1:8701/orders/literal-supplied-secret/receipt",
    ],
)
def test_rehashed_credential_saved_url_is_refused(tmp_path: Path, url: str) -> None:
    from backend.assessment.evidence import artifact_digest

    persistence = store(tmp_path)
    view = persistence.create(scope())
    artifact = sanitize_http_record(view.scope, record(), review())
    altered = artifact.model_copy(update={"fields": {**artifact.fields, "request.url": url}})
    altered = altered.model_copy(update={"sha256": artifact_digest(altered)})
    with pytest.raises(ValueError, match="sanitized"):
        persistence.save(view.model_copy(update={"artifacts": [altered]}))
    assert not persistence.load("assessment-1").artifacts
