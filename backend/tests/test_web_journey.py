"""The website journey on the owned fixture, with the real pinned browser.

A mocked browser cannot pass these: the fixture's forms exist only after its
JavaScript has run. The model is a stand-in here, so the tests establish the
workflow and its boundaries, never model quality.
"""

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("playwright")

from agent.closed import Asker, CannotTellAsker, ScriptedAsker
from agent.llm import ModelTimeout
from backend.contracts.web import WebBudget
from backend.contracts.web_journey import CheckRecord, JourneyApprove, JourneyView
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.browser import status
from backend.web_journey import Journey, journey_answer, journey_label, new_journey
from backend.web_plan import approve, revoke
from backend.web_report import NOT_SECURE, ReportRefused, validate
from backend.web_store import JourneyStore
from verification.egress import Egress
from verification.web_browser import BrowserRunner
from verification.web_fixture import Fixture, launch
from verification.web_secrets import SecretStore

BROWSER = Settings()  # where the provisioned browser lives
pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        not status(BROWSER)["verified"],
        reason="pinned browser not provisioned: python -m backend.setup.browser install",
    ),
]


def browser_factory(
    egress: Egress, secrets: SecretStore, redactor: Redactor, expected: frozenset[str]
) -> BrowserRunner:
    return BrowserRunner(
        BROWSER, egress, secrets=secrets, redactor=redactor, expected_personal=expected
    )


def model(asker: Asker | None) -> Callable[[], AbstractContextManager[Asker | None]]:
    @contextmanager
    def factory() -> Iterator[Asker | None]:
        yield asker

    return factory


def readings(check: CheckRecord) -> list[dict[str, Any]]:
    """The saved independent readings of the owner's rule for one comparison."""
    assert check.judgment is not None
    return cast(list[dict[str, Any]], check.judgment["attempts"])


def prepared(
    settings: Settings, fixture: Fixture, *, signup: bool = True, budget: WebBudget | None = None
) -> JourneyView:
    view = new_journey(settings, fixture.scope(signup=signup, budget=budget))
    view = approve(
        view,
        JourneyApprove(
            plan_sha256=view.plan.sha256, approved_by="Test reviewer", reviewed_plan=True
        ),
    )
    JourneyStore(settings).save(view)
    return view


def run(
    settings: Settings,
    fixture: Fixture,
    view: JourneyView,
    asker: Asker | None = None,
    *,
    cancel: threading.Event | None = None,
    on_update: Callable[[JourneyView], None] | None = None,
    answers: dict[str, str] | None = None,
) -> JourneyView:
    return Journey(
        settings,
        view.journey_id,
        secrets=fixture.secrets,
        fixture=fixture,
        model=model(asker),
        browser=browser_factory,
        cancel=cancel,
        on_update=on_update,
        answers=answers,
    ).run()


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(data_dir=tmp_path_factory.mktemp("journeys"))


@pytest.fixture(scope="module")
def opened(settings: Settings) -> Iterator[Fixture]:
    with launch("open", settings, port=0) as fixture:
        yield fixture


@pytest.fixture(scope="module")
def done(settings: Settings, opened: Fixture) -> JourneyView:
    """One complete journey on the open fixture; the stand-in answers its closed questions."""
    asker = ScriptedAsker({"field_meaning": ["display_name"], "rule_covers": ["forbidden"] * 6})
    return run(settings, opened, prepared(settings, opened), asker)


# --- the complete journey ---------------------------------------------------------------------


def test_the_journey_visits_signs_in_signs_up_maps_checks_and_reports(done: JourneyView) -> None:
    assert done.status == "done", done.stop_reason
    assert {step.state for step in done.steps} == {"completed"}, [
        (s.step_id, s.state, s.note) for s in done.steps if s.state != "completed"
    ]
    assert {a.account_id: a.state for a in done.accounts} == {
        "dilnoza": "signed_in",
        "rustam": "signed_in",
        "newcomer": "created",
    }
    assert done.browser == "used" and done.approval_used_at is not None
    seen = {(page.account_id, page.path) for page in done.pages}
    assert {
        (None, "/"),
        (None, "/help"),
        ("dilnoza", "/parcels"),
        ("dilnoza", "/parcels/4117"),
    } <= seen
    assert ("rustam", "/parcels/4120") in seen and ("rustam", "/parcels/4117") not in seen
    forms = {form for page in done.pages for form in page.forms}
    assert {"sign_in", "sign_up"} <= forms  # both decided by code from the rendered forms


