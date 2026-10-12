"""Local stand-ins for websites, used by the boundary qualification and by the tests.

Everything here listens on loopback only. External mode is exercised without
leaving this computer through an explicit seam: a resolver that answers with a
public address and a connector that carries that address to a local server
while reporting the validated address as its peer, exactly as a real connection
would. Production code never uses this seam: ``Egress`` defaults to the system
resolver and a real socket, and a journey cannot pass another one in.
"""

import socket
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend.contracts.web import WebTarget
from verification import web_tls
from verification.egress import Egress, EgressBudget, EgressPolicy

PUBLIC = "93.184.216.34"
Reply = tuple[int, dict[str, str], bytes]
Route = Reply | Callable[["Hit"], Reply]


@dataclass(frozen=True)
class Hit:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Site:
    """A scripted loopback server that records everything that reaches it."""

    routes: dict[str, Route] = field(default_factory=dict)
    context: ssl.SSLContext | None = None
    hits: list[Hit] = field(default_factory=list)

    def __post_init__(self) -> None:
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                pass

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else b""
                hit = Hit(
                    self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body
                )
                site.hits.append(hit)
                route = site.routes.get(self.path.split("?", 1)[0], (404, {}, b"not found"))
                status, headers, payload = route if isinstance(route, tuple) else route(hit)
                if status == 0:  # the request arrived, then the connection dies unanswered
                    self.close_connection = True
                    return
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                if "Content-Length" not in headers:
                    self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_HEAD = _serve

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._http.daemon_threads = True
        if self.context is not None:
            self._http.socket = self.context.wrap_socket(self._http.socket, server_side=True)
        self.port = self._http.server_port
        self._thread = threading.Thread(
            target=self._http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def paths(self) -> list[str]:
        return [hit.path for hit in self.hits]

    def close(self) -> None:
        self._http.shutdown()
        self._thread.join(timeout=5)
        self._http.server_close()


class Canary:
    """A raw listener that counts every connection, whatever protocol was attempted."""

    def __init__(self) -> None:
        self.connections = 0
        self.first_bytes: list[bytes] = []
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(16)
        self._socket.settimeout(0.1)
        self.port = self._socket.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except OSError:
                continue
            self.connections += 1
            try:
                connection.settimeout(0.3)
                self.first_bytes.append(connection.recv(256))
            except OSError:
                self.first_bytes.append(b"")
            finally:
                connection.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._socket.close()


class PeerSocket(socket.socket):
    """A real socket that reports a chosen peer, standing in for a public server."""

    reported: tuple[str, int] = ("", 0)

    def getpeername(self) -> tuple[str, int]:  # type: ignore[override]
        return self.reported


def carried(
    local_port: int, *, report: str | None = None
) -> Callable[[str, int, float], socket.socket]:
    """A connector that takes a "public" address to the local server on ``local_port``."""

    def connect(address: str, port: int, timeout: float) -> socket.socket:
        plain = socket.create_connection(("127.0.0.1", local_port), timeout=timeout)
        sock = PeerSocket(plain.family, plain.type, plain.proto, fileno=plain.detach())
        sock.settimeout(timeout)
        sock.reported = (report or address, port)
        return sock

    return connect


@dataclass(frozen=True)
class Tls:
    server: ssl.SSLContext
    authority_pem: str


def tls_for(host: str, folder: Path) -> Tls:
    """A throwaway authority and a server certificate for ``host`` signed by it."""
    authority_key = web_tls.new_key()
    authority = web_tls.certificate(authority_key, "Plumb test authority", authority=True)
    key = web_tls.new_key()
    leaf = web_tls.certificate(key, host, issuer_key=authority_key, issuer=authority)
    cert_path, key_path = folder / f"{host}.pem", folder / f"{host}.key"
    cert_path.write_bytes(web_tls.pem(leaf))
    key_path.write_bytes(web_tls.key_pem(key))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return Tls(context, web_tls.pem(authority).decode())


def budget(requests: int = 50, size: int = 1_000_000, seconds: float = 30.0) -> EgressBudget:
    import time

    return EgressBudget(max_requests=requests, max_bytes=size, deadline=time.monotonic() + seconds)


default_budget = budget


def soon(minutes: float = 10) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def owned(
    site: Site,
    paths: list[str] | None = None,
    *,
    budget: EgressBudget | None = None,
    cancel: Callable[[], bool] = lambda: False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Egress:
    policy = EgressPolicy(
        mode="owned_fixture",
        targets=(WebTarget(origin=site.origin, paths=paths or ["/"]),),
        expires_at=soon(),
        owned_port=site.port,
    )
    return Egress(policy, budget or default_budget(), cancel=cancel, now=now)
