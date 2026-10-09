import time
from collections.abc import Callable, Iterator

import pytest

from agent.llm import (
    AnswerError,
    AnswerTruncated,
    BudgetStop,
    ModelAdapter,
    ModelRequest,
    ModelTimeout,
    ModelUnavailable,
    PreflightRefused,
    RequestRejected,
    Spend,
)
from backend.contracts.investigation import Budget
from backend.preflight import PreflightResult

from .fake_llama import DROP, HANG, FakeLlama, Reply, answer, error

SCHEMA = {"type": "object", "properties": {"kind": {"type": "string"}}, "required": ["kind"]}
OWNER = {"kind": "owner"}


def preflight(ok: bool = True) -> PreflightResult:
    return PreflightResult(
        ok=ok,
        model="Qwen3.5-2B",
        ctx_size=8192,
        available_bytes=0,
        requirement=None,
        message="3.1 GB free." if ok else "1.6 GB free. Close other apps.",
    )


def request(user: str = "Which checks does L1 apply?") -> ModelRequest:
    return ModelRequest(
        name="guard_summary", system="Answer one narrow question.", user=user, schema=SCHEMA
    )


def spend(**budget: float) -> Spend:
    return Spend(Budget.model_validate({"max_seconds": 30.0, **budget}))


Scripted = Callable[..., tuple[FakeLlama, ModelAdapter, list[float]]]


@pytest.fixture
def scripted() -> Iterator[Scripted]:
    """A started adapter over a fake server that plays the given replies; pauses are recorded."""
    fakes: list[FakeLlama] = []

    def build(
        *replies: Reply, attempt_seconds: float | None = None
    ) -> tuple[FakeLlama, ModelAdapter, list[float]]:
        fake, pauses = FakeLlama(*replies), []
        fakes.append(fake)
        adapter = ModelAdapter(
            fake, preflight=preflight, attempt_seconds=attempt_seconds, sleep=pauses.append
        )
        return fake, adapter, pauses

    yield build
    for fake in fakes:
        fake.shutdown()


# --- one request ---------------------------------------------------------------------------


def test_answer_is_constrained_parsed_and_charged(scripted: Scripted) -> None:
    fake, adapter, _ = scripted(answer(OWNER, prompt_tokens=41, completion_tokens=7))
    used = spend()
    result = adapter.ask(request(), used)
    assert result.data == OWNER
    assert (result.prompt_tokens, result.completion_tokens, result.attempts) == (41, 7, 1)
    assert (used.requests, used.prompt_tokens, used.completion_tokens, used.retries) == (
        1,
        41,
        7,
        0,
    )
    assert 0 < result.seconds <= used.seconds < 30
    # The whole request, so nothing can be added to it unnoticed.
    assert fake.chats == [
        {
            "messages": [
                {"role": "system", "content": "Answer one narrow question."},
                {"role": "user", "content": "Which checks does L1 apply?"},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "guard_summary", "schema": SCHEMA, "strict": True},
            },
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 512,
            "temperature": 0.0,
            "seed": 42,
            "cache_prompt": False,
        }
    ]


def test_requests_are_stateless(scripted: Scripted) -> None:
    fake, adapter, _ = scripted(answer(OWNER), answer(OWNER))
    used = spend()
    adapter.ask(request("First question about canary-7f3a."), used)
    adapter.ask(request("Second question."), used)
    first, second = fake.chats
    for body in (first, second):
        assert body["cache_prompt"] is False
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        assert not {"id_slot", "session", "conversation_id"} & set(body)
    assert "canary-7f3a" not in str(second)
    assert used.requests == 2


def test_missing_usage_is_charged_at_the_counted_size(scripted: Scripted) -> None:
    _, adapter, _ = scripted(answer(OWNER, prompt_tokens=None))
    used = spend()
    result = adapter.ask(request("one two three"), used)
    # "Answer one narrow question." + "one two three" in the fake's word tokens.
    assert result.prompt_tokens == used.prompt_tokens == 7


# --- retries -------------------------------------------------------------------------------


