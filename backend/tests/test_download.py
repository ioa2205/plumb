import hashlib
import zipfile
from pathlib import Path

import httpx
import pytest

from backend.setup.download import (
    DownloadError,
    UnsafeArchiveError,
    extract_zip,
    fetch,
    is_verified,
    sha256_file,
)

PAYLOAD = b"plumb pinned payload\n" * 1000
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
URL = "https://github.com/example/release/asset.zip"


def client_serving(body: bytes, status: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_fetch_writes_verified_file(tmp_path: Path) -> None:
    client, _ = client_serving(PAYLOAD)
    dest = fetch(URL, tmp_path / "a.zip", sha256=DIGEST, size=len(PAYLOAD), client=client)
    assert dest.read_bytes() == PAYLOAD
    assert sha256_file(dest) == DIGEST
    assert not (tmp_path / "a.zip.part").exists()


def test_fetch_skips_network_when_verified_copy_exists(tmp_path: Path) -> None:
    dest = tmp_path / "a.zip"
    dest.write_bytes(PAYLOAD)
    client, seen = client_serving(b"should not be requested")
    fetch(URL, dest, sha256=DIGEST, size=len(PAYLOAD), client=client)
    assert seen == []


def test_fetch_replaces_a_corrupt_existing_copy(tmp_path: Path) -> None:
    dest = tmp_path / "a.zip"
    dest.write_bytes(b"x" * len(PAYLOAD))
    client, seen = client_serving(PAYLOAD)
    fetch(URL, dest, sha256=DIGEST, size=len(PAYLOAD), client=client)
    assert len(seen) == 1
    assert is_verified(dest, sha256=DIGEST, size=len(PAYLOAD))


def test_hash_mismatch_leaves_nothing_behind(tmp_path: Path) -> None:
    tampered = PAYLOAD[:-1] + b"!"
    client, _ = client_serving(tampered)
    with pytest.raises(DownloadError, match="does not match the pin"):
        fetch(URL, tmp_path / "a.zip", sha256=DIGEST, size=len(PAYLOAD), client=client)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("body", [PAYLOAD[:-10], PAYLOAD + b"extra"])
def test_size_mismatch_is_refused(tmp_path: Path, body: bytes) -> None:
    client, _ = client_serving(body)
    with pytest.raises(DownloadError, match="bytes"):
        fetch(URL, tmp_path / "a.zip", sha256=DIGEST, size=len(PAYLOAD), client=client)
    assert list(tmp_path.iterdir()) == []


def test_http_error_is_reported_and_cleaned_up(tmp_path: Path) -> None:
    client, _ = client_serving(b"not found", status=404)
    with pytest.raises(DownloadError, match="404"):
        fetch(URL, tmp_path / "a.zip", sha256=DIGEST, size=len(PAYLOAD), client=client)
    assert list(tmp_path.iterdir()) == []


def make_zip(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, f"content of {name}")
    return path


def test_extract_zip_writes_members(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "ok.zip", ["llama-server.exe", "lib/ggml.dll"])
    files = extract_zip(archive, tmp_path / "out")
    assert sorted(p.name for p in files) == ["ggml.dll", "llama-server.exe"]
    assert (tmp_path / "out" / "lib" / "ggml.dll").read_text() == "content of lib/ggml.dll"


@pytest.mark.parametrize(
    "evil",
    ["../escape.txt", "lib/../../escape.txt", "/abs.txt", "C:/Windows/evil.dll", "..\\win.txt"],
)
def test_extract_zip_refuses_escaping_members(tmp_path: Path, evil: str) -> None:
    archive = make_zip(tmp_path / "evil.zip", ["fine.txt", evil])
    with pytest.raises(UnsafeArchiveError):
        extract_zip(archive, tmp_path / "out")
    # The whole archive is refused before anything is written.
    assert not (tmp_path / "out" / "fine.txt").exists()
    assert not (tmp_path / "escape.txt").exists()
