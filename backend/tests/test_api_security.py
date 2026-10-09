import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import create_app
from backend.security import (
    BOOTSTRAP_PATH,
    CONTENT_SECURITY_POLICY,
    COOKIE,
    INTERNAL_ERROR,
    NO_SESSION,
    SECURITY_HEADERS,
    USED_LINK,
    Gate,
)
from backend.serve import bind, server
from backend.settings import Settings

from .support import ORIGIN, PORT, signed_in, visitor

MAP = f"/api/snapshots/{'0' * 64}/map"


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return create_app(Settings(data_dir=tmp_path), port=PORT)


def token(app: FastAPI) -> str:
    return app.state.gate.bootstrap_url.split("token=")[1]


def session(client: TestClient) -> str:
    value = client.cookies.get(COOKIE)
    assert value
    return value


# --- the bootstrap link --------------------------------------------------------------------


def test_the_link_is_exchanged_for_a_session_cookie_and_left_behind(app: FastAPI) -> None:
    secret = token(app)
    client = visitor(app)
    response = client.get(f"{BOOTSTRAP_PATH}?token={secret}")
    assert (response.status_code, response.headers["location"]) == (303, "/")
    cookie = response.headers["set-cookie"]
    value = session(client)
    assert cookie.startswith(f"{COOKIE}={value};")
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "samesite=strict", "path=/"} <= attributes
    # The session token is new, and neither token travels on in the redirect or the body.
    assert value != secret and len(value) >= 43
    assert secret not in response.headers["location"] and value not in response.text
    assert app.state.gate.bootstrap_url is None
    assert client.get(MAP).status_code == 404  # signed in: the route answers


def test_the_link_works_once(app: FastAPI) -> None:
    secret = token(app)
    signed_in(app)
    late = visitor(app).get(f"{BOOTSTRAP_PATH}?token={secret}")
    assert (late.status_code, late.text) == (403, USED_LINK)
    assert "set-cookie" not in late.headers


@pytest.mark.parametrize("query", ["", "?token=", "?token=guess", "?other=1"])
def test_a_wrong_or_missing_token_opens_nothing(app: FastAPI, query: str) -> None:
    response = visitor(app).get(f"{BOOTSTRAP_PATH}{query}")
    assert (response.status_code, response.text) == (403, USED_LINK)
    assert "set-cookie" not in response.headers
    # A failed attempt does not use the link up.
    assert signed_in(app).get(MAP).status_code == 404


def test_reopening_the_link_with_a_session_just_goes_home(app: FastAPI) -> None:
    secret = token(app)
    client = signed_in(app)
    again = client.get(f"{BOOTSTRAP_PATH}?token={secret}")
    assert (again.status_code, again.headers["location"]) == (303, "/")
    assert "set-cookie" not in again.headers


def test_each_launch_has_its_own_tokens(tmp_path: Path) -> None:
    first, second = (create_app(Settings(data_dir=tmp_path), port=PORT) for _ in range(2))
    assert token(first) != token(second)
    old = signed_in(first)
    # A cookie from an earlier launch is not a session of this one.
    stale = visitor(second)
    stale.cookies.set(COOKIE, session(old))
    assert stale.get(MAP).status_code == 401


