"""A browser-like test client for the guarded API."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

PORT = 8700
ORIGIN = f"http://127.0.0.1:{PORT}"


def visitor(app: FastAPI) -> TestClient:
    """A client addressing the app by its own loopback address, without a session."""
    return TestClient(app, base_url=ORIGIN, follow_redirects=False)


def signed_in(app: FastAPI) -> TestClient:
    """A client that opened the one-time link, as the person at the terminal would."""
    client = visitor(app)
    link = app.state.gate.bootstrap_url
    assert link is not None, "the bootstrap link was already used"
    assert client.get(link.removeprefix(ORIGIN)).status_code == 303
    return client
