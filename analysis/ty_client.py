"""Bounded, read-only LSP client for the trusted, pinned ty binary.

Only snapshot Python files are staged. Target configuration, environments and
executables are never copied. The server runs with no PATH/PYTHONPATH, an empty
home, generated configuration, uv disabled and untrustedWorkspace enabled.
"""

import json
import os
import queue
import subprocess
import sysconfig
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO, Any

import psutil

from analysis.paths import check_relative

TY_VERSION = "0.0.84"
MAX_MESSAGE = 8 * 1024 * 1024


class TyUnavailable(RuntimeError):
    """The optional type-aware resolver failed; retain the import fallback."""


@dataclass(frozen=True)
class TyLimits:
    request_seconds: float = 10
    total_seconds: float = 60
    rss_bytes: int = 384 * 1024 * 1024


def trusted_binary() -> Path:
    """No PATH lookup and no executable supplied by the reviewed repository."""
    if version("ty") != TY_VERSION:
        raise TyUnavailable(f"Python resolution requires ty {TY_VERSION}")
    name = "ty.exe" if os.name == "nt" else "ty"
    binary = Path(sysconfig.get_path("scripts")) / name
    if not binary.is_file():
        raise TyUnavailable("The pinned ty executable is missing")
    return binary.resolve()


def isolated_environment(directory: Path) -> dict[str, str]:
    # Windows needs SystemRoot to load system DLLs. No activated Python, user
    # configuration, PATH executables, proxies, TY_* or UV_* values are inherited.
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR"}}
    env.update(
        PATH="",
        HOME=str(directory),
        USERPROFILE=str(directory),
        APPDATA=str(directory),
        LOCALAPPDATA=str(directory),
        XDG_CONFIG_HOME=str(directory),
        TMP=str(directory),
        TEMP=str(directory),
        RAYON_NUM_THREADS="2",
    )
    return env


def read_message(stream: IO[bytes]) -> dict[str, Any]:
    """Read one bounded LSP frame; EOF/malformed input fails closed."""
    size: int | None = None
    header_bytes = 0
    while True:
        line = stream.readline(4097)
        header_bytes += len(line)
        if not line or header_bytes > 4096:
            raise TyUnavailable("ty returned an incomplete or oversized header")
        if line == b"\r\n":
            break
        key, separator, value = line.partition(b":")
        if not separator:
            raise TyUnavailable("ty returned a malformed header")
        if key.lower() == b"content-length":
            if size is not None:
                raise TyUnavailable("ty returned duplicate content lengths")
            try:
                size = int(value.strip())
            except ValueError as error:
                raise TyUnavailable("ty returned a malformed content length") from error
    if size is None or not 0 < size <= MAX_MESSAGE:
        raise TyUnavailable("ty returned an invalid message size")
    raw = stream.read(size)
    if len(raw) != size:
        raise TyUnavailable("ty closed the stream mid-message")
    try:
        message = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise TyUnavailable("ty returned invalid JSON") from error
    if not isinstance(message, dict):
        raise TyUnavailable("ty returned a non-object message")
    return message


