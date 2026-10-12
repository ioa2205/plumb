"""Short session tokens stay operational but never become observation or report data.

The HTTP/browser/storage transports are stand-ins. No socket, browser, model or
private filesystem is opened by these tests.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock

import pytest

from agent.web_questions import form_question, page_question
from backend.contracts.web import BlockedRequest, WebEvidence, WebTarget, digest
from backend.redaction import Redactor
from backend.settings import Settings
from backend.tests.test_web_scope import journey, scope
from backend.web_journey import Journey
from backend.web_report import markdown
from backend.web_store import JourneyStore
from backend.web_urls import parse_url
from verification.egress import Egress, EgressResponse
from verification.web_browser import BrowserRunner
from verification.web_http import HttpAdapter, HttpSession
from verification.web_pages import RawPage, build_observation
from verification.web_secrets import SecretStore

ORIGIN = "https://shop.example.com"
TOKEN = "123456"  # noqa: S105 - a synthetic cookie, never a real credential


@pytest.mark.parametrize("token", ["1", "xy", "abc", "1234", "abcde", "123456", "abcdefg"])
def test_no_supported_cookie_length_is_silently_excluded(token: str) -> None:
    session = HttpSession("anna")
    url = parse_url(ORIGIN + "/app")
    session.store(url, [f"sid={token}; Path=/; Secure; HttpOnly"])
    assert session.values() == (token,)
    assert session.header(url) == "sid=" + token
    assert session.header(parse_url("https://other.example.com/app")) is None
    session.store(url, ["sid=; Max-Age=0; Path=/"])
    assert session.header(url) is None and session.values() == ()


def test_empty_browser_cookie_values_are_not_invalid_redaction_inputs() -> None:
    session = HttpSession("anna", {ORIGIN: {"sid": ("", "/", True)}})
    assert session.values() == ()
    Redactor(session.values())


def _raw() -> RawPage:
    return RawPage(
        title="Account " + TOKEN,
        headings=["Session " + TOKEN],
        text="Opaque session token is " + TOKEN,
        links=[{"text": "Details " + TOKEN, "href": "/app/session/" + TOKEN}],
        forms=[
            {
                "action": "/api/session/" + TOKEN,
                "method": "post",
                "heading": "Continue " + TOKEN,
                "submit": "Continue",
                "fields": [{"name": "username", "type": "text", "label": "User " + TOKEN}],
            }
        ],
    )


def _session() -> HttpSession:
    session = HttpSession("anna")
    session.store(parse_url(ORIGIN), [f"sid={TOKEN}; Path=/; Secure; HttpOnly"])
    return session


def test_display_addresses_and_model_facts_are_sanitized_but_transport_maps_stay_exact() -> None:
    session = _session()
    raw = _raw()
    raw.links.append({"text": "Encoded details", "href": "/app/%31%32%33%34%35%36"})
    base = parse_url(ORIGIN + "/app/session/" + TOKEN)
    bound = build_observation(
        raw,
        via="http",
        base=base,
        status=200,
        account_id="anna",
        in_scope=lambda url: url.origin == ORIGIN,
        redactor=Redactor(session.values()),
        expected_personal=frozenset(),
        blocked=[
            BlockedRequest(
                kind="off_scope",
                host="session" + TOKEN + ".example",
                reason="Request with " + TOKEN + " was refused",
            )
        ],
    )
    page = bound.observation
    serialized = page.model_dump_json()
    assert TOKEN not in serialized and "%31%32%33%34%35%36" not in serialized
    assert page.path == page.forms[0].action_path == "[REDACTED]"
    assert all(link.path == "[REDACTED]" for link in page.links)
    assert bound.links[page.links[0].ref].path == "/app/session/" + TOKEN
    assert bound.links[page.links[1].ref].path == "/app/%31%32%33%34%35%36"
    assert bound.forms[page.forms[0].ref].path == "/api/session/" + TOKEN
    for request in [page_question(page).request(), form_question(page.forms[0], page).request()]:
        assert TOKEN not in request.user and "[REDACTED]" in request.user


def test_http_adapter_redacts_a_short_cookie_set_by_the_same_response() -> None:
    broker = Mock(spec=Egress)
    body = (
        f"<title>Account {TOKEN}</title><p>Opaque session token is {TOKEN}</p>"
        f'<a href="/app/{TOKEN}">Continue</a>'
    ).encode()
    broker.send.return_value = EgressResponse(
        status=200,
        headers=[
            ("Content-Type", "text/html"),
            ("Set-Cookie", f"sid={TOKEN}; Path=/; Secure; HttpOnly"),
        ],
        peer="",
        _chunks=iter([body]),
        _close=lambda: None,
    )
    session = HttpSession("anna")
    bound, result = HttpAdapter(broker).observe(
        session,
        parse_url(ORIGIN + "/app"),
        redactor=Redactor(()),
        expected_personal=frozenset(),
    )
    assert result.status == 200 and session.header(parse_url(ORIGIN)) == "sid=" + TOKEN
    assert TOKEN not in bound.observation.model_dump_json()
    assert TOKEN not in page_question(bound.observation).request().user


def test_browser_session_export_and_observation_share_the_short_cookie_policy() -> None:
    broker = Mock(spec=Egress)
    broker.policy = SimpleNamespace(targets=(WebTarget(origin=ORIGIN, paths=["/"]),))
    broker.in_scope.return_value = True
    broker.blocked = []
    runner = BrowserRunner(
        Settings(),
        broker,
        secrets=SecretStore(),
        redactor=Redactor(()),
        expected_personal=frozenset(),
    )
    page, context = Mock(), Mock()
    page.url = ORIGIN + "/app"
    raw = _raw()
    page.evaluate.return_value = {
        "title": raw.title,
        "headings": raw.headings,
        "text": raw.text,
        "links": raw.links,
        "forms": raw.forms,
    }
    context.cookies.return_value = [{"name": "sid", "value": TOKEN, "path": "/", "secure": True}]
    runner._browser = Mock()
    runner._pages["anna"] = page
    runner._contexts["anna"] = context
    session = runner.session("anna")
    assert session.values() == (TOKEN,)
    assert session.header(parse_url(ORIGIN)) == "sid=" + TOKEN
    assert TOKEN not in runner.observe("anna").observation.model_dump_json()


def test_checkpoint_rejects_a_raw_short_token_and_report_keeps_only_sanitized_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    investigator = Journey.__new__(Journey)
    investigator.settings = Settings()
    investigator.secrets = SecretStore()
    investigator.sessions = {"anna": session}
    redactor = investigator.redactor()
    assert TOKEN in redactor.secrets
    bound = build_observation(
        _raw(),
        via="http",
        base=parse_url(ORIGIN + "/app"),
        status=200,
        account_id="anna",
        in_scope=lambda url: True,
        redactor=redactor,
        expected_personal=frozenset(),
    )
    page = bound.observation
    core = {
        "evidence_id": "page-one",
        "kind": "page",
        "account_id": "anna",
        "object_id": None,
        "fields": {
            "page.text": page.text,
            "page.path": page.path,
            "form.action": page.forms[0].action_path,
        },
    }
    evidence = WebEvidence.model_validate(
        {
            **core,
            "website_id": "website-1",
            "via": "http",
            "collected_at": datetime.now(UTC),
            "provenance": "Synthetic adapter stand-in",
            "sha256": digest(core),
        }
    )
    view = journey(scope()).model_copy(update={"evidence": [evidence]})
    store = JourneyStore.__new__(JourneyStore)
    store.settings = investigator.settings
    folder = MagicMock(spec=Path)
    monkeypatch.setattr(store, "folder", lambda identifier: folder)
    monkeypatch.setattr("backend.web_store.replace_atomically", Mock())
    raw = view.model_copy(update={"activity": "Raw session " + TOKEN})
    with pytest.raises(ValueError, match="may not contain a secret"):
        store.save(raw, secrets=redactor.secrets)
    assert not folder.mkdir.called
    store.save(view, secrets=redactor.secrets)
    temporary = cast(MagicMock, folder.__truediv__.return_value)
    saved = temporary.write_text.call_args.args[0]
    assert TOKEN not in saved and "[REDACTED]" in saved
    report = markdown(view)
    assert TOKEN not in report and "[REDACTED]" in report
