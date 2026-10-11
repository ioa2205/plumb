"""Trusted launch hooks are tested without spawning a process or sending HTTP."""

import io
import queue
from pathlib import Path

import httpx
import pytest

from backend.settings import Settings
from verification import lab
from verification.web_assessment import CollectionStopped


class OwnedProcess:
    def __init__(self) -> None:
        self.stdout = io.StringIO('{"port": 19999}\n')
        self.running = True
        self.terminated = False

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def wait(self, timeout: float) -> int:
        return 0


def test_explicit_readiness_replaces_default_requests_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owned = OwnedProcess()
    monkeypatch.setattr(lab.psutil, "process_iter", lambda *args: [])
    monkeypatch.setattr(lab.subprocess, "Popen", lambda *args, **kwargs: owned)
    calls: list[str] = []

    def ready(client: httpx.Client, origin: str) -> None:
        assert origin == "http://127.0.0.1:19999"
        calls.append("ready")
        raise CollectionStopped("canceled")

    def forbidden_get(*args: object, **kwargs: object) -> None:
        pytest.fail("an explicit readiness hook must replace all default health requests")

    monkeypatch.setattr(httpx.Client, "get", forbidden_get)
    with (
        pytest.raises(CollectionStopped, match="canceled"),
        lab.launch(
            {},
            Settings(data_dir=tmp_path),
            readiness_hook=ready,
            startup_check=lambda: None,
        ),
    ):
        pytest.fail("readiness cancellation must not yield a running lab")
    assert calls == ["ready"] and owned.terminated and owned.stdout.closed


def test_startup_cancellation_before_copy_never_spawns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden_spawn(*args: object, **kwargs: object) -> None:
        pytest.fail("canceled startup cannot spawn a target process")

    def canceled() -> None:
        raise CollectionStopped("canceled")

    monkeypatch.setattr(lab.subprocess, "Popen", forbidden_spawn)
    with (
        pytest.raises(CollectionStopped),
        lab.launch(
            {"unused.py": b"never copied"},
            Settings(data_dir=tmp_path),
            startup_check=canceled,
        ),
    ):
        pytest.fail("canceled startup cannot yield")
    assert not list(tmp_path.glob("**/unused.py"))


def test_handshake_polls_cancel_every_tenth_second_and_stops_owned_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owned = OwnedProcess()
    monkeypatch.setattr(lab.psutil, "process_iter", lambda *args: [])
    monkeypatch.setattr(lab.subprocess, "Popen", lambda *args, **kwargs: owned)
    waits: list[float] = []

    class EmptyHandshake:
        def __init__(self, **kwargs: object) -> None:
            pass

        def put(self, value: str) -> None:
            pass

        def get(self, timeout: float) -> str:
            waits.append(timeout)
            raise queue.Empty

    monkeypatch.setattr(lab.queue, "Queue", EmptyHandshake)

    def check() -> None:
        if len(waits) >= 2:
            raise CollectionStopped("time budget exhausted")

    with (
        pytest.raises(CollectionStopped, match="time budget"),
        lab.launch(
            {},
            Settings(data_dir=tmp_path),
            startup_check=check,
        ),
    ):
        pytest.fail("expired handshake cannot yield")
    assert len(waits) == 2 and max(waits) <= 0.1
    assert owned.terminated and owned.stdout.closed


def test_default_source_probe_keeps_existing_health_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owned = OwnedProcess()
    monkeypatch.setattr(lab.psutil, "process_iter", lambda *args: [])
    monkeypatch.setattr(lab.subprocess, "Popen", lambda *args, **kwargs: owned)
    calls: list[str] = []

    def get(self: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        return httpx.Response(200)

    monkeypatch.setattr(httpx.Client, "get", get)
    with lab.launch({}, Settings(data_dir=tmp_path)) as (origin, _client):
        assert origin == "http://127.0.0.1:19999" and not owned.terminated
    assert calls == ["http://127.0.0.1:19999/health"]
    assert owned.terminated and owned.stdout.closed
