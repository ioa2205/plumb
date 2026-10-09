"""Download pinned model files.

    uv run python -m backend.setup.models list
    uv run python -m backend.setup.models install qwen3.5-2b-q4_k_m

Models are only downloaded when named explicitly: anything over 500 MB needs
the owner's approval first (AGENTS.md).
"""

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import httpx

from backend.settings import Settings
from backend.setup.download import Progress, fetch, is_verified
from backend.setup.pins import ModelPin, load_model_pins


def model_path(settings: Settings, model: ModelPin) -> Path:
    return settings.models_dir / model.file


def _progress() -> Progress:
    last = [0.0]

    def report(done: int, total: int) -> None:
        now = time.monotonic()
        if now - last[0] >= 15 or done == total:
            last[0] = now
            print(f"    {done / 1e6:8.1f} / {total / 1e6:.1f} MB", flush=True)

    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show pinned models and whether each is present and verified")
    inst = sub.add_parser("install", help="download and verify the named models")
    inst.add_argument("ids", nargs="+", metavar="MODEL_ID")
    args = parser.parse_args(argv)

    settings, pins = Settings(), load_model_pins()
    if args.command == "list":
        for m in pins.models:
            path = model_path(settings, m)
            state = "verified" if is_verified(path, sha256=m.sha256, size=m.size) else "absent"
            print(f"{m.id:32} {m.size / 1e9:5.2f} GB  {m.license:11} {state}")
        return 0

    try:
        chosen = [pins.get(model_id) for model_id in args.ids]
    except KeyError as error:
        parser.error(str(error))
    with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
        for m in chosen:
            print(f"{m.id}: {m.repo}@{m.revision[:8]} {m.file} ({m.size / 1e9:.2f} GB)", flush=True)
            fetch(
                m.url,
                model_path(settings, m),
                sha256=m.sha256,
                size=m.size,
                client=client,
                progress=_progress(),
            )
            print(f"  verified {m.sha256}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
