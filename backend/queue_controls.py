"""Checkpoint-only queue changes, serialized with the same lock as model work."""

from datetime import UTC, datetime

from backend.contracts.investigation import Question, QuestionStatus
from backend.contracts.review_view import QueueEdit
from backend.contracts.runs import EventKind, ReviewRun, RunEvent, RunLifecycle, RunType
from backend.jobs import WorkerLock
from backend.run_store import RunStore


class QueueConflict(ValueError):
    """Refresh or pause first; never expose database or source details."""


def edit_queue(store: RunStore, run_id: str, edit: QueueEdit) -> None:
    # Lock before reading lifecycle; a paused worker can otherwise resume between the check
    # and commit. BEGIN IMMEDIATE also serializes concurrent browser controls.
    with WorkerLock(store.path.with_suffix(".lock")), store._write() as db:
        saved = db.execute("SELECT payload, request FROM runs WHERE id = ?", (run_id,)).fetchone()
        if saved is None:
            raise QueueConflict("No run has this ID.")
        run = ReviewRun.model_validate_json(saved[0])
        if run.run_type is not RunType.LIVE:
            raise QueueConflict("Saved and replayed runs cannot change an investigation queue.")
        if run.lifecycle is not RunLifecycle.PAUSED or saved[1] is not None:
            raise QueueConflict("Pause at a checkpoint before changing the queue.")
        (cursor,) = db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM events WHERE run_id = ?", (run_id,)
        ).fetchone()
        if cursor != edit.expected_cursor:
            raise QueueConflict("The review changed. Refresh before editing its queue.")
        rows = db.execute(
            "SELECT q.payload, COALESCE(p.position, q.position) FROM questions q "
            "LEFT JOIN queue_positions p ON p.run_id=q.run_id AND p.id=q.id "
            "WHERE q.run_id=? ORDER BY COALESCE(p.position, q.position)",
            (run_id,),
        ).fetchall()
        questions = [Question.model_validate_json(row[0]) for row in rows]
        index = next((i for i, q in enumerate(questions) if q.id == edit.question_id), None)
        if index is None:
            raise QueueConflict("Choose a pending question from this run.")
        question = questions[index]
        if question.status not in (QuestionStatus.PENDING, QuestionStatus.EXCLUDED):
            raise QueueConflict("Only questions that have not started can be edited.")
        coverage = run.coverage
        if edit.action in ("up", "down"):
            direction = -1 if edit.action == "up" else 1
            candidates = range(
                index + direction, -1 if direction < 0 else len(questions), direction
            )
            other = next(
                (i for i in candidates if questions[i].status is QuestionStatus.PENDING), None
            )
            if question.status is not QuestionStatus.PENDING or other is None:
                raise QueueConflict("No pending question can be moved in that direction.")
            questions[index], questions[other] = questions[other], questions[index]
            db.executemany(
                "INSERT OR REPLACE INTO queue_positions VALUES (?, ?, ?)",
                [(run_id, q.id, i) for i, q in enumerate(questions)],
            )
            message = (
                f"Moved {question.id} from position {index + 1} to {other + 1}; coverage unchanged."
            )
        else:
            excluding = edit.action == "exclude"
            expected = QuestionStatus.PENDING if excluding else QuestionStatus.EXCLUDED
            if question.status is not expected:
                raise QueueConflict("This question already has that scope. Refresh the review.")
            question = question.model_copy(
                update={"status": QuestionStatus.EXCLUDED if excluding else QuestionStatus.PENDING}
            )
            db.execute(
                "UPDATE questions SET payload=? WHERE run_id=? AND id=?",
                (question.model_dump_json(), run_id, question.id),
            )
            delta = 1 if excluding else -1
            coverage = type(coverage).model_validate(
                {
                    **coverage.model_dump(),
                    "pending": coverage.pending - delta,
                    "excluded": coverage.excluded + delta,
                }
            )
            message = (
                f"{'Excluded' if excluding else 'Included'} {question.id} by user choice; "
                f"{coverage.pending} pending, {coverage.excluded} excluded, {coverage.total} total."
            )
        updated = run.model_copy(update={"coverage": coverage})
        event = RunEvent(
            run_id=run_id,
            seq=cursor + 1,
            at=datetime.now(UTC),
            kind=EventKind.RUN_QUEUE_CHANGED,
            message=message,
            coverage=coverage,
        )
        db.execute("UPDATE runs SET payload=? WHERE id=?", (updated.model_dump_json(), run_id))
        db.execute(
            "INSERT INTO events VALUES (?, ?, ?)", (run_id, event.seq, event.model_dump_json())
        )
