"""Protected chat API: session and origin checks, bounded input, no echo of refused input."""

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import chat
from backend.app import create_app
from backend.settings import Settings

from .support import ORIGIN, PORT, signed_in, visitor
from .test_chat import Model, model, text  # noqa: F401 - the fixture is used by name


@pytest.fixture
def connected(
    tmp_path: Path,
    model: Model,  # noqa: F811
) -> tuple[FastAPI, TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "private"), port=PORT)
    client = signed_in(app)
    client.headers["origin"] = ORIGIN
    return app, client


def wait(client: TestClient, identifier: str) -> dict:
    for _ in range(200):
        view = client.get(f"/api/chats/{identifier}").json()
        if view["state"] != "running":
            return view
        time.sleep(0.02)
    raise AssertionError("the chat did not finish")


def test_a_chat_starts_with_no_target_and_answers_a_general_question(
    connected: tuple[FastAPI, TestClient],
    model: Model,  # noqa: F811
) -> None:
    _, client = connected
    created = client.post("/api/chats", json={})
    assert created.status_code == 200
    view = created.json()
    assert (view["target_kind"], view["target_id"], view["turns"]) == (None, None, [])
    assert "320 tokens" in view["limits"]
    model.intents, model.texts = ["general_question"], [text("It injects SQL text.")]
    started = client.post(
        f"/api/chats/{view['chat_id']}/ask", json={"prompt": "What is SQL injection?"}
    )
    assert started.status_code == 202 and started.json()["state"] == "running"
    done = wait(client, view["chat_id"])
    (turn,) = done["turns"]
    assert turn["intent"] == "general_question" and turn["parts"][0]["kind"] == "general"
    assert turn["authorization_granted"] is False and turn["actions_executed"] is False
    assert client.get("/api/chats/saved-results").json() == {"results": []}


def test_every_chat_route_needs_the_session_the_origin_and_the_host(
    connected: tuple[FastAPI, TestClient],
) -> None:
    app, client = connected
    identifier = client.post("/api/chats", json={}).json()["chat_id"]
    guest = visitor(app)
    for method, path, body in (
        ("POST", "/api/chats", {}),
        ("GET", "/api/chats/saved-results", None),
        ("GET", f"/api/chats/{identifier}", None),
        ("POST", f"/api/chats/{identifier}/ask", {"prompt": "Hello"}),
        ("POST", f"/api/chats/{identifier}/select", {}),
        ("POST", f"/api/chats/{identifier}/cancel", None),
    ):
        assert guest.request(method, path, headers={"origin": ORIGIN}, json=body).status_code == 401
        assert (
            client.request(
                method, path, headers={"origin": "https://external.invalid"}, json=body
            ).status_code
            == 403
        )
        assert (
            client.request(method, path, headers={"host": "localhost:8700"}, json=body).status_code
            == 421
        )


def test_refused_input_is_bounded_and_never_echoed(
    connected: tuple[FastAPI, TestClient],
) -> None:
    _, client = connected
    identifier = client.post("/api/chats", json={}).json()["chat_id"]
    secret = "sk-" + "a" * 30
    refused = client.post(f"/api/chats/{identifier}/ask", json={"prompt": f"my key is {secret}"})
    assert refused.status_code == 409 and secret not in refused.text
    invalid = client.post(f"/api/chats/{identifier}/ask", json={"prompt": "x", "junk": secret})
    assert invalid.status_code == 422 and secret not in invalid.text
    assert client.post("/api/chats", json={"target_kind": "review"}).status_code == 422
    assert client.get("/api/chats/chat-nope").status_code == 409
    assert client.get("/api/chats/..%2F..%2Fsecrets").status_code in {404, 409}
    huge = client.post(f"/api/chats/{identifier}/ask", content=b"x" * (3 * 1024**2 + 10))
    assert huge.status_code == 413
    assert client.get(f"/api/chats/{identifier}").json()["turns"] == []
    assert chat.MAX_TURNS == 40
