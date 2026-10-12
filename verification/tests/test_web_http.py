"""The HTTP adapter and the owned fixture: isolated accounts, hand-checked redirects, privacy."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.redaction import Redactor
from backend.settings import Settings
from backend.web_urls import parse_url
from verification import web_fixture
from verification.egress import (
    ActionPermission,
    Egress,
    EgressBudget,
    EgressPolicy,
    EgressRefused,
    EgressStopped,
)
from verification.web_fixture import Fixture, FixtureUnavailable, launch
from verification.web_http import HttpAdapter, HttpSession, UncertainWrite
from verification.web_pages import PrivacyStop, personal_data, read_html

from .web_support import Canary, Site, budget, owned

REDACTOR = Redactor(())


def fixture_egress(fixture: Fixture, limit: EgressBudget | None = None) -> Egress:
    scope = fixture.scope()
    policy = EgressPolicy(
        mode="owned_fixture",
        targets=tuple(scope.targets),
        expires_at=scope.expires_at,
        owned_port=fixture.port,
        approved_actions=tuple(
            ActionPermission("signin-" + account.account_id, "sign_in", account.account_id)
            for account in scope.accounts
            if account.provisioned
        ),
    )
    return Egress(policy, limit or budget())


@pytest.fixture(scope="module")
def opened(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Fixture]:
    settings = Settings(data_dir=tmp_path_factory.mktemp("data"))
    with launch("open", settings, port=0) as fixture:
        yield fixture


def sign_in(adapter: HttpAdapter, fixture: Fixture, account: str) -> HttpSession:
    session = HttpSession(account)
    url = parse_url(fixture.origin + "/api/session")
    fields = {"username": account, "password": fixture.secrets.get("chorsu-" + account)}
    with (
        adapter.egress.action("signin-" + account, account),
        adapter.egress.form_grant(
            account,
            "POST",
            url,
            fields,
        ),
    ):
        result = adapter.request(session, "POST", url, form=fields)
    assert result.status == 200
    return session


# --- the owned fixture ----------------------------------------------------------------------


def test_the_fixture_runs_only_when_every_byte_matches_its_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files, manifest = web_fixture.verified_files()
    assert set(files) == set(web_fixture.FILES) and len(manifest) == 64
    changed = tmp_path / "chorsu"
    for name, content in files.items():
        target = changed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content + (b"\n# edited" if name == "server.py" else b""))
    with pytest.raises(FixtureUnavailable, match="differs from its pin"):
        web_fixture.verified_files(changed)
    monkeypatch.setattr(web_fixture, "FIXTURE", changed)
    with (
        pytest.raises(FixtureUnavailable),
        launch("open", Settings(data_dir=tmp_path / "d"), port=0),
    ):
        pass


def test_accounts_are_isolated_and_the_open_variant_has_exactly_its_one_flaw(
    opened: Fixture,
) -> None:
    egress = fixture_egress(opened)
    adapter = HttpAdapter(egress)
    owner, other = sign_in(adapter, opened, "dilnoza"), sign_in(adapter, opened, "rustam")
    visitor = HttpSession(None)
    label = parse_url(opened.origin + "/api/parcels/4117/label")
    record = parse_url(opened.origin + "/api/parcels/4117")
    assert opened.marker in adapter.request(owner, "GET", label).text()
    assert opened.marker in adapter.request(other, "GET", label).text()  # the flaw
    assert adapter.request(visitor, "GET", label).status == 401
    assert adapter.request(owner, "GET", record).status == 200
    assert adapter.request(other, "GET", record).status == 404  # the protected control
    # Nothing crossed between the jars, and the visitor never got a cookie.
    assert owner.cookies != other.cookies and visitor.cookies == {}
    assert set(owner.cookies) == {opened.origin}
    egress.close()


def test_the_defended_variant_denies_the_other_account(tmp_path: Path) -> None:
    with launch("defended", Settings(data_dir=tmp_path / "data"), port=0) as fixture:
        egress = fixture_egress(fixture)
        adapter = HttpAdapter(egress)
        owner, other = sign_in(adapter, fixture, "dilnoza"), sign_in(adapter, fixture, "rustam")
        label = parse_url(fixture.origin + "/api/parcels/4117/label")
        assert fixture.marker in adapter.request(owner, "GET", label).text()
        denied = adapter.request(other, "GET", label)
        assert denied.status == 404 and fixture.marker not in denied.text()
        assert denied.headers.get("x-frame-options") == "DENY"
        egress.close()
    # The secrets existed only for the life of the fixture.
    assert not fixture.secrets.has("chorsu-dilnoza")


def test_a_plain_fetch_sees_links_but_not_the_forms_that_javascript_draws(opened: Fixture) -> None:
    egress = fixture_egress(opened)
    adapter = HttpAdapter(egress)
    session = HttpSession(None)
    expected = frozenset(opened.scope().public_values)
    home, _ = adapter.observe(
        session, parse_url(opened.origin + "/"), redactor=REDACTOR, expected_personal=expected
    )
    page = home.observation
    assert (page.via, page.status, page.title) == ("http", 200, "Welcome · Chorsu Parcel Lockers")
    assert {link.path for link in page.links} >= {"/signin", "/join", "/parcels", "/help"}
    assert all(link.in_scope for link in page.links) and page.forms == []
    assert home.links[page.links[0].ref].origin == opened.origin
    signin, _ = adapter.observe(
        session, parse_url(opened.origin + "/signin"), redactor=REDACTOR, expected_personal=expected
    )
    assert signin.observation.forms == []  # the shell is empty until a browser runs the script
    help_page, _ = adapter.observe(
        session, parse_url(opened.origin + "/help"), redactor=REDACTOR, expected_personal=expected
    )
    outside = [link for link in help_page.observation.links if not link.in_scope]
    assert [link.path for link in outside] == ["https://maps.chorsu-partner.example/lockers"]
    assert (
        outside[0].ref not in help_page.links
    )  # an off-scope link cannot be followed by reference
    egress.close()


def test_the_declared_support_address_is_public_but_any_other_address_stops_the_page(
    opened: Fixture,
) -> None:
    egress = fixture_egress(opened)
    adapter = HttpAdapter(egress)
    with pytest.raises(PrivacyStop) as stop:
        adapter.observe(
            HttpSession(None),
            parse_url(opened.origin + "/help"),
            redactor=REDACTOR,
            expected_personal=frozenset(),
        )
    assert stop.value.kinds == ["email address"] and "chorsu" not in str(stop.value)
    assert personal_data("Call +998 90 123 45 67 or pay with 4111 1111 1111 1111", frozenset()) == [
        "phone number",
        "payment card number",
    ]
    assert personal_data("Order 2026-10-12, total 1 250 000 sum, id 4117", frozenset()) == []
    assert personal_data("a@b.test", frozenset({"A@B.test"})) == []
    egress.close()


# --- redirects, credentials and uncertain writes ---------------------------------------------


@pytest.fixture
def site() -> Iterator[Site]:
    server = Site()
    yield server
    server.close()


def test_redirects_are_followed_one_checked_hop_at_a_time(site: Site) -> None:
    canary = Canary()
    site.routes.update(
        {
            "/start": (302, {"Location": "/middle"}, b""),
            "/middle": (303, {"Location": "/end"}, b""),
            "/end": (200, {"Content-Type": "text/plain"}, b"arrived"),
            "/away": (302, {"Location": f"http://127.0.0.1:{canary.port}/stolen"}, b""),
            "/away-by-name": (302, {"Location": "//evil.example/x"}, b""),
            "/loop": (302, {"Location": "/loop"}, b""),
        }
    )
    egress = owned(site)
    adapter = HttpAdapter(egress)
    result = adapter.request(HttpSession(None), "GET", parse_url(site.origin + "/start"))
    assert (result.status, result.body, result.hops) == (
        200,
        b"arrived",
        ("/start", "/middle", "/end"),
    )
    for path in ("/away", "/away-by-name", "/loop"):
        with pytest.raises(EgressRefused) as refused:
            adapter.request(HttpSession(None), "GET", parse_url(site.origin + path))
        assert refused.value.kind == "redirect"
    assert canary.connections == 0
    assert any("outside the approved scope" in row.reason for row in egress.blocked)
    canary.close()
    egress.close()


def test_a_write_is_sent_once_and_never_repeated_by_a_redirect_or_after_a_lost_answer(
    site: Site,
) -> None:
    site.routes.update(
        {
            "/create": (303, {"Location": "/done"}, b""),
            "/done": (200, {}, b"created"),
            "/repeat": (307, {"Location": "/create"}, b""),
            "/lost": (0, {}, b""),
        }
    )
    from dataclasses import replace

    original = owned(site)
    egress = Egress(
        replace(
            original.policy,
            approved_actions=(ActionPermission("test-submit", "submit_form", "dilnoza"),),
        ),
        original.budget,
    )
    original.close()
    adapter = HttpAdapter(egress)
    session = HttpSession("dilnoza")

    def submit(path: str):  # noqa: ANN202 - test helper
        url = parse_url(site.origin + path)
        with (
            egress.action("test-submit", "dilnoza"),
            egress.form_grant(
                "dilnoza",
                "POST",
                url,
                {"a": "b"},
            ),
        ):
            return adapter.request(session, "POST", url, form={"a": "b"})

    created = submit("/create")
    assert created.body == b"created" and [hit.method for hit in site.hits] == ["POST", "GET"]
    with pytest.raises(EgressRefused, match="not repeated"):
        submit("/repeat")
    assert [hit.path for hit in site.hits].count("/create") == 1
    before = len(site.hits)
    with pytest.raises(UncertainWrite):
        submit("/lost")
    assert len(site.hits) == before + 1  # the one attempt; no automatic second try
    egress.close()


def test_cookies_stay_with_their_origin_account_and_path_and_never_reach_evidence(
    site: Site,
) -> None:
    site.routes.update(
        {
            "/login": (
                200,
                {"Set-Cookie": "sid=tok-9f8e7d6c5b4a; Path=/; HttpOnly; Domain=evil.example"},
                b"ok",
            ),
            "/echo": lambda hit: (
                200,
                {"Content-Type": "text/html"},
                f"<p>your cookie is {hit.headers.get('cookie', 'none')}</p>".encode(),
            ),
            "/logout": (200, {"Set-Cookie": "sid=; Max-Age=0; Path=/"}, b"bye"),
        }
    )
    egress = owned(site)
    adapter = HttpAdapter(egress)
    alice, bob = HttpSession("alice"), HttpSession("bob")
    adapter.request(alice, "GET", parse_url(site.origin + "/login"))
    assert adapter.request(alice, "GET", parse_url(site.origin + "/echo")).text() == (
        "<p>your cookie is sid=tok-9f8e7d6c5b4a</p>"
    )
    assert "none" in adapter.request(bob, "GET", parse_url(site.origin + "/echo")).text()
    # The same jar offers nothing to another origin, whatever Domain the cookie claimed.
    assert alice.header(parse_url("https://evil.example/")) is None
    assert alice.header(parse_url(f"http://127.0.0.1:{site.port + 1}/")) is None
    bound, _ = adapter.observe(
        alice, parse_url(site.origin + "/echo"), redactor=REDACTOR, expected_personal=frozenset()
    )
    assert "tok-9f8e7d6c5b4a" not in bound.observation.model_dump_json()
    assert "[REDACTED]" in bound.observation.text
    adapter.request(alice, "GET", parse_url(site.origin + "/logout"))
    assert alice.header(parse_url(site.origin + "/echo")) is None
    egress.close()


def test_a_used_up_budget_stops_the_adapter_without_losing_what_was_read(site: Site) -> None:
    site.routes["/page"] = (200, {"Content-Type": "text/html"}, b"<title>One</title>")
    egress = owned(site, budget=budget(requests=1))
    adapter = HttpAdapter(egress)
    first = adapter.request(HttpSession(None), "GET", parse_url(site.origin + "/page"))
    with pytest.raises(EgressStopped):
        adapter.request(HttpSession(None), "GET", parse_url(site.origin + "/page"))
    assert first.body == b"<title>One</title>" and len(egress.records) == 1
    egress.close()


def test_static_html_is_read_as_structure_and_scripts_are_never_read_for_meaning() -> None:
    page = read_html(
        """<html><head><title>Join us</title><script>var secretPlan = "/admin";</script></head>
        <body><h1>Create account</h1>
        <form action="/join" method="post" aria-label="Create account">
          <label for="u">Username</label><input id="u" name="username" required>
          <label>Password <input name="password" type="password"></label>
          <input name="code" autocomplete="one-time-code">
          <input type="hidden" name="csrf" value="abc123">
          <button type="submit">Create account</button>
        </form>
        <a href="/help#top">Help</a><a href="javascript:void(0)">Menu</a>
        <iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>
        <style>.x{}</style></body></html>"""
    )
    assert (page.title, page.headings) == ("Join us", ["Create account"])
    assert "secretPlan" not in page.text and "/admin" not in page.text
    (form,) = page.forms
    assert (form["action"], form["method"], form["submit"]) == ("/join", "post", "Create account")
    assert [(item["name"], item["type"], item["label"]) for item in form["fields"]] == [
        ("username", "text", "Username"),
        ("password", "password", "Password"),
        ("code", "text", ""),
        ("csrf", "hidden", ""),
    ]
    assert form["fields"][3]["has_value"] is True and "abc123" not in str(form)
    assert page.frames == ["https://www.google.com/recaptcha/api2/anchor"]
