"""The closed-question layer: shapes that cannot be written wrong, and the ladder."""

import json
from dataclasses import replace

import pytest

from agent.closed import (
    CANNOT_TELL,
    CannotTellAsker,
    ClosedQuestion,
    Fact,
    MenuItem,
    QuestionType,
    Reason,
    ScriptedAsker,
    by_code,
    decide,
    judge_three,
    one_line,
)
from agent.llm import AnswerTruncated, BudgetStop, ModelTimeout

PAGE = QuestionType(
    name="page_sort",
    adds="What a page is for, from its wording.",
    ask="What is this page for?",
    labels=(("sign_in", "signing in to an existing account"), ("listing", "a list of items")),
    reasons=(
        Reason("unclear", "the wording does not say"),
        Reason("evidence_missing", "a needed fact is absent", checkable=True),
    ),
)
STEP = QuestionType(
    name="step_pick",
    adds="Which of several equally valid steps serves the stated goal best.",
    ask="Which step serves the goal best?",
    labels=(),
    reasons=(Reason("no_item_fits", "none of the steps serves the goal"),),
    menu=True,
)
FACTS = (Fact("page title", "Welcome back"), Fact("password field", "present"), Fact("links", "3"))


BASE = ClosedQuestion(kind=PAGE, facts=FACTS)


def page(**changes: object) -> ClosedQuestion:
    return replace(BASE, **changes)


def steps(*, ready: bool = True) -> ClosedQuestion:
    return ClosedQuestion(
        kind=STEP,
        facts=(Fact("goal", "check who can read a parcel label"),),
        menu=(
            MenuItem("read-own", "Read the label as its owner"),
            MenuItem("read-other", "Read the label as another account", ready=ready),
            MenuItem("list", "List parcels"),
        ),
    )


# --- request shape ---------------------------------------------------------------------------


def test_fixed_text_comes_first_and_only_facts_change() -> None:
    first, second = page().request(), page(facts=(Fact("page title", "Orders"),)).request()
    assert first.system == second.system == PAGE.system
    assert first.system.startswith("You answer one closed question.")
    assert "Question: What is this page for?" in first.system
    assert first.user == "Facts:\n- page title: Welcome back\n- password field: present\n- links: 3"
    assert first.user != second.user


def test_every_answer_slot_is_one_fixed_set_built_for_the_request() -> None:
    schema = page().request().schema
    assert schema["additionalProperties"] is False and schema["required"] == ["answer"]
    assert schema["properties"]["answer"]["enum"] == [
        "sign_in",
        "listing",
        "cannot_tell:unclear",
        "cannot_tell:evidence_missing",
    ]
    menu = steps().request()
    assert menu.schema["properties"]["answer"]["enum"] == [
        "1",
        "2",
        "3",
        "cannot_tell:no_item_fits",
    ]
    assert menu.user.endswith(
        "Menu:\n1. Read the label as its owner\n"
        "2. Read the label as another account\n3. List parcels"
    )
    # No free list and no character cap anywhere in the answer schema.
    assert "array" not in json.dumps(schema) and "maxLength" not in json.dumps(schema)


def test_a_type_must_say_what_the_model_adds_and_offer_cannot_tell() -> None:
    with pytest.raises(ValueError, match="what the model adds"):
        QuestionType(
            name="copy", adds=" ", ask="Status?", labels=(("a", "b"),), reasons=PAGE.reasons
        )
    with pytest.raises(ValueError, match="cannot tell"):
        QuestionType(name="copy", adds="x", ask="Status?", labels=(("a", "b"),), reasons=())
    with pytest.raises(ValueError, match="fixed labels or a per-request menu"):
        QuestionType(name="copy", adds="x", ask="Status?", labels=(), reasons=PAGE.reasons)
    with pytest.raises(ValueError, match="single-line"):
        QuestionType(
            name="copy", adds="x", ask="One?\nTwo?", labels=(("a", "b"),), reasons=PAGE.reasons
        )


