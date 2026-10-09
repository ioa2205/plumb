"""Review runs: lifecycle, stage, and conditions are separate fields (design.md §13)."""

from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.common import Contract, Id, Sha256
from backend.contracts.investigation import QuestionStage, QuestionStatus


class RunType(StrEnum):
    """Live, replayed, and saved runs are always labeled differently (PROJECT_PLAN §15)."""

    LIVE = "live"
    REPLAY = "replay"
    SAVED = "saved"


class RunLifecycle(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"  # paused at a checkpoint
    CANCELED = "canceled"
    FAILED = "failed"
    COMPLETED = "completed"


TERMINAL = frozenset({RunLifecycle.CANCELED, RunLifecycle.FAILED, RunLifecycle.COMPLETED})


class RunStage(StrEnum):
    INDEXING = "indexing"
    SCANNING = "scanning"
    INVESTIGATING = "investigating"
    VERIFYING = "verifying"
    REPORTING = "reporting"


class ConditionKind(StrEnum):
    SETUP_REQUIRED = "setup_required"
    MODEL_TOO_LARGE = "model_too_large"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    STALE_SOURCE = "stale_source"
    UNSUPPORTED_FRAMEWORK = "unsupported_framework"
    UNREADABLE_FILE = "unreadable_file"
    PARTIAL_COVERAGE = "partial_coverage"


class Condition(Contract):
    kind: ConditionKind
    message: str  # what happened, in the interface's voice
    action: str | None = None  # the next step, for example "Switch model"


class ModelRef(Contract):
    id: str
    file_sha256: Sha256
    quantization: str


class Toolchain(Contract):
    """Everything needed to reproduce a run (design.md §12, Runs)."""

    llama_cpp_release: str
    llama_cpp_build: str
    backend: str  # "cpu", "cuda-12.4", "vulkan"
    opengrep_version: str | None = None
    opengrep_rules_sha256: Sha256 | None = None
    knowledge_pack_date: date | None = None


class Coverage(Contract):
    """True-denominator progress: every question is counted somewhere."""

    total: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    excluded: int = Field(default=0, ge=0)
    unsupported: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _adds_up(self) -> Self:
        if self.completed + self.pending + self.excluded + self.unsupported != self.total:
            raise ValueError("completed + pending + excluded + unsupported must equal total")
        return self


class ReviewRun(Contract):
    id: Id
    snapshot_id: Sha256
    run_type: RunType
    lifecycle: RunLifecycle
    stage: RunStage | None = None
    conditions: list[Condition] = []
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    model: ModelRef | None = None
    toolchain: Toolchain | None = None
    coverage: Coverage = Coverage()
    finding_ids: list[Id] = []

    @model_validator(mode="after")
    def _lifecycle_fields(self) -> Self:
        active = self.lifecycle in (RunLifecycle.RUNNING, RunLifecycle.PAUSED)
        if (self.stage is not None) != active:
            raise ValueError("a stage is set exactly while the run is running or paused")
        if (self.finished_at is not None) != (self.lifecycle in TERMINAL):
            raise ValueError("finished_at is set exactly when the run has ended")
        started = (RunLifecycle.RUNNING, RunLifecycle.PAUSED, RunLifecycle.COMPLETED)
        if self.lifecycle in started and self.started_at is None:
            raise ValueError("a run that has started records when it started")
        return self


class EventKind(StrEnum):
    RUN_STARTED = "run.started"
    RUN_RESUMED = "run.resumed"
    RUN_PAUSED = "run.paused"
    RUN_CANCELED = "run.canceled"
    RUN_FAILED = "run.failed"
    RUN_COMPLETED = "run.completed"
    RUN_QUEUE_CHANGED = "run.queue_changed"
    QUESTION_STARTED = "question.started"
    QUESTION_STAGE = "question.stage"  # the question entered ``stage``
    QUESTION_ACTIVITY = "question.activity"  # one factual sentence about what was done
    QUESTION_FINISHED = "question.finished"


class RunEvent(Contract):
    """One entry of a run's activity log. ``seq`` counts from 1 within the run, without gaps,
    so a client that reconnects can ask for everything after the last one it saw.
    """

    run_id: Id
    seq: int = Field(ge=1)
    at: AwareDatetime
    kind: EventKind
    question_id: Id | None = None
    stage: QuestionStage | None = None
    status: QuestionStatus | None = None
    message: str | None = None  # a fact, never a simulated thought (PROJECT_PLAN §6)
    coverage: Coverage | None = None

    @model_validator(mode="after")
    def _about_a_run_or_a_question(self) -> Self:
        if self.kind.value.startswith("question.") != (self.question_id is not None):
            raise ValueError("question events, and only those, name their question")
        if self.kind is EventKind.QUESTION_STAGE and self.stage is None:
            raise ValueError("a stage event names the stage that was entered")
        if (self.kind is EventKind.QUESTION_FINISHED) != (self.status is not None):
            raise ValueError("a finished event, and only that, carries the final status")
        if self.kind is EventKind.QUESTION_ACTIVITY and not self.message:
            raise ValueError("an activity event says what was done")
        return self
