"""A same-named program in the working folder is never started (PROJECT_PLAN §8)."""

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backend import system_tools, vulkan_profile
from backend.setup.__main__ import pnpm_command
from backend.system_tools import NO_WORKING_FOLDER, on_search_path, system_tool

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows program lookup")

PLANTED = ("powershell.exe", "nvidia-smi.exe", "pnpm.exe")
STAND_IN = """
class StandIn {
    static int Main() {
        string self = System.Reflection.Assembly.GetExecutingAssembly().Location;
        System.IO.File.AppendAllText(
            System.IO.Path.Combine(System.IO.Path.GetDirectoryName(self), "started.log"),
            System.IO.Path.GetFileName(self) + System.Environment.NewLine);
        return 0;
    }
}
"""


@pytest.fixture(scope="module")
def stand_in(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A harmless program that records, beside itself, that it was started."""
    compiler = system_tool("../Microsoft.NET/Framework64/v4.0.30319/csc.exe").resolve()
    if not compiler.is_file():
        pytest.skip("The Windows C# compiler that builds the stand-in program is absent")
    folder = tmp_path_factory.mktemp("stand-in")
    (folder / "stand_in.cs").write_text(STAND_IN, encoding="utf-8")
    subprocess.run(  # noqa: S603 - Windows' own compiler on this test's fixed source
        [str(compiler), "/nologo", "/out:stand_in.exe", "stand_in.cs"],
        cwd=folder,
        check=True,
        capture_output=True,
        timeout=120,
    )
    return folder / "stand_in.exe"


@pytest.fixture
def project(tmp_path: Path, stand_in: Path) -> Path:
    """A reviewed folder in which someone planted programs named like Plumb's tools."""
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "main.py").write_text("value = 1\n", encoding="utf-8")
    for name in PLANTED:
        shutil.copyfile(stand_in, folder / name)
    return folder


def started(project: Path) -> list[str]:
    log = project / "started.log"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def unprotected_environment(tmp_path: Path) -> dict[str, str]:
    """What a user's terminal passes on: Plumb itself must add the protection."""
    env = {k: v for k, v in os.environ.items() if k.upper() != NO_WORKING_FOLDER.upper()}
    return {**env, "PLUMB_DATA_DIR": str(tmp_path / "data")}


def test_every_plumb_process_excludes_the_working_folder() -> None:
    assert os.environ[NO_WORKING_FOLDER] == "1"  # set when the backend package is imported


def test_the_planted_program_would_start_without_the_protection(
    project: Path, tmp_path: Path
) -> None:
    # Control: shows the stand-in is a real hazard, so the checks below can fail.
    subprocess.run(
        [sys.executable, "-c", "import subprocess; subprocess.run(['nvidia-smi'])"],
        cwd=project,
        env=unprotected_environment(tmp_path),
        check=True,
        timeout=60,
    )
    assert started(project) == ["nvidia-smi.exe"]


@pytest.mark.parametrize("command", ["inspect", "review"])
def test_inspect_and_review_start_no_planted_program(
    project: Path, tmp_path: Path, command: str
) -> None:
    done = subprocess.run(  # noqa: S603 - Plumb's own command line on a fixture folder
        [sys.executable, "-m", "backend.cli", command, "."],
        cwd=project,
        env=unprotected_environment(tmp_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    # Each command reaches the machine-state reading taken as it finishes.
    invocation = next((tmp_path / "data" / "reviews").glob("*/invocation-*.json"))
    assert '"machine_end"' in invocation.read_text(encoding="utf-8"), done.stdout + done.stderr
    assert started(project) == []


def test_tool_lookups_ignore_the_working_folder(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even without the process-wide exclusion, each lookup must stay out of the folder.
    monkeypatch.delenv(NO_WORKING_FOLDER)
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", str(project), os.environ["PATH"]]))
    assert system_tool(system_tools.NVIDIA_SMI).parent == system_tool("")
    found = on_search_path("pnpm")
    assert found is None or project not in found.resolve().parents
    command = pnpm_command(Path(sys.executable))
    assert command is None or all(project not in Path(part).resolve().parents for part in command)
    # A machine without this graphics card refuses; it still starts nothing here.
    with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
        vulkan_profile.nvidia_free()
    assert started(project) == []


# --- A.5: one clear sentence on systems other than Windows (simulated; no such machine) ---


@pytest.mark.parametrize(
    "arguments",
    [["--help"], ["inspect", "anything"], ["report", "review-x"], ["doctor"], ["setup"], ["web"]],
)
def test_other_systems_get_one_sentence_instead_of_a_python_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> None:
    from backend import cli, serve
    from backend.setup import __main__ as wizard

    monkeypatch.setattr(sys, "platform", "linux")
    for entry in (lambda: cli.main(arguments), lambda: wizard.main([]), serve.main):
        assert entry() == 1
        printed = capsys.readouterr().out.strip()
        assert printed.count("\n") == 0 and "Windows 10 or 11 only for now" in printed
        assert "Traceback" not in printed


def test_the_command_line_imports_without_the_windows_registry_module() -> None:
    # On macOS and Linux "import winreg" fails; the public commands must not need it to start.
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['winreg'] = None; "
            "import backend.cli, backend.setup.__main__, backend.serve; print('imported')",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0 and "imported" in done.stdout, done.stderr