def test_facts_are_bounded_single_lines_and_one_item_menus_are_refused() -> None:
    with pytest.raises(ValueError, match="single lines"):
        page(facts=(Fact("title", "two\nlines"),))
    with pytest.raises(ValueError, match="1 to 24"):
        page(facts=tuple(Fact(f"f{index}", "x") for index in range(25)))
    with pytest.raises(ValueError, match="one item is code's decision"):
        ClosedQuestion(kind=STEP, facts=FACTS, menu=(MenuItem("only", "The only step"),))
    assert one_line("a\tb\nc  d\x00e") == "a b c d e"
    assert one_line("x" * 300).endswith("(shortened)") and len(one_line("x" * 300)) <= 200


def test_a_reordered_request_keeps_the_facts_and_renumbers_the_menu() -> None:
    question = steps()
    first, again = question.request(0), question.request(1)
    assert first.user != again.user and first.seed != again.seed
    items = [
        sorted(line.split(". ", 1)[1] for line in request.user.splitlines()[-3:])
        for request in (first, again)
    ]
    assert items[0] == items[1]
    # The same number may now mean another item; code maps it through that request's order.
    keys = {question.grade({"answer": str(number)}, 1)[0] for number in (1, 2, 3)}
    assert keys == {"read-own", "read-other", "list"}


# --- checks ----------------------------------------------------------------------------------


def test_answers_outside_the_set_or_with_extra_fields_are_refused() -> None:
    question = page()
    assert question.grade({"answer": "sign_in"}) == ("sign_in", None, None)
    for wrong in (
        {"answer": "login"},
        {"answer": "sign_in", "why": "x"},
        ["sign_in"],
        {"answer": 1},
    ):
        value, abstained, violation = question.grade(wrong)
        assert value is None and abstained is None and violation


def test_cannot_tell_evidence_missing_must_match_a_gap_code_found() -> None:
    value, abstained, violation = page().grade({"answer": "cannot_tell:evidence_missing"})
    assert (value, abstained) == (None, None) and "does not match a gap" in str(violation)
    assert page(gaps=frozenset({"evidence_missing"})).grade(
        {"answer": "cannot_tell:evidence_missing"}
    ) == (None, "evidence_missing", None)
    # A reason code cannot check is accepted as an abstention.
    assert page().grade({"answer": "cannot_tell:unclear"}) == (None, "unclear", None)
    with pytest.raises(ValueError, match="checkable"):
        page(gaps=frozenset({"unclear"}))


def test_a_label_is_checked_against_the_facts_and_a_menu_item_against_its_prerequisites() -> None:
    def verify(label: str) -> str | None:
        return "A sign-in page needs a password field." if label == "sign_in" else None

    assert page(verify=verify).grade({"answer": "sign_in"})[2] == (
        "A sign-in page needs a password field."
    )
    assert page(verify=verify).grade({"answer": "listing"}) == ("listing", None, None)
    assert steps(ready=False).grade({"answer": "2"})[2] == (
        "The chosen step's prerequisites do not hold."
    )
    assert steps().grade({"answer": "2"}) == ("read-other", None, None)


# --- ladder ----------------------------------------------------------------------------------


def test_code_decides_first_and_asks_nothing() -> None:
    decision = by_code(PAGE, "sign_in", "The page has one form with a password field.")
    assert (decision.value, decision.rung, decision.attempts) == ("sign_in", "code", ())


def test_one_accepted_answer_decides_on_the_model_rung() -> None:
    asker = ScriptedAsker({"page_sort": ["listing"]})
    decision = decide(page(), asker)
    assert (decision.value, decision.rung, len(asker.asked)) == ("listing", "model", 1)
    assert decision.record()["attempts"][0]["outcome"] == "answered"


