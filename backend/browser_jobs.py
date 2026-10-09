"""One owned browser worker invoking the same frozen CLI workflow and gates."""

import argparse
import threading
from uuid import uuid4

from backend.cli import execute_review
from backend.contracts.runs import ReviewRun, RunLifecycle, RunType
from backend.contracts.setup_view import LaunchRequest, ResumeRequest
from backend.jobs import WorkerBusy
from backend.run_store import RunStore
from backend.settings import Settings
from backend.source_binding import association, inspection


class LaunchRefused(RuntimeError):
    pass


class BrowserJobs:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runs = RunStore(settings.cache_dir / "runs.sqlite")
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._run_id: str | None = None
        self._closing = False

    def launch(self, request: LaunchRequest) -> ReviewRun:
        root, snapshot = inspection(self.settings, request.inspection_id)
        args = argparse.Namespace(
            command="review",
            folder=root,
            resource=request.resources,
            route=request.routes,
            family=[f.value for f in request.families],
            guard_cache=None,
            profile="auto",
            limit=request.limit,
            open_report=False,
        )
        return self._start(args, "review-" + uuid4().hex, snapshot, association(root))

    def resume(self, run_id: str, request: ResumeRequest) -> ReviewRun:
        run = self.runs.run(run_id)
        if (
            run is None
            or run.run_type is not RunType.LIVE
            or run.lifecycle
            not in {
                RunLifecycle.PAUSED,
                RunLifecycle.QUEUED,
            }
        ):
            raise LaunchRefused("Only paused or queued live reviews can resume.")
        # Resume uses the saved frozen snapshot. No new folder read or authorization is inferred.
        args = argparse.Namespace(
            command="resume",
            run_id=run_id,
            profile=None,
            limit=request.limit,
            open_report=False,
        )
        return self._start(args, run_id, None)

    def _start(
        self,
        args: argparse.Namespace,
        run_id: str,
        snapshot: str | None,
        source: dict[str, object] | None = None,
    ) -> ReviewRun:
        ready = threading.Event()
        acknowledged = False
        failure: Exception | None = None

        def stopped(error: Exception) -> None:
            nonlocal failure
            failure = error

        def prepared(identifier: str) -> None:
            nonlocal acknowledged
            # Shutdown during preparation pauses before the engine's first source/model stage.
            with self._lock:
                if self._closing:
                    self.runs.request(identifier, "pause")
                acknowledged = True
                ready.set()

        def work() -> None:
            try:
                execute_review(
                    args,
                    self.settings,
                    requested_id=run_id,
                    expected_snapshot=snapshot,
                    ready=prepared,
                    expected_source=source,
                    failed=stopped,
                )
            finally:
                ready.set()

        with self._lock:
            if self._closing or (self._thread is not None and self._thread.is_alive()):
                raise WorkerBusy("A browser worker is already active.")
            self._run_id = run_id
            self._thread = threading.Thread(target=work, name="plumb-review", daemon=False)
            self._thread.start()
        # Source preparation is bounded by the existing snapshot/helper limits. On timeout,
        # request pause; do not report a started run whose durable creation was not observed.
        if not ready.wait(timeout=90):
            self.runs.request(run_id, "pause")
            self.close()
            raise LaunchRefused("Preparation did not complete; check the terminal.")
        run = self.runs.run(run_id)
        if isinstance(failure, WorkerBusy):
            raise failure
        if not acknowledged or run is None:
            raise LaunchRefused(
                "Review prerequisites or frozen source changed. "
                "Check readiness and inspect the folder again; read the terminal for details."
            )
        return run

    def close(self) -> None:
        """Stop at the next durable checkpoint and join; never leave an owned model behind."""
        with self._lock:
            self._closing = True
            thread, run_id = self._thread, self._run_id
            if run_id is not None:
                self.runs.request(run_id, "pause")
        if thread is not None:
            thread.join()
