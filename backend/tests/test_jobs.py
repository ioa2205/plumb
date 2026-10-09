import contextlib
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import pytest
from pydantic import JsonValue

from agent.llm import BudgetStop, ModelUnavailable, PreflightRefused, Spend
from backend.contracts.investigation import Budget, Question, QuestionStage, QuestionStatus
from backend.contracts.runs import (
    ConditionKind,
    Coverage,
    EventKind,
    ReviewRun,
    RunEvent,
    RunLifecycle,
    RunStage,
)
from backend.jobs import Engine, Handler, Step, WorkerBusy, WorkerLock
from backend.preflight import PreflightResult
from backend.run_store import Draft, RunStore

from .job_worker import PATH, logged_handlers

Stage = QuestionStage
RUN = "run:1"
SNAP = "a" * 64
T0 = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
STAGES = [stage.value for stage in PATH]


def question(name: str, **fields: object) -> Question:
    data = {
        "id": name,
        "run_id": RUN,
        "type": "guard_summary",
        "family": "authorization",
        "stage": "frame",
        "status": "pending",
        "subject_ids": [f"site:{name}"],
        "evidence": [],
        **fields,
    }
    return Question.model_validate(data)


def queued(store: RunStore, *names: str, excluded: int = 0, **fields: object) -> None:
    coverage = Coverage(total=len(names) + excluded, pending=len(names), excluded=excluded)
    run = ReviewRun(
        id=RUN,
        snapshot_id=SNAP,
        run_type="live",
        lifecycle="queued",
        created_at=T0,
        coverage=coverage,
    )
    store.create(run, [question(name, **fields) for name in names])


class Clock:
    """One second later every time it is read, so the order of records is visible."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "runs.sqlite")


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / "stages.log"


def calls(log: Path) -> list[tuple[str, str]]:
    """(question, stage) of every handler call, in order."""
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [(line.split()[1], line.split()[2]) for line in lines]


def engine(store: RunStore, log: Path, **overrides: Handler) -> Engine:
    handlers = logged_handlers(log)
    handlers.update({Stage(name): handler for name, handler in overrides.items()})
    return Engine(store, handlers, clock=Clock())


def status_of(store: RunStore) -> dict[str, tuple[str, str]]:
    return {q.id: (q.status.value, q.stage.value) for q in store.questions(RUN)}


def entered(store: RunStore) -> list[str]:
    """The stages the run's questions entered, in order."""
    return [
        event.stage.value
        for event in store.events(RUN)
        if event.kind is EventKind.QUESTION_STAGE and event.stage is not None
    ]


def saved_run(store: RunStore) -> ReviewRun:
    run = store.run(RUN)
    assert run is not None
    return run


def gapless(events: list[RunEvent]) -> bool:
    return [event.seq for event in events] == list(range(1, len(events) + 1))


# --- the straight path ---------------------------------------------------------------------


def test_questions_run_in_queue_order_through_every_stage(store: RunStore, log: Path) -> None:
    queued(store, "q1", "q2", excluded=1)
    run = engine(store, log).run(RUN)
    assert calls(log) == [(name, stage) for name in ("q1", "q2") for stage in STAGES]
    assert (run.lifecycle, run.stage, run.finished_at is not None) == (
        RunLifecycle.COMPLETED,
        None,
        True,
    )
    assert run.coverage == Coverage(total=3, completed=2, pending=0, excluded=1)
    assert store.run(RUN) == run
    for saved in store.questions(RUN):
        assert (saved.status, saved.stage) == (QuestionStatus.ANSWERED, Stage.RECORD)
        assert saved.answer == {"trail": STAGES}  # each stage got what the one before left