def test_the_flaw_is_found_and_the_protected_control_is_not_reported(
    done: JourneyView, opened: Fixture
) -> None:
    results = {check.check_id: check.comparison for check in done.checks}
    assert results == {
        "check-rule-label-owner-only-rustam": "candidate",
        "check-rule-label-owner-only-newcomer": "candidate",
        "check-rule-parcel-owner-only-rustam": "inconclusive",
        "check-rule-parcel-owner-only-newcomer": "inconclusive",
    }
    assert [finding.conclusion for finding in done.findings] == ["supported", "supported"]
    finding = done.findings[0]
    assert finding.affected_endpoint == f"GET {opened.origin}/api/parcels/4117/label"
    assert finding.runtime == "observed_once_by_plumb_runner"
    assert "not guessed here" in finding.mitigation  # no internal fix is inferred from outside
    for value in (
        finding.description,
        finding.safe_reproduction,
        finding.potential_impact,
        finding.evidence,
        finding.methodology,
        finding.tools_and_models,
        finding.limits,
    ):
        assert value
    check = next(c for c in done.checks if c.check_id == finding.check_id)
    assert check.facts["other account received the object"] == "yes"
    assert check.facts["signed-out status"] == "401"
    assert len(readings(check)) == 3
    validate(done)  # every citation resolves to an exact saved value


def test_decisions_say_which_rung_made_them_and_code_made_all_but_two_real_choices(
    done: JourneyView,
) -> None:
    by_type = {(record.question_type, record.rung) for record in done.decisions}
    assert ("field_meaning", "code") in by_type and ("next_step", "code") in by_type
    assert ("rule_covers", "model") in by_type
    asked = [record for record in done.decisions if record.rung != "code"]
    # One field whose label does not say what it is, and the reading of the owner's rule.
    assert sorted({(r.question_type, r.subject) for r in asked}) == [
        ("field_meaning", "field:/join:name"),
        ("rule_covers", "rule:check-rule-label-owner-only-newcomer"),
        ("rule_covers", "rule:check-rule-label-owner-only-rustam"),
    ]
    assert done.spent.model_questions == 7
    assert done.plan.model_questions >= 7 and "rule_covers" in done.plan.unmeasured_question_types
    assert done.waiting == []


def test_the_private_report_has_what_ran_what_did_not_and_every_finding_field(
    done: JourneyView, settings: Settings
) -> None:
    assert done.report_path is not None
    report = Path(done.report_path).read_text(encoding="utf-8")
    assert Path(done.report_path).is_relative_to(settings.data_dir)
    for heading in (
        "## Result",
        "## What ran",
        "## What could not run",
        "## Pages seen",
        "## Comparisons",
        "## Blocked requests",
        "## Decisions and who made them",
        "## Evidence",
        "## Uncertainties and coverage",
    ):
        assert heading in report
    for field in (
        "Description:",
        "Affected application:",
        "Affected endpoint:",
        "Safe reproduction:",
        "Potential impact:",
        "Evidence (sanitized, exact saved values):",
        "Mitigation:",
        "Methodology:",
        "Tools and model:",
        "Runtime: observed once",
    ):
        assert field in report
    assert NOT_SECURE in report and "2 supported finding(s)" in report
    assert "cdn.chorsu-partner.example" in report  # the blocked dependency is visible


