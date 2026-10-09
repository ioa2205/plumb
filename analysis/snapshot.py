"""Content-addressed project snapshots (PROJECT_PLAN §5 and §8, task M2.1).

A snapshot is the exact set of files a review looks at, read from the working
tree, so uncommitted changes are included. Each included file is copied into a
content-addressed blob store as it is read, and every later read (index,
evidence packets, citations) comes from the store, never from the live tree.

Nothing here runs a program from or on the project. In particular, git is not
invoked: a repository's own config can make git run commands (fsmonitor, filter
drivers). The commit is read from the files in ``.git`` instead, and whether the
tree is dirty is left undetermined.
"""

import fnmatch
import hashlib
import os
import re
import stat
import sys
from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from analysis.paths import (
    canonical_root,
    check_relative,
    has_extra_links,
    inside,
    is_link,
    resolve_inside,
)
from backend.contracts.code import (
    ExcludedFile,
    ExclusionReason,
    ProjectSnapshot,
    SnapshotFile,
    snapshot_id,
)
from backend.contracts.common import Language

MIB = 1024 * 1024

LANGUAGES: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".ts": Language.TYPESCRIPT,
    ".mts": Language.TYPESCRIPT,
    ".cts": Language.TYPESCRIPT,
    ".tsx": Language.TSX,
    ".js": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
}
# Text files kept for configuration, routing, and dependency signals.
TEXT_SUFFIXES = frozenset(
    {
        ".json",
        ".jsonc",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".conf",
        ".md",
        ".txt",
        ".sql",
        ".html",
        ".css",
        ".scss",
        ".lock",
        ".example",
    }
)
TEXT_NAMES = frozenset(
    {"Dockerfile", "Makefile", "Procfile", ".gitignore", ".python-version", ".nvmrc"}
)
# Known secret files: excluded from snapshots (and so from model context) and listed.
SECRET_PATTERNS = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
)
SECRET_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".pnpm-store",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".next",
        ".turbo",
        ".cache",
        "dist",
        "build",
        "out",
        "coverage",
        "htmlcov",
        ".idea",
        ".vscode",
    }
)
BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 1 * MIB
    max_files: int = 20_000
    max_total_bytes: int = 256 * MIB


class SnapshotTooLargeError(RuntimeError):
    """The project exceeds the snapshot limits; a partial snapshot would hide code."""


class ChangedWhileReadingError(RuntimeError):
    """A file was replaced (for example by a link) between its check and its read."""


class SnapshotConflictError(ValueError):
    """The same content address was supplied with different review metadata."""