def test_every_transition_is_announced_once_in_order(store: RunStore, log: Path) -> None:
    queued(store, "q1")
    engine(store, log).run(RUN)
    events = store.events(RUN)
    assert gapless(events)
    assert [event.at for event in events] == sorted(event.at for event in events)
    told = [
        (event.kind.value, event.stage.value if event.stage else None, event.message)
        for event in events
    ]
    assert told == [
        ("run.started", None, None),
        ("question.started", None, None),
        ("question.stage", "frame", None),
        ("question.activity", "frame", "Ran frame for q1"),
        ("question.stage", "gather", None),
        ("question.activity", "gather", "Ran gather for q1"),
        ("question.stage", "hypothesize", None),
        ("question.activity", "hypothesize", "Ran hypothesize for q1"),
        ("question.stage", "challenge", None),
        ("question.activity", "challenge", "Ran challenge for q1"),
        ("question.stage", "decide", None),
        ("question.activity", "decide", "Ran decide for q1"),
        ("question.stage", "record", None),
        ("question.activity", "record", "Ran record for q1"),
        ("question.finished", "record", None),
        ("run.completed", None, None),
    ]
    finished = events[-2]
    assert finished.status is QuestionStatus.ANSWERED
    assert finished.coverage == Coverage(total=1, completed=1)
    assert [event.coverage is not None for event in events] == [True] + [False] * 13 + [True, True]
    assert store.events(RUN, after=14) == events[14:]
    assert store.events(RUN, after=99) == []


