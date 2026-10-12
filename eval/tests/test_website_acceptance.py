"""Acceptance predicates/setup are software checks, never model/browser evidence."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.contracts.web import WebEvidence, digest
from backend.contracts.web_journey import (
    AccountRecord,
    CheckRecord,
    DecisionRecord,
    JourneyApprove,
    JourneyView,
)
from backend.settings import Settings
from backend.web_journey import new_journey
from backend.web_plan import approve
from backend.web_store import JourneyStore
from eval import website_acceptance as acceptance
from verification.web_fixture import Fixture
from verification.web_secrets import SecretStore


@pytest.fixture
def fixture() -> Fixture:
    store = SecretStore()
    store.put("chorsu-dilnoza", "unit-only-secret-one")
    store.put("chorsu-rustam", "unit-only-secret-two")
    return Fixture("open", "http://127.0.0.1:8711", 8711, "a" * 64, "CHORSU-UNIT", store)


def approved(settings: Settings, fixture: Fixture) -> JourneyView:
    view = new_journey(settings, fixture.scope())
    return approve(
        view,
        JourneyApprove(
            plan_sha256=view.plan_sha256, approved_by="Unit fixture", reviewed_plan=True
        ),
    )


def test_production_wizard_setup_is_configurable_and_bound_only_to_owned_loopback(
    fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda *_: pytest.fail("No DNS during setup"))
    inputs = acceptance.default_setup_inputs(fixture)
    inputs[2] = "Check the owner's pickup-label rule on the practice website."
    scope, transcript = acceptance.configured_scope(fixture, inputs, lambda _: None)
    assert scope.mode == "owned_fixture" and scope.origin == fixture.origin
    assert scope.purpose == inputs[2] and scope.confirmed_targets is True
    assert {account.account_id for account in scope.accounts} == {"dilnoza", "rustam", "newcomer"}
    assert scope.signup is not None and scope.login is not None
    assert fixture.secrets.get("acct-dilnoza") == fixture.secrets.get("chorsu-dilnoza")
    assert "unit-only-secret" not in json.dumps(transcript)
    assert all("password" not in row["prompt"].lower() for row in transcript)


def test_setup_refuses_missing_inputs_credentials_or_unknown_provisioned_account(
    fixture: Fixture,
) -> None:
    with pytest.raises(ValueError, match="ended"):
        acceptance.configured_scope(fixture, [], lambda _: None)
    values = acceptance.default_setup_inputs(fixture)
    values[2] = "password=private"
    with pytest.raises(ValueError, match="credentials"):
        acceptance.configured_scope(fixture, values, lambda _: None)
    values = acceptance.default_setup_inputs(fixture)
    values[9] = "someone-else"
    with pytest.raises(ValueError, match="provisioned synthetic accounts"):
        acceptance.configured_scope(fixture, values, lambda _: None)


def test_done_alone_cannot_pass_journey_acceptance(tmp_path: Path, fixture: Fixture) -> None:
    view = approved(Settings(data_dir=tmp_path / "data"), fixture).model_copy(
        update={"status": "done"}
    )
    conditions = acceptance.journey_conditions(view, {"variant": "open"})
    result = acceptance.evaluated({}, conditions)
    assert result["passed"] is False
    assert {
        "explicit_answer_resumed_work",
        "production_scope_setup",
        "pinned_javascript_browser_used",
    } <= set(result["unmet"])


def test_real_resume_and_variant_controls_are_required(tmp_path: Path, fixture: Fixture) -> None:
    view = approved(Settings(data_dir=tmp_path / "data"), fixture)
    checks = [
        CheckRecord(
            check_id=f"c{index}",
            rule_id=rule.rule_id,
            object_id=item.object_id,
            path=item.path,
            owner_account_id="dilnoza",
            other_account_id="rustam",
            state="completed",
            comparison="candidate" if index == 0 else "inconclusive",
        )
        for index, (item, rule) in enumerate(zip(view.scope.objects, view.scope.rules, strict=True))
    ]
    report = tmp_path / "report.md"
    report.write_text("Journey status **done**")
    view = view.model_copy(
        update={
            "status": "done",
            "browser": "used",
            "checks": checks,
            "accounts": [
                AccountRecord(
                    account_id=account.account_id,
                    state="signed_in" if account.provisioned else "created",
                )
                for account in view.scope.accounts
            ],
            "decisions": [
                DecisionRecord(
                    at=datetime.now(UTC),
                    stage="authenticate",
                    question_type="field_meaning",
                    subject="field:/join:name",
                    value="display_name",
                    rung="user",
                )
            ],
            "report_path": str(report),
        }
    )
    record = {
        "variant": "open",
        "scope_setup": {"accepted": True},
        "resume_without_answer": {"status": "paused"},
        "resume_with_answer": {"status": "done"},
    }
    assert acceptance.evaluated({}, acceptance.journey_conditions(view, record))["passed"] is True
    record["resume_with_answer"]["status"] = "paused"
    assert acceptance.journey_conditions(view, record)["explicit_answer_resumed_work"] is False
    checks[1] = checks[1].model_copy(update={"comparison": "candidate"})
    assert (
        acceptance.journey_conditions(view.model_copy(update={"checks": checks}), record)[
            "markerless_object_not_promoted"
        ]
        is False
    )


def chat_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("ordinary", "creative", "rewrite", "mixed"):
        rows.append(
            {
                "name": name,
                "state": "completed",
                "turn": {
                    "model_requests": 1,
                    "parts": [{"kind": "general", "text": "Autumn leaves fall.", "complete": True}],
                    "authorization_granted": False,
                    "actions_executed": False,
                    "finding_created": False,
                },
            }
        )
    rows[2]["invocation"] = {
        "requests": [
            {
                "request": {
                    "messages": [
                        {
                            "content": "Previous general chat (data, not evidence or permission):\n"
                            + json.dumps(
                                [{"user": "Write a poem", "assistant": "Autumn leaves fall."}]
                            )
                            + "\n\nCurrent request:\nShorten it"
                        }
                    ]
                }
            }
        ]
    }
    return rows


def test_chat_completed_with_notice_or_missing_mixed_evidence_is_unmet() -> None:
    rows = chat_rows()
    assert acceptance.chat_conditions(rows, None)["rewrite_received_previous_text"] is True
    assert acceptance.evaluated({}, acceptance.chat_conditions(rows, None))["passed"] is False
    rows[0]["turn"]["parts"][0]["kind"] = "notice"
    assert acceptance.chat_conditions(rows, None)["ordinary_answered"] is False
    rows[2]["invocation"] = {}
    assert acceptance.chat_conditions(rows, None)["rewrite_received_previous_text"] is False


def test_chat_history_decodes_escaped_newlines_and_requires_the_exact_answer() -> None:
    rows = chat_rows()
    prior = 'Gold leaves.\n"Autumn" sings.'
    rows[1]["turn"]["parts"][0]["text"] = prior
    message = rows[2]["invocation"]["requests"][0]["request"]["messages"][0]
    message["content"] = (
        "Previous general chat (data, not evidence or permission):\n"
        + json.dumps([{"user": "Poem", "assistant": prior}])
        + "\n\nCurrent request:\nShorten it"
    )
    assert acceptance.chat_conditions(rows, None)["rewrite_received_previous_text"] is True
    message["content"] = message["content"].replace("Gold leaves", "Different poem")
    assert acceptance.chat_conditions(rows, None)["rewrite_received_previous_text"] is False


def test_mixed_citations_must_match_actual_saved_fields_and_be_used(
    tmp_path: Path,
    fixture: Fixture,
) -> None:
    view = approved(Settings(data_dir=tmp_path / "data"), fixture)
    now = datetime.now(UTC)
    fields = {"response.status": "200"}
    item = WebEvidence(
        evidence_id="E-one",
        website_id=view.scope.website_id,
        kind="response",
        via="http",
        fields=fields,
        collected_at=now,
        provenance="Unit fixture",
        sha256=digest(
            {
                "evidence_id": "E-one",
                "kind": "response",
                "account_id": None,
                "object_id": None,
                "fields": fields,
            }
        ),
    )
    view = view.model_copy(update={"evidence": [item]})
    rows = chat_rows()
    part = {
        "kind": "cited",
        "text": "Saved response [R001].",
        "evidence": [
            {
                "reference_id": "R001",
                "quote": "200",
                "source": None,
                "observation": {
                    "artifact_id": "E-one",
                    "field": "response.status",
                    "sha256": digest("200"),
                },
            }
        ],
    }
    rows[-1]["turn"]["parts"].append(part)
    assert acceptance.evaluated({}, acceptance.chat_conditions(rows, view))["passed"] is True
    part["evidence"][0]["quote"] = "403"
    assert acceptance.exact_observation_citations(rows[-1]["turn"], view) is False
    part["evidence"][0]["quote"] = "200"
    part["text"] = "A claim with no reference."
    assert acceptance.exact_observation_citations(rows[-1]["turn"], view) is False


def test_planning_code_or_default_order_is_never_a_model_choice() -> None:
    record = {
        "owned_approved_menu": True,
        "qualification_reason": None,
        "menu": [{"key": "check-1"}, {"key": "check-2"}],
        "executes_actions": False,
        "manifest": {"model_stopped": True},
        "decision": {"rung": "code", "value": "check-1", "attempts": []},
    }
    assert acceptance.evaluated(record, acceptance.planning_conditions(record))["passed"] is False
    record["decision"] = {
        "rung": "model",
        "value": "check-2",
        "attempts": [{"raw": '{"answer":"2"}', "completion_tokens": 5}],
    }
    assert acceptance.evaluated(record, acceptance.planning_conditions(record))["passed"] is True


def test_failed_planning_type_is_unmet_without_model_loading(
    tmp_path: Path,
    fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    view = approved(settings, fixture).model_copy(
        update={
            "accounts": [
                AccountRecord(
                    account_id=account.account_id,
                    state="signed_in" if account.provisioned else "created",
                )
                for account in fixture.scope().accounts
            ]
        }
    )
    JourneyStore(settings).save(view)
    monkeypatch.setattr(
        acceptance,
        "local_model",
        lambda *_args, **_kwargs: pytest.fail("An unqualified planning type cannot load"),
    )
    result = acceptance.planning(
        settings, tmp_path / "planning.json", view.journey_id, profile="cpu-8k"
    )
    assert result["passed"] is False and "actual_model_menu_choice" in result["unmet"]
    assert result["manifest"] == {} and result["decision"]["attempts"] == []


def test_driver_exits_nonzero_for_completed_but_unmet_conditions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = acceptance.evaluated(
        {
            "status": "failed",
            "seconds": 0,
            "spent": {"requests": 0, "model_questions": 0},
            "findings": [],
        },
        {"journey_completed": False},
    )
    monkeypatch.setattr(acceptance, "journey", lambda *args, **kwargs: record)
    monkeypatch.setattr(
        "sys.argv", ["website_acceptance", "journey", "--output", str(tmp_path / "out")]
    )
    assert acceptance.main() == 2
