"""Socket-free action authorization; scope alone never permits website writes."""

import base64
import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TypedDict, cast
from unittest.mock import Mock
from urllib.parse import urlencode

import pytest

from backend.contracts.web import WebTarget
from backend.redaction import Redactor
from backend.settings import Settings
from backend.web_urls import parse_url
from verification.egress import ActionPermission, ActionRefused, Egress, EgressBudget, EgressPolicy
from verification.web_browser import (
    EXTRACT_JS,
    FORM_VALUES_JS,
    BrowserRunner,
    StaleReference,
    _Current,
    _signature,
)
from verification.web_http import HttpAdapter, HttpSession
from verification.web_pages import RawPage, build_observation
from verification.web_proxy import USER, BrowserProxy, _Closed
from verification.web_secrets import SecretStore

ORIGIN = "http://127.0.0.1:9001"
FIELDS = {"username": "synthetic-user", "password": "synthetic-password", "csrf": "token"}
HEADERS = [("Content-Type", "application/x-www-form-urlencoded")]


class _SendChange(TypedDict, total=False):
    method: str
    path: str
    fields: dict[str, str] | None
    account: str | None


@pytest.fixture
def broker() -> Iterator[Egress]:
    egress = Egress(
        EgressPolicy(
            mode="owned_fixture",
            targets=(WebTarget(origin=ORIGIN, paths=["/"]),),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            owned_port=9001,
            approved_actions=(
                ActionPermission("signin-a", "sign_in", "a"),
                ActionPermission("signup-b", "sign_up", "b"),
            ),
        ),
        EgressBudget(20, 100000, time.monotonic() + 60),
    )
    real_pool = egress._pool
    pool = Mock()
    pool.handle_request.side_effect = lambda request: SimpleNamespace(
        status=200, headers=[], stream=iter([b"ok"]), close=lambda: None
    )
    egress._pool = pool
    try:
        yield egress
    finally:
        real_pool.close()
        egress.close()


def send(
    broker: Egress,
    *,
    method: str = "POST",
    path: str = "/api/login",
    fields: dict[str, str] | None = None,
    account: str | None = "a",
) -> bytes:
    return broker.send(
        method,
        parse_url(ORIGIN + path),
        HEADERS,
        urlencode(FIELDS if fields is None else fields).encode(),
        source="browser",
        account_id=account,
    ).read(1000)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_scope_alone_and_an_active_action_without_a_form_cannot_write(
    broker: Egress,
    method: str,
) -> None:
    with pytest.raises(ActionRefused):
        send(broker, method=method)
    with broker.action("signin-a", "a"), pytest.raises(ActionRefused):
        send(broker, method=method)
    assert broker.budget.requests == 0
    assert not cast(Mock, broker._pool).handle_request.called


def test_an_unapproved_step_account_or_read_step_cannot_be_activated(broker: Egress) -> None:
    for step, account in [("discover", None), ("signin-a", "b"), ("signup-b", "a")]:
        with pytest.raises(ActionRefused), broker.action(step, account):
            pass
    with pytest.raises(ActionRefused), broker.form_grant("a", "POST", parse_url(ORIGIN), FIELDS):
        pass
    assert broker.budget.requests == 0


def test_a_grant_binds_exact_endpoint_account_method_fields_values_and_single_use(
    broker: Egress,
) -> None:
    url = parse_url(ORIGIN + "/api/login")
    with broker.action("signin-a", "a"), broker.form_grant("a", "POST", url, FIELDS):
        changes: list[_SendChange] = [
            {"path": "/delete"},
            {"path": "/api/login?next=/admin"},
            {"method": "DELETE"},
            {"account": "b"},
            {"account": None},
            {"fields": {**FIELDS, "admin": "true"}},
            {"fields": {**FIELDS, "username": "real-user"}},
            {"fields": {"username": "synthetic-user"}},
        ]
        for kwargs in changes:
            with pytest.raises(ActionRefused):
                send(broker, **kwargs)
        assert broker.budget.requests == 0
        assert send(broker) == b"ok"
        with pytest.raises(ActionRefused):
            send(broker)
    with pytest.raises(ActionRefused):
        send(broker)
    assert broker.budget.requests == 1
    assert cast(Mock, broker._pool).handle_request.call_count == 1
    assert "synthetic-password" not in repr(broker.records)
    assert "synthetic-password" not in repr(broker.blocked)


@pytest.mark.parametrize("step,account", [("signin-a", "a"), ("signup-b", "b")])
def test_observed_api_forms_can_use_scalar_json_and_optional_hidden_fields(
    broker: Egress,
    step: str,
    account: str,
) -> None:
    url = parse_url(ORIGIN + "/api/login")
    with (
        broker.action(step, account),
        broker.form_grant(
            account,
            "POST",
            url,
            FIELDS,
            required=frozenset({"username", "password"}),
        ),
    ):
        payload = json.dumps({name: value for name, value in FIELDS.items() if name != "csrf"})
        result = broker.send(
            "POST",
            url,
            [("Content-Type", "application/json")],
            payload.encode(),
            source="browser",
            account_id=account,
        ).read(1000)
        assert result == b"ok"
    assert broker.budget.requests == 1


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("application/json", '{"username":"synthetic-user","username":"other"}'),
        ("application/json", '[["username","synthetic-user"]]'),
        ("application/json", '{"username":{"name":"synthetic-user"}}'),
        ("application/x-www-form-urlencoded", "username=synthetic-user&username=other"),
        ("text/plain", "username=synthetic-user"),
    ],
)
def test_ambiguous_or_uninspectable_payloads_do_not_consume_a_grant(
    broker: Egress,
    kind: str,
    payload: str,
) -> None:
    url = parse_url(ORIGIN + "/api/login")
    with broker.action("signin-a", "a"), broker.form_grant("a", "POST", url, FIELDS):
        with pytest.raises(ActionRefused):
            broker.send("POST", url, [("Content-Type", kind)], payload.encode(), account_id="a")
        assert send(broker) == b"ok"
    assert broker.budget.requests == 1