def test_what_a_question_spent_travels_with_its_checkpoint(store: RunStore, log: Path) -> None:
    queued(store, "q1")
    seen: list[int] = []

    def decide(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        seen.append(spend.prompt_tokens)
        spend.retries += 1
        return Step(next=Stage.RECORD, state=dict(state))

    engine(store, log, decide=decide).run(RUN)
    assert seen == [400]  # 100 for each of the four stages before it
    spent = store.state(RUN, "q1")["spend"]
    assert spent == {
        "requests": 0,
        "prompt_tokens": 500,
        "completion_tokens": 0,
        "seconds": 0.0,
        "retries": 1,
    }


# --- the order of stages and the budget of looks -------------------------------------------


def test_gathering_stops_at_the_questions_limit_of_looks(store: RunStore, log: Path) -> None:
    queued(store, "q1", budget=Budget(max_looks=3))

    def gather(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        looks = [*state.get("looks", []), "look"]  # ty: ignore[not-iterable]
        return Step(next=Stage.GATHER, state={"looks": looks, "trail": []})

    engine(store, log, gather=gather).run(RUN)
    stages = entered(store)
    assert stages == [
        "frame",
        "gather",
        "gather",
        "gather",
        "hypothesize",
        "challenge",
        "decide",
        "record",
    ]
    messages = [event.message for event in store.events(RUN) if event.message]
    assert "Stopped gathering after 3 looks, the limit for a question." in messages
    assert store.questions(RUN)[0].status is QuestionStatus.ANSWERED


def test_a_question_may_stop_gathering_early_and_may_verify(store: RunStore, log: Path) -> None:
    queued(store, "q1")

    def decide(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        return Step(next=Stage.VERIFY, state=dict(state))

    def verify(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        return Step(next=Stage.RECORD, state=dict(state), activity=("Ran the probe",))

    engine(store, log, decide=decide, verify=verify).run(RUN)
    stages = entered(store)
    assert stages == ["frame", "gather", "hypothesize", "challenge", "decide", "verify", "record"]


@pytest.mark.parametrize(
    ("stage", "following"),
    [
        ("frame", Stage.HYPOTHESIZE),
        ("gather", Stage.DECIDE),
        ("hypothesize", Stage.RECORD),
        ("challenge", Stage.GATHER),
        ("decide", Stage.CHALLENGE),
        ("record", Stage.FRAME),
        ("decide", None),
    ],
)
def test_a_stage_cannot_skip_or_go_back(
    store: RunStore, log: Path, stage: str, following: Stage | None
) -> None:
    queued(store, "q1", "q2")

    def wrong(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        return Step(next=following, state=dict(state))

    run = engine(store, log, **{stage: wrong}).run(RUN)
    assert status_of(store) == {"q1": ("failed", stage), "q2": ("failed", stage)}
    assert run.lifecycle is RunLifecycle.COMPLETED
    message = store.events(RUN)[-2].message
    assert message == f"The {stage} stage named a next stage that cannot follow it."


def test_a_missing_handler_fails_the_question_not_the_worker(store: RunStore, log: Path) -> None:
    queued(store, "q1")
    handlers = logged_handlers(log)
    del handlers[Stage.CHALLENGE]
    Engine(store, handlers, clock=Clock()).run(RUN)
    assert status_of(store) == {"q1": ("failed", "challenge")}
    assert store.events(RUN)[-2].message == "No handler is installed for the challenge stage."


# --- how a question can end ----------------------------------------------------------------


@pytest.mark.parametrize("status", ["rejected_by_validator", "inconclusive"])
def test_a_stage_may_end_the_question_without_an_answer(
    store: RunStore, log: Path, status: str
) -> None:
    queued(store, "q1", "q2")

    def hypothesize(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if asked.id == "q2":
            return Step(next=Stage.CHALLENGE, state=dict(state))
        return Step(status=QuestionStatus(status), activity=("The answer cited L99",))

    run = engine(store, log, hypothesize=hypothesize).run(RUN)
    assert status_of(store) == {"q1": (status, "hypothesize"), "q2": ("answered", "record")}
    assert store.questions(RUN)[0].answer is None
    assert run.coverage == Coverage(total=2, completed=2)
    assert ("q1", "challenge") not in calls(log)


@pytest.mark.parametrize(
    "step",
    [
        Step(status=QuestionStatus.ANSWERED),  # answered, with no answer
        Step(status=QuestionStatus.INCONCLUSIVE, answer={"kind": "owner"}),
        Step(status=QuestionStatus.CANCELED),  # the worker's to say, not a stage's
        Step(status=QuestionStatus.FAILED),
        Step(status=QuestionStatus.BUDGET_EXHAUSTED),
        Step(status=QuestionStatus.PENDING),
        Step(status=QuestionStatus.INCONCLUSIVE, next=Stage.RECORD),
    ],
)
def test_a_stage_cannot_end_a_question_in_a_way_that_is_not_its_to_say(
    store: RunStore, log: Path, step: Step
) -> None:
    queued(store, "q1")
    engine(store, log, record=lambda asked, state, spend: step).run(RUN)
    assert status_of(store) == {"q1": ("failed", "record")}
    assert store.questions(RUN)[0].answer is None
    message = store.events(RUN)[-2].message
    assert message == "The record stage ended the question in a way it may not."


def test_running_out_of_budget_ends_the_question_and_the_run_goes_on(
    store: RunStore, log: Path
) -> None:
    queued(store, "q1", "q2")

    def gather(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if asked.id == "q1":
            raise BudgetStop("seconds", "The question used its 120 s time budget.")
        return Step(next=Stage.HYPOTHESIZE, state=dict(state))

    run = engine(store, log, gather=gather).run(RUN)
    assert status_of(store) == {"q1": ("budget_exhausted", "gather"), "q2": ("answered", "record")}
    assert run.lifecycle is RunLifecycle.COMPLETED
    finished = next(e for e in store.events(RUN) if e.status is QuestionStatus.BUDGET_EXHAUSTED)
    assert finished.message == "The question used its 120 s time budget."


def test_an_error_in_a_stage_is_recorded_without_its_details(
    store: RunStore, log: Path, caplog: pytest.LogCaptureFixture
) -> None:
    queued(store, "q1", "q2")

    def challenge(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if asked.id == "q1":
            raise ZeroDivisionError("D:/plumb-data/secret/path")
        raise ModelUnavailable("The model server answered 503.")

    engine(store, log, challenge=challenge).run(RUN)
    assert status_of(store) == {"q1": ("failed", "challenge"), "q2": ("failed", "challenge")}
    messages = [event.message for event in store.events(RUN) if event.status]
    assert messages == [
        "The challenge stage stopped on an error: ZeroDivisionError.",
        "The model server answered 503.",
    ]
    # The details go to the terminal's log, not into the run's record.
    assert "secret/path" in caplog.text
    assert "secret" not in "".join(event.model_dump_json() for event in store.events(RUN))


def test_three_failures_in_a_row_stop_the_run_and_keep_the_rest(store: RunStore, log: Path) -> None:
    queued(store, "q1", "q2", "q3", "q4", "q5", "q6", "q7")
    failing = {"q2", "q4", "q5", "q6"}  # one alone, then three together

    def frame(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if asked.id in failing:
            raise ModelUnavailable("The model server did not answer.")
        return Step(next=Stage.GATHER, state={"trail": ["frame"]})

    run = engine(store, log, frame=frame).run(RUN)
    assert (run.lifecycle, run.stage, run.finished_at is not None) == (
        RunLifecycle.FAILED,
        None,
        True,
    )
    assert [status for status, _ in status_of(store).values()] == [
        "answered",
        "failed",
        "answered",
        "failed",
        "failed",
        "failed",
        "pending",
    ]
    assert run.coverage == Coverage(total=7, completed=6, pending=1)
    last = store.events(RUN)[-1]
    assert last.kind is EventKind.RUN_FAILED
    assert last.message == (
        "3 questions failed in a row, so the run stopped. The results so far are kept."
    )
    # A run that has ended is not worked on again.
    before = calls(log)
    assert engine(store, log).run(RUN) == run
    assert calls(log) == before


# --- memory, cancel and pause --------------------------------------------------------------


def refusal(suggestion: str | None) -> PreflightRefused:
    return PreflightRefused(
        PreflightResult(
            ok=False,
            model="Qwen3.5-2B",
            ctx_size=8192,
            available_bytes=0,
            requirement=None,
            message="0.9 GB free. Qwen3.5-2B needs about 2.4 GB. Close other apps.",
            suggestion=suggestion,
        )
    )


def test_a_model_that_does_not_fit_pauses_the_run_with_the_reason(
    store: RunStore, log: Path
) -> None:
    queued(store, "q1", "q2")
    memory = {"free": False}

    def gather(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if not memory["free"]:
            raise refusal("Qwen3.5-0.8B")
        return Step(next=Stage.HYPOTHESIZE, state=dict(state))

    worker = engine(store, log, gather=gather)
    run = worker.run(RUN)
    assert (run.lifecycle, run.stage, run.finished_at) == (
        RunLifecycle.PAUSED,
        RunStage.INVESTIGATING,
        None,
    )
    (condition,) = run.conditions
    assert (condition.kind, condition.action) == (ConditionKind.MODEL_TOO_LARGE, "Switch model")
    assert condition.message.startswith("0.9 GB free.")
    # Nothing is lost and nothing is marked failed: the question waits at its stage.
    assert status_of(store) == {"q1": ("running", "gather"), "q2": ("pending", "frame")}
    assert store.events(RUN)[-1].kind is EventKind.RUN_PAUSED
    assert store.events(RUN)[-1].message == condition.message

    assert worker.run(RUN).lifecycle is RunLifecycle.PAUSED  # still no room
    assert len(saved_run(store).conditions) == 1  # the reason is not piled up
    memory["free"] = True
    run = worker.run(RUN)
    assert (run.lifecycle, run.conditions) == (RunLifecycle.COMPLETED, [])
    assert status_of(store) == {"q1": ("answered", "record"), "q2": ("answered", "record")}
    assert calls(log).count(("q1", "frame")) == 1


def test_cancel_keeps_what_is_done_and_marks_the_rest(store: RunStore, log: Path) -> None:
    queued(store, "q1", "q2", "q3")

    def gather(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if asked.id == "q2":
            assert store.request(RUN, "cancel")
        return Step(next=Stage.HYPOTHESIZE, state=dict(state), activity=("Looked once",))

    run = engine(store, log, gather=gather).run(RUN)
    assert (run.lifecycle, run.stage, run.finished_at is not None) == (
        RunLifecycle.CANCELED,
        None,
        True,
    )
    # The stage that was running finished and was saved; then the run stopped.
    assert status_of(store) == {
        "q1": ("answered", "record"),
        "q2": ("canceled", "hypothesize"),
        "q3": ("canceled", "frame"),
    }
    assert store.questions(RUN)[0].answer is not None
    assert run.coverage == Coverage(total=3, completed=1, pending=2)
    events = store.events(RUN)
    assert gapless(events)
    assert [(e.kind.value, e.question_id) for e in events[-4:]] == [
        ("question.stage", "q2"),
        ("question.finished", "q2"),
        ("question.finished", "q3"),
        ("run.canceled", None),
    ]
    assert len({event.at for event in events[-3:]}) == 1  # one transaction
    assert store.requested(RUN) is None
    assert store.request(RUN, "cancel") is False  # nothing left to cancel
    assert ("q3", "frame") not in calls(log)


def test_pause_stops_at_the_checkpoint_and_resume_continues_from_it(
    store: RunStore, log: Path
) -> None:
    queued(store, "q1", "q2")
    challenged: list[str] = []

    def challenge(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        challenged.append(asked.id)
        if asked.id == "q1":
            assert store.request(RUN, "pause")
        return Step(next=Stage.DECIDE, state=dict(state))

    worker = engine(store, log, challenge=challenge)
    paused = worker.run(RUN)
    assert (paused.lifecycle, paused.stage) == (RunLifecycle.PAUSED, RunStage.INVESTIGATING)
    assert status_of(store) == {"q1": ("running", "decide"), "q2": ("pending", "frame")}
    assert store.requested(RUN) is None
    done = len(calls(log))

    run = worker.run(RUN)
    assert run.lifecycle is RunLifecycle.COMPLETED
    assert run.started_at == paused.started_at
    assert calls(log)[done:][0] == ("q1", "decide")  # not from the start, not the same stage twice
    assert challenged == ["q1", "q2"]
    kinds = [event.kind.value for event in store.events(RUN) if event.kind.value.startswith("run.")]
    assert kinds == ["run.started", "run.paused", "run.resumed", "run.completed"]
    assert gapless(store.events(RUN))


def test_a_cancel_is_never_replaced_by_a_pause_and_waits_for_a_paused_run(
    store: RunStore, log: Path
) -> None:
    queued(store, "q1", "q2")
    framed: list[str] = []

    def frame(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        framed.append(asked.id)
        store.request(RUN, "pause")
        return Step(next=Stage.GATHER, state={"trail": ["frame"]})

    worker = engine(store, log, frame=frame)
    assert worker.run(RUN).lifecycle is RunLifecycle.PAUSED
    assert store.request(RUN, "cancel") and store.request(RUN, "pause")
    assert store.requested(RUN) == "cancel"
    run = worker.run(RUN)
    assert run.lifecycle is RunLifecycle.CANCELED
    assert status_of(store) == {"q1": ("canceled", "gather"), "q2": ("canceled", "frame")}
    assert framed == ["q1"] and calls(log) == []


# --- one worker, and the store's own rules -------------------------------------------------


def test_only_one_worker_runs_at_a_time(store: RunStore, log: Path) -> None:
    queued(store, "q1")
    lock = store.path.with_suffix(".lock")
    with WorkerLock(lock):
        with pytest.raises(WorkerBusy, match="One runs at a time"):
            engine(store, log).run(RUN)
        assert calls(log) == []
    assert engine(store, log).run(RUN).lifecycle is RunLifecycle.COMPLETED
    with WorkerLock(lock):
        pass  # released again after the run


def test_the_store_refuses_what_does_not_belong_to_the_run(store: RunStore, log: Path) -> None:
    queued(store, "q1", "q2")
    run = store.run(RUN)
    assert run is not None
    with pytest.raises(KeyError, match="not a run"):
        engine(store, log).run("run:missing")
    with pytest.raises(KeyError, match="not a question"):
        store.record(run, T0, questions=[question("q9")])
    with pytest.raises(ValueError, match="exactly one question"):
        store.record(run, T0, questions=store.questions(RUN), state={})
    with pytest.raises(ValueError, match="belongs to the run"):
        store.create(run.model_copy(update={"id": "run:2"}), [question("q1")])
    # A refused write leaves nothing behind, not even its events.
    with pytest.raises(KeyError):
        store.record(run, T0, questions=[question("q9")], events=[Draft(EventKind.RUN_PAUSED)])
    assert store.events(RUN) == []
    assert store.run("run:2") is None
    assert store.request("run:missing", "cancel") is False


def test_reading_a_store_that_was_never_written_creates_no_file(tmp_path: Path) -> None:
    empty = RunStore(tmp_path / "none" / "runs.sqlite")
    assert empty.run(RUN) is None
    assert empty.questions(RUN) == [] and empty.events(RUN) == []
    assert empty.requested(RUN) is None and empty.request(RUN, "cancel") is False
    assert not (tmp_path / "none").exists()


def test_a_refused_transition_rolls_back_every_earlier_write(store: RunStore) -> None:
    queued(store, "q1", "q2")
    before = saved_run(store)
    questions = store.questions(RUN)
    assert store.request(RUN, "cancel")
    changed = before.model_copy(update={"coverage": Coverage(total=3, pending=2, excluded=1)})
    moved = questions[0].model_copy(
        update={"status": QuestionStatus.RUNNING, "stage": Stage.GATHER}
    )
    # The run, control request, and first question are written before the missing question
    # is refused. All of those writes must roll back together.
    with pytest.raises(KeyError, match="not a question"):
        store.record(
            changed,
            T0,
            questions=[moved, question("missing")],
            events=[Draft(EventKind.RUN_PAUSED)],
            clear_request=True,
        )
    assert store.run(RUN) == before
    assert store.questions(RUN) == questions
    assert store.requested(RUN) == "cancel"
    assert store.events(RUN) == []


def test_same_question_id_in_another_run_cannot_be_changed(store: RunStore) -> None:
    queued(store, "shared")
    first = saved_run(store)
    other = first.model_copy(update={"id": "run:2"})
    other_question = question("shared", run_id=other.id)
    store.create(other, [other_question])
    moved = question("shared", status="running", stage="gather")
    store.record(first, T0, questions=[moved], state={"checkpoint": "first run"})
    assert store.questions(RUN) == [moved]
    assert store.state(RUN, "shared") == {"checkpoint": "first run"}
    assert store.questions(other.id) == [other_question]
    assert store.state(other.id, "shared") == {}
    assert store.run(other.id) == other
    assert store.events(other.id) == []


# --- a killed process resumes from its checkpoint ------------------------------------------


def worker_process(store: RunStore, log: Path, hang: str | None = None) -> subprocess.Popen[str]:
    command = [sys.executable, "-m", "backend.tests.job_worker", str(store.path), RUN, str(log)]
    return subprocess.Popen(  # noqa: S603 - this repository's own test worker
        [*command, hang] if hang else command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_a_killed_worker_resumes_from_its_checkpoint(store: RunStore, log: Path) -> None:
    queued(store, "q1", "q2", "q3")
    first = worker_process(store, log, hang="q2:challenge")
    try:
        deadline = time.monotonic() + 60
        while ("q2", "challenge") not in calls(log):
            assert first.poll() is None, first.stderr.read() if first.stderr else ""
            assert time.monotonic() < deadline, "the worker never reached the stage"
            time.sleep(0.05)
    finally:
        # The interpreter that does the work may be a child of the one that was started.
        killed_pid = log.read_text(encoding="utf-8").split()[0] if log.exists() else str(first.pid)
        for pid in {int(killed_pid), first.pid}:
            with contextlib.suppress(psutil.Error):
                psutil.Process(pid).kill()
        first.wait(timeout=30)

    # What the dead worker had saved: the run is still marked running, q1 is complete, and
    # q2 stands at the stage it was in, with what the earlier stages left for it.
    interrupted = store.run(RUN)
    assert interrupted is not None and interrupted.lifecycle is RunLifecycle.RUNNING
    assert status_of(store) == {
        "q1": ("answered", "record"),
        "q2": ("running", "challenge"),
        "q3": ("pending", "frame"),
    }
    assert store.state(RUN, "q2")["data"] == {"trail": ["frame", "gather", "hypothesize"]}
    assert store.state(RUN, "q2")["spend"]["prompt_tokens"] == 300  # ty: ignore[not-subscriptable, invalid-argument-type]
    before = store.events(RUN)
    assert gapless(before)
    assert before[-1].kind is EventKind.QUESTION_STAGE and before[-1].stage is Stage.CHALLENGE

    second = worker_process(store, log)
    out, err = second.communicate(timeout=120)
    assert (second.returncode, out.strip()) == (0, "completed"), err

    run = store.run(RUN)
    assert run is not None and run.lifecycle is RunLifecycle.COMPLETED
    assert run.coverage == Coverage(total=3, completed=3)
    assert run.started_at == interrupted.started_at
    for saved in store.questions(RUN):
        assert saved.status is QuestionStatus.ANSWERED
        assert saved.answer == {"trail": STAGES}  # nothing lost, nothing counted twice
    assert store.state(RUN, "q2")["spend"]["prompt_tokens"] == 600  # ty: ignore[not-subscriptable, invalid-argument-type]

    # Only the stage that was interrupted ran twice; finished work was not repeated.
    ran = calls(log)
    assert ran.count(("q2", "challenge")) == 2
    assert all(ran.count(call) == 1 for call in set(ran) - {("q2", "challenge")})
    resumed = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
    after_kill = [(name, stage) for pid, name, stage in resumed if pid != killed_pid]
    assert after_kill == [("q2", stage) for stage in STAGES[3:]] + [
        ("q3", stage) for stage in STAGES
    ]

    # The log of events continues where it stopped: no gap, nothing announced twice.
    events = store.events(RUN)
    assert events[: len(before)] == before and gapless(events)
    assert events[len(before)].kind is EventKind.RUN_RESUMED
    entered = [(e.question_id, e.stage) for e in events if e.kind is EventKind.QUESTION_STAGE]
    assert len(entered) == len(set(entered)) == 18
    assert events[-1].kind is EventKind.RUN_COMPLETED
