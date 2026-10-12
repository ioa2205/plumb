"""One owned local model for a bounded piece of work: admission, cancel, deadline, cleanup.

The profile, memory and first-use gates are the existing ones, unchanged. The
server is stopped when the work is canceled, when its deadline passes and always
on the way out, and the manifest says whether that stop really happened.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent.closed import QuestionType
from agent.llm import ModelAdapter, PreflightRefused
from backend.profiles import Profile, create, first_use_pending, select
from backend.redaction import Redactor
from backend.settings import Settings

_LIVE_RUNTIME = object()


class _QualifiedAdapter(ModelAdapter):
    closed_qualification: Callable[[QuestionType], str | None]


class ModelNotReady(ValueError):
    """The model may not start now. The message is written for the user."""


@dataclass(frozen=True)
class Loaded:
    adapter: ModelAdapter
    profile: Profile
    _runtime_witness: object | None = None


def verified_runtime(loaded: Loaded) -> bool:
    """Only the real admission path supplies the live witness; scripted loads do not."""
    return loaded._runtime_witness is _LIVE_RUNTIME


@contextmanager
def local_model(
    settings: Settings,
    name: str,
    requested_profile: str,
    *,
    cancel: threading.Event,
    deadline: Callable[[], float],
    manifest: dict[str, Any],
    clock: Callable[[], float] = time.perf_counter,
) -> Iterator[Loaded]:
    """Load the selected profile's model for the ``with`` block, then stop it.

    ``deadline`` returns the ``clock`` time after which the server is stopped.
    Raises ``ModelNotReady`` before anything is started when a gate refuses.
    """
    manifest.update(model_created=False, model_stopped=None)
    try:
        profile = select(settings, requested_profile)
    except ValueError as error:
        raise ModelNotReady(str(error)) from error
    if first_use_pending(settings, profile):
        raise ModelNotReady(
            f"The profile {profile.id} has not been checked on this computer yet. "
            f"Run: plumb calibrate --profile {profile.id}"
        )
    if cancel.is_set() or clock() >= deadline():
        raise ModelNotReady("Stopped before the model was started.")
    server = create(settings, name + "-" + uuid4().hex, profile)
    manifest.update(model_created=True, model_stopped=False, profile=profile.identity())
    server.startup_timeout = min(server.startup_timeout, max(0.01, deadline() - clock()))
    finished = threading.Event()
    stop_lock = threading.Lock()

    def stop_server() -> None:
        with stop_lock:
            try:
                server.stop()
            except (OSError, RuntimeError) as error:
                manifest["model_stopped"] = False
                manifest["cleanup_error"] = type(error).__name__
                raise
            manifest["model_stopped"] = True

    def watch() -> None:
        while not finished.wait(0.1):
            if cancel.is_set() or clock() >= deadline():
                # An error here is recorded; the owner makes the final attempt below.
                with suppress(OSError, RuntimeError):
                    stop_server()
                return

    monitor = threading.Thread(target=watch, daemon=True)
    monitor.start()
    try:
        adapter = _QualifiedAdapter(
            server, preflight=server.preflight, redactor=Redactor.configured(settings)
        )
        try:
            adapter.start()
        except PreflightRefused as error:
            manifest["preflight_refused"] = error.result.message
            raise ModelNotReady(error.result.message) from error
        try:
            from backend.model_qualification import Qualifications

            adapter.closed_qualification = Qualifications(settings, profile.identity()).reason
            yield Loaded(adapter, profile, _LIVE_RUNTIME)
        finally:
            with suppress(OSError, RuntimeError):
                adapter.close()
    finally:
        finished.set()
        try:
            stop_server()
        finally:
            monitor.join(timeout=1)
