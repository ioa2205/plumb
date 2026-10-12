"""A bounded, transient handoff between the protected UI and the browser's own thread.

No screenshot or input is written to a checkpoint. A stale screenshot cannot
authorize an event. The browser thread alone consumes an event and publishes
its result, so Playwright is never called from a request thread.
"""

import threading
import time

from backend.contracts.web_journey import HumanAuthInput, HumanAuthView


class HumanChannel:
    def __init__(self) -> None:
        self.changed = threading.Condition()
        self.view: HumanAuthView | None = None
        self._event: HumanAuthInput | None = None
        self._busy = False
        self._revision = 0
        self._closed = False

    def snapshot(self) -> HumanAuthView | None:
        with self.changed:
            return self.view

    def publish(self, view: HumanAuthView | None) -> None:
        with self.changed:
            self.view = view
            self._busy = False
            self._revision += 1
            self.changed.notify_all()

    def send(self, event: HumanAuthInput, *, seconds: float = 10) -> HumanAuthView | None:
        with self.changed:
            if self._closed or self.view is None:
                raise ValueError("There is no live human authentication step.")
            if self._busy or event.view_id != self.view.view_id:
                raise ValueError("Refresh the private challenge before sending another event.")
            revision = self._revision
            self._busy, self._event = True, event
            self.changed.notify_all()
            deadline = time.monotonic() + seconds
            while self._revision == revision and not self._closed:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise ValueError("The human event is still pending; refresh before continuing.")
                self.changed.wait(timeout=left)
            return self.view

    def take(self, *, seconds: float = 0.2) -> HumanAuthInput | None:
        with self.changed:
            if self._event is None and not self._closed:
                self.changed.wait(timeout=seconds)
            event, self._event = self._event, None
            return event

    def close(self) -> None:
        with self.changed:
            self.view, self._event, self._busy = None, None, False
            self._closed = True
            self._revision += 1
            self.changed.notify_all()
