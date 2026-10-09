"""Shared fixtures for the Tandir lab tests.

The tests cover legitimate actions and protections only; the intentional flaws
are declared in eval/ground_truth/tandir.toml (ADR-0005).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tandir.config import Settings
from tandir.main import create_app
from tandir.seed import PASSWORDS, seed

# "vulnerable" for the lab as written, "fixed" for the patched snapshot (M1.3).
VARIANT = os.environ.get("TANDIR_VARIANT", "vulnerable")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(reason="protection added by the fixed snapshot (M1.3)")
    for item in items:
        if VARIANT != "fixed" and item.get_closest_marker("fixed_only"):
            item.add_marker(skip)


class RecordedRun:
    """Stands in for subprocess.run: records the call, executes nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def __call__(self, args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


class Lab:
    def __init__(self, client: TestClient, settings: Settings, commands: RecordedRun) -> None:
        self.client = client
        self.settings = settings
        self.commands = commands
        self._tokens: dict[str, str] = {}

    def token(self, username: str) -> str:
        if username not in self._tokens:
            response = self.client.post(
                "/auth/login", json={"username": username, "password": PASSWORDS[username]}
            )
            assert response.status_code == 200, response.text
            self._tokens[username] = response.json()["token"]
        return self._tokens[username]

    def as_(self, username: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(username)}"}


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> RecordedRun:
    from tandir.routers import kitchen

    recorder = RecordedRun()
    monkeypatch.setattr(kitchen.subprocess, "run", recorder)
    return recorder


def _lab(data_dir: Path, commands: RecordedRun, *, printer: bool) -> Iterator[Lab]:
    settings = Settings(data_dir=data_dir, printer_enabled=printer)
    app = create_app(settings)
    with app.state.sessionmaker() as db:
        seed(db, settings)
    with TestClient(app) as client:
        yield Lab(client, settings, commands)
    app.state.engine.dispose()


@pytest.fixture
def lab(tmp_path: Path, commands: RecordedRun) -> Iterator[Lab]:
    """The seeded lab with the kitchen printer switched on (and recorded)."""
    yield from _lab(tmp_path / "var", commands, printer=True)


@pytest.fixture
def lab_printer_off(tmp_path: Path, commands: RecordedRun) -> Iterator[Lab]:
    """The seeded lab in its default configuration: kitchen printer offline."""
    yield from _lab(tmp_path / "var", commands, printer=False)
