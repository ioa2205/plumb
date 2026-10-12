"""Explicit provisioning of the pinned browser runner (ADR-0028).

    uv run --extra browser python -m backend.setup.browser           # installed and pinned
    uv run --extra browser python -m backend.setup.browser install   # explicit download
    uv run --extra browser python -m backend.setup.browser check     # version and hash

The download happens only on ``install``. It goes to the external data
directory, never into the repository, and uses Playwright's own installer for
the build that the pinned Playwright release selects. Afterwards the browser's
executable is hashed; a launch is refused when that hash differs from the pin.
"""

import hashlib
import importlib.metadata
import importlib.util
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from backend.settings import Settings

PIN_PATH = Path(__file__).with_name("pins") / "browser.toml"


class BrowserUnavailable(ValueError):
    """The pinned browser cannot be used. The message says what to run."""


def pin() -> dict[str, Any]:
    return tomllib.loads(PIN_PATH.read_text(encoding="utf-8"))


def directory(settings: Settings) -> Path:
    return settings.data_dir / "browsers"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _folder_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def status(settings: Settings) -> dict[str, Any]:
    """A read-only description: what is pinned, what is present and whether it matches."""
    pinned = pin()
    platform = pinned["executables"].get(sys.platform)
    result: dict[str, Any] = {
        "pinned_playwright": pinned["playwright"],
        "pinned_browser": f"{pinned['browser']} {pinned['browser_version']}",
        "revision": pinned["revision"],
        "licenses": [
            f"Playwright: {pinned['playwright_license']}",
            f"{pinned['browser']}: {pinned['browser_license']}",
        ],
        "download_source": pinned["source"],
        "install_location": str(directory(settings)),
        "playwright_installed": None,
        "executable": None,
        "installed_bytes": 0,
        "verified": False,
        "problems": [],
    }
    if platform is None:
        result["problems"].append("No browser build is pinned for this operating system.")
        return result
    if importlib.util.find_spec("playwright") is None:
        result["problems"].append(
            "The Playwright package is not installed. Run: uv sync --extra browser"
        )
    else:
        result["playwright_installed"] = importlib.metadata.version("playwright")
        if result["playwright_installed"] != pinned["playwright"]:
            result["problems"].append(
                f"Playwright {result['playwright_installed']} is installed; "
                f"{pinned['playwright']} is pinned."
            )
    executable = directory(settings) / platform["relative_path"]
    if not executable.is_file():
        result["problems"].append(
            "The pinned browser is not installed. Run: python -m backend.setup.browser install"
        )
        return result
    result["executable"] = str(executable)
    result["installed_bytes"] = _folder_bytes(directory(settings))
    actual = _sha256(executable)
    result["executable_sha256"] = actual
    if not platform["sha256"]:
        result["problems"].append("The pin has no executable hash yet; the browser stays refused.")
    elif actual != platform["sha256"] or executable.stat().st_size != platform["size"]:
        result["problems"].append(
            "The installed browser differs from its pinned hash. Reinstall it: "
            "python -m backend.setup.browser install"
        )
    result["verified"] = not result["problems"]
    return result


def verified_executable(settings: Settings) -> Path:
    """The pinned browser's executable, only when package version and hash both match."""
    report = status(settings)
    if not report["verified"]:
        raise BrowserUnavailable(" ".join(report["problems"]))
    return Path(report["executable"])


def install(settings: Settings) -> dict[str, Any]:
    """Download the pinned build with Playwright's installer. Explicit, never automatic."""
    if importlib.util.find_spec("playwright") is None:
        raise BrowserUnavailable(
            "The Playwright package is not installed. Run: uv sync --extra browser"
        )
    target = directory(settings)
    repository = Path(__file__).resolve().parents[2]
    if target.resolve() == repository or repository in target.resolve().parents:
        raise BrowserUnavailable("Browser files must live outside the repository.")
    target.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(target)}
    completed = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--only-shell", "--no-remove", "chromium"],
        env=env,
        check=False,
        timeout=1800,
    )
    if completed.returncode != 0:
        raise BrowserUnavailable("The browser download did not finish. Nothing was verified.")
    return status(settings)


def main(argv: list[str] | None = None) -> int:
    command = (argv if argv is not None else sys.argv[1:]) or ["status"]
    try:
        settings = Settings()
        if command == ["install"]:
            pinned = pin()
            print(
                f"Downloading {pinned['browser']} {pinned['browser_version']} for Playwright "
                f"{pinned['playwright']} into {directory(settings)} (about 0.3 GB on disk)."
            )
            report = install(settings)
        elif command in (["status"], ["check"]):
            report = status(settings)
        else:
            print("Use: python -m backend.setup.browser [status | install | check]")
            return 2
    except (BrowserUnavailable, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Browser setup stopped: {error}")
        return 1
    print(f"Pinned: Playwright {report['pinned_playwright']}, {report['pinned_browser']}")
    print(f"Location: {report['install_location']}")
    for line in report["licenses"]:
        print(f"Licence: {line}")
    if report["executable"]:
        print(f"Executable: {report['executable']}")
        print(f"SHA-256: {report.get('executable_sha256')}")
        print(f"On disk: {report['installed_bytes']} bytes")
    for problem in report["problems"]:
        print(f"Problem: {problem}")
    print("Verified: yes" if report["verified"] else "Verified: no")
    return 0 if report["verified"] or command == ["status"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
