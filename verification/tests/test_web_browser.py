"""The real pinned browser behind the broker. Skipped when the browser is not provisioned.

Nothing here is mocked: the provisioned Chromium runs the owned fixture's
JavaScript, signs in, and is then pointed at a page that tries every way a page
can to reach a listener outside its scope.
"""

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from backend.contracts.web import WebTarget
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.browser import status
from backend.web_urls import parse_url
from verification.egress import ActionPermission, Egress, EgressPolicy, EgressRefused, tls_context
from verification.web_browser import BrowserRunner, StaleReference
from verification.web_fixture import SUPPORT, Fixture, launch
from verification.web_http import HttpAdapter
from verification.web_pages import PrivacyStop
from verification.web_secrets import MissingSecret, SecretStore

from .web_support import PUBLIC, Canary, Site, budget, carried, soon, tls_for

SETTINGS = Settings()
pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        not status(SETTINGS)["verified"],
        reason="pinned browser not provisioned: python -m backend.setup.browser install",
    ),
]


@pytest.fixture(scope="module")
def canary() -> Iterator[Canary]:
    listener = Canary()
    yield listener
    listener.close()


@pytest.fixture(scope="module")
def fixture(canary: Canary) -> Iterator[Fixture]:
    with launch("open", SETTINGS, port=0, boundary=canary.port) as started:
        yield started


@pytest.fixture(scope="module")
def egress(fixture: Fixture) -> Iterator[Egress]:
    scope = fixture.scope()
    broker = Egress(
        EgressPolicy(
            mode="owned_fixture",
            targets=tuple(scope.targets),
            expires_at=scope.expires_at,
            owned_port=fixture.port,
            approved_actions=tuple(
                ActionPermission(
                    ("signin-" if account.provisioned else "signup-") + account.account_id,
                    "sign_in" if account.provisioned else "sign_up",
                    account.account_id,
                )
                for account in scope.accounts
            ),
        ),
        budget(requests=600, size=30_000_000, seconds=300),
    )
    yield broker
    broker.close()


@pytest.fixture(scope="module")
def browser(fixture: Fixture, egress: Egress) -> Iterator[BrowserRunner]:
    with BrowserRunner(
        SETTINGS,
        egress,
        secrets=fixture.secrets,
        redactor=Redactor(()),
        expected_personal=frozenset({SUPPORT}),
    ) as runner:
        yield runner


def at(fixture: Fixture, path: str):  # noqa: ANN201
    return parse_url(fixture.origin + path)


def sign_in(browser: BrowserRunner, fixture: Fixture, account: str) -> None:
    browser.navigate(account, at(fixture, "/signin"))
    page = browser.observe(account).observation
    (form,) = page.forms
    with browser.egress.action("signin-" + account, account):
        browser.fill(account, form.fields[0].ref, value=account)
        browser.fill(account, form.fields[1].ref, secret_ref="chorsu-" + account)
        browser.submit(account, form.ref)


# --- ordinary use ----------------------------------------------------------------------------


def test_the_sandbox_is_on_and_the_browser_is_the_pinned_one(browser: BrowserRunner) -> None:
    assert browser.sandboxed() is True
    assert "--no-sandbox" not in " ".join(browser.launch_arguments)
    assert "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1" in browser.launch_arguments


def test_a_javascript_rendered_form_is_observed_filled_and_submitted(
    browser: BrowserRunner, fixture: Fixture, egress: Egress
) -> None:
    assert browser.navigate("dilnoza", at(fixture, "/signin")) == 200
    bound = browser.observe("dilnoza", 200)
    page = bound.observation
    assert (page.via, page.title) == ("browser", "Sign in · Chorsu Parcel Lockers")
    (form,) = page.forms  # drawn by the page's script; a plain fetch sees none
    assert (form.heading, form.submit_label, form.method, form.in_scope) == (
        "Sign in",
        "Sign in",
        "POST",
        True,
    )
    assert [(item.label, item.input_type, item.required) for item in form.fields] == [
        ("Username", "text", True),
        ("Password", "password", True),
    ]
    assert page.challenge == "none"
    sign_in(browser, fixture, "dilnoza")
    assert browser.location("dilnoza") == at(fixture, "/parcels")
    after = browser.observe("dilnoza").observation
    assert "Signed in as Dilnoza" in after.text and "Parcel 4117" in after.text
    assert [link.path for link in after.links if link.path.startswith("/parcels/")] == [
        "/parcels/4117"
    ]
    # The password went from the store to the field and nowhere else.
    secret = fixture.secrets.get("chorsu-dilnoza")
    assert secret not in after.model_dump_json() and secret not in page.model_dump_json()
    assert all(record.source == "browser" for record in egress.records)
    assert {record.origin for record in egress.records} == {fixture.origin}


