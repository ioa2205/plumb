"""The website terminal entry: a scope from plain answers, a printed plan, an explicit yes."""

import argparse
from pathlib import Path

import pytest

from backend.contracts.web_journey import UserChoice, UserQuestion
from backend.settings import Settings
from backend.web_cli import (
    activity_text,
    confirm_and_approve,
    execute_website,
    plan_text,
    terminal_asker,
    wizard,
)
from backend.web_journey import new_journey
from backend.web_store import JourneyStore

from .test_chat_cli import Terminal
from .test_web_scope import scope

ANSWERS = [
    "/app, /api",  # approved paths
    "/app",  # start page
    "Check who can read an invoice.",  # purpose
    "Owner of the shop",  # who authorized
    "Ticket 7, 12 October 2026",  # reference
    "anna",  # account 1
    "",  # it exists
    "customer",
    "Anna (test)",
    "anna@test.example",
    "",  # no sign-up email
    "boris",  # account 2
    "y",
    "customer",
    "Boris (test)",
    "boris@test.example",
    "",
    "",  # no more accounts
    "/app/login",  # sign-in page
    "",  # no success path
    "Signed in",  # success text
    "/api/invoices/12",  # object 1
    "anna",
    "invoice 12",
    "INV-MARK-12",
    "Only the customer an invoice belongs to may read it.",
    "",  # no more objects
    "2",  # hours
    "120",  # requests
    "y",  # the list is complete
    "Example shop",  # name
    "help@shop.example.com",  # public contact
]


def arguments(action: str, journey: str | None = None, **more: object) -> argparse.Namespace:
    values = {"action": action, "journey_id": journey, "variant": "open", "no_model": True}
    return argparse.Namespace(**{**values, "profile": "auto", "yes": False, **more})


def test_the_wizard_builds_an_exact_external_scope_and_visits_nothing() -> None:
    terminal = Terminal(*ANSWERS)
    built = wizard(terminal.read, terminal.write, "shop.example.com")
    assert built is not None and terminal.lines == []
    assert (built.mode, built.origin, built.start_path) == (
        "external",
        "https://shop.example.com",
        "/app",
    )
    assert built.targets[0].paths == ["/app", "/api"]
    assert [(a.account_id, a.secret_ref, a.provisioned) for a in built.accounts] == [
        ("anna", "acct-anna", True),
        ("boris", "acct-boris", True),
    ]
    assert built.objects[0].marker == "INV-MARK-12" and built.rules[0].allowed_account_ids == [
        "anna"
    ]
    assert built.allowed_actions == ["read", "report", "sign_in", "compare"]
    assert built.budget.max_requests == 120 and built.public_values == ["help@shop.example.com"]
    assert built.confirmed_targets is True
    # No password was asked for during setup, and none is in the scope.
    assert not any("assword" in prompt for prompt in terminal.asked)
    assert "linked sites, CDNs and sign-in providers are not included" in terminal.output


@pytest.mark.parametrize(
    ("address", "answers", "message"),
    [
        ("http://shop.example.com", [], "Only https websites can be tested"),
        ("http://127.0.0.1:8711", [], "plumb website fixture"),
        ("https://user:pw@shop.example.com", [], "cannot be used"),
        ("https://shop.example.com/a/../b", [], "cannot be used"),
        ("shop.example.com", ["", "", "", "", ""], "purpose and an authorization are required"),
        ("shop.example.com", [*ANSWERS[:29], "n"], "Not confirmed. Nothing was saved."),
    ],
)
def test_the_wizard_refuses_what_it_cannot_scope(
    address: str, answers: list[str], message: str
) -> None:
    terminal = Terminal(*answers)
    assert wizard(terminal.read, terminal.write, address) is None
    assert message in terminal.output and "pw" not in terminal.output.replace("pw@", "")


def test_the_plan_is_printed_in_plain_words_and_needs_an_explicit_yes(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    view = new_journey(settings, scope())
    text = plan_text(view)
    assert "Plan for Example shop" in text and "Authorized by: Owner (Ticket 7)" in text
    assert "1. Open https://shop.example.com/app without signing in" in text
    assert "The local model may be asked up to" in text
    assert "That wait is an upper limit, not a measurement" in text
    assert "Not in this plan: No other form is submitted" in text
    declined = Terminal("n")
    assert confirm_and_approve(view, settings, declined.read, declined.write, False) is None
    assert "Not approved. Nothing was visited." in declined.output
    assert JourneyStore(settings).load(view.journey_id).status == "planned"
    accepted = Terminal("y", "Reviewer One")
    approved = confirm_and_approve(view, settings, accepted.read, accepted.write, False)
    assert approved is not None and approved.approval is not None
    assert approved.approval.approved_by == "Reviewer One"
    assert JourneyStore(settings).load(view.journey_id).status == "approved"


def test_show_list_and_stop_read_and_change_only_the_saved_record(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    empty = Terminal()
    assert execute_website(settings, arguments("list"), empty.read, empty.write) == 0
    assert "No website test is saved" in empty.output
    view = new_journey(settings, scope())
    accepted = Terminal("y", "R")
    confirm_and_approve(view, settings, accepted.read, accepted.write, False)
    shown = Terminal()
    assert (
        execute_website(settings, arguments("show", view.journey_id), shown.read, shown.write) == 0
    )
    assert (
        f"{view.journey_id}: approved" in shown.output and "Steps: 0 of 8 completed" in shown.output
    )
    assert activity_text(JourneyStore(settings).load(view.journey_id)).count("not started") == 0
    stopped = Terminal()
    assert (
        execute_website(settings, arguments("stop", view.journey_id), stopped.read, stopped.write)
        == 0
    )
    assert JourneyStore(settings).load(view.journey_id).approval_revoked_at is not None
    again = Terminal()
    assert (
        execute_website(settings, arguments("run", view.journey_id), again.read, again.write) == 2
    )
    assert "there is nothing to run" in again.output
    for action in ("show", "report", "run"):
        missing = Terminal()
        assert execute_website(settings, arguments(action), missing.read, missing.write) == 2
    unknown = Terminal()
    assert (
        execute_website(settings, arguments("show", "journey-nope"), unknown.read, unknown.write)
        == 1
    )
    assert "Website command stopped" in unknown.output
    report = Terminal()
    assert (
        execute_website(settings, arguments("report", view.journey_id), report.read, report.write)
        == 1
    )
    assert "no report yet" in report.output


def test_a_user_question_is_asked_plainly_and_only_a_listed_answer_counts() -> None:
    question = UserQuestion(
        subject="field:/join:name",
        question_type="field_meaning",
        text="What should be entered in the field “Your name”?",
        choices=[
            UserChoice(label="username", meaning="the account's user name"),
            UserChoice(label="display_name", meaning="the person's own name"),
        ],
    )
    picked = Terminal("﻿2")
    assert terminal_asker(picked.read, picked.write)(question) == "display_name"
    assert "  2. the person's own name" in picked.output
    for answer in ("", "9", "display_name", "0"):
        terminal = Terminal(answer)
        assert terminal_asker(terminal.read, terminal.write)(question) is None
    nobody = Terminal()
    assert terminal_asker(nobody.read, nobody.write)(question) is None
