"""A run's events as a server-sent event stream that can be picked up again.

Each event is sent with its number as the SSE ``id``. A browser that loses the
connection reconnects by itself and sends the last number it saw in
``Last-Event-ID``; the stream then starts after it. Nothing is skipped and
nothing is sent twice, because the numbers have no gaps (see ``RunStore``).

The stream ends when the run has ended or paused and everything has been sent.
While the run is being worked on it waits for more.
"""

import time
from collections.abc import Callable, Iterator

from backend.contracts.runs import TERMINAL, RunEvent, RunLifecycle
from backend.run_store import RunStore

RETRY_MILLISECONDS = 2000
POLL_SECONDS = 0.25
KEEP_ALIVE_SECONDS = 15.0


def last_seen(header: str | None) -> int:
    """The event number a client says it has; 0, and so a full replay, for anything else."""
    if header is None or not header.isascii() or not header.isdigit():
        return 0
    return int(header)


def frame(event: RunEvent) -> str:
    # One line of JSON: a line break inside the data would end the SSE field early.
    return f"id: {event.seq}\nevent: {event.kind.value}\ndata: {event.model_dump_json()}\n\n"


def stream(
    store: RunStore,
    run_id: str,
    after: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = POLL_SECONDS,
) -> Iterator[str]:
    yield f"retry: {RETRY_MILLISECONDS}\n\n"
    waited = 0.0
    while True:
        run = store.run(run_id)
        # Read after the run, so that an ending seen above has all of its events below.
        events = store.events(run_id, after)
        for event in events:
            yield frame(event)
            after = event.seq
        if run is None or run.lifecycle in TERMINAL or run.lifecycle is RunLifecycle.PAUSED:
            return
        if events:
            waited = 0.0
            continue
        sleep(poll_seconds)
        waited += poll_seconds
        if waited >= KEEP_ALIVE_SECONDS:
            yield ": waiting\n\n"  # a comment: keeps the connection open, means nothing
            waited = 0.0