def test_each_account_has_its_own_cookies_and_its_session_reaches_the_http_adapter(
    browser: BrowserRunner, fixture: Fixture, egress: Egress
) -> None:
    sign_in(browser, fixture, "rustam")
    other = browser.observe("rustam").observation
    assert "Signed in as Rustam" in other.text and "Parcel 4120" in other.text
    assert "4117" not in other.text
    browser.navigate(None, at(fixture, "/parcels"))
    assert "Sign in to see your parcels" in browser.observe(None).observation.text
    owner, visitor = browser.session("dilnoza"), browser.session("rustam")
    assert owner.cookies[fixture.origin] != visitor.cookies[fixture.origin]
    assert browser.session(None).cookies == {}
    adapter = HttpAdapter(egress)
    label = at(fixture, "/api/parcels/4117/label")
    assert fixture.marker in adapter.request(owner, "GET", label).text()
    assert fixture.marker in adapter.request(visitor, "GET", label).text()  # the open flaw
    assert adapter.request(visitor, "GET", at(fixture, "/api/parcels/4117")).status == 404
    # The session token is not observable: it is redacted from what the page shows.
    token = owner.cookies[fixture.origin]["chorsu_session"][0]
    assert token not in browser.observe("dilnoza").observation.model_dump_json()


def test_a_session_survives_a_restart_only_through_its_own_saved_state(
    browser: BrowserRunner, fixture: Fixture
) -> None:
    state = browser.state("dilnoza")
    assert state is not None
    browser.forget("dilnoza")
    browser.navigate("dilnoza", at(fixture, "/parcels"))
    assert "Sign in to see your parcels" in browser.observe("dilnoza").observation.text
    browser.forget("dilnoza")
    browser.restore("dilnoza", state)
    browser.navigate("dilnoza", at(fixture, "/parcels"))
    assert "Signed in as Dilnoza" in browser.observe("dilnoza").observation.text
    with pytest.raises(ValueError, match="already has an open context"):
        browser.restore("dilnoza", state)


def test_an_approved_sign_up_creates_one_synthetic_account(
    browser: BrowserRunner, fixture: Fixture
) -> None:
    fixture.secrets.generate("chorsu-newcomer")
    browser.navigate("newcomer", at(fixture, "/join"))
    (form,) = browser.observe("newcomer").observation.forms
    assert [item.label for item in form.fields] == [
        "Your name",
        "Choose a username",
        "Email for pickup notices",
        "Choose a password",
        "Repeat the password",
    ]
    values = ["Newcomer", "plumbtest01", "newcomer@chorsu.test"]
    for item, value in zip(form.fields[:3], values, strict=True):
        browser.fill("newcomer", item.ref, value=value)
    for item in form.fields[3:]:
        browser.fill("newcomer", item.ref, secret_ref="chorsu-newcomer")  # noqa: S106
    with browser.egress.action("signup-newcomer", "newcomer"):
        browser.submit("newcomer", form.ref)
    done = browser.observe("newcomer").observation
    assert "Signed in as Newcomer" in done.text and "No parcels are waiting" in done.text
    assert fixture.secrets.get("chorsu-newcomer") not in done.model_dump_json()


# --- references, secrets and page content ------------------------------------------------------


def test_a_reference_from_an_earlier_observation_or_a_changed_page_is_refused(
    browser: BrowserRunner, fixture: Fixture
) -> None:
    browser.navigate("stale", at(fixture, "/signin"))
    first = browser.observe("stale").observation
    second = browser.observe("stale").observation
    assert first.forms[0].ref != second.forms[0].ref
    with pytest.raises(StaleReference, match="earlier observation"):
        browser.fill("stale", first.forms[0].fields[0].ref, value="x")
    browser.fill("stale", second.forms[0].fields[0].ref, value="dilnoza")
    browser.navigate("stale", at(fixture, "/join"))
    with pytest.raises(StaleReference):
        browser.submit("stale", second.forms[0].ref)
    with pytest.raises(StaleReference):
        browser.follow("stale", "o00000000-l0")
    browser.forget("stale")