def test_no_password_cookie_or_page_instruction_leaks_or_takes_effect(
    done: JourneyView, opened: Fixture, settings: Settings
) -> None:
    folder = JourneyStore(settings).folder(done.journey_id)
    saved = (folder / "journey.json").read_text(encoding="utf-8")
    report = (folder / "report.md").read_text(encoding="utf-8")
    for secret in opened.secrets.values():
        assert secret not in saved and secret not in report
    assert "chorsu_session=" not in saved and "Set-Cookie" not in saved
    # The page's planted instruction was read as text and changed nothing.
    assert "ignore your earlier" in saved
    assert [target.origin for target in done.scope.targets] == [opened.origin]
    assert {step.step_id for step in done.steps} == {step.step_id for step in done.plan.steps}
    assert all(row.kind != "off_scope" or row.host != "127.0.0.1" for row in done.blocked)
    assert done.spent.requests <= done.scope.budget.max_requests


def test_the_chat_reads_a_journey_from_its_record_with_exact_citations(
    done: JourneyView, settings: Settings, opened: Fixture
) -> None:
    assert opened.origin in journey_label(settings, done.journey_id)
    part = journey_answer(settings, done.journey_id, "Explain that result")
    assert part.kind == "cited" and "Supported:" in part.text and part.evidence
    assert all(item.observation is not None for item in part.evidence)
    assert "No model wrote" in part.basis or "by code" in part.basis


# --- the journey without a deciding model -----------------------------------------------------


@pytest.mark.parametrize("stand_in", ["cannot_tell", "none", "malformed", "timeout"])
def test_without_a_usable_model_the_journey_still_visits_records_and_reports(
    settings: Settings, opened: Fixture, stand_in: str
) -> None:
    asker: Asker | None = {
        "cannot_tell": CannotTellAsker(),
        "none": None,
        "malformed": ScriptedAsker({"rule_covers": [{"verdict": "yes"}, "allowed", "bogus"]}),
        "timeout": ScriptedAsker({"rule_covers": [ModelTimeout("slow")]}),
    }[stand_in]
    view = run(settings, opened, prepared(settings, opened, signup=False), asker)
    assert view.status == "done", view.stop_reason
    assert {step.state for step in view.steps} == {"completed"}
    assert [check.comparison for check in view.checks] == ["candidate", "inconclusive"]
    # The complete comparison stays a lead: nothing was promoted and nothing was lost.
    assert [finding.conclusion for finding in view.findings] == ["candidate"]
    assert view.findings[0].explanation_source == "code"
    assert view.checks[0].judged == "not_confirmed"
    report = Path(str(view.report_path)).read_text(encoding="utf-8")
    assert "0 supported finding(s), 1 lead(s) not confirmed" in report and NOT_SECURE in report
    # No answer, however wrong, added a step, an account or an origin.
    assert {step.step_id for step in view.steps} == {step.step_id for step in view.plan.steps}
    assert len(view.scope.targets) == 1 and view.approval is not None
    if stand_in == "malformed":
        first = readings(view.checks[0])[0]
        assert first["outcome"] == "refused" and first["raw"] == '{"verdict": "yes"}'
    with pytest.raises(ReportRefused):
        validate(
            view.model_copy(
                update={
                    "findings": [view.findings[0].model_copy(update={"conclusion": "supported"})]
                }
            )
        )


def test_the_defended_fixture_ends_with_zero_findings_and_says_what_that_means(
    settings: Settings,
) -> None:
    with launch("defended", settings, port=0) as fixture:
        view = run(settings, fixture, prepared(settings, fixture, signup=False), CannotTellAsker())
    assert view.status == "done" and view.findings == []
    assert [check.comparison for check in view.checks] == ["protected", "inconclusive"]
    assert view.spent.model_questions == 0  # nothing needed a model: code decided everything
    report = Path(str(view.report_path)).read_text(encoding="utf-8")
    assert "0 supported finding(s), 0 lead(s) not confirmed" in report and NOT_SECURE in report
    assert not any("X-Frame-Options" in lead for lead in view.leads)


# --- approval, expiry, budgets ----------------------------------------------------------------


