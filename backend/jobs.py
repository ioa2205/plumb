"""The worker: runs a queue of questions through the investigation state machine.

    FRAME -> GATHER (up to max_looks) -> HYPOTHESIZE -> CHALLENGE -> DECIDE -> [VERIFY] -> RECORD

One worker processes one question at a time, one stage at a time (PROJECT_PLAN
§5). After every stage it saves the question, the state it carries into the
next stage, and the events that announce the change, in one transaction. That
saved point is the checkpoint: cancel and pause take effect there, and a
process that was killed continues from there.

A stage that was running when the process died runs again from its start, so a
stage may run more than once and must not depend on having run only once. What
a question has already spent of its budget is part of the checkpoint.

What each stage does is not decided here. Stage handlers are plugged in; this
module owns the order of stages, the budget of looks, how failures end a
question, and the run's lifecycle.
"""

import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from pydantic import JsonValue

from agent.llm import BudgetStop, ModelError, PreflightRefused, Spend
from backend.contracts.investigation import Question, QuestionStage, QuestionStatus
from backend.contracts.runs import (
    TERMINAL,
    Condition,
    ConditionKind,
    Coverage,
    EventKind,
    ReviewRun,
    RunLifecycle,
    RunStage,
)
from backend.run_store import Draft, RunStore

Stage = QuestionStage
_NEXT: dict[Stage, frozenset[Stage]] = {
    Stage.FRAME: frozenset({Stage.GATHER}),
    Stage.GATHER: frozenset({Stage.GATHER, Stage.HYPOTHESIZE}),
    Stage.HYPOTHESIZE: frozenset({Stage.CHALLENGE}),
    Stage.CHALLENGE: frozenset({Stage.DECIDE}),
    Stage.DECIDE: frozenset({Stage.VERIFY, Stage.RECORD}),
    Stage.VERIFY: frozenset({Stage.RECORD}),
    Stage.RECORD: frozenset(),
}
# How a handler may end a question. Canceled, failed and out-of-budget are the worker's to say.
_HANDLER_ENDINGS = frozenset(
    {QuestionStatus.ANSWERED, QuestionStatus.REJECTED_BY_VALIDATOR, QuestionStatus.INCONCLUSIVE}
)
_UNFINISHED = frozenset({QuestionStatus.PENDING, QuestionStatus.RUNNING, QuestionStatus.CANCELED})
_SPENT = ("requests", "prompt_tokens", "completion_tokens", "seconds", "retries")

_LOG = logging.getLogger("plumb.jobs")


@dataclass(frozen=True)
class Step:
    """What a stage hands back: the next stage, or how the question ends.

    ``state`` is what the next stage will be given; it must be JSON. ``activity``
    is a list of facts for the activity log ("Read services/orders.py:1-30").
    """

    next: Stage | None = None
    state: Mapping[str, JsonValue] = field(default_factory=dict)
    activity: tuple[str, ...] = ()
    status: QuestionStatus | None = None
    answer: Mapping[str, JsonValue] | None = None


Handler = Callable[[Question, Mapping[str, JsonValue], Spend], Step]


class WorkerBusy(RuntimeError):
    """Another worker is already processing runs of this store."""


