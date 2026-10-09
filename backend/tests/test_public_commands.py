"""Public entry points reuse the engine and protected bootstrap; no model/browser in tests."""

import argparse
import asyncio
import socket
import webbrowser
from pathlib import Path

import pytest
import uvicorn

from backend import cli, serve
from backend.setup import __main__ as wizard


def forbidden(*args: object, **kwargs: object) -> None:
    pytest.fail("Public setup/web tried to construct review settings or start analysis")


def test_setup_routes_all_flags_to_the_existing_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[argparse.Namespace] = []

    def execute(args: argparse.Namespace) -> int:
        seen.append(args)
        return 2

    monkeypatch.setattr(wizard, "execute", execute)
    monkeypatch.setattr(cli, "Settings", forbidden)
    assert (
        cli.main(
            [
                "setup",
                "--install",
                "--inspect-only",
                "--json",
                "--data-dir",
                "custom",
                "--approve-large-downloads",
            ]
        )
        == 2
    )
    args = seen[0]
    assert args.install and args.inspect_only and args.json and args.approve_large_downloads
    assert args.data_dir == Path("custom")  # validation remains in the real installer


@pytest.mark.parametrize("headless", [False, True])
def test_web_routes_to_same_server_without_starting_review(
    monkeypatch: pytest.MonkeyPatch, headless: bool
) -> None:
    opened: list[bool] = []

    def main(*, open_browser: bool = False) -> int:
        opened.append(open_browser)
        return 1

    monkeypatch.setattr(serve, "main", main)
    monkeypatch.setattr(cli, "Settings", forbidden)
    assert cli.main(["web", *(["--no-open"] if headless else [])]) == 1
    assert opened == [not headless]


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("browser", ["success", "refused", "error"])
def test_browser_waits_for_server_start_and_failure_keeps_the_link_usable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], started: bool, browser: str
) -> None:
    link = "http://127.0.0.1:8700/session/fixture-one-time-token"
    running = serve.BrowserServer(uvicorn.Config("unused", log_config=None), link)
    calls: list[str] = []

    async def startup(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        self.started = started

    def open_link(url: str) -> bool:
        assert running.started
        calls.append(url)
        if browser == "error":
            raise webbrowser.Error("fixture")
        return browser == "success"

    monkeypatch.setattr(uvicorn.Server, "startup", startup)
    monkeypatch.setattr(serve.webbrowser, "open", open_link)
    asyncio.run(running.startup())
    assert calls == ([link] if started else [])
    output = capsys.readouterr().out
    assert "fixture-one-time-token" not in output  # original link is printed only by main
    assert ("Browser did not open" in output) == (started and browser != "success")


def test_port_collision_explains_next_action_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def occupied(port: int) -> socket.socket:
        raise OSError("fixture port occupied")

    monkeypatch.setattr(serve, "bind", occupied)
    assert serve.main() == 1
    output = capsys.readouterr().out
    assert "Close the existing Plumb server" in output and "PLUMB_PORT" in output
    assert "Traceback" not in output
