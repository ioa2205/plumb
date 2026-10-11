"""HTTP transport pinned to the verified worker's numeric IPv4 socket.

No DNS lookup occurs: the socket connects directly to the literal loopback
address. The destination is checked before connection and against the peer before
the first HTTP byte can be written. This transport cannot become an external adapter.
"""

import re
import socket
from collections.abc import Iterable
from typing import cast

import httpcore
import httpx


def runtime_port(origin: str) -> int:
    match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", origin)
    if match is None or not 1 <= int(match[1]) <= 65535:
        raise ValueError("owned runner requires canonical IPv4 loopback and an explicit port")
    return int(match[1])


class PinnedNetworkBackend(httpcore.NetworkBackend):
    def __init__(self, port: int) -> None:
        self.port = port

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        if host != "127.0.0.1" or port != self.port or local_address is not None:
            raise httpcore.ConnectError("destination differs from the verified worker socket")
        # Build the numeric socket ourselves; SyncBackend.create_connection would
        # still call getaddrinfo.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            for option in socket_options or ():
                sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect(("127.0.0.1", self.port))
            if sock.getpeername() != ("127.0.0.1", self.port):
                raise httpcore.ConnectError("connected peer differs from the verified worker")
        except OSError as error:
            sock.close()
            raise httpcore.ConnectError("verified loopback connection failed") from error
        except httpcore.ConnectError:
            sock.close()
            raise
        # httpx/httpcore are locked in uv.lock. Reuse their socket stream for
        # timeout/error mapping rather than duplicate an HTTP implementation.
        from httpcore._backends.sync import SyncStream

        return SyncStream(sock)

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("owned HTTP collection permits no Unix socket")


class PinnedLoopbackTransport(httpx.HTTPTransport):
    def __init__(self, origin: str) -> None:
        self.port = runtime_port(origin)
        super().__init__(trust_env=False, retries=0)
        cast(httpcore.ConnectionPool, self._pool).close()
        self._pool = httpcore.ConnectionPool(
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
            http2=False,
            network_backend=PinnedNetworkBackend(self.port),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.raw_scheme != b"http"
            or request.url.raw_host != b"127.0.0.1"
            or request.url.port != self.port
            or request.url.userinfo
            or request.headers.get("host") != f"127.0.0.1:{self.port}"
        ):
            raise httpx.ConnectError("request differs from the verified worker", request=request)
        return super().handle_request(request)
