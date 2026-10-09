import json
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import JsonValue

from agent.llm import Spend
from backend.app import create_app
from backend.contracts.investigation import Question, QuestionStage, QuestionStatus
from backend.contracts.runs import ReviewRun, RunEvent, RunLifecycle
from backend.jobs import Engine, Handler, Step
from backend.run_store import RunStore
from backend.settings import Settings
from backend.sse import KEEP_ALIVE_SECONDS, last_seen, stream

from .job_worker import logged_handlers
from .support import ORIGIN, PORT, signed_in, visitor
from .test_jobs import RUN, Clock, queued

EVENTS = f"/api/runs/{RUN}/events"
OWN = {"Origin": ORIGIN}
WIDE_DIGITS = chr(0xFF11) + chr(0xFF12)  # digits to str.isdigit, not to a parser of IDs


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path)


@pytest.fixture
def store(settings: Settings) -> RunStore:
    return RunStore(settings.cache_dir / "runs.sqlite")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings, port=PORT)


def worker(store: RunStore, tmp_path: Path, **overrides: Handler) -> Engine:
    handlers = logged_handlers(tmp_path / "stages.log")
    handlers.update({QuestionStage(name): handler for name, handler in overrides.items()})
    return Engine(store, handlers, clock=Clock())


def parse(text: str) -> tuple[list[RunEvent], list[str]]:
    """The events of an SSE body, and its other lines."""
    events, other = [], []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "data" not in fields:
            other.append(block)
            continue
        event = RunEvent.model_validate_json(fields["data"])
        assert (fields["id"], fields["event"]) == (str(event.seq), event.kind.value)
        events.append(event)
    return events, other


# --- reading a run -------------------------------------------------------------------------


