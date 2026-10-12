"""The website scope, its plan and its approval: exact, expiring, and nothing inherited."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from backend.contracts.web import STATE_CHANGING, WebBudget, WebsiteScope
from backend.contracts.web_journey import (
    JourneyApprove,
    JourneyView,
    StepRecord,
)
from backend.web_plan import approval_in_force, approve, make_plan, revoke


def scope(**changes: Any) -> WebsiteScope:  # noqa: ANN401 - scope fields under test
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "scope_id": "scope-1",
        "website_id": "website-1",
        "name": "Example shop",
        "mode": "external",
        "targets": [{"origin": "https://shop.example.com", "paths": ["/app", "/api"]}],
        "start_path": "/app",
        "purpose": "Check who can read an invoice.",
        "authority": {
            "granted_by": "Owner",
            "reference": "Ticket 7",
            "granted_at": now - timedelta(minutes=1),
        },
        "accounts": [
            {
                "account_id": "anna",
                "role": "customer",
                "label": "Anna (test)",
                "username": "anna@test.example",
                "secret_ref": "acct-anna",
            },
            {
                "account_id": "boris",
                "role": "customer",
                "label": "Boris (test)",
                "username": "boris@test.example",
                "secret_ref": "acct-boris",
            },
        ],
        "objects": [
            {
                "object_id": "invoice-12",
                "owner_account_id": "anna",
                "kind": "invoice 12",
                "path": "/api/invoices/12",
                "marker": "INV-MARK-12",
            }
        ],
        "rules": [
            {
                "rule_id": "rule-1",
                "statement": "Only the customer an invoice belongs to may read it.",
                "object_id": "invoice-12",
                "allowed_account_ids": ["anna"],
                "declared_by": "Owner",
                "basis": "Ticket 7",
            }
        ],
        "allowed_actions": ["read", "sign_in", "compare", "report"],
        "login": {"path": "/app/login", "success_text": "Signed in"},
        "expires_at": now + timedelta(hours=2),
        "stop_conditions": ["Unexpected personal data appears."],
        "confirmed_targets": True,
    }
    return WebsiteScope.model_validate({**base, **changes})


def journey(value: WebsiteScope) -> JourneyView:
    plan = make_plan(value, None, "auto")
    now = datetime.now(UTC)
    return JourneyView(
        journey_id="journey-" + "a" * 32,
        scope=value,
        plan=plan,
        plan_sha256=plan.sha256,
        steps=[StepRecord(step_id=s.step_id, action=s.action) for s in plan.steps],
        created_at=now,
        updated_at=now,
    )


def test_a_complete_scope_is_accepted_and_has_a_stable_identity() -> None:
    value = scope()
    assert value.origin == "https://shop.example.com"
    again = WebsiteScope.model_validate(value.model_dump(mode="json"))
    assert len(value.sha256) == 64 and value.sha256 == again.sha256
    assert value.sha256 != again.model_copy(update={"start_path": "/api"}).sha256
    assert "acct-anna" in value.model_dump_json()  # a reference name; never a password
    assert not hasattr(value.accounts[0], "password")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"confirmed_targets": False}, "explicit confirmation"),
        ({"confirmed_targets": "yes"}, "explicit confirmation"),
        ({"targets": []}, "at least 1 item"),
        ({"targets": [{"origin": "http://shop.example.com", "paths": ["/"]}]}, "https"),
        ({"targets": [{"origin": "https://127.0.0.1", "paths": ["/"]}]}, "not this computer"),
        ({"targets": [{"origin": "https://shop.example.com/app", "paths": ["/"]}]}, "origin"),
        ({"targets": [{"origin": "https://SHOP.example.com", "paths": ["/"]}]}, "origin"),
        ({"targets": [{"origin": "https://a@shop.example.com", "paths": ["/"]}]}, "credentials"),
        ({"targets": [{"origin": "https://shop.example.com", "paths": ["/a/../b"]}]}, "canonical"),
        (
            {"targets": [{"origin": "https://shop.example.com", "paths": ["/app", "/app"]}]},
            "distinct",
        ),
        (
            {
                "targets": [
                    {"origin": "https://shop.example.com", "paths": ["/app", "/api"]},
                    {"origin": "https://shop.example.com", "paths": ["/x"]},
                ]
            },
            "appears once",
        ),
        ({"start_path": "/elsewhere"}, "inside the first approved origin"),
        ({"login": {"path": "/login", "success_text": "Signed in"}}, "inside the first approved"),
        ({"login": {"path": "/app/login"}}, "post-sign-in check"),
        ({"login": None}, "sign-in page"),
        ({"allowed_actions": ["read", "read"]}, "distinct"),
        ({"allowed_actions": ["read", "erase_database"]}, "Input should be"),
        ({"expires_at": datetime.now(UTC) - timedelta(days=1)}, "expiry"),
        ({"expires_at": datetime(2030, 1, 1)}, "timezone"),
        ({"mode": "owned_fixture"}, "owned fixture"),
        ({"external_access_enabled": True}, "Extra inputs"),
    ],
)
def test_an_incomplete_ambiguous_or_widened_scope_is_refused(
    change: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        scope(**change)


def test_accounts_objects_and_rules_must_name_each_other_exactly() -> None:
    base = scope().model_dump(mode="json")
    stranger = {**base["objects"][0], "owner_account_id": "carol"}
    with pytest.raises(ValidationError, match="declared account"):
        scope(objects=[stranger])
    with pytest.raises(ValidationError, match="declared objects and accounts"):
        scope(rules=[{**base["rules"][0], "allowed_account_ids": ["carol"]}])
    with pytest.raises(ValidationError, match="must be unique"):
        scope(accounts=[base["accounts"][0], {**base["accounts"][1], "secret_ref": "acct-anna"}])
    with pytest.raises(ValidationError, match="two declared accounts"):
        scope(accounts=[base["accounts"][0]])
    with pytest.raises(ValidationError, match="sign-up approved and configured"):
        scope(accounts=[base["accounts"][0], {**base["accounts"][1], "provisioned": False}])
    with pytest.raises(ValidationError, match="inside the first approved origin"):
        scope(objects=[{**base["objects"][0], "path": "/admin/invoices/12"}])


def test_the_plan_is_made_by_code_from_the_scope_and_says_what_is_not_covered() -> None:
    value = scope()
    plan = make_plan(value, None, "auto")
    assert [step.step_id for step in plan.steps] == [
        "discover",
        "signin-anna",
        "signin-boris",
        "map-visitor",
        "map-anna",
        "map-boris",
        "check-rule-1-boris",
        "report",
    ]
    assert not any(step.state_changing for step in plan.steps)
    assert plan.scope_sha256 == value.sha256 and plan.expires_at == value.expires_at
    assert "No other form is submitted; forms are only described." in plan.not_covered
    # Nothing has been measured here, so the wait is an upper limit and says so.
    assert plan.unmeasured_question_types and plan.expected_model_seconds > 0
    assert plan.model_questions <= value.budget.max_model_questions
    tight = make_plan(scope(budget=WebBudget(max_requests=10, max_model_questions=1)), None, "auto")
    assert any("budget is 10" in line for line in tight.not_covered)
    assert any("1 are budgeted" in line for line in tight.not_covered)
    assert tight.model_questions <= 1
    assert frozenset({"sign_up", "submit_form"}) == STATE_CHANGING


def test_a_sign_up_step_is_marked_as_changing_the_website_and_needs_its_own_approval() -> None:
    base = scope().model_dump(mode="json")
    value = scope(
        accounts=[
            *base["accounts"],
            {
                **base["accounts"][1],
                "account_id": "new",
                "secret_ref": "acct-new",
                "provisioned": False,
            },
        ],
        allowed_actions=["read", "sign_in", "sign_up", "compare", "report"],
        signup={
            "path": "/app/join",
            "approved_side_effects": ["Creates one synthetic account."],
            "sends_messages": False,
            "success_text": "Welcome",
        },
    )
    plan = make_plan(value, None, "auto")
    changing = [step for step in plan.steps if step.state_changing]
    assert [step.step_id for step in changing] == ["signup-new"]
    assert "Creates one synthetic account." in changing[0].summary
    view = journey(value)
    partial = approve(
        view,
        JourneyApprove(
            plan_sha256=view.plan.sha256,
            approved_by="R",
            reviewed_plan=True,
            step_ids=[s.step_id for s in plan.steps if not s.state_changing],
        ),
    )
    assert partial.approval is not None and "signup-new" not in partial.approval.approved_step_ids


def test_approval_is_for_one_exact_plan_can_be_withdrawn_and_expires() -> None:
    view = journey(scope())
    assert approval_in_force(view) == "The plan has not been approved."
    with pytest.raises(ValidationError, match="Input should be True"):
        JourneyApprove.model_validate(
            {"plan_sha256": view.plan.sha256, "approved_by": "R", "reviewed_plan": False}
        )
    request = JourneyApprove(plan_sha256=view.plan.sha256, approved_by="R", reviewed_plan=True)
    approved = approve(view, request)
    assert approved.status == "approved" and approval_in_force(approved) is None
    assert approved.approval is not None and approved.approval.expires_at == view.scope.expires_at
    with pytest.raises(ValueError, match="already decided"):
        approve(approved, request)
    # A changed scope under an old approval is not in force.
    widened = approved.model_copy(update={"scope": scope(start_path="/api")})
    assert approval_in_force(widened) == "The scope or plan changed after approval."
    with pytest.raises(ValidationError, match="does not belong to this scope"):
        JourneyView.model_validate(widened.model_dump(mode="json"))
    later = datetime.now(UTC) + timedelta(hours=3)
    assert approval_in_force(approved, later) == "The scope or its approval has expired."
    with pytest.raises(ValueError, match="expired"):
        approve(view, request, later)
    withdrawn = revoke(approved)
    assert approval_in_force(withdrawn) == "The approval was withdrawn."
    assert withdrawn.status == "stopped" and withdrawn.approval_revoked_at is not None
    with pytest.raises(ValueError, match="no approval in force"):
        revoke(withdrawn)
