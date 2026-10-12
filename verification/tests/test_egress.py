"""The egress broker: what may leave, where it really goes, and what is counted.

Loopback servers only. The external-mode tests use the explicit resolver and
connector seam from ``web_support``; no request leaves this computer.
"""

import socket
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.contracts.web import WebTarget
from backend.web_urls import parse_url
from verification.egress import (
    Egress,
    EgressPolicy,
    EgressRefused,
    EgressStopped,
    public_address,
    tls_context,
)

from .web_support import PUBLIC, Canary, Site, budget, carried, owned, soon, tls_for


@pytest.fixture
def site() -> Iterator[Site]:
    server = Site(
        {
            "/app/hello": (200, {"Content-Type": "text/plain"}, b"hello"),
            "/app/big": (200, {}, b"x" * 50_000),
            "/other": (200, {}, b"outside the approved paths"),
        }
    )
    yield server
    server.close()


@pytest.fixture
def canary() -> Iterator[Canary]:
    listener = Canary()
    yield listener
    listener.close()


def get(egress: Egress, address: str, headers: list[tuple[str, str]] | None = None) -> bytes:
    return egress.send("GET", parse_url(address), headers or []).read(1_000_000)


# --- owned mode ----------------------------------------------------------------------------


def test_an_in_scope_request_is_sent_recorded_and_counted(site: Site) -> None:
    egress = owned(site, ["/app"])
    assert get(egress, site.origin + "/app/hello?token=abc&page=2") == b"hello"
    (record,) = egress.records
    assert (record.method, record.path, record.status, record.body_bytes) == (
        "GET",
        "/app/hello",
        200,
        5,
    )
    # Query values are never kept, only their names.
    assert record.query_keys == ("token", "page") and record.peer == "127.0.0.1"
    assert egress.budget.requests == 1 and egress.budget.bytes > 5
    assert site.hits[0].headers["host"] == f"127.0.0.1:{site.port}"
    egress.close()


def test_other_paths_ports_hosts_and_schemes_are_refused_and_stay_visible(
    site: Site, canary: Canary
) -> None:
    egress = owned(site, ["/app"])
    for address in (
        site.origin + "/other",
        site.origin + "/apple",
        f"http://127.0.0.1:{canary.port}/app/hello",
        f"http://localhost:{site.port}/app/hello",
        f"https://127.0.0.1:{site.port}/app/hello",
        "https://shop.example.com/app/hello",
    ):
        with pytest.raises(EgressRefused) as refused:
            get(egress, address)
        assert refused.value.kind == "off_scope"
    assert site.hits == [] and canary.connections == 0 and egress.budget.requests == 0
    assert sum(row.count for row in egress.blocked) == 6
    assert {row.kind for row in egress.blocked} == {"off_scope"}
    egress.close()