def test_the_link_cannot_be_posted(app: FastAPI) -> None:
    client = visitor(app)
    response = client.post(f"{BOOTSTRAP_PATH}?token={token(app)}", headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert app.state.gate.bootstrap_url is not None


# --- missing sessions ----------------------------------------------------------------------


@pytest.mark.parametrize("path", [MAP, "/openapi.json", "/", "/findings", "/api/unknown"])
def test_nothing_is_served_without_a_session(app: FastAPI, path: str) -> None:
    response = visitor(app).get(path)
    assert response.status_code == 401
    if path.startswith("/api/"):
        assert response.json() == {"detail": NO_SESSION}
    else:
        assert response.text == NO_SESSION
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("cookie", ["", "guess", "0" * 43, f"{COOKIE}=x", "true"])
def test_a_wrong_session_cookie_is_refused(app: FastAPI, cookie: str) -> None:
    signed_in(app)
    client = visitor(app)
    client.cookies.set(COOKIE, cookie)
    assert client.get(MAP).status_code == 401


def test_a_planted_cookie_of_the_same_name_does_not_lock_the_user_out(app: FastAPI) -> None:
    value = session(signed_in(app))
    client = visitor(app)
    # Wherever the planted cookie lands in the header, the real one still counts.
    for sent in (
        f"{COOKIE}=planted; {COOKIE}={value}; theme=night",
        f"theme=night; {COOKIE}={value}; {COOKIE}=planted",
    ):
        assert client.get(MAP, headers={"Cookie": sent}).status_code == 404
    planted = client.get(MAP, headers={"Cookie": f"{COOKIE}=planted; other={value}"})
    assert planted.status_code == 401


def test_a_session_does_not_exist_before_the_link_is_used() -> None:
    gate = Gate(PORT)
    assert not gate.has_session(f"{COOKIE}=")
    assert not gate.has_session(f"{COOKIE}=None")
    assert not gate.has_session(None)
    assert gate.exchange("") is None and gate.exchange("guess") is None


# --- bad Host ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        f"evil.example:{PORT}",
        f"127.0.0.1.evil.example:{PORT}",
        "127.0.0.1",
        "127.0.0.1:8701",
        f"localhost:{PORT}",
        f"[::1]:{PORT}",
        f"0.0.0.0:{PORT}",
        f"127.0.0.1:{PORT}.",
        f" 127.0.0.1:{PORT}",
        "",
    ],
)
def test_a_request_under_another_host_name_is_refused(app: FastAPI, host: str) -> None:
    client = signed_in(app)
    for path in (MAP, f"{BOOTSTRAP_PATH}?token=x", "/"):
        response = client.get(path, headers={"Host": host})
        assert (response.status_code, response.text) == (421, "This address is not Plumb's.")


def test_two_host_headers_are_refused(app: FastAPI) -> None:
    client = signed_in(app)
    own = f"127.0.0.1:{PORT}"
    response = client.get(MAP, headers=[("Host", own), ("Host", "evil.example")])
    assert response.status_code == 421


def test_a_bad_host_does_not_use_up_the_link(app: FastAPI) -> None:
    link = f"{BOOTSTRAP_PATH}?token={token(app)}"
    assert visitor(app).get(link, headers={"Host": "evil.example"}).status_code == 421
    assert app.state.gate.bootstrap_url is not None


def test_the_gate_needs_a_real_port() -> None:
    for port in (0, -1, 65536):
        with pytest.raises(ValueError, match="bound to"):
            Gate(port)


# --- cross-origin requests -----------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "http://127.0.0.1:8702",  # another server on this machine, such as the lab
        f"https://127.0.0.1:{PORT}",
        f"http://localhost:{PORT}",
        f"http://127.0.0.1:{PORT}.evil.example",
        "null",
        "",
    ],
)
def test_a_request_from_another_origin_is_refused_even_with_a_session(
    app: FastAPI, origin: str
) -> None:
    client = signed_in(app)
    for method in ("GET", "POST", "DELETE", "OPTIONS"):
        response = client.request(method, MAP, headers={"Origin": origin})
        assert (response.status_code, response.text) == (403, "Plumb answers only its own pages.")
        assert not [name for name in response.headers if name.startswith("access-control-")]