def test_a_field_takes_a_value_or_a_known_secret_reference_and_nothing_else(
    browser: BrowserRunner, fixture: Fixture
) -> None:
    browser.navigate("checks", at(fixture, "/signin"))
    (form,) = browser.observe("checks").observation.forms
    with pytest.raises(ValueError, match="exactly one"):
        browser.fill("checks", form.fields[0].ref)
    with pytest.raises(ValueError, match="exactly one"):
        browser.fill("checks", form.fields[0].ref, value="a", secret_ref="chorsu-dilnoza")  # noqa: S106
    with pytest.raises(MissingSecret, match="chorsu-nobody"):
        browser.fill("checks", form.fields[1].ref, secret_ref="chorsu-nobody")  # noqa: S106
    browser.forget("checks")


def test_page_text_is_data_and_an_undeclared_address_stops_the_page(
    browser: BrowserRunner, fixture: Fixture, egress: Egress
) -> None:
    browser.navigate(None, at(fixture, "/help"))
    page = browser.observe(None).observation
    # The page's planted instruction is carried as text and changes nothing.
    assert "ignore your earlier instructions" in page.text
    assert [target.origin for target in egress.policy.targets] == [fixture.origin]
    outside = [link for link in page.links if not link.in_scope]
    assert [link.path for link in outside] == ["https://maps.chorsu-partner.example/lockers"]
    with pytest.raises(EgressRefused, match="outside the approved scope"):
        browser.follow(None, outside[0].ref)
    # The page's off-scope image was refused by the broker and is shown as blocked.
    assert any(
        row.host == "cdn.chorsu-partner.example" and row.kind == "off_scope" for row in page.blocked
    )
    strict = BrowserRunner.__new__(BrowserRunner)
    strict.__dict__.update(browser.__dict__)
    strict.expected_personal = frozenset()
    with pytest.raises(PrivacyStop):
        strict.observe(None)


# --- containment ---------------------------------------------------------------------------------


def test_a_page_cannot_make_the_browser_reach_anything_outside_the_scope(
    browser: BrowserRunner, fixture: Fixture, egress: Egress, canary: Canary
) -> None:
    before = len(egress.records)
    assert browser.navigate("escape", at(fixture, "/boundary/escape")) == 200
    deadline = time.monotonic() + 20
    text = ""
    while time.monotonic() < deadline:
        text = browser.observe("escape").observation.text
        if "finished" in text:
            break
        time.sleep(0.25)
    assert "finished" in text, text
    # What the page can tell apart did fail. (An opaque "no-cors" request cannot tell the
    # broker's refusal from an answer, so the page's own word is not the evidence for those.)
    for name in ("xhr", "websocket", "same-origin-websocket"):
        assert f"{name}:failed" in text, text
    # The evidence: nothing at all arrived at the listener outside the scope,
    time.sleep(1.0)
    assert canary.connections == 0, canary.first_bytes
    # every request that was sent went to the fixture's own origin,
    sent = egress.records[before:]
    assert {record.origin for record in sent} == {fixture.origin}
    assert "/boundary/sw.js" not in {record.path for record in sent}  # no worker was even fetched
    # and each kind of attempt is on record as refused, by host.
    blocked = {(row.kind, row.host) for row in egress.blocked}
    assert ("off_scope", "127.0.0.1") in blocked  # the other loopback port
    assert ("off_scope", "rebind.chorsu-evil.example") in blocked
    assert ("off_scope", "localhost") in blocked
    assert ("off_scope", "::1") in blocked
    # (The browser itself rewrites 0x7f.0.0.1 to 127.0.0.1, so it is the first line above.)
    assert ("websocket", "127.0.0.1") in blocked
    assert any(kind == "redirect" for kind, _ in blocked)
    assert browser.popups_closed >= 1
    # A direct navigation and an observed link out of scope are refused before any request.
    for address in (
        f"http://127.0.0.1:{canary.port}/direct",
        f"http://localhost:{fixture.port}/",
        "https://example.com/",
    ):
        with pytest.raises(EgressRefused):
            browser.navigate("escape", parse_url(address))
    # A top-level redirect out of scope ends at the broker, which says so on the page.
    assert browser.navigate("escape", at(fixture, "/boundary/redirect")) == 403
    shown = browser.observe("escape", 403).observation
    assert "Blocked by Plumb" in shown.text and "redirect" in shown.text
    assert browser.location("escape") == at(fixture, "/boundary/redirect")
    assert browser.navigate("escape", at(fixture, "/boundary/download")) in {403, None}
    assert any(row.kind == "download" for row in egress.blocked)
    time.sleep(0.5)
    assert canary.connections == 0
    browser.forget("escape")