def test_environment_proxies_are_ignored(
    site: Site, canary: Canary, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{canary.port}")
    egress = owned(site)
    assert get(egress, site.origin + "/app/hello") == b"hello"
    assert canary.connections == 0
    egress.close()


def test_expiry_cancel_and_each_budget_stop_further_requests(site: Site) -> None:
    stopped = [False]
    egress = owned(site, cancel=lambda: stopped[0])
    get(egress, site.origin + "/app/hello")
    stopped[0] = True
    with pytest.raises(EgressStopped, match="stopped"):
        get(egress, site.origin + "/app/hello")
    egress.close()

    expired = owned(site, now=lambda: datetime.now(UTC) + timedelta(hours=1))
    with pytest.raises(EgressStopped, match="expired"):
        get(expired, site.origin + "/app/hello")
    expired.close()

    two = owned(site, budget=budget(requests=2))
    get(two, site.origin + "/app/hello")
    get(two, site.origin + "/app/hello")
    with pytest.raises(EgressStopped, match="request budget"):
        get(two, site.origin + "/app/hello")
    two.close()

    small = owned(site, budget=budget(size=10_000))
    with pytest.raises(EgressStopped, match="data budget"):
        get(small, site.origin + "/app/big")
    assert any(row.kind == "budget" for row in small.blocked)
    small.close()

    late = owned(site, budget=budget(seconds=-1))
    with pytest.raises(EgressStopped, match="time budget"):
        get(late, site.origin + "/app/hello")
    late.close()
    assert len(site.hits) == 4  # one, two and the start of the big one; nothing after a stop


def test_framing_and_hop_headers_cannot_be_supplied_by_a_caller(site: Site) -> None:
    egress = owned(site)
    for header in ("Host", "Connection", "Transfer-Encoding", "Content-Length", "Upgrade"):
        with pytest.raises(EgressRefused):
            get(egress, site.origin + "/app/hello", [(header, "x")])
    with pytest.raises(EgressRefused):
        egress.send("TRACE", parse_url(site.origin + "/app/hello"), [])
    assert site.hits == []
    egress.close()


def test_redirect_destinations_are_checked_by_hand_before_any_next_hop(
    site: Site, canary: Canary
) -> None:
    egress = owned(site, ["/app"])
    current = parse_url(site.origin + "/app/start")
    assert egress.redirect_target(current, "/app/next?x=1").url == site.origin + "/app/next?x=1"
    assert egress.redirect_target(current, "next").path == "/app/next"
    for location in (
        None,
        "",
        f"http://127.0.0.1:{canary.port}/app/next",
        "//evil.example/app/next",
        "https://evil.example/",
        "/other",
        "/app/../other",
        "http://127.1/app",
        "javascript:alert(1)",
        "\\\\evil.example\\share",
    ):
        with pytest.raises(EgressRefused) as refused:
            egress.redirect_target(current, location)
        assert refused.value.kind == "redirect"
    assert canary.connections == 0 and site.hits == []
    egress.close()


def test_owned_policy_admits_only_the_started_fixtures_loopback_origin(site: Site) -> None:
    def policy(origin: str, port: int | None) -> EgressPolicy:
        return EgressPolicy(
            mode="owned_fixture",
            targets=(WebTarget(origin=origin, paths=["/"]),),
            expires_at=soon(),
            owned_port=port,
        )

    for origin, port in (
        (site.origin, None),
        (site.origin, site.port + 1),
        (f"http://localhost:{site.port}", site.port),
        (f"https://127.0.0.1:{site.port}", site.port),
        (f"http://127.0.0.2:{site.port}", site.port),
        ("https://shop.example.com", site.port),
    ):
        with pytest.raises(ValueError, match="owned mode"):
            policy(origin, port)


# --- external mode, through the explicit test seam -------------------------------------------


def external(
    port: int,
    *,
    answers: list[str] | None = None,
    authority: str | None = None,
    report: str | None = None,
    host: str = "shop.test",
) -> tuple[Egress, list[tuple[str, int]]]:
    asked: list[tuple[str, int]] = []

    def resolver(name: str, number: int) -> list[str]:
        asked.append((name, number))
        return list(answers if answers is not None else [PUBLIC])

    policy = EgressPolicy(
        mode="external",
        targets=(WebTarget(origin=f"https://{host}", paths=["/"]),),
        expires_at=soon(),
    )
    egress = Egress(
        policy,
        budget(),
        resolver=resolver,
        connect=carried(port, report=report),
        context=tls_context(authority),
    )
    return egress, asked


@pytest.fixture
def secure(tmp_path: Path) -> Iterator[tuple[Site, str]]:
    material = tls_for("shop.test", tmp_path)
    server = Site({"/": (200, {}, b"secure hello")}, context=material.server)
    yield server, material.authority_pem
    server.close()


def test_a_public_name_is_resolved_validated_pinned_and_verified(secure: tuple[Site, str]) -> None:
    server, authority = secure
    answers = [PUBLIC]
    egress, asked = external(server.port, answers=answers, authority=authority)
    assert get(egress, "https://shop.test/") == b"secure hello"
    assert egress.records[0].peer == PUBLIC and asked == [("shop.test", 443)]
    # A later answer that points inward is never consulted: the first one is pinned.
    answers[:] = ["10.0.0.5"]
    assert get(egress, "https://shop.test/") == b"secure hello"
    assert asked == [("shop.test", 443)]
    egress.close()


@pytest.mark.parametrize(
    "answers",
    [
        ["127.0.0.1"],
        ["10.1.2.3"],
        ["192.168.1.10"],
        ["169.254.169.254"],
        ["::1"],
        ["fd00:ec2::254"],
        ["::ffff:127.0.0.1"],
        [PUBLIC, "172.16.0.9"],  # one inward answer among public ones
        [],
    ],
)
def test_a_name_that_resolves_inward_is_refused_before_any_connection(
    secure: tuple[Site, str], answers: list[str]
) -> None:
    server, authority = secure
    egress, _ = external(server.port, answers=answers, authority=authority)
    with pytest.raises(EgressRefused) as refused:
        get(egress, "https://shop.test/")
    assert refused.value.kind == "address" and server.hits == []
    assert egress.blocked[0].kind == "address"
    egress.close()


def test_a_connection_that_lands_somewhere_else_is_dropped_before_any_http_byte(
    secure: tuple[Site, str],
) -> None:
    server, authority = secure
    egress, _ = external(server.port, authority=authority, report="203.0.113.77")
    with pytest.raises(EgressRefused, match="not the validated address"):
        get(egress, "https://shop.test/")
    assert server.hits == []
    egress.close()


def test_the_certificate_must_be_valid_for_the_requested_name(
    secure: tuple[Site, str], tmp_path: Path
) -> None:
    server, authority = secure
    # Untrusted issuer: the default trust store does not know the test authority.
    untrusted, _ = external(server.port)
    with pytest.raises(EgressRefused):
        get(untrusted, "https://shop.test/")
    untrusted.close()
    # Right issuer, wrong name: the server's certificate is for shop.test only.
    wrong, _ = external(server.port, authority=authority, host="bank.test")
    with pytest.raises(EgressRefused):
        get(wrong, "https://bank.test/")
    wrong.close()
    assert server.hits == []
    context = tls_context()
    assert context.check_hostname is True and context.verify_mode.name == "CERT_REQUIRED"


def test_external_policy_refuses_plain_http_inward_literals_and_an_owned_port() -> None:
    def policy(origin: str, port: int | None = None) -> EgressPolicy:
        return EgressPolicy(
            mode="external",
            targets=(WebTarget(origin=origin, paths=["/"]),),
            expires_at=soon(),
            owned_port=port,
        )

    for origin in (
        "http://shop.example.com",
        "https://127.0.0.1",
        "https://10.0.0.8",
        "https://[::1]",
    ):
        with pytest.raises(ValueError, match="external mode"):
            policy(origin)
    with pytest.raises(ValueError, match="external mode"):
        policy("https://shop.example.com", 8711)
    assert policy("https://shop.example.com").mode == "external"


@pytest.mark.parametrize(
    ("address", "allowed"),
    [
        ("8.8.8.8", True),
        ("2606:4700:4700::1111", True),
        ("127.0.0.1", False),
        ("127.255.255.254", False),
        ("10.0.0.1", False),
        ("172.31.255.255", False),
        ("192.168.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),  # noqa: S104 - an address under test, not a bind
        ("224.0.0.1", False),
        ("240.0.0.1", False),
        ("192.0.2.1", False),
        ("::", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
        ("::ffff:8.8.8.8", False),
        ("::ffff:10.0.0.1", False),
        ("64:ff9b::7f00:1", False),
        ("2002:7f00:1::", False),
        ("2001:db8::1", False),
        ("not-an-address", False),
    ],
)
def test_only_public_addresses_pass_in_external_mode(address: str, allowed: bool) -> None:
    assert (public_address(address) is None) is allowed


def test_the_system_resolver_and_connector_are_the_defaults_and_use_literal_addresses(
    site: Site,
) -> None:
    from verification.egress import system_resolver, tcp_connect

    assert system_resolver("127.0.0.1", site.port) == ["127.0.0.1"]
    sock = tcp_connect("127.0.0.1", site.port, 2.0)
    assert sock.getpeername() == ("127.0.0.1", site.port)
    sock.close()
    with pytest.raises(OSError):
        tcp_connect("not-a-literal.invalid", 80, 0.2)
    with pytest.raises(EgressRefused):
        system_resolver("definitely-missing.invalid", 443)
    closed = socket.socket()
    closed.close()
    assert time.monotonic() > 0
