"""Protected conversation API/lifecycle boundaries using synthetic evidence and no model."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agent.llm import JsonAnswer, ModelRequest, Spend
from backend import conversation
from backend.app import create_app
from backend.assessment import AssessmentStore
from backend.assessment_security import MAX_REQUEST_BYTES
from backend.contracts.conversation import ConversationAsk, ConversationCreate
from backend.conversation import Conversations
from backend.jobs import WorkerBusy, WorkerLock
from backend.security import COOKIE
from backend.settings import Settings

from .support import ORIGIN, PORT, signed_in, visitor
from .test_assessment_core import record, review, scope


@pytest.fixture
def connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FastAPI, TestClient, Conversations]:
    settings = Settings(
        data_dir=tmp_path / "private", redaction_secrets=(SecretStr("configured-private-token"),)
    )
    store = AssessmentStore(settings)
    store.create(scope())
    store.import_records("assessment-1", json.dumps({"records": [record()]}), review())
    worker = conversation.Conversations(settings)
    monkeypatch.setattr(conversation, "Conversations", lambda *args: worker)
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    client.headers["origin"] = ORIGIN
    return app, client, worker


def new_conversation(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/conversations",
        json={"target_kind": "assessment", "target_id": "assessment-1"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "idle"
    return response.json()


def test_all_conversation_routes_require_session_origin_and_host(
    connected: tuple[FastAPI, TestClient, Conversations],
) -> None:
    app, client, _ = connected
    identifier = new_conversation(client)["conversation_id"]
    guest = visitor(app)
    for method, path, body in (
        ("POST", "/api/conversations", {}),
        ("GET", f"/api/conversations/{identifier}", None),
        ("POST", f"/api/conversations/{identifier}/ask", {"prompt": "Explain"}),
        ("POST", f"/api/conversations/{identifier}/cancel", None),
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
        assert (
            client.request(
                method, path, headers={"sec-fetch-site": "cross-site"}, json=body
            ).status_code
            == 403
        )
    missing_origin = visitor(app)
    missing_origin.cookies.update(client.cookies)
    assert missing_origin.post(f"/api/conversations/{identifier}/cancel").status_code == 403
    forged = visitor(app)
    forged.cookies.set(COOKIE, "wrong-launch-session")
    assert forged.get(f"/api/conversations/{identifier}").status_code == 401


def test_private_contract_errors_oversize_and_action_fields_never_echo_input_or_launch(
    connected: tuple[FastAPI, TestClient, Conversations],
) -> None:
    _, client, worker = connected
    identifier = new_conversation(client)["conversation_id"]
    private = "private-unmatched-human-input-value"
    cases = (
        ("/api/conversations", {"target_kind": private, "target_id": "assessment-1"}),
        (
            "/api/conversations",
            {"target_kind": "assessment", "target_id": "assessment-1", "authority": private},
        ),
        (f"/api/conversations/{identifier}/ask", {"prompt": "Explain", "actions": [private]}),
        (
            f"/api/conversations/{identifier}/ask",
            {"prompt": "Explain", "authorization_granted": True},
        ),
        (f"/api/conversations/{identifier}/ask", {"prompt": "Explain", "max_seconds": 301}),
        (f"/api/conversations/{identifier}/ask", {"prompt": "Explain", "model_api_key": private}),
    )
    for path, body in cases:
        response = client.post(path, json=body)
        assert response.status_code == 422
        assert private not in response.text and "input" not in response.json()[
            "detail"
        ].lower().replace("private input", "")
    malformed = client.post(
        f"/api/conversations/{identifier}/ask",
        content='{ "prompt": "' + private,
        headers={"content-type": "application/json"},
    )
    assert malformed.status_code == 422 and private not in malformed.text
    oversized = client.post(
        f"/api/conversations/{identifier}/ask",
        content=b" " * (MAX_REQUEST_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413
    view = worker.read(identifier)
    assert view.state == "idle" and not view.turns and not worker.threads
    assert not list(worker.directory.glob("*.invocation.json"))


def test_unknown_target_and_unknown_conversation_ids_have_private_generic_refusals(
    connected: tuple[FastAPI, TestClient, Conversations],
) -> None:
    _, client, worker = connected
    marker = "private-target-label"
    response = client.post(
        "/api/conversations", json={"target_kind": "assessment", "target_id": marker}
    )
    assert response.status_code == 409 and marker not in response.text
    for method, path, body in (
        ("GET", f"/api/conversations/{marker}", None),
        ("POST", f"/api/conversations/{marker}/ask", {"prompt": "Explain"}),
        ("POST", f"/api/conversations/{marker}/cancel", None),
    ):
        refused = client.request(method, path, json=body)
        assert refused.status_code == 409 and marker not in refused.text
    assert not worker.directory.exists()


def test_questions_with_configured_secrets_are_refused_before_worker_and_storage(
    connected: tuple[FastAPI, TestClient, Conversations],
) -> None:
    _, client, worker = connected
    identifier = new_conversation(client)["conversation_id"]
    refused = client.post(
        f"/api/conversations/{identifier}/ask",
        json={"prompt": "Explain configured-private-token"},
    )
    assert refused.status_code == 409 and "configured-private-token" not in refused.text
    assert worker.read(identifier).state == "idle" and not worker.threads
    assert "configured-private-token" not in worker.path(identifier).read_text(encoding="utf-8")


def test_read_restores_interrupted_lifecycle_without_inventing_a_completed_answer(
    connected: tuple[FastAPI, TestClient, Conversations],
) -> None:
    _, client, worker = connected
    identifier = new_conversation(client)["conversation_id"]
    view = worker.read(identifier)
    worker.save(view.model_copy(update={"state": "running"}))
    response = client.get(f"/api/conversations/{identifier}")
    assert response.status_code == 200 and response.json()["state"] == "failed"
    assert (
        response.json()["turns"] == [] and "Previous worker stopped" in response.json()["message"]
    )


def test_api_cancellation_stops_fake_inflight_model_preserves_prior_turn_and_charges_attempt(
    connected: tuple[FastAPI, TestClient, Conversations], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client, worker = connected
    saved = new_conversation(client)
    identifier = saved["conversation_id"]
    target = ConversationCreate(target_kind="assessment", target_id="assessment-1")
    evidence, unknowns, identity = conversation.evidence_for(worker.settings, target, "response")
    previous = conversation.validate_answer(
        {
            "answer": "Saved observation only.",
            "references": [evidence[0].reference_id],
            "unknowns": [],
        },
        "Explain the saved observation",
        evidence,
        unknowns,
        identity,
    )
    worker.save(worker.read(identifier).model_copy(update={"turns": [previous]}))
    entered, stopped = threading.Event(), threading.Event()
    stops: list[str] = []
    server = SimpleNamespace(startup_timeout=300, preflight=lambda: None)

    def stop() -> None:
        stops.append("owned-server-stop")
        stopped.set()

    server.stop = stop
    monkeypatch.setattr(
        conversation, "select", lambda *args: SimpleNamespace(identity=lambda: {"fixture": True})
    )
    monkeypatch.setattr(conversation, "first_use_pending", lambda *args: False)
    monkeypatch.setattr(conversation, "create", lambda *args: server)
    monkeypatch.setattr("eval.bench.machine.machine_state", lambda: {"fixture": True})

    class FixtureAdapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FixtureAdapter":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            entered.set()
            assert stopped.wait(5), "cancellation monitor must stop its owned server"
            answer = {"answer": "Canceled fake output", "references": ["R001"], "unknowns": []}
            return JsonAnswer(answer, json.dumps(answer), 10, 10, 0.1)

    monkeypatch.setattr(conversation, "ModelAdapter", FixtureAdapter)
    try:
        starting = client.post(
            f"/api/conversations/{identifier}/ask", json={"prompt": "Fetch a website"}
        )
        assert starting.status_code == 202 and starting.json()["state"] == "running"
        assert entered.wait(5)
        duplicate = client.post(
            f"/api/conversations/{identifier}/ask", json={"prompt": "Another question"}
        )
        assert duplicate.status_code == 409
        canceled = client.post(f"/api/conversations/{identifier}/cancel")
        assert canceled.status_code == 200
        worker.close()

        ended = client.get(f"/api/conversations/{identifier}")
        assert ended.status_code == 200 and ended.json()["state"] == "canceled"
        assert (
            len(ended.json()["turns"]) == 1
            and ended.json()["turns"][0]["prompt"] == previous.prompt
        )
        assert not ended.json()["turns"][0]["actions_executed"]
        assert not ended.json()["turns"][0]["authorization_granted"]
        assert not ended.json()["turns"][0]["verdict_changed"]
        assert stops and not worker.threads and not worker.cancels
        assert AssessmentStore(worker.settings).load("assessment-1").spent_requests == 1
        manifests = list(worker.directory.glob("*.invocation.json"))
        assert len(manifests) == 1 and json.loads(manifests[0].read_text())["error"] == "ValueError"
    finally:
        stopped.set()
        worker.close()


def test_assessment_elapsed_budget_is_charged_before_shared_worker_lock_releases(
    connected: tuple[FastAPI, TestClient, Conversations], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client, worker = connected
    identifier = new_conversation(client)["conversation_id"]
    original = AssessmentStore.charge_budget
    charges: list[tuple[int, float]] = []

    def charge(
        store: AssessmentStore, target: str, *, requests: int = 0, seconds: float = 0
    ) -> object:
        with pytest.raises(WorkerBusy), WorkerLock(worker.settings.cache_dir / "review.lock"):
            pytest.fail("reservation and completion charges must hold the shared worker lock")
        charges.append((requests, seconds))
        return original(store, target, requests=requests, seconds=seconds)

    monkeypatch.setattr(AssessmentStore, "charge_budget", charge)
    monkeypatch.setattr(
        conversation, "select", lambda *args: SimpleNamespace(identity=lambda: {"fixture": True})
    )
    monkeypatch.setattr(conversation, "first_use_pending", lambda *args: False)

    # Refuse after reservation without constructing any model process. Even this
    # admission failure must charge its elapsed time before freeing the worker.
    def refuse(*args: object) -> object:
        raise ValueError("Fixture refuses model creation")

    monkeypatch.setattr(conversation, "create", refuse)
    worker._run(
        worker.read(identifier), ConversationAsk(prompt="Explain the response"), threading.Event()
    )
    assert charges[0] == (1, 0) and charges[-1][0] == 0 and charges[-1][1] > 0
    assert worker.read(identifier).state == "failed"
