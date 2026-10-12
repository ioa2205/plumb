"""Offline human-handoff state and channel checks; no browser, target or model runs."""

import threading
from pathlib import Path
from typing import Any, cast

import pytest

from backend.contracts.web_journey import HumanAuthInput, HumanAuthView
from backend.web_human import HumanChannel
from backend.web_journey import Halt, Journey
from backend.web_store import JourneyStore
from backend.web_urls import WebUrl, parse_url
from verification.web_http import HttpAdapter, HttpSession, UncertainWrite

from .test_web_object_identity import investigator

PNG = "iVBORw0KGgo="


def image(view_id: str = "a" * 32) -> HumanAuthView:
    return HumanAuthView(
        view_id=view_id,
        step_id="signin-anna",
        account_id="anna",
        label="Anna",
        challenge="one_time_code",
        question="Complete the challenge.",
        screenshot_png=PNG,
    )


class Contained:
    def __init__(self) -> None:
        self.kept = {"cookies": [{"name": "session", "value": "tiny"}], "origins": []}
        self.restored: list[str] = []
        self.navigated: list[tuple[str, str]] = []
        self.solved = False
        self.uncertain = False
        self.submit_calls = 0
        self.private_text: str | None = None

    def state(self, account: str) -> dict[str, Any]:
        assert account == "anna"
        return self.kept

    def location(self, account: str) -> WebUrl:
        assert account == "anna"
        return parse_url("https://shop.example.com/app/challenge")

    def restore(self, account: str, state: dict[str, Any]) -> None:
        assert "plumb_handoff" not in state
        self.restored.append(account)
        self.kept = state

    def navigate(self, account: str, url: WebUrl) -> None:
        self.navigated.append((account, url.url))

    def session(self, account: str) -> HttpSession:
        assert account == "anna"
        return HttpSession(account)


class HumanTools:
    def __init__(self, browser: Contained, *_: object, **__: object) -> None:
        self.browser = browser
        self.submitted = False

    def snapshot(self, _: str, note: str = "") -> HumanAuthView:
        return image().model_copy(update={"question": note or "Complete the challenge."})

    def submission(self) -> str:
        if self.submitted:
            raise ValueError("already submitted")
        return "observed-challenge-form"

    def input(self, event: HumanAuthInput) -> None:
        if event.kind == "text":
            self.browser.private_text = event.text
            self.browser.solved = True
        if event.kind == "submit":
            self.submitted = True
            self.browser.submit_calls += 1
            if self.browser.uncertain:
                raise UncertainWrite("unknown")


class Events(HumanChannel):
    def __init__(self, *events: str) -> None:
        super().__init__()
        self.events = list(events)

    def take(self, *, seconds: float = 0.2) -> HumanAuthInput:
        del seconds
        event = self.events.pop(0)
        assert self.view is not None
        return HumanAuthInput.model_validate(
            {
                "view_id": self.view.view_id,
                "kind": event,
                "text": "private-code-738291" if event == "text" else None,
            }
        )


def checkpoint(journey: Journey, browser: Contained) -> None:
    step = journey.plan["signin-anna"]
    journey.set_step(step.step_id, "attempted")  # original form was sent, never send it again
    journey.handoff(
        step, journey.accounts["anna"], "one_time_code", browser, cast(HttpAdapter, None)
    )


def test_handoff_checkpoint_keeps_only_same_account_protected_interim_state(tmp_path: Path) -> None:
    journey, browser = investigator(tmp_path), Contained()
    checkpoint(journey, browser)
    assert journey.account_state("anna") == "handoff"
    assert journey.step("signin-anna").state == "blocked"
    assert journey.view.waiting[0].subject == "human:signin-anna"
    assert journey.store.session(journey.view.journey_id, "boris") is None
    saved = JourneyStore(journey.settings).load(journey.view.journey_id).model_dump_json()
    assert "tiny" not in saved and "plumb_handoff" not in saved
    state = journey.store.session(journey.view.journey_id, "anna")
    assert state is not None and state["plumb_handoff"]["before_write"] is False


def test_resume_requires_explicit_human_confirmation_and_revalidates_same_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journey, browser = investigator(tmp_path), Contained()
    checkpoint(journey, browser)
    channel = Events("completed", "text", "completed")
    resumed = Journey(
        journey.settings,
        journey.view.journey_id,
        secrets=journey.secrets,
        answers={"human:signin-anna": "resume"},
        human=channel,
    )
    checked: list[str] = []

    def confirmed(_: object, __: object, name: str, ___: object, ____: str) -> str | None:
        checked.append(name)
        return None if browser.solved else "The challenge is still present."

    monkeypatch.setattr("backend.web_journey.HumanBrowser", HumanTools)
    monkeypatch.setattr(resumed, "confirmed", confirmed)
    resumed.take_answers()
    resumed.resume_handoffs(browser, cast(HttpAdapter, None))
    assert checked == ["anna", "anna"] and browser.restored == ["anna"]
    assert browser.submit_calls == 0
    assert resumed.account_state("anna") == "signed_in"
    assert resumed.account_state("boris") == "not_tried"
    assert resumed.step("signin-anna").state == "completed"
    assert resumed.view.waiting == [] and channel.snapshot() is None
    assert "private-code-738291" not in resumed.view.model_dump_json()
    saved = resumed.store.session(resumed.view.journey_id, "anna")
    assert saved is not None and "plumb_handoff" not in saved


