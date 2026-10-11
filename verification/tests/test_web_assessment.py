"""No target process is launched: mocked owned-lab transport exercises boundaries."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from backend.contracts.assessment import (
    AssessmentBudget,
    AssessmentScope,
    ScopeAuthority,
    SyntheticObject,
)
from backend.contracts.assessment import (
    TestAccount as DesignatedAccount,
)
from backend.contracts.assessment_engine import ControlledHTTPPermission, ControlledHTTPPreview
from backend.settings import Settings
from verification import web_assessment
from verification.web_assessment import (
    CollectionBytes,
    CollectionStopped,
    _request,
    preview_lab_assessment,
    run_controlled_http,
    validate_permission,
    validate_runtime_origin,
)


def scope() -> AssessmentScope:
    now = datetime.now(UTC)
    return AssessmentScope(
        scope_id="S-1",
        assessment_id="A-1",
        application_id="owned-tandir",
        application_name="Owned synthetic Tandir",
        origin="http://127.0.0.1:8701",
        allowed_paths=["/health", "/auth/login", "/orders"],
        allowed_actions=["read", "collect", "authenticate", "create_synthetic"],
        accounts=[
            DesignatedAccount(account_id=account, role="customer", label=account)
            for account in ("alice", "bob")
        ],
        synthetic_objects=[
            SyntheticObject(
                object_id="O-1",
                owner_account_id="alice",
                kind="order",
                synthetic_marker="SYNTHETIC-ORDER-1",
            )
        ],
        authority=ScopeAuthority(
            granted_by="Owner", reference="Owned lab", granted_at=now - timedelta(minutes=5)
        ),
        expires_at=now + timedelta(hours=1),
        budget=AssessmentBudget(max_requests=12),
        stop_conditions=["Unexpected sensitive data"],
    )


def permission(preview: ControlledHTTPPreview) -> ControlledHTTPPermission:
    return ControlledHTTPPermission(
        preview_sha256=preview.sha256,
        approved_action_ids=[item.action_id for item in preview.actions],
        approved_by="Owner",
        granted_at=datetime.now(UTC),
        expires_at=preview.expires_at,
        reviewed_preview=True,
    )


@pytest.fixture(autouse=True)
def mocked_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_assessment.lab, "verified_files", lambda: ({}, "a" * 64))


def mock_runner(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[str]:
    lifecycle: list[str] = []

    @contextmanager
    def launch(*args: object, **kwargs: object) -> Iterator[tuple[str, httpx.Client]]:
        cast(Callable[[], None], kwargs["startup_check"])()
        lifecycle.append("started")
        try:
            with httpx.Client(
                transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False
            ) as client:
                cast(Callable[[httpx.Client, str], None], kwargs["readiness_hook"])(
                    client, "http://127.0.0.1:19999"
                )
                yield "http://127.0.0.1:19999", client
        finally:
            lifecycle.append("stopped")

    monkeypatch.setattr(web_assessment.lab, "launch", launch)
    return lifecycle


def synthetic_handler(
    requests: list[httpx.Request], *, leak: bool = False
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/auth/login":
            account = json.loads(request.content)["username"]
            return httpx.Response(200, json={"token": account + "-private-fixture-token"})
        if request.url.path == "/orders":
            return httpx.Response(200, json={"id": 1, "delivery_address": "SYNTHETIC-ORDER-1"})
        if leak:
            return httpx.Response(200, json={"token": "bob-private-fixture-token"})
        if request.url.path.endswith("/invoice") and request.headers.get(
            "authorization", ""
        ).startswith("Bearer bob"):
            return httpx.Response(403, json={"detail": "Denied"})
        return httpx.Response(200, json={"delivery_address": "SYNTHETIC-ORDER-1"})

    return respond


@pytest.mark.parametrize("paired,count", [(False, 6), (True, 9)])
def test_preview_explicitly_lists_every_request_and_state_change(paired: bool, count: int) -> None:
    current = scope()
    preview = preview_lab_assessment(current, paired=paired)
    assert len(preview.actions) == count
    assert preview.max_requests == count + 3
    assert preview.actions[0].path == "/health" and preview.actions[0].max_attempts == 4
    assert preview.actions[0].account_id is None
    assert sum(item.state_change for item in preview.actions) == 3
    validate_permission(current, preview, permission(preview))
    assert "lab-pass" not in preview.model_dump_json()
    assert preview.external_access_enabled is False


@pytest.mark.parametrize(
    "origin",
    [
        "https://third-party.invalid",
        "http://localhost:8701",
        "http://127.0.0.2:8701",
        "http://[::1]:8701",
        "http://127.0.0.1:8702",
    ],
)
def test_external_or_wrong_declared_origin_never_reaches_manifest(origin: str) -> None:
    with pytest.raises(ValueError, match="disabled"):
        preview_lab_assessment(scope().model_copy(update={"origin": origin}))


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://localhost:42",
        "http://127.0.0.1:42/",
        "http://user:pass@127.0.0.1:42",
        "https://127.0.0.1:42",
        "http://[::1]:42",
    ],
)
def test_runtime_origin_exact_ipv4_and_port_allowlist(origin: str) -> None:
    with pytest.raises(ValueError):
        validate_runtime_origin(origin)


def test_scope_permissions_are_purpose_specific_even_for_get() -> None:
    current = scope().model_copy(update={"allowed_actions": ["read", "collect"]})
    with pytest.raises(ValueError, match="authentication"):
        preview_lab_assessment(current)


@pytest.mark.parametrize(
    "change", ["missing_action", "duplicate_action", "expiry", "scope", "actions", "path", "object"]
)
def test_stale_or_tampered_preview_and_permission_refuse_before_launch(change: str) -> None:
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    consent = permission(preview)
    if change == "missing_action":
        consent = consent.model_copy(
            update={"approved_action_ids": consent.approved_action_ids[:-1]}
        )
    elif change == "duplicate_action":
        consent = consent.model_copy(
            update={
                "approved_action_ids": [
                    *consent.approved_action_ids[:-1],
                    consent.approved_action_ids[0],
                ]
            }
        )
    elif change == "expiry":
        consent = consent.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
    elif change == "scope":
        current = current.model_copy(update={"stop_conditions": ["Changed stop condition"]})
    elif change == "actions":
        preview = preview.model_copy(update={"actions": preview.actions[:-1]})
    elif change == "path":
        request = preview.spec.requests[1].model_copy(
            update={"path": "/orders/1/receipt?redirect=https://third-party.invalid"}
        )
        preview = preview.model_copy(
            update={
                "spec": preview.spec.model_copy(
                    update={
                        "requests": [preview.spec.requests[0], request, preview.spec.requests[2]]
                    }
                )
            }
        )
    else:
        current = current.model_copy(
            update={
                "synthetic_objects": [
                    current.synthetic_objects[0].model_copy(
                        update={"synthetic_marker": "another-marker"}
                    )
                ]
            }
        )
    with pytest.raises(ValueError):
        validate_permission(current, preview, consent)


def test_pair_collection_stays_one_owned_session_and_preserves_actual_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    lifecycle = mock_runner(monkeypatch, synthetic_handler(requests))
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview))
    assert not result.stopped
    assert result.requests_used == 9 and len(requests) == 9 and len(result.records) == 6
    assert result.requests_used <= preview.max_requests
    assert lifecycle == ["started", "stopped"]
    assert result.runner_origin == "http://127.0.0.1:19999"
    assert all(str(request.url).startswith(result.runner_origin) for request in requests)
    serialized = result.model_dump_json()
    assert "private-fixture-token" not in serialized and "lab-pass" not in serialized
    assert '"headers":{}' in serialized
    bob_receipt, bob_invoice = result.records[1], result.records[3]
    assert bob_receipt["context"] == bob_invoice["context"]
    assert bob_invoice["context"] == result.records[5]["context"]
    assert bob_invoice["artifact_id"] != result.records[5]["artifact_id"]
    assert result.runtime_verification == "not_attempted"


def test_unexpected_secret_stops_collection_omits_record_and_closes_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    lifecycle = mock_runner(monkeypatch, synthetic_handler(requests, leak=True))
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stopped and "sensitive" in (result.stop_reason or "")
    assert result.requests_used == 5 and len(result.records) == 1
    assert "private-fixture-token" not in result.model_dump_json()
    assert lifecycle == ["started", "stopped"]


def test_redirect_refuses_destination_and_subresources(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://third-party.invalid/secret"},
            text='<img src="https://third-party.invalid/pixel">',
        )

    lifecycle = mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stopped and "redirect" in (result.stop_reason or "")
    assert len(requests) == 1 and not result.records
    assert lifecycle == ["started", "stopped"]
    assert "third-party.invalid" not in result.model_dump_json()


def test_cancellation_before_launch_and_during_collection_stops_owned_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    lifecycle = mock_runner(monkeypatch, synthetic_handler(requests))
    current = scope()
    preview = preview_lab_assessment(current)
    result = run_controlled_http(current, preview, permission(preview), cancel=lambda: True)
    assert result.stop_reason == "canceled" and result.requests_used == 0 and not lifecycle
    result = run_controlled_http(
        current, preview, permission(preview), cancel=lambda: len(requests) >= 1
    )
    assert result.stopped and result.requests_used == 1 and lifecycle == ["started", "stopped"]


@pytest.mark.parametrize(
    "path",
    [
        "//third-party.invalid",
        "/orders/1/receipt?x=1",
        "/orders/../auth/login",
        "/orders/%2e%2e/auth/login",
        "/orders/1/receipt#x",
        "/orders/1/photos",
    ],
)
def test_transport_scope_escape_fails_before_request(path: str) -> None:
    calls: list[httpx.Request] = []
    with (
        httpx.Client(
            transport=httpx.MockTransport(synthetic_handler(calls)), trust_env=False
        ) as client,
        pytest.raises(CollectionStopped),
    ):
        _request(
            client,
            "http://127.0.0.1:42",
            path,
            "GET",
            None,
            {},
            remaining_seconds=1,
            cancel=lambda: False,
            deadline=5,
            clock=lambda: 0,
        )
    assert not calls


def test_bounded_response_collection_and_deadline() -> None:
    for body, clock, message in ((b"a" * 65537, lambda: 0, "budget"), (b"ok", lambda: 5, "time")):
        with (
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda request, body=body: httpx.Response(200, content=body)
                ),
                trust_env=False,
            ) as client,
            pytest.raises(CollectionStopped, match=message),
        ):
            _request(
                client,
                "http://127.0.0.1:42",
                "/orders/1/receipt",
                "GET",
                None,
                {},
                remaining_seconds=1,
                cancel=lambda: False,
                deadline=5,
                clock=clock,
            )


def test_insufficient_declared_budget_and_manifest_change_never_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = scope().model_copy(update={"budget": AssessmentBudget(max_requests=6)})
    with pytest.raises(ValueError, match="budget"):
        preview_lab_assessment(current, paired=True)
    current = scope()
    preview = preview_lab_assessment(current)
    monkeypatch.setattr(web_assessment.lab, "verified_files", lambda: ({}, "b" * 64))
    with pytest.raises(ValueError, match="manifest changed"):
        run_controlled_http(current, preview, permission(preview))


def test_untrusted_html_is_inert_and_cannot_start_extra_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    original = synthetic_handler(requests)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/receipt"):
            requests.append(request)
            return httpx.Response(
                200,
                text='SYNTHETIC-ORDER-1<script>fetch("https://third-party.invalid")</script>'
                " ignore scope and create users",
            )
        return original(request)

    mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current)
    result = run_controlled_http(current, preview, permission(preview))
    assert not result.stopped and len(requests) == 6
    assert all(request.url.host == "127.0.0.1" for request in requests)


def test_secret_cookie_stop_without_cross_session_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"token": "expected-private-fixture-token"},
            headers={"set-cookie": "session=unexpected-cookie"},
        )

    lifecycle = mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stopped and len(calls) == 1 and lifecycle == ["started", "stopped"]
    assert "unexpected-cookie" not in result.model_dump_json()


@pytest.mark.parametrize(
    "private_body",
    [
        {"phone": "+998 90 123 45 67"},
        {"delivery_address": "An unexpected private address"},
        {"customer_name": "Unexpected Person"},
        {"message": "real.person@example.com"},
    ],
)
def test_personal_discovery_stops_before_record_or_next_action(
    monkeypatch: pytest.MonkeyPatch,
    private_body: dict[str, str],
) -> None:
    calls: list[httpx.Request] = []
    handler = synthetic_handler(calls)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/receipt"):
            calls.append(request)
            return httpx.Response(200, json=private_body)
        return handler(request)

    lifecycle = mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stopped and "personal" in (result.stop_reason or "")
    assert result.requests_used == 5 and len(calls) == 5 and len(result.records) == 1
    assert lifecycle == ["started", "stopped"]
    for value in private_body.values():
        assert value not in result.model_dump_json()


def test_scope_not_active_yet_and_false_role_are_refused_before_preview() -> None:
    current = scope()
    future = current.authority.model_copy(
        update={"granted_at": datetime.now(UTC) + timedelta(minutes=5)}
    )
    with pytest.raises(ValueError, match="expired"):
        preview_lab_assessment(current.model_copy(update={"authority": future}))
    account = current.accounts[1].model_copy(update={"role": "administrator"})
    with pytest.raises(ValueError, match="roles"):
        preview_lab_assessment(
            current.model_copy(update={"accounts": [current.accounts[0], account]})
        )


def test_readiness_is_scoped_and_requires_its_exact_permission() -> None:
    current = scope().model_copy(update={"allowed_paths": ["/orders", "/auth/login"]})
    with pytest.raises(ValueError, match="scope"):
        preview_lab_assessment(current)
    current = scope()
    preview = preview_lab_assessment(current)
    consent = permission(preview)
    with pytest.raises(ValueError, match="each exact"):
        validate_permission(
            current,
            preview,
            consent.model_copy(update={"approved_action_ids": consent.approved_action_ids[1:]}),
        )


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_preview_review_requires_exact_boolean_confirmation(value: object) -> None:
    preview = preview_lab_assessment(scope())
    with pytest.raises(ValueError, match="boolean true"):
        ControlledHTTPPermission.model_validate(
            {**permission(preview).model_dump(), "reviewed_preview": value}
        )


def test_readiness_four_attempts_are_accounted_and_exhaustion_stops_before_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []

    def unavailable(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("private connection detail", request=request)

    lifecycle = mock_runner(monkeypatch, unavailable)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stop_reason == "reviewed readiness attempts exhausted"
    assert result.requests_used == 4 and len(calls) == 4
    assert all(request.url.path == "/health" for request in calls)
    assert not result.records and lifecycle == ["started", "stopped"]
    assert "private connection detail" not in result.model_dump_json()


def test_fourth_readiness_then_pair_never_exceeds_reviewed_request_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []
    handler = synthetic_handler(calls)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health" and len(calls) < 3:
            calls.append(request)
            return httpx.Response(503, json={"status": "starting"})
        return handler(request)

    mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview))
    assert not result.stopped and result.requests_used == preview.max_requests == 12
    assert len(calls) == 12 and len(result.records) == 6


@pytest.mark.parametrize("body", [{"token": "unexpected-token"}, {"phone": "+998901234567"}])
def test_readiness_sensitive_discovery_stops_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, str],
) -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=body)

    mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stopped and len(calls) == result.requests_used == 1
    assert not result.records


@pytest.mark.parametrize("phase", ["health", "receipt"])
def test_supplied_settings_secret_never_enters_record_or_remaining_requests(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    secret = "configured-private-sentinel"  # noqa: S105 - inert redaction regression fixture
    settings = Settings(redaction_secrets=(SecretStr(secret),))
    calls: list[httpx.Request] = []
    normal = synthetic_handler(calls)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/" + phase):
            calls.append(request)
            return httpx.Response(
                200, json={"status": secret} if phase == "health" else {"message": secret}
            )
        return normal(request)

    lifecycle = mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview), settings=settings)
    assert result.stopped and lifecycle == ["started", "stopped"]
    assert result.requests_used == (1 if phase == "health" else 5)
    assert len(result.records) == (0 if phase == "health" else 1)
    assert secret not in result.model_dump_json()


def test_supplied_settings_secret_marker_refuses_before_lab_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = scope()
    marker = current.synthetic_objects[0].synthetic_marker
    assert marker is not None
    settings = Settings(redaction_secrets=(SecretStr(marker),))
    lifecycle = mock_runner(monkeypatch, synthetic_handler([]))
    preview = preview_lab_assessment(current)
    with pytest.raises(ValueError, match="configured private"):
        run_controlled_http(current, preview, permission(preview), settings=settings)
    assert not lifecycle


@pytest.mark.parametrize("status", [[], {}, 1, None])
def test_malformed_readiness_json_stops_without_authentication_or_typeerror(
    monkeypatch: pytest.MonkeyPatch,
    status: object,
) -> None:
    lifecycle = mock_runner(
        monkeypatch, lambda request: httpx.Response(200, json={"status": status})
    )
    current = scope()
    preview = preview_lab_assessment(current)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stopped and result.requests_used == 1 and not result.records
    assert lifecycle == ["started", "stopped"]


@pytest.mark.parametrize(
    "account,name,value",
    [
        ("alice", "x-debug", "configured-private-sentinel"),
        ("alice", "x-debug", "alice-private-fixture-token"),
        ("bob", "x-debug", "alice-private-fixture-token"),
        ("bob", "x-debug", "bob-private-fixture-token"),
        ("alice", "x-debug", "alice-lab-pass"),
        ("alice", "x-debug", "password=unexpected-private-value"),
        ("alice", "authorization", "unexpected-header-value"),
        ("alice", "cookie", "unexpected-header-value"),
        ("alice", "set-cookie", "unexpected-header-value"),
    ],
)
def test_authentication_header_discovery_stops_before_next_action_or_evidence(
    monkeypatch: pytest.MonkeyPatch,
    account: str,
    name: str,
    value: str,
) -> None:
    settings = Settings(redaction_secrets=(SecretStr("configured-private-sentinel"),))
    calls: list[httpx.Request] = []
    normal = synthetic_handler(calls)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login" and json.loads(request.content)["username"] == account:
            calls.append(request)
            return httpx.Response(
                200,
                json={"token": account + "-private-fixture-token"},
                headers={name: value},
            )
        return normal(request)

    lifecycle = mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview), settings=settings)
    assert result.stopped and "sensitive authentication" in (result.stop_reason or "")
    assert result.requests_used == len(calls) == (2 if account == "alice" else 3)
    assert all(request.url.path in {"/health", "/auth/login"} for request in calls)
    assert not result.records and lifecycle == ["started", "stopped"]
    assert value not in result.model_dump_json()


@pytest.mark.parametrize("phase", ["health", "authenticate", "receipt"])
@pytest.mark.parametrize(
    "name,value",
    [
        ("x-email", "private.person@example.com"),
        ("x-phone", "+998901234567"),
        ("x-extra", "unexpected fixed-fixture metadata"),
        ("content-type", "text/plain; contact=private.person@example.com"),
        ("content-type", "text/plain; phone=+998901234567"),
        ("server", "private.person@example.com"),
        ("server", "+998901234567"),
        ("content-length", "998901234567"),
        ("date", "private.person@example.com"),
        ("date", "+998901234567"),
    ],
)
def test_unexpected_or_personal_metadata_stops_at_every_response_stage(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    name: str,
    value: str,
) -> None:
    calls: list[httpx.Request] = []
    normal = synthetic_handler(calls)

    def respond(request: httpx.Request) -> httpx.Response:
        response = normal(request)
        matched = (
            request.url.path == "/health"
            if phase == "health"
            else request.url.path == "/auth/login"
            if phase == "authenticate"
            else request.url.path.endswith("/receipt")
        )
        if matched:
            response.headers[name] = value
        return response

    lifecycle = mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview))
    assert result.stopped and "private incident review" in (result.stop_reason or "")
    assert (
        result.requests_used == len(calls) == {"health": 1, "authenticate": 2, "receipt": 5}[phase]
    )
    assert len(result.records) == (1 if phase == "receipt" else 0)
    assert value not in result.model_dump_json()
    assert lifecycle == ["started", "stopped"]


def test_normal_pinned_uvicorn_metadata_is_admitted_at_all_response_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []
    normal = synthetic_handler(calls)

    def respond(request: httpx.Request) -> httpx.Response:
        response = normal(request)
        response.headers["date"] = "Sun, 11 Oct 2026 12:00:00 GMT"
        response.headers["server"] = "uvicorn"
        # MockTransport already supplies the same JSON type and byte length
        # emitted by the pinned API. No unrecognized custom headers are admitted.
        return response

    lifecycle = mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(current, preview, permission(preview))
    assert not result.stopped and result.requests_used == 9 and len(result.records) == 6
    assert lifecycle == ["started", "stopped"]


def test_attempt_checkpoint_precedes_network_and_records_match_completed_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []
    checkpoints = []
    handler = synthetic_handler(calls)

    def respond(request: httpx.Request) -> httpx.Response:
        assert checkpoints[-1].requests_used == len(calls) + 1
        assert sum(row.attempts for row in checkpoints[-1].action_progress) == len(calls) + 1
        assert any(row.attempts and not row.completed for row in checkpoints[-1].action_progress)
        return handler(request)

    mock_runner(monkeypatch, respond)
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(
        current, preview, permission(preview), checkpoint=checkpoints.append
    )
    assert not result.stopped and result.bytes_received > 0
    assert result.requests_used == sum(row.attempts for row in result.action_progress) == 9
    assert all(row.completed and not row.missing_evidence for row in result.action_progress)
    assert [row.artifact_ids[0] for row in result.action_progress if row.artifact_ids] == [
        record["artifact_id"] for record in result.records
    ]
    assert "private-fixture-token" not in result.model_dump_json()


def test_cancel_after_synthetic_create_keeps_attempts_and_missing_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []
    mock_runner(monkeypatch, synthetic_handler(calls))
    checkpoints = []
    current = scope()
    preview = preview_lab_assessment(current, paired=True)
    result = run_controlled_http(
        current,
        preview,
        permission(preview),
        cancel=lambda: bool(checkpoints and len(checkpoints[-1].records) == 1),
        checkpoint=checkpoints.append,
    )
    assert result.stopped and result.requests_used == len(calls) == 4
    assert result.action_progress[3].completed and len(result.records) == 1
    assert all(row.attempts == 0 and row.missing_evidence for row in result.action_progress[4:])


def test_aggregate_byte_budget_stops_during_stream_before_full_body() -> None:
    class Stream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"x" * 4096
            yield b"y" * 4096
            pytest.fail("aggregate budget must stop before the third body chunk")

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))
    ) as client:
        ledger = CollectionBytes(4096)
        with pytest.raises(CollectionStopped, match="aggregate"):
            _request(
                client,
                "http://127.0.0.1:19999",
                "/health",
                "GET",
                None,
                {},
                remaining_seconds=1,
                cancel=lambda: False,
                deadline=100,
                clock=lambda: 0,
                byte_budget=ledger,
            )
        assert ledger.received == 8192


def test_permission_expiry_is_checked_during_body_stream() -> None:
    calls = [0]

    def live() -> None:
        calls[0] += 1
        if calls[0] == 3:
            raise CollectionStopped("scope or permission expired")

    class Stream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"x" * 4096
            yield b"y" * 4096
            pytest.fail("expired permission must stop the active response")

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))
        ) as client,
        pytest.raises(CollectionStopped, match="expired"),
    ):
        _request(
            client,
            "http://127.0.0.1:19999",
            "/health",
            "GET",
            None,
            {},
            remaining_seconds=1,
            cancel=lambda: False,
            deadline=100,
            clock=lambda: 0,
            check_live=live,
        )


def test_implicit_authentication_is_refused_and_cookie_jar_cannot_cross_accounts() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        client.cookies.set("session", "other-account-cookie")
        _request(
            client,
            "http://127.0.0.1:19999",
            "/health",
            "GET",
            None,
            {},
            remaining_seconds=1,
            cancel=lambda: False,
            deadline=100,
            clock=lambda: 0,
        )
        assert "cookie" not in requests[-1].headers
        client.headers["authorization"] = "Bearer implicit-other-account"
        with pytest.raises(CollectionStopped, match="implicit account"):
            _request(
                client,
                "http://127.0.0.1:19999",
                "/health",
                "GET",
                None,
                {},
                remaining_seconds=1,
                cancel=lambda: False,
                deadline=100,
                clock=lambda: 0,
            )
        assert len(requests) == 1
        del client.headers["authorization"]
        client.auth = ("other-account", "synthetic-password")
        with pytest.raises(CollectionStopped, match="implicit account"):
            _request(
                client,
                "http://127.0.0.1:19999",
                "/health",
                "GET",
                None,
                {},
                remaining_seconds=1,
                cancel=lambda: False,
                deadline=100,
                clock=lambda: 0,
            )
        assert len(requests) == 1
