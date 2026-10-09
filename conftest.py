"""Skip, with the reason, tests that need files only the development checkout holds (M7.9c).

The development checkout keeps saved evaluation records under ``docs/results`` and a
prepared, hash-pinned runner environment for the practice app. A public copy has neither.
There, a test that stops for exactly that reason is reported as skipped with the reason.
Where the files exist nothing here applies, and a missing file is still a failure.
"""

import sys
from collections.abc import Generator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
RECORDS = ROOT / "docs" / "results"
LAB_PYTHON = (
    ROOT
    / "labs/tandir/api/.venv"
    / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
)
# verification.lab refuses with this sentence when the runner environment is not prepared.
LAB_REFUSAL = "Trusted lab interpreter differs from its local release manifest"


def absent_prerequisite(error: BaseException) -> str | None:
    """Why ``error`` is only a file this copy lacks, or None when it is a real failure."""
    if isinstance(error, FileNotFoundError) and not RECORDS.is_dir():
        missing = Path(str(error.filename or ""))
        if missing.is_absolute() and missing.is_relative_to(ROOT / "docs"):
            return (
                f"needs the saved record {missing.relative_to(ROOT).as_posix()}; "
                "this copy does not hold the evaluation records"
            )
    if not LAB_PYTHON.is_file() and LAB_REFUSAL in str(error):
        return (
            "needs the practice app's prepared runner environment (labs/tandir/api/.venv), "
            "which is not set up in this copy"
        )
    return None


def _skip_if_absent(error: BaseException) -> None:
    reason = absent_prerequisite(error)
    if reason is not None:
        pytest.skip(reason)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Generator[None]:
    try:
        return (yield)
    except Exception as error:
        _skip_if_absent(error)
        raise


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None]:
    try:
        return (yield)
    except Exception as error:
        _skip_if_absent(error)
        raise