class WorkerLock:
    """A lock the operating system drops when the process dies, however it dies."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: IO[bytes] | None = None

    def __enter__(self) -> Self:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        try:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise WorkerBusy("A review is already running. One runs at a time.") from error
        self._file = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._file is not None:
            self._file.close()  # closing the handle releases the lock
            self._file = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Engine:
    def __init__(
        self,
        store: RunStore,
        handlers: Mapping[Stage, Handler],
        *,
        clock: Callable[[], datetime] = _utc_now,
        failures_before_stop: int = 3,
    ) -> None:
        self._store = store
        self._handlers = dict(handlers)
        self._clock = clock
        self._failures_before_stop = failures_before_stop

    def run(self, run_id: str) -> ReviewRun:
        """Work on the run until it completes, pauses, is canceled, or fails."""
        with WorkerLock(self._store.path.with_suffix(".lock")):
            run = self._store.run(run_id)
            if run is None:
                raise KeyError(f"{run_id} is not a run of this store")
            if run.lifecycle in TERMINAL:
                return run
            run = self._begin(run)
            failures = 0
            while run.lifecycle is RunLifecycle.RUNNING:
                requested = self._store.requested(run_id)
                if requested == "cancel":
                    return self._cancel(run)
                if requested == "pause":
                    return self._pause(run, [])
                questions = self._store.questions(run_id)
                current = next(
                    (q for q in questions if q.status is QuestionStatus.RUNNING), None
                ) or next((q for q in questions if q.status is QuestionStatus.PENDING), None)
                if current is None:
                    return self._end(run, RunLifecycle.COMPLETED, EventKind.RUN_COMPLETED, None)
                run, ended = self._advance(run, current)
                if ended is QuestionStatus.FAILED:
                    failures += 1
                    if failures >= self._failures_before_stop:
                        message = (
                            f"{failures} questions failed in a row, so the run stopped. "
                            "The results so far are kept."
                        )
                        return self._end(run, RunLifecycle.FAILED, EventKind.RUN_FAILED, message)
                elif ended is not None:
                    failures = 0
            return run

    # --- the run's lifecycle ---------------------------------------------------------------

    def _coverage(self, run: ReviewRun, questions: list[Question] | None = None) -> Coverage:
        """Every question counted once; excluded and unsupported scope stays as it was set."""
        questions = self._store.questions(run.id) if questions is None else questions
        pending = sum(question.status in _UNFINISHED for question in questions)
        excluded = sum(question.status is QuestionStatus.EXCLUDED for question in questions)
        original_excluded = run.coverage.total - len(questions) - run.coverage.unsupported
        return run.coverage.model_copy(
            update={
                "total": run.coverage.total,
                "completed": len(questions) - pending - excluded,
                "pending": pending,
                "excluded": original_excluded + excluded,
            }
        )

    def _begin(self, run: ReviewRun) -> ReviewRun:
        first = run.lifecycle is RunLifecycle.QUEUED
        now = self._clock()
        started = run.model_copy(
            update={
                "lifecycle": RunLifecycle.RUNNING,
                "stage": RunStage.INVESTIGATING,
                "started_at": run.started_at or now,
                "coverage": self._coverage(run),
                # A condition that paused the run is looked at again, not carried along.
                "conditions": [
                    c for c in run.conditions if c.kind is not ConditionKind.MODEL_TOO_LARGE
                ],
            }
        )
        kind = EventKind.RUN_STARTED if first else EventKind.RUN_RESUMED
        # A cancel asked for while the run was paused is still pending, and is honored next.
        self._store.record(started, now, events=[Draft(kind)])
        return started

    def _pause(self, run: ReviewRun, conditions: list[Condition]) -> ReviewRun:
        paused = run.model_copy(
            update={
                "lifecycle": RunLifecycle.PAUSED,
                "conditions": [*run.conditions, *conditions],
            }
        )
        message = conditions[0].message if conditions else None
        draft = Draft(EventKind.RUN_PAUSED, message=message)
        self._store.record(paused, self._clock(), events=[draft], clear_request=True)
        return paused

    def _end(
        self,
        run: ReviewRun,
        lifecycle: RunLifecycle,
        kind: EventKind,
        message: str | None,
        *,
        questions: list[Question] | None = None,
        changed: list[Question] | None = None,
        before: list[Draft] | None = None,
    ) -> ReviewRun:
        now = self._clock()
        ended = run.model_copy(
            update={
                "lifecycle": lifecycle,
                "stage": None,
                "finished_at": now,
                "coverage": self._coverage(run, questions),
            }
        )
        self._store.record(
            ended,
            now,
            questions=changed or [],
            events=[*(before or []), Draft(kind, message=message)],
            clear_request=True,
        )
        return ended

    def _cancel(self, run: ReviewRun) -> ReviewRun:
        """Stop here. What is finished stays; what is not is marked canceled, not removed."""
        questions = self._store.questions(run.id)
        open_statuses = (QuestionStatus.PENDING, QuestionStatus.RUNNING)
        canceled = [
            question.model_copy(update={"status": QuestionStatus.CANCELED})
            for question in questions
            if question.status in open_statuses
        ]
        drafts = [
            Draft(EventKind.QUESTION_FINISHED, q.id, q.stage, QuestionStatus.CANCELED)
            for q in canceled
        ]
        after = {question.id: question for question in canceled}
        return self._end(
            run,
            RunLifecycle.CANCELED,
            EventKind.RUN_CANCELED,
            None,
            questions=[after.get(question.id, question) for question in questions],
            changed=canceled,
            before=drafts,
        )

    # --- one question, one stage -----------------------------------------------------------

    def _advance(
        self, run: ReviewRun, question: Question
    ) -> tuple[ReviewRun, QuestionStatus | None]:
        """Run the question's current stage and save the result; its final status, if it ended."""
        now = self._clock()
        if question.status is QuestionStatus.PENDING:
            started = question.model_copy(
                update={"status": QuestionStatus.RUNNING, "stage": Stage.FRAME}
            )
            drafts = [
                Draft(EventKind.QUESTION_STARTED, question.id),
                Draft(EventKind.QUESTION_STAGE, question.id, Stage.FRAME),
            ]
            self._store.record(run, now, questions=[started], state={}, events=drafts)
            return run, None

        saved = self._store.state(run.id, question.id)
        spend = Spend(question.budget)
        spent = saved.get("spend")
        if isinstance(spent, dict):
            for name in _SPENT:
                amount = spent.get(name)
                if isinstance(amount, int | float):
                    setattr(spend, name, amount)
        looks = saved.get("looks")
        looks = looks if isinstance(looks, int) else 0
        data = saved.get("data")
        stage = question.stage
        handler = self._handlers.get(stage)

        def finish(
            status: QuestionStatus,
            message: str | None,
            activity: tuple[str, ...] = (),
            answer: Mapping[str, JsonValue] | None = None,
        ) -> tuple[ReviewRun, QuestionStatus]:
            ended = question.model_copy(update={"status": status, "answer": answer})
            ended = Question.model_validate(ended.model_dump())
            drafts = [
                Draft(EventKind.QUESTION_ACTIVITY, question.id, stage, message=line)
                for line in activity
            ]
            drafts.append(Draft(EventKind.QUESTION_FINISHED, question.id, stage, status, message))
            others = self._store.questions(run.id)
            counted = run.model_copy(
                update={
                    "coverage": self._coverage(
                        run, [ended if other.id == ended.id else other for other in others]
                    )
                }
            )
            self._store.record(
                counted,
                now,
                questions=[ended],
                state=_checkpoint(spend, looks, data),
                events=drafts,
            )
            return counted, status

        if handler is None:
            return finish(QuestionStatus.FAILED, f"No handler is installed for the {stage} stage.")
        try:
            step = handler(question, data if isinstance(data, dict) else {}, spend)
        except PreflightRefused as refused:
            action = "Switch model" if refused.result.suggestion else None
            condition = Condition(
                kind=ConditionKind.MODEL_TOO_LARGE, message=str(refused), action=action
            )
            return self._pause(run, [condition]), None
        except BudgetStop as stop:
            return finish(QuestionStatus.BUDGET_EXHAUSTED, str(stop))
        except ModelError as error:
            return finish(QuestionStatus.FAILED, str(error))
        except Exception as error:
            self._store.redactor.exception(
                _LOG, f"the {stage} stage of {question.id} failed", error
            )
            reason = f"The {stage} stage stopped on an error: {type(error).__name__}."
            return finish(QuestionStatus.FAILED, reason)

        if step.status is not None:
            valid = (
                step.next is None
                and step.status in _HANDLER_ENDINGS
                and (step.status is QuestionStatus.ANSWERED) == (step.answer is not None)
            )
            if not valid:
                reason = f"The {stage} stage ended the question in a way it may not."
                return finish(QuestionStatus.FAILED, reason)
            return finish(step.status, None, step.activity, step.answer)

        following = step.next
        activity = list(step.activity)
        if stage is Stage.GATHER:
            looks += 1
            if following is Stage.GATHER and looks >= question.budget.max_looks:
                following = Stage.HYPOTHESIZE
                activity.append(f"Stopped gathering after {looks} looks, the limit for a question.")
        if following is None or following not in _NEXT[stage]:
            reason = f"The {stage} stage named a next stage that cannot follow it."
            return finish(QuestionStatus.FAILED, reason)
        moved = question.model_copy(update={"stage": following})
        drafts = [
            Draft(EventKind.QUESTION_ACTIVITY, question.id, stage, message=line)
            for line in activity
        ]
        drafts.append(Draft(EventKind.QUESTION_STAGE, question.id, following))
        self._store.record(
            run,
            now,
            questions=[moved],
            state=_checkpoint(spend, looks, dict(step.state)),
            events=drafts,
        )
        return run, None


def _checkpoint(spend: Spend, looks: int, data: JsonValue) -> dict[str, JsonValue]:
    return {
        "spend": {name: getattr(spend, name) for name in _SPENT},
        "looks": looks,
        "data": data,
    }
