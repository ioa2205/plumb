"""Build and check Tandir's fixed snapshot (task M1.3, ADR-0005).

    python labs/tandir/fixed/snapshot.py make DEST   # copy the lab to DEST, apply the patches
    python labs/tandir/fixed/snapshot.py check       # make it in a temp folder, run both suites

The fixed snapshot is the lab plus api.patch and web.patch from this folder. On it,
the lab tests run with TANDIR_VARIANT=fixed, which adds the fixed-only protection tests.
Standard library only; needs git, uv, and pnpm on PATH.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
PATCHES = (LAB / "fixed" / "api.patch", LAB / "fixed" / "web.patch")
SKIP = shutil.ignore_patterns(
    ".venv",
    "node_modules",
    ".next",
    "var",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "*.tsbuildinfo",
    "next-env.d.ts",
)


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} is not on PATH")
    return path


def _repository_root() -> Path:
    out = subprocess.run(
        [_tool("git"), "rev-parse", "--show-toplevel"],
        cwd=LAB,
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(out.stdout.strip()).resolve()


def make(dest: Path) -> Path:
    dest = dest.resolve()
    if dest.exists():
        raise SystemExit(f"{dest} already exists")
    if dest.is_relative_to(_repository_root()):
        # Inside a repository, git apply resolves paths against its root.
        raise SystemExit(f"{dest} is inside the repository; choose a folder outside it")
    for part in ("api", "web"):
        shutil.copytree(LAB / part, dest / part, ignore=SKIP)
    # Never let git discover a repository above the copy.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(dest.parent)}
    for patch in PATCHES:
        for extra in (["--check"], []):
            subprocess.run(
                [_tool("git"), "apply", *extra, str(patch)], cwd=dest, env=env, check=True
            )
    return dest


def _link_node_modules(web: Path) -> Path:
    """Point the copy at the lab's installed packages instead of reinstalling them."""
    source = LAB / "web" / "node_modules"
    if not source.is_dir():
        raise SystemExit("run pnpm install in labs/tandir/web first")
    link = web / "node_modules"
    if sys.platform == "win32":
        # A directory junction needs no administrator rights.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(source)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(source, target_is_directory=True)
    return link


def _unlink(link: Path) -> None:
    # Remove only the link; never recurse into the lab's real node_modules.
    if sys.platform == "win32":
        os.rmdir(link)
    else:
        link.unlink()


def check() -> int:
    env = {**os.environ, "TANDIR_VARIANT": "fixed"}
    with tempfile.TemporaryDirectory(prefix="tandir-fixed-", ignore_cleanup_errors=True) as tmp:
        dest = make(Path(tmp) / "tandir")
        print(f"fixed snapshot at {dest}", flush=True)
        link = _link_node_modules(dest / "web")
        try:
            steps = [
                ("api tests", [_tool("uv"), "run", "--frozen", "pytest", "-q"], dest / "api"),
                ("web typecheck", [_tool("pnpm"), "exec", "tsc", "--noEmit"], dest / "web"),
                ("web tests", [_tool("pnpm"), "exec", "vitest", "run"], dest / "web"),
            ]
            for label, command, cwd in steps:
                print(f"--- {label}", flush=True)
                result = subprocess.run(command, cwd=cwd, env=env, check=False)
                if result.returncode != 0:
                    print(f"FAILED: {label} (exit {result.returncode})", flush=True)
                    return result.returncode
        finally:
            _unlink(link)
    print("fixed snapshot: all checks passed", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    make_parser = sub.add_parser("make", help="copy the lab and apply the patch set")
    make_parser.add_argument("dest", type=Path)
    sub.add_parser("check", help="build the snapshot in a temporary folder and run both suites")
    args = parser.parse_args()
    if args.command == "make":
        print(make(args.dest))
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