def test_only_approved_steps_run_and_a_withdrawn_approval_runs_nothing(
    settings: Settings, opened: Fixture
) -> None:
    view = new_journey(settings, opened.scope(signup=False))
    with pytest.raises(ValueError, match="not waiting to run"):
        run(settings, opened, view)
    with pytest.raises(ValueError, match="plan changed"):
        approve(view, JourneyApprove(plan_sha256="0" * 64, approved_by="R", reviewed_plan=True))
    with pytest.raises(ValueError, match="steps of this plan"):
        approve(
            view,
            JourneyApprove(
                plan_sha256=view.plan.sha256,
                approved_by="R",
                reviewed_plan=True,
                step_ids=["discover", "delete-everything"],
            ),
        )
    partial = approve(
        view,
        JourneyApprove(
            plan_sha256=view.plan.sha256,
            approved_by="R",
            reviewed_plan=True,
            step_ids=["discover", "report"],
        ),
    )
    JourneyStore(settings).save(partial)
    result = run(settings, opened, partial)
    states = {step.step_id: (step.state, step.note) for step in result.steps}
    assert states["discover"][0] == states["report"][0] == "completed"
    assert all(
        value == ("skipped", "Not approved by the reviewer.")
        for name, value in states.items()
        if name not in {"discover", "report"}
    )
    assert result.checks == [] and all(a.state == "not_tried" for a in result.accounts)

    withdrawn = revoke(prepared(settings, opened, signup=False))
    JourneyStore(settings).save(withdrawn)
    assert withdrawn.approval_revoked_at is not None and withdrawn.status == "stopped"
    with pytest.raises(ValueError, match="not waiting to run"):
        run(settings, opened, withdrawn)


def test_an_expired_scope_and_a_used_up_budget_stop_the_journey_and_keep_its_work(
    settings: Settings, opened: Fixture
) -> None:
    scope = opened.scope(signup=False)
    short = scope.model_copy(update={"expires_at": datetime.now(UTC) + timedelta(seconds=2)})
    view = new_journey(settings, short)
    view = approve(
        view, JourneyApprove(plan_sha256=view.plan.sha256, approved_by="R", reviewed_plan=True)
    )
    JourneyStore(settings).save(view)
    time.sleep(2.2)
    with pytest.raises(ValueError, match="expired"):
        run(settings, opened, view)

    small = prepared(settings, opened, signup=False, budget=WebBudget(max_requests=22))
    result = run(settings, opened, small)
    assert result.status == "stopped" and "budget" in str(result.stop_reason)
    assert result.spent.requests <= 22
    assert any(step.state == "completed" for step in result.steps)
    assert Path(str(result.report_path)).is_file()  # what was done is still reported
    assert any(row.kind == "budget" for row in result.blocked)


# --- stop and resume, uncertain writes, privacy -----------------------------------------------


def test_stop_then_resume_continues_without_signing_in_again(
    settings: Settings, opened: Fixture
) -> None:
    view = prepared(settings, opened, signup=False)
    cancel = threading.Event()

    def stop_while_mapping(current: JourneyView) -> None:
        if current.stage == "map":
            cancel.set()

    paused = run(settings, opened, view, cancel=cancel, on_update=stop_while_mapping)
    assert paused.status == "paused" and "Stopped by the user" in str(paused.stop_reason)
    assert {a.account_id: a.state for a in paused.accounts} == {
        "dilnoza": "signed_in",
        "rustam": "signed_in",
    }
    signed = {s.step_id: s.state for s in paused.steps if s.action == "sign_in"}
    assert set(signed.values()) == {"completed"}
    resumed = run(settings, opened, paused, CannotTellAsker())
    assert resumed.status == "done", resumed.stop_reason
    assert {s.step_id: s.state for s in resumed.steps if s.action == "sign_in"} == signed
    assert [check.comparison for check in resumed.checks] == ["candidate", "inconclusive"]
    assert all(a.state == "signed_in" for a in resumed.accounts)


