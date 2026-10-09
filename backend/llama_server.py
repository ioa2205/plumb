"""Start and stop a pinned ``llama-server`` for one model, locked down and stateless.

Every launch binds to loopback with a fresh API key, runs a single slot, and
turns off every form of cross-request state the server offers: prompt caching,
the host-memory prompt cache (``--cache-ram``, 8 GiB by default), and context
checkpoints. The web UI and the slots endpoint are disabled, and ``--offline``
forbids network access (ADR-0001). Thinking is off
unless a request turns it on (PROJECT_PLAN §9).
"""

import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TextIO

import httpx
import psutil

from backend.memory import MemoryStatus, read_memory
from backend.redaction import Redactor, capture_log

LOOPBACK = "127.0.0.1"


@dataclass(frozen=True)
class ServerConfig:
    binary: Path
    model: Path
    ctx_size: int = 8192
    threads: int = 4
    batch_size: int = 2048
    ubatch_size: int = 512
    gpu_layers: int = 0
    reasoning: str = "off"
    # False only for the canary diagnostic that probes llama.cpp's own caches.
    stateless: bool = True
    extra_args: tuple[str, ...] = ()

    def argv(self, port: int, api_key: str) -> list[str]:
        return [
            str(self.binary),
            "--model", str(self.model),
            "--host", LOOPBACK,
            "--port", str(port),
            "--api-key", api_key,
            "--ctx-size", str(self.ctx_size),
            "--threads", str(self.threads),
            "--batch-size", str(self.batch_size),
            "--ubatch-size", str(self.ubatch_size),
            "--n-gpu-layers", str(self.gpu_layers),
            "--parallel", "1",
            *(("--no-cache-prompt", "--cache-ram", "0", "--ctx-checkpoints", "0")
              if self.stateless else ()),
            "--no-webui",
            "--no-slots",
            "--offline",
            "--reasoning", self.reasoning,
            *self.extra_args,
        ]  # fmt: skip


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((LOOPBACK, 0))
        return s.getsockname()[1]


@dataclass
class PeakSampler:
    """Peak working set and peak private commit of the server process.

    Windows tracks both peaks itself (``peak_wset``, ``peak_pagefile``), so the
    last successful read before the process exits holds the true peaks.
    """

    process: psutil.Process
    peak_working_set: int = 0
    peak_private: int = 0
    samples: int = 0

    def sample(self) -> None:
        try:
            info = self.process.memory_info()
        except psutil.Error:
            return
        self.samples += 1
        self.peak_working_set = max(self.peak_working_set, getattr(info, "peak_wset", info.rss))
        self.peak_private = max(self.peak_private, getattr(info, "peak_pagefile", 0))


class ServerError(RuntimeError):
    """The server failed to start or answer."""


class LlamaServer:
    """Context manager around one ``llama-server`` process.

    ``load_seconds`` is the wall time from process start until ``/health``
    reports the model ready.
    """

    def __init__(
        self,
        config: ServerConfig,
        log_path: Path,
        startup_timeout: float = 300,
        *,
        redactor: Redactor | None = None,
    ) -> None:
        self.config = config
        self.log_path = log_path
        self.startup_timeout = startup_timeout
        self.port = free_port()
        self.api_key = secrets.token_urlsafe(24)
        policy = redactor or Redactor.configured()
        self.redactor = Redactor((*policy.secrets, self.api_key))
        self.base_url = f"http://{LOOPBACK}:{self.port}"
        self.memory_before: MemoryStatus | None = None
        self.load_seconds: float | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._log: TextIO | None = None
        self._log_thread: threading.Thread | None = None
        self._log_failed = False
        self.sampler: PeakSampler | None = None
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(10.0, read=600.0),
        )

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def start(self) -> None:
        self.memory_before = read_memory()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("w", encoding="utf-8", newline="\n")
        started = time.perf_counter()
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - pinned, hash-verified binary
                self.config.argv(self.port, self.api_key),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError:
            self.stop()
            raise ServerError("llama-server could not be started") from None
        self._log_thread = threading.Thread(target=self._capture_log, daemon=True)
        self._log_thread.start()
        try:
            self.sampler = PeakSampler(psutil.Process(self._proc.pid))
        except psutil.NoSuchProcess:
            self.sampler = None
        deadline = started + self.startup_timeout
        while time.perf_counter() < deadline:
            if self.sampler is not None:
                self.sampler.sample()
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self.stop()
                raise ServerError(
                    self.redactor.text(f"llama-server exited with {code}; see {self.log_path}")
                )
            try:
                if self.client.get("/health", timeout=2.0).status_code == 200:
                    self.load_seconds = time.perf_counter() - started
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        self.stop()
        raise ServerError(
            self.redactor.text(
                f"llama-server not ready after {self.startup_timeout}s; see {self.log_path}"
            )
        )

    def _capture_log(self) -> None:
        proc, output = self._proc, self._log
        if proc is None or proc.stdout is None or output is None:
            self._log_failed = True
            return
        try:
            capture_log(proc.stdout, output, self.redactor)
        except Exception:
            self._log_failed = True
        finally:
            proc.stdout.close()

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            if self.sampler is not None:
                self.sampler.sample()
            self._proc.terminate()
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=30)
        if self._log_thread is not None:
            self._log_thread.join(timeout=5)
            if self._log_thread.is_alive():
                raise ServerError("llama-server log capture did not finish")
            self._log_thread = None
        if self._log is not None:
            self._log.close()
            self._log = None
        self.client.close()
        if self._log_failed:
            raise ServerError("llama-server log capture failed")

    def post(self, path: str, body: Mapping[str, object]) -> dict[str, Any]:
        if self.sampler is not None:
            self.sampler.sample()
        try:
            cleaned = self.redactor.strings(dict(body))
        except ValueError:
            raise ServerError("a credential occurs in a model request identity") from None
        if cleaned.get("response_format") != body.get("response_format"):
            raise ServerError("a credential occurs in a model request schema")
        response = self.client.post(path, json=cleaned)
        if self.sampler is not None:
            self.sampler.sample()
        if response.status_code != 200:
            raise ServerError(f"model request failed ({response.status_code})")
        try:
            result = response.json()
        except ValueError:
            raise ServerError("model server returned invalid JSON") from None
        if not isinstance(result, dict):
            raise ServerError("model server returned no JSON object")
        return result

    def tokenize(self, text: str) -> list[int]:
        tokens = self.post("/tokenize", {"content": text, "add_special": False}).get("tokens")
        if not isinstance(tokens, list) or not all(isinstance(t, int) for t in tokens):
            raise ServerError("/tokenize returned no token list")
        return [t for t in tokens if isinstance(t, int)]