def test_http_sessions_bind_their_account_and_cookie(broker: Egress) -> None:
    adapter = HttpAdapter(broker)
    session = HttpSession("a")
    url = parse_url(ORIGIN + "/api/login")
    session.store(url, ["sid=session-for-a; Path=/; HttpOnly"])
    with pytest.raises(ActionRefused):
        adapter.request(session, "POST", url, form=FIELDS)
    with broker.action("signin-a", "a"), broker.form_grant("a", "POST", url, FIELDS):
        result = adapter.request(session, "POST", url, form=FIELDS)
        assert result.status == 200
    wire = cast(Mock, broker._pool).handle_request.call_args.args[0]
    assert (b"Cookie", b"sid=session-for-a") in wire.headers
    assert adapter.request(session, "GET", url).status == 200


class _Socket:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.output = bytearray()

    def settimeout(self, value: float) -> None:
        pass

    def recv(self, count: int) -> bytes:
        data, self.data = self.data[:count], self.data[count:]
        return data

    def sendall(self, data: bytes) -> None:
        self.output.extend(data)


def test_proxy_authentication_attributes_the_request_to_its_browser_account(broker: Egress) -> None:
    proxy = BrowserProxy.__new__(BrowserProxy)
    proxy.egress = broker
    proxy.certificates = None
    proxy.port = 12345
    proxy._credentials = {}
    proxy._credential_lock = threading.Lock()
    a, b = proxy.proxy_for("a"), proxy.proxy_for("b")
    assert a["password"] != b["password"]
    body = urlencode(FIELDS).encode()

    def attempt(credentials: dict[str, str]) -> bytes:
        auth = base64.b64encode(f"{USER}:{credentials['password']}".encode()).decode()
        request = (
            f"POST {ORIGIN}/api/login HTTP/1.1\r\nHost: 127.0.0.1:9001\r\n"
            f"Proxy-Authorization: Basic {auth}\r\n"
            f"Content-Type: application/x-www-form-urlencoded\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode() + body
        sock = _Socket(request)
        with pytest.raises(_Closed):
            proxy._serve(cast(socket.socket, sock))
        return bytes(sock.output)

    url = parse_url(ORIGIN + "/api/login")
    assert b"403" in attempt(a)
    with broker.action("signin-a", "a"), broker.form_grant("a", "POST", url, FIELDS):
        assert b"403" in attempt(b)
        assert broker.budget.requests == 0
        assert b"200" in attempt(a)
    assert cast(Mock, broker._pool).handle_request.call_count == 1


def test_a_safe_read_cannot_smuggle_an_unapproved_body(broker: Egress) -> None:
    with pytest.raises(ActionRefused):
        send(broker, method="GET")
    assert broker.budget.requests == 0


@pytest.mark.parametrize("changed", [False, True])
def test_browser_tool_grants_only_the_observed_form_and_unchanged_filled_values(
    broker: Egress,
    changed: bool,
) -> None:
    pytest.importorskip("playwright")  # library only; no browser process is created
    raw = {
        "action": "/api/login",
        "method": "post",
        "fields": [
            {"name": "username", "type": "text", "required": True},
            {"name": "password", "type": "password", "required": True},
            {"name": "csrf", "type": "hidden"},
        ],
    }
    bound = build_observation(
        RawPage(forms=[raw]),
        via="browser",
        base=parse_url(ORIGIN + "/signin"),
        status=200,
        account_id="a",
        in_scope=broker.in_scope,
        redactor=Redactor(()),
        expected_personal=frozenset(),
    )
    runner = BrowserRunner(
        Settings(),
        broker,
        secrets=SecretStore(),
        redactor=Redactor(()),
        expected_personal=frozenset(),
    )
    form = bound.observation.forms[0]
    values = [
        {"index": i, "name": name, "value": value, "included": True, "required": name != "csrf"}
        for i, (name, value) in enumerate(FIELDS.items())
    ]
    current = _Current(
        bound.observation.observation_id,
        ORIGIN + "/signin",
        [_signature(raw)],
        bound,
        filled={(0, 0): FIELDS["username"], (0, 1): FIELDS["password"]},
    )
    page = Mock()
    page.url = current.url
    page.evaluate.side_effect = lambda script, *args: (
        {"forms": [raw]} if script == EXTRACT_JS else values if script == FORM_VALUES_JS else None
    )
    handle = Mock()
    handle.evaluate.return_value = "BUTTON"
    handle.click.side_effect = lambda **kwargs: send(broker)
    page.evaluate_handle.return_value.as_element.return_value = handle
    runner._pages["a"] = page
    runner._current["a"] = current
    runner._settle = Mock()
    with pytest.raises(ActionRefused):
        runner.submit("a", form.ref)
    assert not handle.click.called
    with broker.action("signin-a", "a"):
        if changed:
            values[0]["value"] = "real-user"
            with pytest.raises(StaleReference, match="changed before"):
                runner.submit("a", form.ref)
            assert not handle.click.called and broker.budget.requests == 0
        else:
            runner.submit("a", form.ref)
            assert handle.click.call_count == 1 and broker.budget.requests == 1
            with pytest.raises(ActionRefused):
                send(broker)