@pytest.mark.parametrize("site", ["cross-site", "same-site", "weird"])
def test_a_request_the_browser_marks_as_foreign_is_refused(app: FastAPI, site: str) -> None:
    client = signed_in(app)
    assert client.get(MAP, headers={"Sec-Fetch-Site": site}).status_code == 403
    assert client.get(MAP, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 404


def test_a_foreign_page_cannot_use_up_or_use_the_link(app: FastAPI) -> None:
    link = f"{BOOTSTRAP_PATH}?token={token(app)}"
    client = visitor(app)
    assert client.get(link, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get(link, headers={"Origin": "http://evil.example"}).status_code == 403
    assert COOKIE not in client.cookies
    # The person at the terminal opens it from the address bar.
    assert client.get(link, headers={"Sec-Fetch-Site": "none"}).status_code == 303


def test_a_write_must_say_where_it_comes_from(app: FastAPI) -> None:
    client = signed_in(app)
    assert client.post(MAP).status_code == 403
    assert client.post(MAP, headers={"Sec-Fetch-Site": "none", "Origin": ORIGIN}).status_code == 403
    # From Plumb's own page the write reaches the router, which has no such route.
    assert client.post(MAP, headers={"Origin": ORIGIN}).status_code == 405
    own_page = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
    assert client.post(MAP, headers=own_page).status_code == 405


# --- response headers ----------------------------------------------------------------------


def test_the_content_security_policy_allows_only_own_files() -> None:
    parts = (part.partition(" ") for part in CONTENT_SECURITY_POLICY.split("; "))
    directives = {name: value for name, _, value in parts}
    assert directives["default-src"] == "'none'"
    assert directives["script-src"] == directives["style-src"] == "'self'"
    assert directives["frame-ancestors"] == directives["base-uri"] == "'none'"
    for banned in ("unsafe-inline", "unsafe-eval", "*", "http:", "https:"):
        assert banned not in CONTENT_SECURITY_POLICY


def test_every_answer_carries_the_security_headers(app: FastAPI) -> None:
    link = f"{BOOTSTRAP_PATH}?token={token(app)}"
    anonymous = visitor(app)
    responses = [
        anonymous.get(MAP),  # 401
        anonymous.get(MAP, headers={"Host": "evil.example"}),  # 421
        anonymous.get(MAP, headers={"Origin": "http://evil.example"}),  # 403
        anonymous.get(f"{BOOTSTRAP_PATH}?token=guess"),  # 403
        anonymous.get(link),  # 303
        anonymous.get(MAP),  # 404, signed in now
        anonymous.get("/api/snapshots/abc/map"),  # 422
        anonymous.get("/openapi.json"),  # 200
    ]
    assert [r.status_code for r in responses] == [401, 421, 403, 403, 303, 404, 422, 200]
    for response in responses:
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value, (response.status_code, name)
        assert response.headers["cache-control"] == "no-store"
        assert "access-control-allow-origin" not in response.headers


def test_a_failing_handler_answers_with_the_headers_and_no_details(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    @app.get("/api/broken")
    def broken() -> None:
        raise RuntimeError("secret detail at D:/plumb-data")

    link = app.state.gate.bootstrap_url
    client = signed_in(app)
    response = client.get("/api/broken")
    assert (response.status_code, response.text) == (500, INTERNAL_ERROR)
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    # The failure is logged for the person at the terminal, without the request or its tokens.
    assert "a request handler failed" in caplog.text and "secret detail" in caplog.text
    assert link.split("token=")[1] not in caplog.text and session(client) not in caplog.text


def test_no_websocket_is_accepted(app: FastAPI) -> None:
    client = signed_in(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/events"):
        pytest.fail("the socket must not open")


# --- tokens stay out of logs, and the server binds loopback --------------------------------


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[httpx.Client, FastAPI, int]]:
    """The real server on a system-chosen loopback port, as ``python -m backend.serve`` runs it."""
    listener = bind(0)
    address, port = listener.getsockname()
    assert address == "127.0.0.1"
    live, app = server(listener, Settings(data_dir=tmp_path))
    assert live.config.access_log is False
    thread = threading.Thread(target=live.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not live.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert live.started
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5.0) as client:
        yield client, app, port
    live.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_the_running_server_is_guarded_and_logs_no_token(
    running: tuple[httpx.Client, FastAPI, int],
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    client, app, port = running
    caplog.set_level(logging.DEBUG)
    link = app.state.gate.bootstrap_url
    secret = link.split("token=")[1]
    assert link.startswith(f"http://127.0.0.1:{port}{BOOTSTRAP_PATH}?token=")
    assert client.get(MAP).status_code == 401
    assert client.get(MAP, headers={"Host": f"evil.example:{port}"}).status_code == 421
    assert client.get(MAP, headers={"Origin": "http://evil.example"}).status_code == 403
    opened = client.get(link)
    assert opened.status_code == 303
    answer = client.get(MAP)
    assert answer.status_code == 404
    assert "server" not in answer.headers
    assert answer.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    value = client.cookies.get(COOKIE)
    assert value
    printed = capfd.readouterr()
    # This test's own HTTP client logs the URLs it calls; only the server's side counts.
    logged = " | ".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith(("httpx", "httpcore"))
    )
    for text in (logged, printed.out, printed.err):
        assert secret not in text and value not in text
        assert "/bootstrap" not in text


def test_the_server_refuses_a_socket_that_is_not_loopback() -> None:
    class Elsewhere:
        def getsockname(self) -> tuple[str, int]:
            return ("0.0.0.0", 8700)  # noqa: S104 - the address that must be refused

    with pytest.raises(ValueError, match="loopback only"):
        server(Elsewhere())  # ty: ignore[invalid-argument-type]


def test_the_listening_socket_is_loopback_and_exclusive() -> None:
    listener = bind(0)
    try:
        address, port = listener.getsockname()
        assert address == "127.0.0.1" and port > 0
        with pytest.raises(OSError):
            bind(port)
    finally:
        listener.close()