def test_resume_without_answer_does_not_restore_or_repeat_signin(tmp_path: Path) -> None:
    journey, browser = investigator(tmp_path), Contained()
    checkpoint(journey, browser)
    resumed = Journey(journey.settings, journey.view.journey_id, secrets=journey.secrets)
    resumed.take_answers()
    resumed.resume_handoffs(browser, cast(HttpAdapter, None))
    assert browser.restored == [] and browser.submit_calls == 0
    assert resumed.view.waiting and resumed.account_state("anna") == "handoff"


def test_mismatched_account_state_is_refused_before_restore(tmp_path: Path) -> None:
    journey, browser = investigator(tmp_path), Contained()
    checkpoint(journey, browser)
    state = journey.store.session(journey.view.journey_id, "anna")
    assert state is not None
    state["plumb_handoff"]["account_id"] = "boris"
    resumed = Journey(
        journey.settings,
        journey.view.journey_id,
        secrets=journey.secrets,
        answers={"human:signin-anna": "resume"},
    )
    resumed.take_answers()
    resumed.resume_handoffs(browser, cast(HttpAdapter, None))
    assert browser.restored == [] and resumed.account_state("anna") == "needs_sign_in"


def test_uncertain_human_submission_cannot_be_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journey, browser = investigator(tmp_path), Contained()
    browser.uncertain = True
    journey.human = Events("submit")
    monkeypatch.setattr("backend.web_journey.HumanBrowser", HumanTools)

    class Transport:
        def live(self) -> None:
            pass

        def action(self, *_: object) -> object:
            from contextlib import nullcontext

            return nullcontext()

    # Avoid budget recording of the transport stand-in; the state machine still checkpoints.
    monkeypatch.setattr(journey, "save", lambda: None)
    journey._egress = cast(Any, Transport())
    with pytest.raises(Halt, match="uncertain"):
        checkpoint(journey, browser)
    assert browser.submit_calls == 1
    assert journey.step("signin-anna").state == "uncertain"
    assert journey.account_state("anna") == "uncertain"
    assert journey.human.snapshot() is None


def test_channel_stale_view_is_refused_and_private_event_is_consumed_once() -> None:
    channel = HumanChannel()
    channel.publish(image())
    with pytest.raises(ValueError, match="Refresh"):
        channel.send(HumanAuthInput(view_id="b" * 32, kind="text", text="private"))
    received: list[HumanAuthInput] = []

    def browser_thread() -> None:
        event = channel.take(seconds=1)
        assert event is not None
        received.append(event)
        channel.publish(image("c" * 32))

    worker = threading.Thread(target=browser_thread)
    worker.start()
    result = channel.send(HumanAuthInput(view_id="a" * 32, kind="text", text="private"))
    worker.join(timeout=2)
    assert result is not None and result.view_id == "c" * 32
    assert channel._event is None and "private" not in repr(received[0])
    channel.close()
    assert channel.snapshot() is None


def test_human_endpoints_require_protected_session_and_never_cache_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import create_app
    from backend.web_api import WebsiteJobs

    from .support import ORIGIN, PORT, signed_in, visitor

    journey = investigator(tmp_path)
    jobs = WebsiteJobs(journey.settings)
    channel = HumanChannel()
    channel.publish(image())
    jobs.humans[journey.view.journey_id] = channel
    monkeypatch.setattr("backend.web_api.WebsiteJobs", lambda _: jobs)
    app = create_app(journey.settings, port=PORT)
    path = f"/api/websites/{journey.view.journey_id}/human"
    with signed_in(app) as client, visitor(app) as guest:
        client.headers["origin"] = ORIGIN
        guest.headers["origin"] = ORIGIN
        assert guest.get(path).status_code == 401
        assert guest.post(path, json={"view_id": "a" * 32, "kind": "refresh"}).status_code == 401
        assert (
            client.post(
                path,
                json={"view_id": "a" * 32, "kind": "refresh"},
                headers={"origin": "https://other.invalid"},
            ).status_code
            == 403
        )
        current = client.get(path)
        assert current.status_code == 200 and current.headers["cache-control"] == "no-store"
        assert current.json()["account_id"] == "anna"
        assert client.post(path, json={"view_id": "b" * 32, "kind": "refresh"}).status_code == 409
        rejected = client.post(
            path,
            json={
                "view_id": "a" * 32,
                "kind": "pointer",
                "x": 1,
                "y": 1,
                "text": "must-never-be-echoed",
            },
        )
        assert rejected.status_code == 422 and "must-never-be-echoed" not in rejected.text
        assert client.get("/api/websites/journey-" + "b" * 32 + "/human").status_code == 409
    assert channel.snapshot() is None
