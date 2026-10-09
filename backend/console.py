"""Route Windows console breaks through the CLI's existing interruption cleanup."""

import signal
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def review_interrupts() -> Iterator[None]:
    # Browser review threads do not own process-global signal handlers.
    if sys.platform != "win32" or threading.current_thread() is not threading.main_thread():
        yield
        return
    break_signal = signal.SIGBREAK
    previous = signal.signal(break_signal, signal.default_int_handler)
    try:
        yield
    finally:
        signal.signal(break_signal, previous)
