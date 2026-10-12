"""The interactive terminal entry: plain messages in, explicit yes/no before any work."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import chat_cli, cli
from backend.chat import ABOUT, GENERAL_BASIS, Chats
from backend.chat_cli import run_repl
from backend.settings import Settings

from .test_chat import Model, model, text  # noqa: F401 - the fixture is used by name


class Terminal:
    def __init__(self, *lines: str) -> None:
        self.lines = list(lines)
        self.asked: list[str] = []
        self.shown: list[str] = []

    def read(self, prompt: str) -> str:
        self.asked.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)

    def write(self, line: str) -> None:
        self.shown.append(line)

    @property
    def output(self) -> str:
        return "\n".join(self.shown)


def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def test_a_plain_question_is_answered_without_ids_or_commands(
    tmp_path: Path,
    model: Model,  # noqa: F811
) -> None:
    model.intents, model.texts = ["general_question"], [text("It injects SQL text.")]
    terminal = Terminal("What is SQL injection?", "/quit")
    assert run_repl(settings(tmp_path), read=terminal.read, write=terminal.write) == 0
    assert "Type a message in your own words" in terminal.output
    assert "Each answer stops at 320 tokens" in terminal.output
    assert "I read this as a general question. (decided by the local model)" in terminal.output
    assert "It injects SQL text." in terminal.output and GENERAL_BASIS in terminal.output
    assert "(local model: 2 requests" in terminal.output


def test_an_unclear_message_gets_a_numbered_question_and_the_pick_is_the_users(
    tmp_path: Path,
    model: Model,  # noqa: F811
) -> None:
    model.intents = ["cannot_tell:unclear_request", "cannot_tell:unclear_request"]
    terminal = Terminal("hmm", "6")
    assert run_repl(settings(tmp_path), read=terminal.read, write=terminal.write) == 0
    assert "Please pick one" in terminal.output
    assert "  6. Tell me what Plumb can do" in terminal.output
    assert ABOUT in terminal.output and "(your choice)" in terminal.output
    assert len(model.closed) == 2  # asked once, then once more reordered; never a third time


def test_a_folder_is_inspected_only_after_an_explicit_yes(
    tmp_path: Path,
    model: Model,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    calls: list[str] = []

    def inspect(_: Settings, folder: str) -> SimpleNamespace:
        calls.append(folder)
        return SimpleNamespace(
            name="project",
            included_files=12,
            entries_total=3,
            excluded_files=1,
            limitations=["Static only."],
            inspection_id="inspect-" + "a" * 32,
        )

    monkeypatch.setattr("backend.setup_reads.inspect_folder", inspect)
    monkeypatch.setattr(Chats, "_label", lambda self, target: "Inspected folder project")
    model.intents = ["review_folder", "review_folder"]
    declined = Terminal(f"Review my folder {project}", "n", "/quit")
    run_repl(settings(tmp_path), read=declined.read, write=declined.write)
    assert calls == [] and "Nothing has been read yet" in declined.output
    accepted = Terminal(f"Review my folder {project}", "y", "/quit")
    run_repl(settings(tmp_path), read=accepted.read, write=accepted.write)
    assert calls == [str(project)]
    assert "Inspected project: 12 files read, 3 entry points recognized" in accepted.output
    assert "This folder is now selected" in accepted.output
    assert any("Nothing in it is run" in prompt for prompt in accepted.asked)


def test_ctrl_c_stops_the_answer_and_the_chat_goes_on(
    tmp_path: Path,
    model: Model,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model.intents = ["general_question", "general_question"]
    model.texts = [text("Never shown."), text("Shown.")]
    interrupted = iter([True, False])
    real_sleep = time.sleep

    def sleep(seconds: float) -> None:
        # Interrupt only once the answer is really being written.
        if model.written and next(interrupted, False):
            raise KeyboardInterrupt
        real_sleep(0.01)

    model.gate = threading.Event()
    # Only the terminal loop's own clock: the worker thread keeps the real one.
    monkeypatch.setattr(chat_cli, "time", SimpleNamespace(sleep=sleep))
    terminal = Terminal("First", "Second", "/quit")
    original = Chats.cancel

    def cancel(self: Chats, identifier: str) -> object:
        result = original(self, identifier)
        assert model.gate is not None
        model.gate.set()
        return result

    monkeypatch.setattr(Chats, "cancel", cancel)
    assert run_repl(settings(tmp_path), read=terminal.read, write=terminal.write) == 0
    assert "Stopping. Earlier turns are kept." in terminal.output
    assert "Never shown." not in terminal.output and "Shown." in terminal.output


def test_plumb_without_a_command_opens_the_chat_and_one_message_can_be_sent(
    tmp_path: Path,
    model: Model,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "unsupported_system", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError))
    assert cli.main([]) == 0
    assert "Type a message in your own words" in capsys.readouterr().out
    model.intents, model.texts = ["creative_writing"], [text("Leaves fall.")]
    assert cli.main(["chat", "Write a short poem"]) == 0
    printed = capsys.readouterr().out
    assert "Leaves fall." in printed and "Type a message" not in printed
