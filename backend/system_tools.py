"""Find helper programs without ever looking in the working folder.

Plumb is often started from inside the project it reads. Windows looks for a
bare program name in the current folder before anywhere else, so a bare name
could start a same-named file planted in that project (PROJECT_PLAN §8).
"""

import os
import platform
import shutil
import sys
from pathlib import Path

POWERSHELL = "WindowsPowerShell/v1.0/powershell.exe"
NVIDIA_SMI = "nvidia-smi.exe"
# Windows' own spelling; the name is not case-sensitive there.
NO_WORKING_FOLDER = "NoDefaultCurrentDirectoryInExePath"


def unsupported_system() -> str | None:
    """One sentence for a system Plumb does not run on yet; None on Windows."""
    if sys.platform == "win32":
        return None
    return (
        "Plumb runs on 64-bit Windows 10 or 11 only for now; "
        f"this system ({platform.system() or sys.platform}) is not supported yet."
    )


def exclude_working_folder() -> None:
    """Make this process and its children skip the current folder for bare names."""
    if sys.platform == "win32":
        os.environ[NO_WORKING_FOLDER] = "1"


def system_tool(name: str) -> Path:
    """Windows system directory, never a same-named program in an analyzed folder."""
    if sys.platform != "win32":
        raise OSError("Windows system tools exist only on Windows")
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError("Cannot locate Windows system tools")
    return Path(buffer.value) / name


def on_search_path(name: str) -> Path | None:
    """First match in an absolute PATH folder other than the working folder."""
    here = Path.cwd().resolve()
    folders = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and Path(entry).is_absolute() and Path(entry).resolve() != here
    ]
    found = shutil.which(name, path=os.pathsep.join(folders))
    # Without the exclusion above, Windows lookup still offers ".\name"; refuse it.
    if found is None or not Path(found).is_absolute():
        return None
    return Path(found)