def test_transient_failures_are_retried_and_their_pauses_charged(scripted: Scripted) -> None:
    fake, adapter, pauses = scripted(error(503, "Loading model"), DROP, answer(OWNER))
    used = spend(max_retries=2)
    result = adapter.ask(request(), used)
    assert result.data == OWNER
    assert (result.attempts, used.retries, len(fake.chats)) == (3, 2, 3)
    assert pauses == [0.5, 2.0]
    assert used.seconds >= sum(pauses)
    assert fake.chats[0] == fake.chats[1] == fake.chats[2]


def test_the_retry_allowance_ends_with_the_failure_that_kept_happening(
    scripted: Scripted,
) -> None:
    fake, adapter, _ = scripted(error(503), error(503), error(503), answer(OWNER))
    used = spend(max_retries=2)
    with pytest.raises(ModelUnavailable, match="503"):
        adapter.ask(request(), used)
    assert (used.retries, len(fake.chats), used.requests) == (2, 3, 0)


def test_retries_are_counted_across_the_question(scripted: Scripted) -> None:
    fake, adapter, _ = scripted(error(500), answer(OWNER), DROP, answer(OWNER))
    used = spend(max_retries=1)
    assert adapter.ask(request(), used).attempts == 2
    with pytest.raises(ModelUnavailable, match="did not answer"):
        adapter.ask(request(), used)
    assert (used.retries, used.requests, len(fake.chats)) == (1, 1, 3)


@pytest.mark.parametrize("status", [400, 401, 404])
def test_refused_requests_are_not_retried(scripted: Scripted, status: int) -> None:
    fake, adapter, _ = scripted(error(status, "the request exceeds the context"), answer(OWNER))
    used = spend(max_retries=2)
    with pytest.raises(RequestRejected, match=str(status)):
        adapter.ask(request(), used)
    assert (used.retries, len(fake.chats)) == (0, 1)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (answer('{"kind": "own', finish_reason="length"), AnswerTruncated),
        (answer("not json"), AnswerError),
        (answer(["owner"]), AnswerError),
        (Reply(body={"choices": []}), AnswerError),
        (Reply(body=["not", "an", "object"]), AnswerError),
    ],
)
def test_unusable_answers_are_not_retried_but_still_charged(
    scripted: Scripted, reply: Reply, expected: type[AnswerError]
) -> None:
    fake, adapter, _ = scripted(reply, answer(OWNER))
    used = spend(max_retries=2)
    with pytest.raises(expected) as raised:
        adapter.ask(request(), used)
    assert type(raised.value) is expected
    assert (used.retries, len(fake.chats)) == (0, 1)
    if isinstance(reply.body, dict) and "usage" in reply.body:
        assert (used.requests, used.prompt_tokens) == (1, 20)


# --- timeouts ------------------------------------------------------------------------------


def test_a_stalled_attempt_times_out_and_is_retried(scripted: Scripted) -> None:
    fake, adapter, pauses = scripted(HANG, answer(OWNER), attempt_seconds=0.5)
    used = spend(max_retries=1)
    result = adapter.ask(request(), used)
    assert result.data == OWNER
    assert (result.attempts, used.retries, len(fake.chats)) == (2, 1, 2)
    assert used.seconds >= 0.5 + pauses[0]
    assert result.seconds < 0.5  # the answering attempt, not the stalled one


def test_timeouts_without_a_retry_left_fail_as_timeouts(scripted: Scripted) -> None:
    fake, adapter, _ = scripted(HANG, HANG, answer(OWNER), attempt_seconds=0.2)
    used = spend(max_retries=1)
    with pytest.raises(ModelTimeout, match=r"within 0\.2 s"):
        adapter.ask(request(), used)
    assert (used.retries, len(fake.chats), used.requests) == (1, 2, 0)


# --- budget stops --------------------------------------------------------------------------


