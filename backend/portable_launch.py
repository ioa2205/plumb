"""Standalone standard-library entry point copied to a portable artifact's root.

The inventory detects damaged/modified installs, not a malicious replacement of
both manifest and launcher. Release signing and clean-profile acceptance are separate.
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path, PureWindowsPath


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def member(root: Path, name: str) -> Path:
    if (
        not name
        or "\\" in name
        or ":" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or re.search(r'[<>"|?*\x00-\x1f]', name)
        or any(PureWindowsPath(part).is_reserved() for part in name.split("/"))
        or any(part.endswith((".", " ")) for part in name.split("/"))
    ):
        raise ValueError("Invalid package path")
    result = root / name
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Package path escapes installation")
    for part in (result, *result.parents):
        if part == root:
            break
        if part.is_symlink() or part.is_junction():
            raise ValueError("Linked package content is not supported")
    return result


def verify(root: Path) -> dict[str, object]:
    manifest = member(root, "release.json")
    if manifest.stat().st_size > 4_000_000:
        raise ValueError("Package inventory is too large")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("format") != 1 or not isinstance(record.get("files"), dict):
        raise ValueError("Unknown package inventory")
    expected = record["files"]
    if not expected or len(expected) > 25000:
        raise ValueError("Invalid package inventory")
    folded: set[str] = set()
    for name, sha in expected.items():
        if (
            name.casefold() in folded
            or not isinstance(sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha)
        ):
            raise ValueError("Invalid package digest")
        folded.add(name.casefold())
        path = member(root, name)
        if not path.is_file() or digest(path) != sha:
            raise ValueError(f"Package content changed or missing: {name}")
    actual = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            path = Path(directory) / name
            member(root, path.relative_to(root).as_posix())
        actual.update((Path(directory) / name).relative_to(root).as_posix() for name in files)
    if actual != set(expected) | {"release.json"}:
        raise ValueError("Unexpected files in installation; extract a fresh package")
    return record


def main() -> int:
    root = Path(__file__).resolve().parent
    try:
        verify(root)
        data = os.environ.get("PLUMB_DATA_DIR")
        if data and Path(data).resolve().is_relative_to(root):
            raise ValueError("Keep PLUMB_DATA_DIR outside the portable installation")
        os.environ["PLUMB_NODE_BINARY"] = str(root / "node/node.exe")
        os.environ["OTEL_SDK_DISABLED"] = "true"
        # Import only after validating the assembled application/dependencies.
        from backend.cli import main as cli_main

        if len(sys.argv) == 1:
            sys.argv.append("web")
        return cli_main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Plumb portable could not start: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
