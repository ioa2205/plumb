"""Hash-verified downloads and safe archive extraction.

A downloaded file appears at its final path only after its size and SHA256
match the pin. Until then it lives next to it with a ``.part`` suffix.
"""

import hashlib
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

import httpx

CHUNK = 1 << 20

Progress = Callable[[int, int], None]


class DownloadError(Exception):
    """A download failed or did not match its pin."""


class UnsafeArchiveError(Exception):
    """An archive member would be written outside the extraction folder."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_verified(path: Path, *, sha256: str, size: int) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256_file(path) == sha256


def fetch(
    url: str,
    dest: Path,
    *,
    sha256: str,
    size: int,
    client: httpx.Client,
    progress: Progress | None = None,
) -> Path:
    """Download ``url`` to ``dest`` unless a verified copy is already there."""
    if is_verified(dest, sha256=sha256, size=size):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    received = 0
    try:
        with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            with part.open("wb") as out:
                for chunk in response.iter_bytes(CHUNK):
                    received += len(chunk)
                    if received > size:
                        raise DownloadError(f"{url}: more than the pinned {size} bytes")
                    digest.update(chunk)
                    out.write(chunk)
                    if progress is not None:
                        progress(received, size)
        if received != size:
            raise DownloadError(f"{url}: received {received} bytes, pinned size is {size}")
        actual = digest.hexdigest()
        if actual != sha256:
            raise DownloadError(f"{url}: SHA256 {actual} does not match the pin {sha256}")
    except httpx.HTTPError as error:
        part.unlink(missing_ok=True)
        raise DownloadError(f"{url}: {error}") from error
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(dest)
    return dest


def _check_member(name: str, root: Path) -> None:
    windows, posix = PureWindowsPath(name), PurePosixPath(name)
    if windows.drive or windows.root or posix.is_absolute():
        raise UnsafeArchiveError(f"absolute path in archive: {name!r}")
    if ".." in windows.parts or ".." in posix.parts:
        raise UnsafeArchiveError(f"parent reference in archive: {name!r}")
    if not (root / name).resolve().is_relative_to(root):
        raise UnsafeArchiveError(f"archive member escapes the target folder: {name!r}")


def extract_zip(archive: Path, target: Path) -> list[Path]:
    """Extract ``archive`` into ``target``; refuse the whole archive if any member is unsafe."""
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        for member in members:
            _check_member(member.filename, root)
        zf.extractall(root)
    return [root / m.filename for m in members if not m.is_dir()]
