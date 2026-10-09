"""Install the pinned Opengrep binary.

uv run python -m backend.setup.opengrep install
uv run python -m backend.setup.opengrep check
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from backend.settings import Settings
from backend.setup.download import fetch, is_verified
from backend.setup.llama_cpp import run_tool
from backend.setup.pins import OpengrepPin, load_opengrep_pin


def binary_path(settings: Settings, pin: OpengrepPin) -> Path:
    return settings.data_dir / "opengrep" / pin.release / "opengrep.exe"


def binary(settings: Settings, pin: OpengrepPin) -> Path:
    path = binary_path(settings, pin)
    if not is_verified(path, sha256=pin.asset.sha256, size=pin.asset.size):
        raise FileNotFoundError(f"{path} is missing or modified; run the opengrep install command")
    return path


def install(settings: Settings, pin: OpengrepPin, client: httpx.Client) -> Path:
    return fetch(
        pin.asset.url,
        binary_path(settings, pin),
        sha256=pin.asset.sha256,
        size=pin.asset.size,
        client=client,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["install", "check"])
    args = parser.parse_args(argv)
    settings, pin = Settings(), load_opengrep_pin()
    if args.command == "install":
        with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            path = install(settings, pin, client)
        print(f"installed and verified {path}")
        return 0
    result = run_tool(binary(settings, pin), "--version")
    print(f"$ opengrep --version  (exit {result.returncode})")
    print((result.stdout + result.stderr).strip())
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
