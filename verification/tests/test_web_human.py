"""Pure human-tool boundaries with rendered-page stand-ins, never Chromium."""

from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from backend.contracts.web_journey import HumanAuthInput
from backend.redaction import Redactor
from backend.tests.test_web_scope import scope
from backend.web_plan import make_plan
from backend.web_urls import parse_url
from verification.egress import EgressRefused
from verification.web_browser import BrowserRunner
from verification.web_http import HttpSession
from verification.web_human import HumanBrowser
from verification.web_pages import PrivacyStop, RawPage, build_observation
from verification.web_secrets import SecretStore


class Page:
    def __init__(self, text: str = "Enter your one-time code") -> None:
        self.text = text
        self.masks: list[object] = []
        self.clicks: list[tuple[int, int]] = []
        self.mouse = SimpleNamespace(click=lambda x, y: self.clicks.append((x, y)))
        self.values = [{"index": 0, "value": ""}]

    def locator(self, selector: str) -> object:
        return SimpleNamespace(inner_text=lambda **_: self.text) if selector == "body" else selector

    def screenshot(self, **kwargs: object) -> bytes:
        self.masks = cast(list[object], kwargs["mask"])
        return b"\x89PNG\r\n\x1a\n"

    def evaluate(self, script: str, _: object) -> object:
        return [0, 0] if "elementFromPoint" in script else self.values


def controller(
    *, before_write: bool = False, code: bool = True, text: str = "Challenge"
) -> tuple[HumanBrowser, SimpleNamespace, Page]:
    website = scope()
    account = website.accounts[0]
    location = parse_url("https://shop.example.com/app/challenge")
    bound = build_observation(
        RawPage(
            text="one-time code",
            forms=[
                {
                    "action": "/app/challenge",
                    "method": "POST",
                    "fields": [
                        {
                            "name": "code" if code else "password",
                            "type": "text" if code else "password",
                            "autocomplete": "one-time-code" if code else "",
                        }
                    ],
                }
            ],
        ),
        via="browser",
        base=location,
        status=200,
        account_id="anna",
        in_scope=lambda url: url.origin == location.origin,
        redactor=Redactor(),
        expected_personal=frozenset(),
    )
    step = next(
        step for step in make_plan(website, None, "auto").steps if step.step_id == "signin-anna"
    )
    page = Page(text)
    session = HttpSession("anna")
    session.cookies[location.origin] = {"session": ("tiny", "/", False)}
    runner = SimpleNamespace(
        _own_thread=lambda: None,
        _page=lambda name: page,
        _timeout=lambda: 1000,
        _current={"anna": SimpleNamespace(url=location.url, bound=bound)},
        observe=lambda name: bound,
        location=lambda name: location,
        expected_personal=frozenset(),
        redactor=Redactor(),
        secrets=SecretStore(),
        session=lambda name: session,
        _settle=lambda _: None,
        fill=lambda *args, **kwargs: None,
        submits=[],
        egress=SimpleNamespace(
            in_scope=lambda url: url.origin == location.origin,
            refuse=lambda kind, host, reason: EgressRefused(kind, reason, host),
        ),
    )
    runner.submit = lambda name, ref: runner.submits.append((name, ref))
    runner._bound_form = lambda name, ref: (page, 0, runner._current[name])
    runner.fill = lambda name, ref, secret_ref: page.values[0].update(
        value=runner.secrets.get(secret_ref)
    )
    return (
        HumanBrowser(cast(BrowserRunner, runner), step, account, before_write=before_write),
        runner,
        page,
    )


def test_snapshot_masks_all_inputs_and_is_not_a_persisted_artifact() -> None:
    human, _, page = controller()
    view = human.snapshot("one_time_code")
    assert page.masks == ["input, textarea, [contenteditable]"]
    assert view.account_id == "anna" and view.screenshot_png.startswith("iVBORw0KGgo")


@pytest.mark.parametrize("text", ["Cookie tiny", "Password private-pass", "customer@example.net"])
def test_private_body_echo_is_refused_before_screenshot(text: str) -> None:
    human, runner, page = controller(text=text)
    runner.secrets.put("password", "private-pass")
    with pytest.raises(PrivacyStop):
        human.snapshot("one_time_code")
    assert page.masks == []


def test_pointer_on_moved_or_off_scope_page_cannot_act() -> None:
    human, runner, page = controller()
    runner.location = lambda _: parse_url("https://other.example.net/")
    with pytest.raises(EgressRefused):
        human.input(HumanAuthInput(view_id="a" * 32, kind="pointer", x=10, y=10))
    assert page.clicks == []


def test_post_write_handoff_cannot_resubmit_original_password_form() -> None:
    human, runner, _ = controller(code=False)
    with pytest.raises(ValueError, match="original"):
        human.input(HumanAuthInput(view_id="a" * 32, kind="submit"))
    assert runner.submits == []


def test_observed_code_form_submits_once_under_existing_runner_boundary() -> None:
    human, runner, _ = controller()
    human.input(HumanAuthInput(view_id="a" * 32, kind="pointer", x=10, y=10))
    human.input(HumanAuthInput(view_id="a" * 32, kind="text", text="human-code"))
    event = HumanAuthInput(view_id="a" * 32, kind="submit")
    human.input(event)
    with pytest.raises(ValueError, match="never repeated"):
        human.input(event)
    assert len(runner.submits) == 1 and runner.submits[0][0] == "anna"


def test_human_cannot_change_the_designated_account_identity() -> None:
    human, runner, page = controller(before_write=True)
    form = runner._current["anna"].bound.observation.forms[0]
    form.fields[0] = form.fields[0].model_copy(update={"name": "username", "hint": "username"})
    human.input(HumanAuthInput(view_id="a" * 32, kind="pointer", x=10, y=10))
    with pytest.raises(ValueError, match="identity"):
        human.input(HumanAuthInput(view_id="a" * 32, kind="text", text="undeclared-account"))
    assert runner.secrets.values() == ()
    page.values[0]["value"] = "undeclared-account"  # asynchronous page mutation is also refused
    with pytest.raises(ValueError, match="differs"):
        human.submission()
    assert runner.submits == []


def test_async_code_mutation_is_refused_before_the_write_grant() -> None:
    human, runner, page = controller()
    human.input(HumanAuthInput(view_id="a" * 32, kind="pointer", x=10, y=10))
    human.input(HumanAuthInput(view_id="a" * 32, kind="text", text="human-code"))
    page.values[0]["value"] = "replaced-code"
    with pytest.raises(ValueError, match="differs"):
        human.submission()
    assert runner.submits == []


def test_hidden_account_identity_is_also_bound_to_scope() -> None:
    human, runner, page = controller(before_write=True)
    form = runner._current["anna"].bound.observation.forms[0]
    form.fields[0] = form.fields[0].model_copy(
        update={"name": "username", "hint": "username", "input_type": "hidden"}
    )
    page.values[0]["value"] = "undeclared-account"
    with pytest.raises(ValueError, match="differs"):
        human.submission()
    assert runner.submits == []


@pytest.mark.parametrize("changes", [{"x": 1280}, {"y": -1}, {"text": "secret"}])
def test_pointer_contract_refuses_extra_text_and_outside_coordinates(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        HumanAuthInput.model_validate(
            {"view_id": "a" * 32, "kind": "pointer", "x": 1, "y": 1, **changes}
        )