class BlobStore:
    """Files by SHA256, written once, verified on every read."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError(f"not a SHA256: {sha256!r}")
        return self.directory / sha256[:2] / sha256

    def put(self, data: bytes) -> str:
        sha256 = hashlib.sha256(data).hexdigest()
        path = self._path(sha256)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{sha256}.{os.getpid()}.part")
            temporary.write_bytes(data)
            temporary.replace(path)
        return sha256

    def get(self, sha256: str) -> bytes:
        data = self._path(sha256).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError(f"blob {sha256[:12]}… is corrupted")
        return data


class SnapshotStore:
    """Snapshot manifests plus the blobs they reference, under one folder."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.blobs = BlobStore(directory / "blobs")

    def _manifest(self, snapshot_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise ValueError(f"not a snapshot id: {snapshot_id!r}")
        return self.directory / "snapshots" / f"{snapshot_id}.json"

    def save(self, snapshot: ProjectSnapshot) -> ProjectSnapshot:
        """Publish once; identical recaptures return the first capture's metadata.

        Only capture time may differ. Other differences (including excluded scope)
        must fail rather than silently replacing or misrepresenting an old review.
        """
        snapshot = ProjectSnapshot.model_validate(snapshot.model_dump())
        path = self._manifest(snapshot.id)
        try:
            stored = self.load(snapshot.id)
        except FileNotFoundError:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            try:
                with NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(snapshot.model_dump_json(indent=1).encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                with suppress(FileExistsError):
                    # Atomic create-if-absent: readers see a complete file, and a
                    # concurrent writer cannot replace the winning manifest.
                    os.link(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink()
            stored = self.load(snapshot.id)
        if stored.model_dump(exclude={"created_at"}) != snapshot.model_dump(exclude={"created_at"}):
            raise SnapshotConflictError(f"snapshot {snapshot.id} has conflicting metadata")
        return stored

    def load(self, snapshot_id: str) -> ProjectSnapshot:
        text = self._manifest(snapshot_id).read_text(encoding="utf-8")
        snapshot = ProjectSnapshot.model_validate_json(text)
        if snapshot.id != snapshot_id:
            raise ValueError("snapshot manifest id does not match its storage key")
        return snapshot

    def read(self, snapshot: ProjectSnapshot, path: str) -> bytes:
        """A file's bytes as they were when the snapshot was taken."""
        check_relative(path)
        entry = next((f for f in snapshot.files if f.path == path), None)
        if entry is None:
            raise FileNotFoundError(f"{path} is not in snapshot {snapshot.id[:12]}…")
        return self.blobs.get(entry.sha256)


@dataclass
class _Walk:
    root: Path
    limits: Limits
    sealed: set[str]
    files: list[SnapshotFile] = field(default_factory=list)
    excluded: list[ExcludedFile] = field(default_factory=list)
    total_bytes: int = 0

    def exclude(self, rel: str, reason: ExclusionReason) -> None:
        self.excluded.append(ExcludedFile(path=rel, reason=reason))


def _is_secret(name: str) -> bool:
    if name in SECRET_TEMPLATES:
        return False
    return any(fnmatch.fnmatchcase(name.lower(), pattern) for pattern in SECRET_PATTERNS)


def _kind(name: str) -> tuple[bool, Language | None]:
    """Whether a file name is kept, and its language if it is source code."""
    suffix = Path(name).suffix.lower()
    if suffix in LANGUAGES:
        return True, LANGUAGES[suffix]
    return (suffix in TEXT_SUFFIXES or name in TEXT_NAMES), None


def read_contained(path: Path, expected: os.stat_result, max_bytes: int) -> bytes | None:
    """Read at most ``max_bytes``; None when the file is larger.

    The open handle must be the same file that was checked (same device and
    inode), so a file swapped for a link after the check is never read.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise ChangedWhileReadingError(f"{path} changed while it was being read")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        return None if len(data) > max_bytes else data
    finally:
        os.close(fd)


def _walk_dir(walk: _Walk, directory: Path, prefix: str) -> Iterator[tuple[str, Path]]:
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name)
    except OSError:
        walk.exclude(prefix.rstrip("/") or ".", ExclusionReason.UNREADABLE)
        return
    for entry in entries:
        rel = f"{prefix}{entry.name}"
        try:
            st = os.lstat(entry.path)
        except OSError:
            walk.exclude(rel, ExclusionReason.UNREADABLE)
            continue
        if is_link(st):
            walk.exclude(rel, ExclusionReason.LINK)
        elif stat.S_ISDIR(st.st_mode):
            if entry.name in IGNORED_DIRS or entry.name.endswith(".egg-info"):
                walk.exclude(rel, ExclusionReason.DEFAULT_IGNORED)
            else:
                yield from _walk_dir(walk, Path(entry.path), f"{rel}/")
        elif not stat.S_ISREG(st.st_mode):
            walk.exclude(rel, ExclusionReason.UNSUPPORTED)
        elif has_extra_links(st):
            walk.exclude(rel, ExclusionReason.LINK)
        else:
            yield rel, Path(entry.path)


def _take(walk: _Walk, store: BlobStore) -> None:
    for rel, path in _walk_dir(walk, walk.root, ""):
        name = path.name
        if rel in walk.sealed:
            walk.exclude(rel, ExclusionReason.SEALED)
            continue
        if _is_secret(name):
            walk.exclude(rel, ExclusionReason.SECRET)
            continue
        kept, language = _kind(name)
        if not kept:
            walk.exclude(rel, ExclusionReason.UNSUPPORTED)
            continue
        try:
            check_relative(rel)
        except ValueError:
            walk.exclude(rel, ExclusionReason.UNSUPPORTED)  # e.g. a Windows device name
            continue
        try:
            st = os.lstat(path)
            data = read_contained(path, st, walk.limits.max_file_bytes)
        except (OSError, ChangedWhileReadingError):
            walk.exclude(rel, ExclusionReason.UNREADABLE)
            continue
        if data is None:
            walk.exclude(rel, ExclusionReason.TOO_LARGE)
            continue
        if b"\0" in data[:BINARY_SNIFF_BYTES]:
            walk.exclude(rel, ExclusionReason.BINARY)
            continue
        walk.total_bytes += len(data)
        if len(walk.files) >= walk.limits.max_files:
            raise SnapshotTooLargeError(f"more than {walk.limits.max_files} files to review")
        if walk.total_bytes > walk.limits.max_total_bytes:
            raise SnapshotTooLargeError(
                f"more than {walk.limits.max_total_bytes // MIB} MiB of files to review"
            )
        walk.files.append(
            SnapshotFile(path=rel, sha256=store.put(data), size=len(data), language=language)
        )


def git_commit(root: Path) -> str | None:
    """The checked-out commit, read from ``.git`` files without running git.

    None when there is no plain ``.git`` folder inside the root (a worktree's
    ``.git`` file points outside it), when HEAD is unborn, or on anything odd.
    """
    try:
        git = resolve_inside(root, ".git")
        if not git.is_dir():
            return None
        head = resolve_inside(root, ".git/HEAD").read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
            return head  # detached HEAD
        match = re.fullmatch(r"ref: (refs/heads/[A-Za-z0-9._/-]+)", head)
        if match is None or ".." in match.group(1):
            return None
        ref = match.group(1)
        try:
            value = resolve_inside(root, f".git/{ref}").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            packed = resolve_inside(root, ".git/packed-refs").read_text(encoding="utf-8")
            value = next(
                (line.split(" ")[0] for line in packed.splitlines() if line.endswith(f" {ref}")),
                "",
            )
        return value if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) else None
    except (OSError, ValueError):
        return None


def capture_snapshot(
    root: Path,
    store: SnapshotStore,
    *,
    limits: Limits | None = None,
    sealed: Iterable[Path] = (),
    now: datetime | None = None,
) -> ProjectSnapshot:
    """Read bounded current source into blobs without publishing a snapshot manifest.

    Source freshness checks use this observation so changed excluded scope cannot
    replace (or conflict with) a saved review's content-addressed manifest.
    """
    canonical = canonical_root(root)
    sealed_rel = {
        Path(os.path.relpath(p.resolve(), canonical)).as_posix()
        for p in sealed
        if inside(canonical, p.resolve())
    }
    walk = _Walk(root=canonical, limits=limits or Limits(), sealed=sealed_rel)
    _take(walk, store.blobs)
    snapshot = ProjectSnapshot(
        id=snapshot_id(walk.files),
        root_name=canonical.name,
        created_at=now or datetime.now(UTC),
        git_commit=git_commit(canonical),
        dirty=None,
        files=walk.files,
        excluded=walk.excluded,
    )
    return snapshot


def take_snapshot(
    root: Path,
    store: SnapshotStore,
    *,
    limits: Limits | None = None,
    sealed: Iterable[Path] = (),
    now: datetime | None = None,
) -> ProjectSnapshot:
    """Publish a frozen working-tree snapshot with unchanged metadata-conflict checks."""
    return store.save(capture_snapshot(root, store, limits=limits, sealed=sealed, now=now))


def main(argv: list[str] | None = None) -> int:
    import argparse
    from collections import Counter

    from backend.settings import Settings
    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(description="Snapshot a project folder for review.")
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    store = SnapshotStore(Settings().cache_dir / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    languages = Counter(f.language.value for f in snapshot.files if f.language)
    reasons = Counter(e.reason.value for e in snapshot.excluded)
    print(f"snapshot {snapshot.id}")
    print(f"root {snapshot.root_name}, commit {snapshot.git_commit or 'unknown'}")
    print(f"{len(snapshot.files)} files ({sum(f.size for f in snapshot.files):,} bytes): "
          f"{dict(languages)}")  # fmt: skip
    print(f"excluded {len(snapshot.excluded)}: {dict(reasons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
