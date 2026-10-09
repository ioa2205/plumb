"""Path safety for reading a reviewed project (PROJECT_PLAN §8, task M2.1).

Every path Plumb reads is checked against the registered root:

- a requested path is snapshot-relative POSIX text, never absolute, never
  ``..``, and free of Windows tricks (drive letters, alternate data streams,
  reserved device names, trailing dots or spaces);
- each component on the way down is checked with ``lstat``: symlinks,
  junctions, and other reparse points are refused, not followed;
- files with more than one hard link are refused, since a hard link can point
  at a file outside the root;
- the final canonical path must still lie inside the canonical root.
"""

import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath

from pydantic import TypeAdapter, ValidationError

from backend.contracts.common import RelPath

_REL_PATH = TypeAdapter(RelPath)
# Windows device names, with or without an extension ("nul", "con.txt", "com1.py").
_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\..*)?$", re.I)
_CONTROL = re.compile(r"[\x00-\x1f]")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafePathError(ValueError):
    """A requested path could escape the root or reach through a link."""


class RootError(ValueError):
    """The project root is missing, not a directory, or not usable."""


def canonical_root(path: Path) -> Path:
    """The registered root: absolute, resolved, and an existing directory."""
    try:
        root = path.resolve(strict=True)
    except OSError as e:
        raise RootError(f"project folder not found: {path}") from e
    if not root.is_dir():
        raise RootError(f"not a folder: {path}")
    return root


def is_link(st: os.stat_result) -> bool:
    """True for symlinks, junctions, and any other Windows reparse point."""
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def has_extra_links(st: os.stat_result) -> bool:
    """True for a regular file that is also reachable under another name."""
    return stat.S_ISREG(st.st_mode) and st.st_nlink > 1


def check_relative(rel: str) -> PurePosixPath:
    """Validate a snapshot-relative path; raise UnsafePathError if it is not one."""
    try:
        _REL_PATH.validate_python(rel)
    except ValidationError as e:
        raise UnsafePathError(f"not a path inside the project: {rel!r}") from e
    path = PurePosixPath(rel)
    for part in path.parts:
        if _CONTROL.search(part) or ":" in part:
            raise UnsafePathError(f"not a plain file name: {part!r}")
        if part.endswith((".", " ")):
            # Windows drops trailing dots and spaces, so "a." would open "a".
            raise UnsafePathError(f"name ends with a dot or space: {part!r}")
        if _DEVICE.match(part):
            raise UnsafePathError(f"reserved device name: {part!r}")
    return path


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


def inside(root: Path, path: Path) -> bool:
    """True when ``path`` is ``root`` or below it (case-insensitively on Windows)."""
    if sys.platform == "win32":
        root_text, path_text = os.path.normcase(root), os.path.normcase(path)
        return path_text == root_text or path_text.startswith(root_text.rstrip("\\") + "\\")
    return path == root or path.is_relative_to(root)


def resolve_inside(root: Path, rel: str) -> Path:
    """The file or folder at ``rel`` under the canonical ``root``, with no link on the way.

    Raises UnsafePathError for an unsafe request or a link, and FileNotFoundError
    when the path does not exist.
    """
    current = root
    for part in check_relative(rel).parts:
        current = current / part
        st = os.lstat(current)
        if is_link(st):
            raise UnsafePathError(f"refusing to follow a link: {rel!r}")
        if has_extra_links(st):
            raise UnsafePathError(f"refusing a file with several hard links: {rel!r}")
    final = current.resolve(strict=True)
    if not inside(root, final) or not _same(final, current):
        raise UnsafePathError(f"path resolves outside the project: {rel!r}")
    return current
