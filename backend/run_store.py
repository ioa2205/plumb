"""SQLite store for review runs: the run, its questions in queue order, and its event log.

One file holds everything a run needs to continue after the process dies
(PROJECT_PLAN §5, "Jobs"). ``record`` is the only write after creation: it saves
the run, the questions that changed with their working state, and the events that
announce the change, in a single transaction. So a transition is either wholly
on disk with its events or not there at all, and an event never describes a
state that was not saved.

Events are numbered from 1 within a run without gaps, which is what lets a
client that lost its connection ask for everything after the last one it saw.
"""

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from backend.contracts.investigation import Question, QuestionStage, QuestionStatus
from backend.contracts.runs import TERMINAL, EventKind, ReviewRun, RunEvent
from backend.redaction import Redactor

Request = Literal["cancel", "pause"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    request TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    run_id TEXT NOT NULL REFERENCES runs(id),
    id TEXT NOT NULL,
    position INTEGER NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (run_id, id),
    UNIQUE (run_id, position)
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(id),
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS queue_positions (
    run_id TEXT NOT NULL,
    id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (run_id, id),
    FOREIGN KEY (run_id, id) REFERENCES questions(run_id, id)
);
"""


@dataclass(frozen=True)
class Draft:
    """An event before the store gives it a number."""

    kind: EventKind
    question_id: str | None = None
    stage: QuestionStage | None = None
    status: QuestionStatus | None = None
    message: str | None = None


# Events that report where the run stands, and so carry its coverage.
_WITH_COVERAGE = frozenset(EventKind) - {
    EventKind.QUESTION_STARTED,
    EventKind.QUESTION_STAGE,
    EventKind.QUESTION_ACTIVITY,
}


class RunStore:
    def __init__(self, path: Path, *, redactor: Redactor | None = None) -> None:
        self.path = path
        self.redactor = redactor or Redactor.configured()
        self._prepared = False

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One transaction. The file and its tables are created on the first write."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30, isolation_level=None)) as db:
            if not self._prepared:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(_SCHEMA)
                self._prepared = True
            # A transition must survive the process being killed right after it is reported.
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def _read(self, query: str, *parameters: object) -> list[tuple]:
        """Rows of a query; nothing, and no file, when no run was ever saved."""
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            try:
                return db.execute(query, parameters).fetchall()
            except sqlite3.OperationalError as error:
                if "no such table" in str(error):
                    return []
                raise

    def create(self, run: ReviewRun, questions: Sequence[Question]) -> None:
        """Save a new run with its questions in queue order."""
        if any(question.run_id != run.id for question in questions):
            raise ValueError("every question belongs to the run it is queued in")
        with self._write() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, NULL)", (run.id, run.model_dump_json()))
            db.executemany(
                "INSERT INTO questions VALUES (?, ?, ?, ?, '{}')",
                [
                    (run.id, question.id, position, question.model_dump_json())
                    for position, question in enumerate(questions)
                ],
            )

    def run(self, run_id: str) -> ReviewRun | None:
        rows = self._read("SELECT payload FROM runs WHERE id = ?", run_id)
        return ReviewRun.model_validate_json(rows[0][0]) if rows else None

    def questions(self, run_id: str) -> list[Question]:
        """The run's questions in queue order, whatever their state: partial results included."""
        rows = self._read(
            "SELECT payload, position, id FROM questions WHERE run_id = ? ORDER BY position", run_id
        )
        overrides = dict(
            self._read("SELECT id, position FROM queue_positions WHERE run_id = ?", run_id)
        )
        return [
            Question.model_validate_json(row[0])
            for row in sorted(rows, key=lambda row: overrides.get(row[2], row[1]))
        ]

    def state(self, run_id: str, question_id: str) -> dict[str, JsonValue]:
        """The working state a question carried into its current stage."""
        rows = self._read(
            "SELECT state FROM questions WHERE run_id = ? AND id = ?", run_id, question_id
        )
        if not rows:
            raise KeyError(f"{question_id} is not a question of {run_id}")
        return json.loads(rows[0][0])

    def events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        rows = self._read(
            "SELECT payload FROM events WHERE run_id = ? AND seq > ? ORDER BY seq", run_id, after
        )
        return [RunEvent.model_validate_json(row[0]) for row in rows]

    def request(self, run_id: str, action: Request) -> bool:
        """Ask the worker to cancel or pause at its next checkpoint.

        False when there is no such run or it has already ended. A cancel is
        never replaced by a pause.
        """
        if not self.path.exists():
            return False
        with self._write() as db:
            row = db.execute("SELECT payload, request FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or ReviewRun.model_validate_json(row[0]).lifecycle in TERMINAL:
                return False
            if row[1] != "cancel":
                db.execute("UPDATE runs SET request = ? WHERE id = ?", (action, run_id))
        return True

    def requested(self, run_id: str) -> Request | None:
        rows = self._read("SELECT request FROM runs WHERE id = ?", run_id)
        return rows[0][0] if rows else None

    def record(
        self,
        run: ReviewRun,
        at: datetime,
        *,
        questions: Sequence[Question] = (),
        state: Mapping[str, JsonValue] | None = None,
        events: Sequence[Draft] = (),
        clear_request: bool = False,
    ) -> list[RunEvent]:
        """Save one transition and the events that announce it, all or nothing.

        ``state`` is the working state of the one question given; without it,
        questions keep the state they have.
        """
        if state is not None and len(questions) != 1:
            raise ValueError("a working state belongs to exactly one question")
        with self._write() as db:
            changed = db.execute(
                "UPDATE runs SET payload = ? WHERE id = ?", (run.model_dump_json(), run.id)
            ).rowcount
            if changed != 1:
                raise KeyError(f"{run.id} is not a run of this store")
            if clear_request:
                db.execute("UPDATE runs SET request = NULL WHERE id = ?", (run.id,))
            for question in questions:
                changed = db.execute(
                    "UPDATE questions SET payload = ?, state = COALESCE(?, state) "
                    "WHERE run_id = ? AND id = ?",
                    (
                        question.model_dump_json(),
                        None if state is None else json.dumps(state),
                        run.id,
                        question.id,
                    ),
                ).rowcount
                if changed != 1:
                    raise KeyError(f"{question.id} is not a question of {run.id}")
            (last,) = db.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE run_id = ?", (run.id,)
            ).fetchone()
            saved = [
                RunEvent(
                    run_id=run.id,
                    seq=last + number,
                    at=at,
                    kind=draft.kind,
                    question_id=draft.question_id,
                    stage=draft.stage,
                    status=draft.status,
                    message=None if draft.message is None else self.redactor.text(draft.message),
                    coverage=run.coverage if draft.kind in _WITH_COVERAGE else None,
                )
                for number, draft in enumerate(events, start=1)
            ]
            db.executemany(
                "INSERT INTO events VALUES (?, ?, ?)",
                [(run.id, event.seq, event.model_dump_json()) for event in saved],
            )
        return saved