def test_a_question_only_the_user_can_answer_waits_and_the_answer_resumes_the_work(
    settings: Settings, opened: Fixture
) -> None:
    waiting = run(settings, opened, prepared(settings, opened), CannotTellAsker())
    assert waiting.status == "paused" and "Waiting for your answer" in str(waiting.stop_reason)
    (question,) = waiting.waiting
    assert (question.subject, question.question_type) == ("field:/join:name", "field_meaning")
    assert question.text == "What should be entered in the field “Your name”?"
    assert ("display_name", "the person's own name as shown to others") in {
        (choice.label, choice.meaning) for choice in question.choices
    }
    step = next(s for s in waiting.steps if s.step_id == "signup-newcomer")
    assert step.state == "blocked" and step.note.startswith("Needs your answer")
    # Everything that did not depend on the answer ran, and is already reported.
    assert {c.check_id: c.comparison for c in waiting.checks}[
        "check-rule-label-owner-only-rustam"
    ] == "candidate"
    assert Path(str(waiting.report_path)).is_file()
    # A wrong or made-up answer changes nothing; the right kind of answer resumes.
    still = run(settings, opened, waiting, CannotTellAsker(), answers={"field:/join:name": "admin"})
    assert still.status == "paused" and len(still.waiting) == 1
    resumed = run(
        settings, opened, still, CannotTellAsker(), answers={"field:/join:name": "display_name"}
    )
    assert resumed.status == "done", resumed.stop_reason
    assert next(a for a in resumed.accounts if a.account_id == "newcomer").state == "created"
    answered = next(d for d in resumed.decisions if d.subject == "field:/join:name" and d.value)
    assert (answered.value, answered.rung) == ("display_name", "user")
    assert {c.other_account_id for c in resumed.checks if c.state == "completed"} == {
        "rustam",
        "newcomer",
    }
    assert {s.step_id: s.state for s in resumed.steps if s.action == "sign_in"} == {
        "signin-dilnoza": "completed",
        "signin-rustam": "completed",
    }


def test_an_interrupted_sign_up_is_uncertain_and_is_never_sent_again(
    settings: Settings, opened: Fixture
) -> None:
    view = prepared(settings, opened)
    interrupted = view.model_copy(
        update={
            "steps": [
                step.model_copy(update={"state": "attempted"})
                if step.step_id == "signup-newcomer"
                else step
                for step in view.steps
            ]
        }
    )
    JourneyStore(settings).save(interrupted)
    result = run(settings, opened, interrupted, CannotTellAsker())
    step = next(s for s in result.steps if s.step_id == "signup-newcomer")
    assert step.state == "uncertain" and "not repeated automatically" in step.note
    assert next(a for a in result.accounts if a.account_id == "newcomer").state == "uncertain"
    assert result.status == "done"
    # The account that may or may not exist is not used for anything afterwards.
    assert not any(page.account_id == "newcomer" for page in result.pages)
    assert all(
        check.state == "blocked" for check in result.checks if check.other_account_id == "newcomer"
    )


def test_unexpected_personal_data_stops_that_page_and_keeps_none_of_it(
    settings: Settings, opened: Fixture
) -> None:
    scope = opened.scope(signup=False).model_copy(update={"public_values": []})
    view = new_journey(settings, scope)
    view = approve(
        view, JourneyApprove(plan_sha256=view.plan.sha256, approved_by="R", reviewed_plan=True)
    )
    JourneyStore(settings).save(view)
    result = run(settings, opened, view, CannotTellAsker())
    assert result.status == "done"
    assert next((i.path, i.kinds, i.content_kept) for i in result.incidents) == (
        "/help",
        ["email address"],
        False,
    )
    saved = (JourneyStore(settings).folder(result.journey_id) / "journey.json").read_text("utf-8")
    assert "help@chorsu-lockers.test" not in saved and "Lockers are open" not in saved
    assert "## Privacy stops" in Path(str(result.report_path)).read_text(encoding="utf-8")
    assert [check.comparison for check in result.checks] == ["candidate", "inconclusive"]


def test_an_owned_scope_runs_only_against_the_fixture_plumb_started(
    settings: Settings, opened: Fixture
) -> None:
    view = prepared(settings, opened, signup=False)
    result = Journey(
        settings, view.journey_id, secrets=SecretStore(), fixture=None, browser=browser_factory
    ).run()
    assert result.status == "stopped" and "fixture Plumb started" in str(result.stop_reason)
    assert result.spent.requests == 0 and result.pages == []
    record = json.loads(
        (JourneyStore(settings).folder(result.journey_id) / "journey.json").read_text("utf-8")
    )
    assert record["status"] == "stopped"
