"""Protected local endpoints for website tests (ADR-0028).

Creating a scope, approving a plan and starting a run are three separate
requests. Nothing is visited before the third, and a chat message can make none
of them. Secrets arrive only with the run request, are held in memory for that
run and are never stored or returned.
"""

import threading
from contextlib import AbstractContextManager, suppress
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse

from backend.contracts.web_journey import (
    FixtureCreate,
    HumanAuthInput,
    HumanAuthView,
    JourneyApprove,
    JourneyCreate,
    JourneyList,
    JourneyRun,
    JourneyView,
    WebsiteReadiness,
)
from backend.settings import Settings
from backend.web_boundary import qualified
from backend.web_human import HumanChannel
from backend.web_journey import new_journey
from backend.web_plan import approve, revoke
from backend.web_run import run_journey
from backend.web_store import JourneyStore
from verification.web_fixture import Fixture, FixtureUnavailable, launch
from verification.web_secrets import SecretStore


class WebsiteJobs:
    """Owned worker threads and fixture processes for website tests in this server."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = JourneyStore(settings)
        self.lock = threading.RLock()
        self.threads: dict[str, threading.Thread] = {}
        self.cancels: dict[str, threading.Event] = {}
        self.fixtures: dict[str, tuple[AbstractContextManager[Fixture], Fixture]] = {}
        self.notes: dict[str, list[str]] = {}
        self.humans: dict[str, HumanChannel] = {}

    def read(self, journey_id: str) -> JourneyView:
        view = self.store.load(journey_id)
        if view.status in {"running", "handoff"} and journey_id not in self.threads:
            # The worker is gone (the server was restarted): say so instead of "running".
            view = view.model_copy(
                update={
                    "status": "paused",
                    "stop_reason": "The previous worker stopped. Completed work is kept.",
                    "activity": "Stopped with the server. Run it again to continue.",
                }
            )
        return view

    def create_fixture(self, variant: Literal["open", "defended"]) -> JourneyView:
        with self.lock:
            if any(fixture.variant == variant for _, fixture in self.fixtures.values()):
                raise ValueError("That practice website is already running for another test")
            manager = launch(variant, self.settings)
            fixture = manager.__enter__()
            try:
                view = new_journey(self.settings, fixture.scope())
            except BaseException:
                manager.__exit__(None, None, None)
                raise
            self.fixtures[view.journey_id] = (manager, fixture)
            return view

    def release_fixture(self, journey_id: str) -> None:
        with self.lock:
            entry = self.fixtures.pop(journey_id, None)
        if entry is not None:
            with suppress(Exception):
                entry[0].__exit__(None, None, None)

    def start(self, journey_id: str, request: JourneyRun) -> JourneyView:
        with self.lock:
            view = self.read(journey_id)
            if journey_id in self.threads:
                raise ValueError("This website test is already running")
            if view.status not in {"approved", "paused", "handoff"}:
                raise ValueError("Approve the plan first, or this test has already ended")
            fixture = self.fixtures.get(journey_id, (None, None))[1]
            if view.scope.mode == "owned_fixture" and fixture is None:
                raise ValueError("The practice website for this test is no longer running")
            secrets = fixture.secrets if fixture is not None else SecretStore()
            for ref, value in request.secrets.items():
                if ref not in {account.secret_ref for account in view.scope.accounts}:
                    raise ValueError("A secret was given for an account this scope does not name")
                secrets.put(ref, value)
            secrets.load_environment([a.secret_ref for a in view.scope.accounts if a.provisioned])
            cancel = threading.Event()
            thread = threading.Thread(
                target=self._run, args=(journey_id, request, secrets, cancel, fixture), daemon=True
            )
            self.threads[journey_id], self.cancels[journey_id] = thread, cancel
            self.humans[journey_id] = HumanChannel()
            view = view.model_copy(update={"status": "running", "activity": "Starting."})
            self.store.save(view, secrets=secrets.values())
            thread.start()
            return view

    def _run(
        self,
        journey_id: str,
        request: JourneyRun,
        secrets: SecretStore,
        cancel: threading.Event,
        fixture: Fixture | None,
    ) -> None:
        try:
            view, notes = run_journey(
                self.settings,
                journey_id,
                secrets=secrets,
                cancel=cancel,
                fixture=fixture,
                use_model=request.use_model,
                profile=request.profile,
                answers=request.answers,
                human=self.humans[journey_id],
            )
            self.notes[journey_id] = notes
            if view.status in {"done", "stopped", "failed"}:
                self.release_fixture(journey_id)
        except Exception:
            with suppress(Exception):
                view = self.store.load(journey_id)
                self.store.save(
                    view.model_copy(
                        update={
                            "status": "failed",
                            "stop_reason": "The worker stopped on an internal error. "
                            "Completed work is kept.",
                        }
                    ),
                    secrets=secrets.values(),
                )
        finally:
            if channel := self.humans.pop(journey_id, None):
                channel.close()
            if fixture is None:
                secrets.clear()
            with self.lock:
                self.threads.pop(journey_id, None)
                self.cancels.pop(journey_id, None)

    def stop(self, journey_id: str) -> JourneyView:
        with self.lock:
            if event := self.cancels.get(journey_id):
                event.set()
            return self.read(journey_id)

    def human_view(self, journey_id: str) -> HumanAuthView | None:
        with self.lock:
            self.read(journey_id)  # validate the journey id/storage boundary
            channel = self.humans.get(journey_id)
            return channel.snapshot() if channel is not None else None

    def human_input(self, journey_id: str, event: HumanAuthInput) -> HumanAuthView | None:
        with self.lock:
            self.read(journey_id)
            channel = self.humans.get(journey_id)
        if channel is None:
            raise ValueError("There is no live human authentication step.")
        return channel.send(event)

    def close(self) -> None:
        for event in list(self.cancels.values()):
            event.set()
        for channel in list(self.humans.values()):
            channel.close()
        self.humans.clear()
        for thread in list(self.threads.values()):
            thread.join(timeout=90)
        for journey_id in list(self.fixtures):
            self.release_fixture(journey_id)


def router(jobs: WebsiteJobs) -> APIRouter:
    result = APIRouter(prefix="/api/websites")
    settings = jobs.settings

    def refused(error: Exception) -> HTTPException:
        detail = str(error) if isinstance(error, ValueError | FixtureUnavailable) else ""
        return HTTPException(
            status_code=409,
            detail=(detail[:300] if detail and "validation error" not in detail else "")
            or "Website request refused. Check the scope, the approval and the saved test.",
        )

    def guarded(action: Any) -> Any:  # noqa: ANN401 - a small wrapper around route bodies
        try:
            return action()
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.get("", response_model=JourneyList)
    def listing() -> JourneyList:
        return JourneyList(journeys=[jobs.read(view.journey_id) for view in jobs.store.list()])

    @result.get("/readiness", response_model=WebsiteReadiness)
    def readiness() -> WebsiteReadiness:
        from backend.setup.browser import status

        browser = status(settings)
        external = qualified(settings)
        return WebsiteReadiness(
            browser_ready=bool(browser["verified"]),
            browser_note="The pinned browser is installed and verified."
            if browser["verified"]
            else " ".join(browser["problems"])[:400],
            external_ready=external is None,
            external_note=external
            or "The network boundary is qualified; an approved external scope may run.",
        )

    @result.post("/fixture", response_model=JourneyView)
    def fixture(request: FixtureCreate) -> JourneyView:
        return guarded(lambda: jobs.create_fixture(request.variant))

    @result.post("", response_model=JourneyView)
    def create(request: JourneyCreate) -> JourneyView:
        if request.scope.mode != "external":
            raise HTTPException(status_code=409, detail="Use the practice-site button for that.")
        return guarded(lambda: new_journey(settings, request.scope))

    @result.get("/{journey_id}", response_model=JourneyView)
    def read(journey_id: str) -> JourneyView:
        return guarded(lambda: jobs.read(journey_id))

    @result.post("/{journey_id}/approve", response_model=JourneyView)
    def approve_plan(journey_id: str, request: JourneyApprove) -> JourneyView:
        def action() -> JourneyView:
            view = approve(jobs.store.load(journey_id), request)
            jobs.store.save(view)
            return view

        return guarded(action)

    @result.post("/{journey_id}/run", response_model=JourneyView, status_code=202)
    def run(journey_id: str, request: JourneyRun) -> JourneyView:
        return guarded(lambda: jobs.start(journey_id, request))

    @result.post("/{journey_id}/stop", response_model=JourneyView)
    def stop(journey_id: str) -> JourneyView:
        return guarded(lambda: jobs.stop(journey_id))

    @result.get("/{journey_id}/human", response_model=HumanAuthView | None)
    def human_view(journey_id: str, response: Response) -> HumanAuthView | None:
        response.headers["Cache-Control"] = "no-store"
        return guarded(lambda: jobs.human_view(journey_id))

    @result.post("/{journey_id}/human", response_model=HumanAuthView | None)
    def human_input(
        journey_id: str, request: HumanAuthInput, response: Response
    ) -> HumanAuthView | None:
        response.headers["Cache-Control"] = "no-store"
        return guarded(lambda: jobs.human_input(journey_id, request))

    @result.post("/{journey_id}/revoke", response_model=JourneyView)
    def withdraw(journey_id: str) -> JourneyView:
        def action() -> JourneyView:
            jobs.stop(journey_id)
            view = revoke(jobs.store.load(journey_id))
            jobs.store.save(view)
            return view

        return guarded(action)

    @result.get("/{journey_id}/report", response_class=PlainTextResponse)
    def report(journey_id: str) -> PlainTextResponse:
        def action() -> PlainTextResponse:
            view = jobs.read(journey_id)
            folder = jobs.store.folder(journey_id).resolve()
            path = Path(view.report_path or "").resolve()
            if not view.report_path or path.parent != folder or not path.is_file():
                raise ValueError("This website test has no report yet")
            return PlainTextResponse(
                path.read_text(encoding="utf-8"),
                media_type="text/markdown; charset=utf-8",
                headers={"Cache-Control": "no-store"},
            )

        return guarded(action)

    return result
