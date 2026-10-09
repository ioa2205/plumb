"""Export the contracts as JSON Schema (draft 2020-12).

uv run python -m backend.contracts.export          # write backend/contracts/schemas/
uv run python -m backend.contracts.export --check  # fail if the files are stale
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from backend.contracts import CONTRACTS, READ_CONTRACTS

SCHEMA_DIR = Path(__file__).with_name("schemas")


def render() -> dict[str, str]:
    """File name -> schema text, for every contract."""
    files = {}
    for model in (*CONTRACTS, *READ_CONTRACTS):
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://plumb.local/schemas/{model.__name__}.schema.json"
        files[f"{model.__name__}.schema.json"] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return files


def stale(directory: Path = SCHEMA_DIR) -> list[str]:
    expected = render()
    present = {p.name for p in directory.glob("*.schema.json")} if directory.is_dir() else set()
    changed = [
        name
        for name, text in expected.items()
        if not (directory / name).is_file()
        or (directory / name).read_text(encoding="utf-8") != text
    ]
    return sorted(changed + sorted(present - set(expected)))


def write(directory: Path = SCHEMA_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    expected = render()
    for path in directory.glob("*.schema.json"):
        if path.name not in expected:
            path.unlink()
    for name, text in expected.items():
        (directory / name).write_text(text, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if schemas are stale")
    args = parser.parse_args(argv)
    if args.check:
        if out_of_date := stale():
            print("stale schemas (run python -m backend.contracts.export):", *out_of_date)
            return 1
        print(f"{len(CONTRACTS) + len(READ_CONTRACTS)} schemas up to date")
        return 0
    write()
    print(f"wrote {len(CONTRACTS) + len(READ_CONTRACTS)} schemas to {SCHEMA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
