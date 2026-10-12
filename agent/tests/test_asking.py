"""Real request path for closed questions, timing records and non-gating explanations."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent.asking import (
    EXPLAIN_SYSTEM,
    EvaluationAsker,
    ModelAsker,
    TimingLog,
    expected_wait,
    explain,
    unsupported_names,
)
from agent.closed import ClosedQuestion, Fact, QuestionType, Reason, decide
from agent.llm import ModelAdapter, ModelTimeout, TextAnswer, TextRequest
from backend.preflight import PreflightResult

from .fake_llama import HANG, FakeLlama, Reply, answer

KIND = QuestionType(
    name="page_sort",
    adds="What a page is for, from its wording.",
    ask="What is this page for?",
    labels=(("sign_in", "signing in"), ("listing", "a list of items")),
    reasons=(Reason("unclear", "the wording does not say"),),
    max_prompt_tokens=400,
)
QUESTION = ClosedQuestion(kind=KIND, facts=(Fact("page title", "Welcome back"),))
FACTS = (
    Fact("account", "dilnoza"),
    Fact("page", "/parcels/41/label"),
    Fact("status", "200"),
)


def preflight() -> PreflightResult:
    return PreflightResult(
        ok=True, model="m", ctx_size=8192, available_bytes=0, requirement=None, message="ok"
    )


def timed(content: object, *, finish: str = "stop") -> Reply:
    reply = answer(content, prompt_tokens=90, completion_tokens=6, finish_reason=finish)
    reply.body["timings"] = {"prompt_ms": 1800.5, "predicted_ms": 420.0, "prompt_n": 90}
    return reply


Served = Callable[..., tuple[FakeLlama, ModelAdapter]]


@pytest.fixture
def served() -> Iterator[Served]:
    fakes: list[FakeLlama] = []

    def build(*replies: Reply) -> tuple[FakeLlama, ModelAdapter]:
        fake = FakeLlama(*replies)
        fakes.append(fake)
        return fake, ModelAdapter(fake, preflight=preflight)

    yield build
    for fake in fakes:
        fake.shutdown()


def test_output_limit_comes_from_the_tokenizer_and_timings_are_recorded(
    served: Served, tmp_path: Path
) -> None:
    fake, adapter = served(timed({"answer": "listing"}), timed({"answer": "sign_in"}))
    log = TimingLog(tmp_path / "timings.jsonl")
    seen: list[tuple[str, str]] = []
    asker = EvaluationAsker(
        adapter,
        profile="p",
        seconds_per_question=30,
        log=log,
        progress=lambda kind, state: seen.append((kind, state)),
    )
    decision = decide(QUESTION, asker)
    assert (decision.value, decision.rung) == ("listing", "model")
    made = decision.attempts[0]
    assert (made.prompt_ms, made.predicted_ms, made.prompt_tokens) == (1800.5, 420.0, 90)
    # The fake tokenizer counts words: the longest allowed answer, pretty-printed, is
    # four "words" ({, "answer":, "listing", }), plus the whitespace margin.
    assert fake.chats[0]["max_tokens"] == 12
    assert fake.chats[0]["cache_prompt"] is False
    assert fake.chats[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen == [("page_sort", "asking"), ("page_sort", "answered")]
    (row,) = log.rows()
    assert (row["question_type"], row["profile"], row["prompt_ms"], row["predicted_ms"]) == (
        "page_sort",
        "p",
        1800.5,
        420.0,
    )
    # Allowed answers are tokenized once, not again for the next request.
    tokenized = len([path for path, _ in fake.requests if path == "/tokenize"])
    decide(QUESTION, asker)
    assert len([path for path, _ in fake.requests if path == "/tokenize"]) == tokenized + 1


def test_a_slow_answer_is_a_resource_stop_and_leaves_no_timing(
    served: Served, tmp_path: Path
) -> None:
    _, adapter = served(HANG)
    log = TimingLog(tmp_path / "timings.jsonl")
    asker = EvaluationAsker(adapter, profile="p", seconds_per_question=0.3, log=log)
    decision = decide(QUESTION, asker)
    assert (decision.value, decision.rung, len(decision.attempts)) == (None, "stop", 1)
    assert decision.reason == "BudgetStop" and log.rows() == []


def test_production_rejects_an_unqualified_type_before_any_tokenizer_or_completion(
    served: Served,
) -> None:
    fake, adapter = served(timed({"answer": "listing"}))
    decision = decide(QUESTION, ModelAsker(adapter, profile="p", seconds_per_question=30))
    assert decision.value is None and decision.reason == "UnqualifiedQuestion"
    assert len(decision.attempts) == 1
    assert fake.requests == []


def test_expected_wait_names_unmeasured_types_instead_of_inventing_a_time(tmp_path: Path) -> None:
    log = TimingLog(tmp_path / "timings.jsonl")
    for seconds in (4.0, 6.0, 20.0):
        log.add("page_sort", "p", TextAnswer("x", True, 10, 2, seconds))
    log.add("page_sort", "other-profile", TextAnswer("x", True, 10, 2, 900.0))
    assert log.expected_seconds("page_sort", "p") == 6.0
    assert expected_wait(log, "p", [("page_sort", 2), ("step_pick", 1)], ceiling=60) == {
        "questions": 3,
        "expected_seconds": 72.0,
        "unmeasured_types": ["step_pick"],
    }
    assert expected_wait(None, "p", [("page_sort", 1)], ceiling=60)["unmeasured_types"] == [
        "page_sort"
    ]


def test_timing_log_is_bounded_and_survives_a_damaged_line(tmp_path: Path) -> None:
    path = tmp_path / "timings.jsonl"
    path.write_text('{"seconds": 1, "question_type": "a", "profile": "p"}\nnot json\n[1]\n')
    log = TimingLog(path)
    log.add("a", "p", TextAnswer("x", True, 1, 1, 3.0))
    assert [row["seconds"] for row in log.rows()] == [1, 3.0]


# --- explanations ------------------------------------------------------------------------------


class Scripted:
    def __init__(self, reply: TextAnswer | Exception) -> None:
        self.reply = reply
        self.requests: list[TextRequest] = []

    def text(self, name: str, request: TextRequest, *, max_prompt_tokens: int) -> TextAnswer:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


FALLBACK = "The account dilnoza received status 200 for /parcels/41/label."


def test_supported_wording_is_shown_and_asked_separately_from_any_decision() -> None:
    writer = Scripted(
        TextAnswer(
            "The account dilnoza could open /parcels/41/label.\nIt answered 200.", True, 1, 1, 1
        )
    )
    result = explain("The owner can read the label.", FACTS, FALLBACK, writer)
    assert result.source == "model"
    assert result.text == "The account dilnoza could open /parcels/41/label. It answered 200."
    (request,) = writer.requests
    assert request.system == EXPLAIN_SYSTEM and request.name == "explanation"
    assert request.user.startswith("Decision: The owner can read the label.\nFacts:\n- account")
    # Plain wording: no schema, so nothing can be parsed as a verdict or a citation.
    assert "response_format" not in request.body()


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (TextAnswer("The account dilnoza could open the", False, 1, 1, 1), "cut off"),
        (TextAnswer("   ", True, 1, 1, 1), "wrote nothing"),
        (ModelTimeout("slow"), "ModelTimeout"),
        (TextAnswer("The account rustam got 200.", True, 1, 1, 1), "rustam"),
        (TextAnswer("It answered 403.", True, 1, 1, 1), "403"),
        (TextAnswer("See /admin/users for details.", True, 1, 1, 1), "/admin/users"),
        (TextAnswer("Reported by evil.example.org.", True, 1, 1, 1), "evil.example.org"),
        (TextAnswer('The parcel "Golden box" leaked.', True, 1, 1, 1), "Golden box"),
    ],
)
def test_slow_cut_off_or_unsupported_wording_is_replaced_by_the_code_sentence(
    reply: TextAnswer | Exception, reason: str
) -> None:
    result = explain(
        "The owner can read the label.", FACTS, FALLBACK, Scripted(reply), universe=["rustam"]
    )
    assert (result.text, result.source) == (FALLBACK, "code")
    assert reason in str(result.reason)
    if isinstance(reply, TextAnswer) and reply.text.strip():
        assert result.raw == " ".join(reply.text.split())  # kept, never shown as accepted


def test_no_writer_means_the_code_sentence_and_a_missing_fallback_is_a_bug() -> None:
    assert explain("d", FACTS, FALLBACK, None).source == "code"
    with pytest.raises(ValueError, match="always show"):
        explain("d", FACTS, " ", None)


def test_unsupported_names_checks_numbers_addresses_quotes_and_known_names() -> None:
    facts = "account: dilnoza\npage: /parcels/41/label\nstatus: 200\nsite: https://shop.test"
    assert unsupported_names("dilnoza opened /parcels/41/label and got 200.", facts) == []
    assert unsupported_names("Visit https://shop.test for it.", facts) == []
    assert unsupported_names("Order 42 at /parcels/42/label", facts) == ["42", "/parcels/42/label"]
    assert unsupported_names("Rustam saw it", facts, ["rustam", "dilnoza"]) == ["rustam"]
