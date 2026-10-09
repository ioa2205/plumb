"""Real store/worker/API integration with software handlers, never model-quality evidence."""

import threading
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from agent.llm import Spend
from backend.app import create_app
from backend.case_reads import CaseReads
from backend.contracts.investigation import Conclusion, Question, QuestionStage, QuestionStatus
from backend.contracts.review_view import FindingList, ReviewPage
from backend.contracts.runs import EventKind
from backend.jobs import Engine, Step
from backend.reports import ReportBundle
from backend.review_reads import review_page
from backend.run_store import Draft, RunStore
from backend.settings import Settings
from backend.tests.job_worker import logged_handlers
from backend.tests.support import ORIGIN, PORT, signed_in, visitor
from backend.tests.test_jobs import RUN, T0, queued
from backend.tests.test_saved_reports import saved as saved


def test_live_checkpoints_cancel_and_reconnect_keep_partial_results(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    store = RunStore(settings.cache_dir / "runs.sqlite")
    queued(
        store, "first", "second", excluded=3, priority_reasons=["public route"], exploration=True
    )
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    path = f"/api/runs/{RUN}/review"
    assert visitor(app).get(path).status_code == 401
    assert client.get(path, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    assert client.get(path, params={"offset": -1}).status_code == 422
    before = ReviewPage.model_validate(client.get(path).json())
    assert before.cursor == 0 and before.run.coverage.total == 5
    entered, proceed = threading.Event(), threading.Event()
    handlers = logged_handlers(tmp_path / "worker.log")

    def frame(question: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if question.id == "second":
            entered.set()
            assert proceed.wait(10)
        return Step(next=QuestionStage.GATHER, state={})

    handlers[QuestionStage.FRAME] = frame
    thread = threading.Thread(target=Engine(store, handlers).run, args=(RUN,))
    thread.start()
    try:
        assert entered.wait(10)
        live = ReviewPage.model_validate(client.get(path).json())
        assert live.run.lifecycle == "running" and live.run.coverage.completed == 1
        assert live.questions[0].status == QuestionStatus.ANSWERED
        assert live.questions[1].status == QuestionStatus.RUNNING
        assert live.questions[1].priority_reasons == ["public route"]
        assert live.questions[1].exploration
        assert "answer" not in live.model_dump()["questions"][0]
        assert client.post(f"/api/runs/{RUN}/cancel").status_code == 403
        assert client.post(f"/api/runs/{RUN}/cancel", headers={"Origin": ORIGIN}).status_code == 202
        assert client.get(path).json()["requested"] == "cancel"
    finally:
        proceed.set()
        thread.join(10)
    assert not thread.is_alive()
    final = ReviewPage.model_validate(client.get(path).json())
    assert final.run.lifecycle == "canceled" and final.run.coverage.total == 5
    assert final.run.coverage.completed == 1 and final.run.coverage.pending == 1
    assert final.questions[0].status == "answered" and final.questions[1].status == "canceled"
    from backend.tests.test_run_api import parse

    events, _ = parse(
        client.get(f"/api/runs/{RUN}/events", headers={"Last-Event-ID": str(live.cursor)}).text
    )
    assert [e.seq for e in events] == list(range(live.cursor + 1, final.cursor + 1))
    assert events[-1].kind == "run.canceled"


def test_queue_pages_and_activity_tail_are_bounded_and_identity_checked(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, *(f"q{i}" for i in range(45)))
    run = store.run(RUN)
    assert run is not None
    store.record(
        run,
        T0,
        events=[
            Draft(
                EventKind.QUESTION_ACTIVITY,
                question_id="q0",
                message="Read a recorded source span.",
            )
        ]
        * 130,
    )
    page = review_page(store, RUN, 20)
    assert page is not None
    assert page.total == 45 and page.next_offset == 40
    assert [q.position for q in page.questions] == list(range(21, 41))
    assert [e.seq for e in page.events] == list(range(31, 131))
    for field, value in (("cursor", 129), ("next_offset", 21)):
        with pytest.raises(ValidationError):
            ReviewPage.model_validate({**page.model_dump(), field: value})
    assert review_page(store, "missing") is None


def test_finding_filters_cover_the_whole_report_before_pagination(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved
    findings = [
        bundle.findings[0].model_copy(
            update={
                "id": f"f:{i}",
                "display_id": f"F-{i:02}",
                "severity": "high" if i == 29 else "unknown",
            }
        )
        for i in range(30)
    ]
    expanded = ReportBundle.model_validate(
        {
            **bundle.model_dump(),
            "run": bundle.run.model_copy(update={"finding_ids": [f.id for f in findings]}),
            "findings": findings,
        }
    )
    monkeypatch.setattr(CaseReads, "_bundle", lambda self, run_id: expanded)
    client = signed_in(create_app(settings, port=PORT))
    path = f"/api/runs/{bundle.run.id}/finding-list"
    first = FindingList.model_validate(client.get(path).json())
    assert first.total == 30 and len(first.findings) == 20 and first.next_offset == 20
    filtered = FindingList.model_validate(client.get(path, params={"severity": "high"}).json())
    assert filtered.total == 1 and filtered.findings[0].id == "f:29"
    assert filtered.counts[Conclusion.SUPPORTED] == 1
    assert client.get(path, params={"severity": "untrusted"}).status_code == 422
    assert client.get(path, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    assert visitor(create_app(settings, port=PORT)).get(path).status_code == 401


def test_actual_saved_list_preserves_report_bytes(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, directory = saved
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    client = signed_in(create_app(settings, port=PORT))
    page = FindingList.model_validate(client.get(f"/api/runs/{bundle.run.id}/finding-list").json())
    assert page.findings[0].id == bundle.findings[0].id
    assert page.findings[0].location == bundle.findings[0].exhibits[0].span
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
