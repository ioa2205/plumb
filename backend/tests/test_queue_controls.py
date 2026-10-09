"""Persisted queue edits preserve evidence, original ranking and the worker boundary."""

import sqlite3
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import JsonValue

from agent.llm import Spend
from backend.app import create_app
from backend.contracts.investigation import Question, QuestionStage, QuestionStatus
from backend.contracts.review_view import QueueEdit
from backend.contracts.runs import EventKind, RunType
from backend.jobs import Engine, Step, WorkerBusy, WorkerLock
from backend.queue_controls import QueueConflict, edit_queue
from backend.review_reads import review_page
from backend.run_store import RunStore
from backend.settings import Settings
from backend.tests.job_worker import logged_handlers
from backend.tests.support import ORIGIN, PORT, signed_in, visitor
from backend.tests.test_jobs import RUN, queued


def pause(store: RunStore, path: Path) -> None:
    store.request(RUN, "pause")
    Engine(store, logged_handlers(path / "stages.log")).run(RUN)
    run = store.run(RUN)
    assert run is not None and run.lifecycle == "paused"


def edit(store: RunStore, question: str, action: str) -> None:
    page = review_page(store, RUN)
    assert page is not None
    edit_queue(
        store,
        RUN,
        QueueEdit.model_validate(
            {"question_id": question, "action": action, "expected_cursor": page.cursor}
        ),
    )


def test_changes_survive_new_store_and_resume_with_original_ranking_and_coverage(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    queued(
        store, "a", "b", "c", excluded=7, exploration=True, priority_reasons=["uncertain guards"]
    )
    pause(store, tmp_path)
    edit(store, "c", "up")
    edit(store, "b", "exclude")
    restored = RunStore(store.path)
    page = review_page(restored, RUN)
    assert page is not None
    assert [(q.id, q.position, q.original_position) for q in page.questions] == [
        ("a", 1, 1),
        ("c", 2, 3),
        ("b", 3, 2),
    ]
    assert page.queue_excluded == 1
    assert page.run.coverage.model_dump() == {
        "total": 10,
        "completed": 0,
        "pending": 2,
        "excluded": 8,
        "unsupported": 0,
    }
    assert all(q.exploration and q.priority_reasons == ["uncertain guards"] for q in page.questions)
    calls: list[str] = []
    handlers = logged_handlers(tmp_path / "resume.log")

    def frame(question: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        calls.append(question.id)
        return Step(next=QuestionStage.GATHER, state={})

    handlers[QuestionStage.FRAME] = frame
    result = Engine(restored, handlers).run(RUN)
    assert calls == ["a", "c"]
    assert result.lifecycle == "completed" and result.coverage.total == 10
    assert result.coverage.completed == 2 and result.coverage.excluded == 8
    assert restored.questions(RUN)[-1].status is QuestionStatus.EXCLUDED
    events = restored.events(RUN)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert sum(e.kind is EventKind.RUN_QUEUE_CHANGED for e in events) == 2


def test_include_restores_pending_without_erasing_reasons_and_excluding_all_is_honest(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, "a", "b", excluded=3)
    pause(store, tmp_path)
    edit(store, "a", "exclude")
    edit(store, "a", "include")
    page = review_page(store, RUN)
    assert page is not None and page.run.coverage.pending == 2 and page.run.coverage.excluded == 3
    for name in ("a", "b"):
        edit(store, name, "exclude")
    result = Engine(store, {}).run(RUN)
    assert result.lifecycle == "completed"
    assert result.coverage.completed == 0 and result.coverage.excluded == result.coverage.total == 5


def test_invalid_stale_active_and_started_edits_do_not_mutate_records(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, "a", "b")
    with pytest.raises(QueueConflict):
        edit(store, "a", "exclude")  # queued is deliberately not editable
    pause(store, tmp_path)
    page = review_page(store, RUN)
    assert page is not None
    stale = QueueEdit(question_id="b", action="up", expected_cursor=page.cursor)
    edit(store, "a", "exclude")
    before = (store.run(RUN), store.questions(RUN), store.events(RUN))
    for operation in (
        lambda: edit_queue(store, RUN, stale),
        lambda: edit(store, "foreign", "exclude"),
        lambda: edit(store, "a", "exclude"),
        lambda: edit(store, "b", "down"),
    ):
        with pytest.raises(QueueConflict):
            operation()
        assert before == (store.run(RUN), store.questions(RUN), store.events(RUN))
    with WorkerLock(store.path.with_suffix(".lock")), pytest.raises(WorkerBusy):
        edit(store, "b", "exclude")
    assert before == (store.run(RUN), store.questions(RUN), store.events(RUN))


def test_simultaneous_clients_only_commit_one_change(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, "a", "b")
    pause(store, tmp_path)
    page = review_page(store, RUN)
    assert page is not None

    def attempt(name: str) -> str:
        try:
            edit_queue(
                RunStore(store.path),
                RUN,
                QueueEdit(question_id=name, action="exclude", expected_cursor=page.cursor),
            )
            return "saved"
        except (WorkerBusy, QueueConflict):
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ("a", "b"))) == ["refused", "saved"]
    run = store.run(RUN)
    assert run is not None and run.coverage.excluded == 1


def test_protected_edit_api_requires_current_checkpoint_and_preserves_membership(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    store = RunStore(settings.cache_dir / "runs.sqlite")
    queued(store, "a", "b")
    pause(store, tmp_path)
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    path = f"/api/runs/{RUN}/queue"
    page = review_page(store, RUN)
    assert page is not None
    body = {"question_id": "b", "action": "up", "expected_cursor": page.cursor}
    assert visitor(app).post(path, json=body, headers={"Origin": ORIGIN}).status_code == 401
    assert client.post(path, json=body).status_code == 403
    assert (
        client.post(path, json=body, headers={"Origin": "https://foreign.invalid"}).status_code
        == 403
    )
    assert (
        client.post(
            path, json={**body, "question_id": "../escape"}, headers={"Origin": ORIGIN}
        ).status_code
        == 422
    )
    response = client.post(path, json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json()["questions"][0]["id"] == "b"
    assert response.json()["questions"][0]["original_position"] == 2
    assert client.post(path, json=body, headers={"Origin": ORIGIN}).status_code == 409


def test_legacy_store_reads_without_migration_and_first_edit_keeps_original_order(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, "a", "b")
    pause(store, tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE queue_positions")
    old = RunStore(store.path)
    assert [q.id for q in old.questions(RUN)] == ["a", "b"]
    page = review_page(old, RUN)
    assert page is not None and page.questions[1].original_position == 2
    edit(old, "b", "up")
    assert [q.id for q in RunStore(store.path).questions(RUN)] == ["b", "a"]


def test_started_questions_and_historical_runs_cannot_be_edited(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, "a", "b")
    handlers = logged_handlers(tmp_path / "stages.log")

    def frame(question: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        store.request(RUN, "pause")
        return Step(next=QuestionStage.GATHER, state={})

    handlers[QuestionStage.FRAME] = frame
    Engine(store, handlers).run(RUN)
    with pytest.raises(QueueConflict, match="not started"):
        edit(store, "a", "exclude")
    for kind in (RunType.REPLAY, RunType.SAVED):
        run = store.run(RUN)
        assert run is not None
        store.record(run.model_copy(update={"run_type": kind}), run.created_at)
        with pytest.raises(QueueConflict, match="replayed"):
            edit(store, "b", "exclude")