def test_a_run_and_its_queue_can_be_read_at_any_point(
    app: FastAPI, store: RunStore, tmp_path: Path
) -> None:
    queued(store, "q1", "q2")
    client = signed_in(app)
    before = ReviewRun.model_validate(client.get(f"/api/runs/{RUN}").json())
    assert before.lifecycle is RunLifecycle.QUEUED

    def gather(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if asked.id == "q2":
            store.request(RUN, "pause")
        return Step(next=QuestionStage.HYPOTHESIZE, state=dict(state))

    worker(store, tmp_path, gather=gather).run(RUN)
    paused = ReviewRun.model_validate(client.get(f"/api/runs/{RUN}").json())
    assert paused.lifecycle is RunLifecycle.PAUSED
    # Partial results: the first question's answer is there while the second is under way.
    questions = [
        Question.model_validate(q) for q in client.get(f"/api/runs/{RUN}/questions").json()
    ]
    assert [(q.id, q.status, q.stage) for q in questions] == [
        ("q1", QuestionStatus.ANSWERED, QuestionStage.RECORD),
        ("q2", QuestionStatus.RUNNING, QuestionStage.HYPOTHESIZE),
    ]
    assert questions[0].answer is not None and questions[1].answer is None


@pytest.mark.parametrize("path", ["", "/questions", "/events"])
def test_an_unknown_run_is_not_found_and_creates_nothing(
    app: FastAPI, settings: Settings, path: str
) -> None:
    response = signed_in(app).get(f"/api/runs/run:missing{path}")
    assert (response.status_code, response.json()) == (404, {"detail": "No run has this ID."})
    assert not (settings.cache_dir / "runs.sqlite").exists()


@pytest.mark.parametrize("run_id", ["..%2Foutside", "run 1", "-run", "a" * 129])
def test_malformed_run_ids_are_refused(app: FastAPI, run_id: str) -> None:
    client = signed_in(app)
    for path in ("", "/questions", "/events"):
        assert client.get(f"/api/runs/{run_id}{path}").status_code in (404, 422)
    assert client.post(f"/api/runs/{run_id}/cancel", headers=OWN).status_code in (404, 422)


def test_runs_need_a_session_like_everything_else(app: FastAPI, store: RunStore) -> None:
    queued(store, "q1")
    anonymous = visitor(app)
    for path in ("", "/questions", "/events"):
        assert anonymous.get(f"/api/runs/{RUN}{path}").status_code == 401
    assert anonymous.post(f"/api/runs/{RUN}/cancel", headers=OWN).status_code == 401
    assert store.requested(RUN) is None


# --- the event stream ----------------------------------------------------------------------


def test_the_stream_replays_a_finished_run_and_ends(
    app: FastAPI, store: RunStore, tmp_path: Path
) -> None:
    queued(store, "q1", "q2")
    worker(store, tmp_path).run(RUN)
    response = signed_in(app).get(EVENTS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    events, other = parse(response.text)
    assert other == ["retry: 2000"]
    assert events == store.events(RUN)
    assert len(events) == 30 and events[-1].kind.value == "run.completed"


def test_a_reconnect_gets_exactly_what_it_missed(
    app: FastAPI, store: RunStore, tmp_path: Path
) -> None:
    queued(store, "q1")
    worker(store, tmp_path).run(RUN)
    client = signed_in(app)
    everything = store.events(RUN)
    for seen in (0, 1, 7, 15, 16, 99):
        events, _ = parse(client.get(EVENTS, headers={"Last-Event-ID": str(seen)}).text)
        assert events == everything[seen:]
    # An ID that is not a number means the client knows nothing: send everything.
    for odd in ("", "abc", "-3", "1.5", WIDE_DIGITS, "7; DROP TABLE events"):
        events, _ = parse(client.get(EVENTS, headers={b"Last-Event-ID": odd.encode()}).text)
        assert events == everything


def test_the_last_event_id_is_a_plain_number_or_nothing() -> None:
    assert [last_seen(value) for value in ("0", "7", "0012")] == [0, 7, 12]
    assert [last_seen(value) for value in (None, "", "-1", "1e3", " 7", "seven", WIDE_DIGITS)] == [
        0
    ] * 7


def test_events_are_single_lines_whatever_a_message_contains(
    app: FastAPI, store: RunStore, tmp_path: Path
) -> None:
    queued(store, "q1")
    hostile = "Read api/x.py\n\nid: 999\nevent: run.completed\ndata: {}"

    def frame(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        return Step(next=QuestionStage.GATHER, state={}, activity=(hostile,))

    worker(store, tmp_path, frame=frame).run(RUN)
    text = signed_in(app).get(EVENTS).text
    events, other = parse(text)
    assert other == ["retry: 2000"]
    assert events == store.events(RUN)
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert hostile in [event.message for event in events]
    assert text.count("\nevent: run.completed\n") == 1


def test_the_stream_follows_a_run_while_it_is_worked_on(
    app: FastAPI, store: RunStore, tmp_path: Path
) -> None:
    queued(store, "q1", "q2")
    client = signed_in(app)
    started = threading.Event()

    def frame(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        started.set()
        time.sleep(0.4)  # long enough for the stream to be waiting on the worker
        return Step(next=QuestionStage.GATHER, state={"trail": ["frame"]})

    engine = worker(store, tmp_path, frame=frame)
    thread = threading.Thread(target=engine.run, args=(RUN,), daemon=True)
    thread.start()
    assert started.wait(timeout=10)
    running = store.run(RUN)
    assert running is not None and running.lifecycle is RunLifecycle.RUNNING
    events, _ = parse(client.get(EVENTS).text)  # returns only when the run has ended
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert events == store.events(RUN)
    assert events[-1].kind.value == "run.completed"


def test_a_paused_run_ends_the_stream_and_a_waiting_one_is_kept_open(
    store: RunStore, tmp_path: Path
) -> None:
    queued(store, "q1")
    slept: list[float] = []

    class Stop(Exception):
        pass

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        if sum(slept) > KEEP_ALIVE_SECONDS * 2:
            raise Stop

    # Queued, with no worker yet: the stream waits and says so now and then.
    sent: list[str] = []
    with pytest.raises(Stop):
        for chunk in stream(store, RUN, 0, sleep=sleep):
            sent.append(chunk)
    assert sent[0] == "retry: 2000\n\n"
    assert sent[1:] == [": waiting\n\n"] * 2
    assert set(slept) == {0.25}

    def frame(asked: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        store.request(RUN, "pause")
        return Step(next=QuestionStage.GATHER, state={})

    worker(store, tmp_path, frame=frame).run(RUN)
    chunks = list(stream(store, RUN, 0, sleep=sleep))
    assert json.loads(chunks[-1].split("data: ")[1])["kind"] == "run.paused"


def test_completion_between_stream_reads_never_loses_final_events(
    store: RunStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued(store, "q1")
    read_events = store.events
    completed = False

    def events(run_id: str, after: int = 0) -> list[RunEvent]:
        nonlocal completed
        result = read_events(run_id, after)
        if not completed:
            completed = True
            # Completion occurs just after the event read; the next event read must still
            # happen even if the lifecycle has changed to completed in the meantime.
            worker(store, tmp_path).run(RUN)
        return result

    monkeypatch.setattr(store, "events", events)
    sent, _ = parse("".join(stream(store, RUN, 0, sleep=lambda seconds: None)))
    assert sent == read_events(RUN)
    assert sent[-1].kind.value == "run.completed"


# --- cancel and pause ----------------------------------------------------------------------


def test_cancel_and_pause_are_requests_the_worker_honors(
    app: FastAPI, store: RunStore, tmp_path: Path
) -> None:
    queued(store, "q1", "q2")
    client = signed_in(app)
    paused = client.post(f"/api/runs/{RUN}/pause", headers=OWN)
    assert (paused.status_code, paused.json()) == (202, {"requested": "pause"})
    assert store.requested(RUN) == "pause"
    canceled = client.post(f"/api/runs/{RUN}/cancel", headers=OWN)
    assert (canceled.status_code, canceled.json()) == (202, {"requested": "cancel"})
    assert client.post(f"/api/runs/{RUN}/pause", headers=OWN).status_code == 202
    assert store.requested(RUN) == "cancel"  # a pause does not undo a cancel

    run = worker(store, tmp_path).run(RUN)
    assert run.lifecycle is RunLifecycle.CANCELED
    assert [q.status for q in store.questions(RUN)] == [QuestionStatus.CANCELED] * 2
    late = client.post(f"/api/runs/{RUN}/cancel", headers=OWN)
    assert (late.status_code, late.json()) == (409, {"detail": "This run has already ended."})


def test_control_routes_refuse_foreign_pages_and_unknown_runs(
    app: FastAPI, store: RunStore
) -> None:
    queued(store, "q1")
    client = signed_in(app)
    assert client.post(f"/api/runs/{RUN}/cancel").status_code == 403  # no origin named
    foreign = {"Origin": "http://127.0.0.1:8702"}
    assert client.post(f"/api/runs/{RUN}/cancel", headers=foreign).status_code == 403
    assert client.get(f"/api/runs/{RUN}/cancel").status_code == 405
    assert store.requested(RUN) is None
    assert client.post("/api/runs/run:missing/cancel", headers=OWN).status_code == 404