class TyClient:
    def __init__(self, root: Path, config: Path, home: Path, limits: TyLimits) -> None:
        self.root = root
        self.limits = limits
        self.peak_rss_bytes = 0
        self.started = time.monotonic()
        self.messages: queue.Queue[dict[str, Any] | Exception] = queue.Queue(maxsize=128)
        self.stopped = threading.Event()
        self.failure: str | None = None
        self.sequence = 0
        self.process = subprocess.Popen(  # noqa: S603 - fixed, trusted executable; no shell
            [str(trusted_binary()), "server"],
            cwd=home,
            env=isolated_environment(home),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.reader.start()
        self.monitor.start()
        try:
            reply = self.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": root.as_uri(),
                    "workspaceFolders": [{"uri": root.as_uri(), "name": "snapshot"}],
                    "capabilities": {"general": {"positionEncodings": ["utf-16"]}},
                    "initializationOptions": {
                        "untrustedWorkspace": True,
                        "experimental": {"useUv": "off"},
                        "configurationFile": str(config),
                        "diagnosticMode": "off",
                    },
                },
            )
            capabilities = reply.get("capabilities", {}) if isinstance(reply, dict) else {}
            if capabilities.get("positionEncoding", "utf-16") != "utf-16":
                raise TyUnavailable("ty did not negotiate UTF-16 positions")
            if not capabilities.get("referencesProvider"):
                raise TyUnavailable("ty does not support find-references")
            self.notify("initialized", {})
        except Exception:
            self.close()
            raise

    def _read(self) -> None:
        stream = self.process.stdout
        if stream is None:
            return
        try:
            while not self.stopped.is_set():
                self.messages.put_nowait(read_message(stream))
        except queue.Full:
            self.failure = "ty exceeded the message queue limit"
            self.process.kill()
        except (OSError, TyUnavailable) as error:
            if not self.stopped.is_set():
                try:
                    self.messages.put_nowait(error)
                except queue.Full:
                    self.failure = "ty exceeded the message queue limit"

    def _monitor(self) -> None:
        try:
            process = psutil.Process(self.process.pid)
        except psutil.NoSuchProcess:
            return
        while not self.stopped.wait(0.05):
            try:
                self.peak_rss_bytes = max(self.peak_rss_bytes, process.memory_info().rss)
            except psutil.NoSuchProcess:
                return
            except psutil.AccessDenied:
                self.failure = "ty memory could not be monitored"
                self.process.kill()
                return
            if self.peak_rss_bytes > self.limits.rss_bytes:
                self.failure = "ty exceeded the RSS budget"
            elif time.monotonic() - self.started > self.limits.total_seconds:
                self.failure = "ty exceeded the total time budget"
            if self.failure:
                self.process.kill()
                return

    def _write(self, message: dict[str, Any]) -> None:
        stream = self.process.stdin
        if stream is None or self.process.poll() is not None:
            raise TyUnavailable(self.failure or "ty exited")
        raw = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=True).encode()
        if len(raw) > MAX_MESSAGE:
            raise TyUnavailable("LSP request exceeds the message budget")
        try:
            stream.write(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
            stream.flush()
        except OSError as error:
            raise TyUnavailable(self.failure or "ty closed its input") from error

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"method": method, "params": params})

    def request(self, method: str, params: dict[str, Any] | None) -> object:
        self.sequence += 1
        request_id = self.sequence
        self._write({"id": request_id, "method": method, "params": params})
        deadline = min(
            time.monotonic() + self.limits.request_seconds,
            self.started + self.limits.total_seconds,
        )
        while True:
            remaining = deadline - time.monotonic()
            if self.failure or remaining <= 0:
                raise TyUnavailable(self.failure or "ty request timed out")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as error:
                raise TyUnavailable("ty request timed out") from error
            if isinstance(message, Exception):
                raise TyUnavailable(self.failure or str(message)) from message
            if "method" in message:
                if "id" in message:
                    # No workspace edits, dynamic registrations, configuration
                    # requests or other server-initiated actions are executed.
                    self._write(
                        {"id": message["id"], "error": {"code": -32601, "message": "Disabled"}}
                    )
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise TyUnavailable(f"ty rejected {method}")
            return message.get("result")

    def open_file(self, path: str, text: str) -> None:
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": (self.root / path).as_uri(),
                    "languageId": "python",
                    "version": 1,
                    "text": text,
                }
            },
        )

    def references(self, path: str, line: int, character: int) -> list[dict[str, Any]]:
        result = self.request(
            "textDocument/references",
            {
                "textDocument": {"uri": (self.root / path).as_uri()},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": False},
            },
        )
        if result is None:
            return []
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise TyUnavailable("ty returned malformed references")
        return result

    def close(self) -> None:
        # Kill only our own helper; bound teardown even after protocol failure.
        self.stopped.set()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        self.monitor.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()


@contextmanager
def snapshot_server(
    sources: dict[str, bytes], roots: list[str], cache: Path, limits: TyLimits | None = None
) -> Iterator[TyClient]:
    cache.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="ty-", dir=cache) as folder:
        base = Path(folder).resolve()
        root, home = base / "source", base / "home"
        root.mkdir()
        home.mkdir()
        for path, source in sources.items():
            rel = check_relative(path)
            if rel.suffix not in {".py", ".pyi"}:
                raise ValueError("ty workspace accepts only Python snapshot files")
            target = root.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source)
        search_roots = [str(root / check_relative(r)) if r != "." else str(root) for r in roots]
        config = base / "ty.toml"
        config.write_text(
            '[environment]\npython-version = "3.12"\nroot = '
            + json.dumps(search_roots)
            + "\n[src]\nrespect-ignore-files = false\n"
            + "[analysis]\nrespect-type-ignore-comments = false\n",
            encoding="utf-8",
        )
        client = TyClient(root, config, home, limits or TyLimits())
        try:
            for path, source in sources.items():
                client.open_file(path, source.decode("utf-8"))
            yield client
        finally:
            client.close()