def test_the_time_budget_stops_a_request_that_never_answers(scripted: Scripted) -> None:
    fake, adapter, _ = scripted(HANG, answer(OWNER))
    used = spend(max_seconds=0.3, max_retries=5)
    started = time.perf_counter()
    with pytest.raises(BudgetStop, match=r"0\.3 s time budget") as stop:
        adapter.ask(request(), used)
    assert stop.value.reason == "seconds"
    assert isinstance(stop.value.__cause__, ModelTimeout)
    assert time.perf_counter() - started < 5
    assert (len(fake.chats), used.retries) == (1, 0)
    assert used.seconds_left <= 0
    # Nothing more is sent for this question, not even a token count.
    sent = len(fake.requests)
    with pytest.raises(BudgetStop):
        adapter.ask(request(), used)
    assert len(fake.requests) == sent


def test_a_retry_pause_that_would_outlast_the_time_budget_stops_instead(
    scripted: Scripted,
) -> None:
    fake, adapter, pauses = scripted(error(503), error(503), answer(OWNER))
    used = spend(max_seconds=1.5, max_retries=5)
    with pytest.raises(BudgetStop) as stop:
        adapter.ask(request(), used)
    assert stop.value.reason == "seconds"
    assert isinstance(stop.value.__cause__, ModelUnavailable)
    # The first pause (0.5 s) fits; the second (2.0 s) does not, so it is never taken.
    assert pauses == [0.5]
    assert (len(fake.chats), used.retries) == (2, 1)


def test_the_prompt_budget_stops_before_anything_is_generated(scripted: Scripted) -> None:
    fake, adapter, _ = scripted(answer(OWNER))
    used = spend(max_prompt_tokens=6)
    with pytest.raises(BudgetStop, match="at least 7 prompt tokens") as stop:
        adapter.ask(request("one two three"), used)
    assert stop.value.reason == "prompt_tokens"
    assert fake.chats == []
    assert (used.requests, used.prompt_tokens) == (0, 0)


def test_the_prompt_budget_is_shared_by_a_questions_requests(scripted: Scripted) -> None:
    fake, adapter, _ = scripted(answer(OWNER, prompt_tokens=30), answer(OWNER, prompt_tokens=30))
    used = spend(max_prompt_tokens=36)
    adapter.ask(request("one two three"), used)
    assert used.prompt_tokens_left == 6
    with pytest.raises(BudgetStop, match="has 6 of its 36 left"):
        adapter.ask(request("one two three"), used)
    assert len(fake.chats) == 1
    # A new question starts with its own budget.
    assert adapter.ask(request("one two three"), spend(max_prompt_tokens=36)).data == OWNER


# --- preflight -----------------------------------------------------------------------------


def test_a_refused_preflight_never_starts_the_server() -> None:
    fake = FakeLlama(answer(OWNER))
    try:
        adapter = ModelAdapter(fake, preflight=lambda: preflight(ok=False))
        with pytest.raises(PreflightRefused, match="Close other apps") as refused:
            adapter.ask(request(), spend())
        assert refused.value.result.ok is False
        with pytest.raises(PreflightRefused), adapter:
            pytest.fail("the adapter must not open")
        assert (fake.starts, fake.stops, fake.requests) == (0, 0, [])
    finally:
        fake.shutdown()


def test_preflight_runs_once_and_the_server_is_stopped_on_close() -> None:
    fake, checks = FakeLlama(answer(OWNER), answer(OWNER)), []

    def check() -> PreflightResult:
        checks.append(fake.starts)
        return preflight()

    try:
        with ModelAdapter(fake, preflight=check) as adapter:
            adapter.ask(request(), spend())
            adapter.ask(request(), spend())
            assert (fake.starts, fake.stops) == (1, 0)
        assert checks == [0]  # asked before the server was started, and only then
        assert (fake.starts, fake.stops) == (1, 1)
        adapter.close()
        assert fake.stops == 1
    finally:
        fake.shutdown()


def test_adapter_settings_are_checked() -> None:
    fake = FakeLlama()
    try:
        with pytest.raises(ValueError, match="attempt_seconds"):
            ModelAdapter(fake, preflight=preflight, attempt_seconds=0)
        for pauses in ((), (-1.0,)):
            with pytest.raises(ValueError, match="retry_pauses"):
                ModelAdapter(fake, preflight=preflight, retry_pauses=pauses)
    finally:
        fake.shutdown()
