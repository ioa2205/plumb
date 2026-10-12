"""Wiring a journey to the real browser and the real local model (ADR-0028).

The browser and the model never run together: the journey closes the browser
and saves a checkpoint before any model question, and the model is stopped
again before the browser returns. When the model may not start (memory gate,
another task, first-use check pending) the journey goes on without it and says so.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from typing import Any

from agent.asking import ModelAsker, TimingLog
from agent.closed import Asker
from backend.contracts.web_journey import JourneyView, UserQuestion
from backend.jobs import WorkerBusy, WorkerLock
from backend.local_model import ModelNotReady, local_model
from backend.redaction import Redactor
from backend.settings import Settings
from backend.web_human import HumanChannel
from backend.web_journey import Journey
from backend.web_plan import QUESTION_SECONDS
from verification.egress import Egress
from verification.web_fixture import Fixture
from verification.web_secrets import SecretStore

MODEL_PHASE_SECONDS = 1800.0


def browser_factory(settings: Settings) -> Callable[..., AbstractContextManager[Any]]:
    def factory(
        egress: Egress, secrets: SecretStore, redactor: Redactor, expected: frozenset[str]
    ) -> AbstractContextManager[Any]:
        from verification.web_browser import BrowserRunner

        return BrowserRunner(
            settings, egress, secrets=secrets, redactor=redactor, expected_personal=expected
        )

    return factory


def model_factory(
    settings: Settings,
    profile: str,
    cancel: threading.Event,
    notes: list[str],
    progress: Callable[[str, str], None] | None = None,
) -> Callable[[], AbstractContextManager[Asker | None]]:
    """One model phase: load under the unchanged gates, or yield None and note why."""

    @contextmanager
    def factory() -> Iterator[Asker | None]:
        stack = ExitStack()
        manifest: dict[str, Any] = {}
        deadline = time.perf_counter() + MODEL_PHASE_SECONDS
        try:
            stack.enter_context(WorkerLock(settings.cache_dir / "review.lock"))
            loaded = stack.enter_context(
                local_model(
                    settings,
                    "website",
                    profile,
                    cancel=cancel,
                    deadline=lambda: deadline,
                    manifest=manifest,
                )
            )
        except WorkerBusy:
            stack.close()
            notes.append("Another Plumb task was using the local model, so it was not asked.")
            yield None
            return
        except (ModelNotReady, OSError, RuntimeError, ValueError) as error:
            stack.close()
            notes.append(f"The local model was not used: {error}")
            yield None
            return
        with stack:
            yield ModelAsker(
                loaded.adapter,
                profile=loaded.profile.id,
                seconds_per_question=QUESTION_SECONDS,
                log=TimingLog(settings.cache_dir / "closed-questions" / "timings.jsonl"),
                progress=progress,
            )

    return factory


def run_journey(
    settings: Settings,
    journey_id: str,
    *,
    secrets: SecretStore,
    cancel: threading.Event | None = None,
    fixture: Fixture | None = None,
    use_model: bool = True,
    profile: str = "auto",
    ask_user: Callable[[UserQuestion], str | None] | None = None,
    answers: dict[str, str] | None = None,
    on_update: Callable[[JourneyView], None] | None = None,
    progress: Callable[[str, str], None] | None = None,
    human: HumanChannel | None = None,
) -> tuple[JourneyView, list[str]]:
    """Run or resume one approved journey. Returns the saved view and notes about the model."""
    cancel = cancel or threading.Event()
    notes: list[str] = []
    view = Journey(
        settings,
        journey_id,
        secrets=secrets,
        cancel=cancel,
        fixture=fixture,
        model=model_factory(settings, profile, cancel, notes, progress) if use_model else None,
        browser=browser_factory(settings),
        ask_user=ask_user,
        answers=answers,
        on_update=on_update,
        human=human,
    ).run()
    return view, list(dict.fromkeys(notes))
