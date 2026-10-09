"""Exercise actual Ctrl+Break delivery and CLI unwinding without loading a model."""

import json
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from backend.console import review_interrupts
from backend.tests.cli_interrupt_worker import RUN


def test_signal_scope_does_not_change_background_thread_handlers() -> None:
    errors: list[Exception] = []

    def worker() -> None:
        try:
            with review_interrupts():
                pass
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive() and errors == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console control event")
def test_break_handler_restored_after_exception() -> None:
    previous = signal.getsignal(signal.SIGBREAK)
    with pytest.raises(KeyboardInterrupt), review_interrupts():
        assert signal.getsignal(signal.SIGBREAK) is signal.default_int_handler
        raise KeyboardInterrupt
    assert signal.getsignal(signal.SIGBREAK) == previous


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console control event")
@pytest.mark.parametrize("phase", ["running", "construction"])
def test_real_console_break_preserves_report_and_stops_owned_resources(
    tmp_path: Path, phase: str
) -> None:
    process = subprocess.Popen(  # noqa: S603 - fixed trusted fixture, never target code
        [sys.executable, "-m", "backend.tests.cli_interrupt_worker", str(tmp_path), phase],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    lines: queue.Queue[str] = queue.Queue()

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line.rstrip())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    output = []
    try:
        while True:
            line = lines.get(timeout=15)
            output.append(line)
            if line == "READY_FOR_BREAK":
                break
        process.send_signal(signal.CTRL_BREAK_EVENT)
        assert process.wait(timeout=15) == 2
        reader.join(timeout=2)
        output.extend(list(lines.queue))
        assert "Interrupted. Saved checkpoints can be resumed." in output
        assert all(
            (tmp_path / name).read_text() == "done"
            for name in (
                "context-closed",
                "model-stopped",
                "adapter-closed",
                "returned",
            )
        )
        directory = tmp_path / "data/reviews" / RUN
        report = json.loads((directory / "report.json").read_bytes())
        assert report["run"]["lifecycle"] == "paused"
        assert report["run"]["coverage"]["pending"] == 1 and report["findings"] == []
        invocation = json.loads(next(directory.glob("invocation-*.json")).read_bytes())
        assert invocation["memory_abort"] is None and invocation["findings"] == []
        assert invocation["requests"] == [] and "error" not in invocation
        assert invocation["machine_end"]["real_model"] is False
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