def test_a_failed_check_is_kept_raw_and_the_question_is_asked_again_reordered() -> None:
    def verify(label: str) -> str | None:
        return "A sign-in page needs a password field." if label == "sign_in" else None

    asker = ScriptedAsker({"page_sort": ["sign_in", "listing"]})
    decision = decide(page(verify=verify), asker)
    assert (decision.value, decision.rung) == ("listing", "model_reordered")
    refused, accepted = decision.attempts
    assert refused.raw == '{"answer": "sign_in"}' and refused.outcome == "refused"
    assert refused.value is None and accepted.outcome == "answered"
    first, second = asker.asked
    assert first.user != second.user and (first.seed, second.seed) == (42, 43)
    assert first.system == second.system


def test_two_non_answers_go_to_the_user_or_to_a_recorded_stop() -> None:
    asked = decide(
        page(user_question="Is this the sign-in page?"),
        ScriptedAsker({"page_sort": ["cannot_tell:unclear", "cannot_tell:unclear"]}),
    )
    assert (asked.value, asked.rung, asked.user_question) == (
        None,
        "user",
        "Is this the sign-in page?",
    )
    assert [attempt.outcome for attempt in asked.attempts] == ["abstained", "abstained"]
    stopped = decide(page(), ScriptedAsker({"page_sort": ["cannot_tell:unclear", "bogus"]}))
    assert (stopped.value, stopped.rung) == (None, "stop")
    assert stopped.reason == "The answer is not one of the allowed values."


@pytest.mark.parametrize("failure", [BudgetStop("seconds", "out of time"), ModelTimeout("slow")])
def test_a_resource_stop_is_not_asked_again(failure: Exception) -> None:
    asker = ScriptedAsker({"page_sort": [failure, "listing"]})
    decision = decide(page(), asker)
    assert (decision.value, decision.rung, len(asker.asked)) == (None, "stop", 1)
    assert decision.reason == type(failure).__name__


def test_a_cut_off_answer_moves_down_the_ladder_without_being_repaired() -> None:
    asker = ScriptedAsker({"page_sort": [AnswerTruncated("cut off"), "listing"]})
    decision = decide(page(), asker)
    assert (decision.value, decision.rung) == ("listing", "model_reordered")
    assert decision.attempts[0].outcome == "failed" and decision.attempts[0].raw is None


def test_no_model_goes_straight_to_the_last_rung() -> None:
    decision = decide(page(user_question="What is this page?"), None)
    assert (decision.rung, decision.attempts) == ("user", ())
    assert decision.reason == "The local model is not available for this decision."


def test_a_stand_in_that_always_abstains_never_decides() -> None:
    asker = CannotTellAsker()
    assert decide(page(), asker).rung == "stop"
    assert decide(steps(), asker).value is None
    assert asker.asked == ["page_sort", "page_sort", "step_pick", "step_pick"]
    assert CANNOT_TELL + ":unclear" in page().allowed()


# --- three independent judgments ---------------------------------------------------------------


def test_three_agreeing_independent_answers_are_decisive() -> None:
    asker = ScriptedAsker({"page_sort": ["listing", "listing", "listing"]})
    judgment = judge_three(page(), asker)
    assert judgment.value == "listing" and len(judgment.attempts) == 3
    assert [request.seed for request in asker.asked] == [42, 43, 44]
    assert len({request.user for request in asker.asked}) == 3


def test_disagreement_or_one_non_answer_stops_without_a_conclusion() -> None:
    split = judge_three(page(), ScriptedAsker({"page_sort": ["listing", "sign_in", "listing"]}))
    assert (split.value, len(split.attempts)) == (None, 2)
    assert split.reason == "The independent answers disagree."
    abstained = judge_three(
        page(), ScriptedAsker({"page_sort": ["cannot_tell:unclear", "listing"]})
    )
    assert (abstained.value, len(abstained.attempts)) == (None, 1)
    assert judge_three(page(), None).value is None
