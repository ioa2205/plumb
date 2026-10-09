"""Atomic, bounded reads of a running investigation for the local workbench."""

import sqlite3
from contextlib import closing

from backend.contracts.investigation import Question
from backend.contracts.review_view import QueueRow, ReviewPage
from backend.contracts.runs import ReviewRun, RunEvent
from backend.run_store import RunStore


def review_page(store: RunStore, run_id: str, offset: int = 0) -> ReviewPage | None:
    if not 0 <= offset <= 1_000_000:
        raise ValueError("Invalid queue page")
    if not store.path.exists():
        return None
    # One SQLite read transaction pins metadata, queue and event cursor to the same checkpoint.
    with closing(sqlite3.connect(store.path, timeout=30)) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT payload, request FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        run = ReviewRun.model_validate_json(row[0])
        (total,) = db.execute(
            "SELECT COUNT(*) FROM questions WHERE run_id = ?", (run_id,)
        ).fetchone()
        has_order = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='queue_positions' AND type='table'"
        ).fetchone()
        query = (
            "SELECT q.payload, q.position FROM questions q LEFT JOIN queue_positions p "
            "ON p.run_id=q.run_id AND p.id=q.id WHERE q.run_id=? "
            "ORDER BY COALESCE(p.position, q.position) LIMIT 20 OFFSET ?"
            if has_order
            else "SELECT payload, position FROM questions WHERE run_id=? "
            "ORDER BY position LIMIT 20 OFFSET ?"
        )
        rows = db.execute(query, (run_id, offset)).fetchall()
        questions = [Question.model_validate_json(q[0]) for q in rows]
        (excluded,) = db.execute(
            "SELECT COUNT(*) FROM questions WHERE run_id=? "
            "AND json_extract(payload, '$.status')='excluded'",
            (run_id,),
        ).fetchone()
        events = [
            RunEvent.model_validate_json(e[0])
            for e in db.execute(
                "SELECT payload FROM events WHERE run_id = ? ORDER BY seq DESC LIMIT 100", (run_id,)
            )
        ][::-1]
        return ReviewPage(
            run=run,
            questions=[
                QueueRow(
                    id=q.id,
                    position=offset + i + 1,
                    original_position=rows[i][1] + 1,
                    type=q.type,
                    family=q.family,
                    stage=q.stage,
                    status=q.status,
                    location=q.evidence[0] if q.evidence else None,
                    priority_reasons=[store.redactor.text(reason) for reason in q.priority_reasons],
                    exploration=q.exploration,
                )
                for i, q in enumerate(questions)
            ],
            total=total,
            offset=offset,
            next_offset=offset + len(questions) if offset + len(questions) < total else None,
            events=events,
            cursor=events[-1].seq if events else 0,
            requested=row[1],
            queue_excluded=excluded,
        )