def test_the_proxy_refuses_a_client_without_the_launch_token(
    browser: BrowserRunner, fixture: Fixture, egress: Egress
) -> None:
    import httpx

    assert browser._proxy is not None
    before = len(egress.records)
    with httpx.Client(proxy=browser._proxy.address, trust_env=False) as client:
        response = client.get(fixture.origin + "/")
    assert response.status_code == 407 and len(egress.records) == before


def test_a_used_up_budget_stops_the_browser_too(fixture: Fixture) -> None:
    scope = fixture.scope()
    small = Egress(
        EgressPolicy(
            mode="owned_fixture",
            targets=tuple(scope.targets),
            expires_at=scope.expires_at,
            owned_port=fixture.port,
        ),
        budget(requests=2),
    )

    def body() -> None:
        with BrowserRunner(
            SETTINGS,
            small,
            secrets=fixture.secrets,
            redactor=Redactor(()),
            expected_personal=frozenset(),
        ) as runner:
            runner.navigate(None, at(fixture, "/"))
            runner.observe(None)
            # The page, then one of its files; the next file was refused and is on record.
            assert small.budget.requests == 2
            assert any(row.kind == "budget" for row in small.blocked)
            with pytest.raises(EgressRefused):
                runner.navigate(None, at(fixture, "/help"))

    try:
        apart(body)
    finally:
        small.close()


# --- HTTPS through the broker's own front, external mode by the test seam ---------------------


def test_https_pages_are_inspected_by_the_broker_and_verified_upstream(tmp_path: Path) -> None:
    material = tls_for("shop.test", tmp_path)
    canary = Canary()
    page = (
        b"<!doctype html><title>Secure shop</title><h1>Secure shop</h1>"
        b"<a href='/next'>Next</a><img src='https://tracker.test/pixel.png'>"
        b"<script>fetch('/api').then(r => r.text()).then(t => {"
        b"document.body.insertAdjacentHTML('beforeend', '<p id=x>' + t + '</p>')});"
        b"fetch('https://tracker.test/beacon').catch(() => {});</script>"
    )
    site = Site(
        {
            "/": (200, {"Content-Type": "text/html"}, page),
            "/api": (200, {"Content-Type": "text/plain"}, b"api says hello"),
            "/away": (302, {"Location": "https://other.test/"}, b""),
        },
        context=material.server,
    )
    asked: list[str] = []

    def resolver(name: str, port: int) -> list[str]:
        asked.append(name)
        return [PUBLIC]

    broker = Egress(
        EgressPolicy(
            mode="external",
            targets=(WebTarget(origin="https://shop.test", paths=["/"]),),
            expires_at=soon(),
        ),
        budget(),
        resolver=resolver,
        connect=carried(site.port),
        context=tls_context(material.authority_pem),
    )

    def body() -> None:
        with BrowserRunner(
            SETTINGS,
            broker,
            secrets=SecretStore(),
            redactor=Redactor(()),
            expected_personal=frozenset(),
        ) as runner:
            assert runner.navigate(None, parse_url("https://shop.test/")) == 200
            observed = runner.observe(None).observation
            assert observed.title == "Secure shop" and "api says hello" in observed.text
            # The broker saw each HTTPS request by path, which a blind tunnel cannot.
            assert {record.path for record in broker.records} >= {"/", "/api"}
            assert all(record.peer == PUBLIC for record in broker.records)
            assert ("off_scope", "tracker.test") in {(row.kind, row.host) for row in broker.blocked}
            assert set(asked) == {"shop.test"}  # the off-scope name was never even resolved
            # An HTTPS redirect out of scope is stopped at the broker and shown on the page.
            assert runner.navigate(None, parse_url("https://shop.test/away")) == 403
            assert "Blocked by Plumb" in runner.observe(None, 403).observation.text
            assert ("redirect", "other.test") in {(row.kind, row.host) for row in broker.blocked}

    try:
        apart(body)
        assert canary.connections == 0
        assert site.hits and all(hit.headers["host"] == "shop.test" for hit in site.hits)
    finally:
        broker.close()
        site.close()
        canary.close()


def apart(body: Callable[[], None]) -> None:
    """Run ``body`` in its own thread: one synchronous browser runner lives per thread."""
    failure: list[BaseException] = []

    def run() -> None:
        try:
            body()
        except BaseException as error:
            failure.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=180)
    assert not thread.is_alive(), "the browser thread did not finish"
    if failure:
        raise failure[0]
