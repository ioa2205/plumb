"""The broker's front toward Plumb's own browser (ADR-0028).

The browser is started with this loopback proxy as its only network path, so
every navigation, frame, popup, script, image and background request arrives
here and is decided by the same ``Egress`` as the HTTP adapter: same scope, same
address checks, same budgets. A route callback inside the browser is not what
contains it; this is.

- A plain-HTTP request is forwarded through ``Egress.send``.
- ``CONNECT`` to an approved HTTPS origin is answered by the broker itself, under
  the launch's own certificate, so the requests inside can be seen and checked;
  the broker then makes its own verified HTTPS connection to the real server.
- ``CONNECT`` to anything else, WebSocket upgrades and downloads are refused.
- Every refusal is answered with a short 403 and recorded, so a blocked
  dependency is visible instead of silently missing.

Only a client that knows the launch's random token may use the proxy.
"""

import base64
import contextlib
import hmac
import re
import secrets
import socket
import socketserver
import ssl
import threading
from typing import Any

import h11

from backend.web_urls import UrlRefused, WebUrl, parse_url
from verification.egress import HOP_BY_HOP, Egress, EgressRefused
from verification.web_tls import FrontCertificates

MAX_REQUEST_BODY = 1024 * 1024
USER = "plumb"
_DROP_REQUEST = HOP_BY_HOP | {"host", "content-length"}
_DROP_RESPONSE = HOP_BY_HOP | {"content-length"}


class _Closed(Exception):
    pass


class BrowserProxy:
    def __init__(self, egress: Egress, certificates: FrontCertificates | None = None) -> None:
        self.egress = egress
        self.certificates = certificates
        self.token = secrets.token_urlsafe(24)
        self._expected = "Basic " + base64.b64encode(f"{USER}:{self.token}".encode()).decode()
        self._credentials: dict[str | None, tuple[str, str]] = {None: (self.token, self._expected)}
        self._credential_lock = threading.Lock()
        proxy = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                with contextlib.suppress(_Closed, OSError, ssl.SSLError, h11.ProtocolError):
                    proxy._serve(self.request)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = False

        self._server = Server(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def proxy_for(self, account_id: str | None) -> dict[str, str]:
        """Unforgeable proxy identity for one isolated browser context, not a page header."""
        with self._credential_lock:
            if account_id not in self._credentials:
                token = secrets.token_urlsafe(24)
                expected = "Basic " + base64.b64encode(f"{USER}:{token}".encode()).decode()
                self._credentials[account_id] = (token, expected)
            token, _ = self._credentials[account_id]
        return {
            "server": self.address,
            "bypass": "<-loopback>",
            "username": USER,
            "password": token,
        }

    def _identity(self, authorization: str) -> tuple[bool, str | None]:
        with self._credential_lock:
            for account_id, (_, expected) in self._credentials.items():
                if hmac.compare_digest(authorization, expected):
                    return True, account_id
        return False, None

    def close(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()

    # --- one browser connection -----------------------------------------------------------

    @staticmethod
    def _next(connection: h11.Connection, sock: socket.socket) -> Any:  # noqa: ANN401 - h11 events
        while True:
            event = connection.next_event()
            if event is h11.NEED_DATA:
                data = sock.recv(65536)
                connection.receive_data(data)
                if not data and connection.their_state is h11.IDLE:
                    raise _Closed
                continue
            if isinstance(event, h11.ConnectionClosed) or event is h11.PAUSED:
                raise _Closed
            return event

    @staticmethod
    def _reply(
        connection: h11.Connection,
        sock: socket.socket,
        status: int,
        text: str,
        extra: list[tuple[str, str]] | None = None,
    ) -> None:
        body = text.encode("utf-8")
        headers = [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            *(extra or []),
        ]
        sock.sendall(connection.send(h11.Response(status_code=status, headers=headers)) or b"")
        sock.sendall(connection.send(h11.Data(data=body)) or b"")
        sock.sendall(connection.send(h11.EndOfMessage()) or b"")

    def _refused(
        self, connection: h11.Connection, sock: socket.socket, error: EgressRefused
    ) -> None:
        self._reply(connection, sock, 403, "Blocked by Plumb: " + error.reason)

    def _serve(self, sock: socket.socket) -> None:
        sock.settimeout(60)
        connection = h11.Connection(h11.SERVER, max_incomplete_event_size=128 * 1024)
        tunnel: WebUrl | None = None  # set once the browser opened an approved HTTPS tunnel
        tunnel_account: str | None = None
        while True:
            request = self._next(connection, sock)
            if not isinstance(request, h11.Request):
                raise _Closed
            headers = [
                (name.decode("latin-1"), value.decode("latin-1")) for name, value in request.headers
            ]
            named = {name.lower(): value for name, value in headers}
            method = request.method.decode("ascii", "replace")
            target = request.target.decode("ascii", "replace")
            # The whole request is read before anything is answered, CONNECT included.
            body = self._drain(connection, sock)
            valid, account_id = (
                self._identity(named.get("proxy-authorization", ""))
                if tunnel is None
                else (True, tunnel_account)
            )
            if not valid:
                self._reply(
                    connection,
                    sock,
                    407,
                    "Plumb's browser proxy needs its launch token.",
                    [("Proxy-Authenticate", 'Basic realm="Plumb"')],
                )
            elif method == "CONNECT":
                opened = self._connect(connection, sock, target)
                if opened is None:
                    raise _Closed
                sock, tunnel = opened
                tunnel_account = account_id
                connection = h11.Connection(h11.SERVER, max_incomplete_event_size=128 * 1024)
                continue
            else:
                self._forward(
                    connection,
                    sock,
                    method,
                    target,
                    headers,
                    named,
                    tunnel,
                    body,
                    account_id=account_id,
                )
            if connection.our_state is h11.MUST_CLOSE or connection.their_state is h11.MUST_CLOSE:
                raise _Closed
            try:
                connection.start_next_cycle()
            except h11.ProtocolError:
                raise _Closed from None

    def _drain(self, connection: h11.Connection, sock: socket.socket) -> bytes:
        body = bytearray()
        while True:
            event = self._next(connection, sock)
            if isinstance(event, h11.EndOfMessage):
                return bytes(body)
            if isinstance(event, h11.Data):
                if len(body) + len(event.data) > MAX_REQUEST_BODY:
                    raise _Closed
                body.extend(event.data)

    def _connect(
        self, connection: h11.Connection, sock: socket.socket, authority: str
    ) -> tuple[socket.socket, WebUrl] | None:
        """Open an inspected HTTPS tunnel to an approved origin, or refuse."""
        host, _, port = authority.rpartition(":")
        try:
            origin = parse_url(f"https://{host}:{port}/")
            approved = {target.origin for target in self.egress.policy.targets}
            if f"http://{origin.authority}" in approved or (
                origin.port == 80 and f"http://{origin.host}" in approved
            ):
                # A tunnel to a plain-HTTP origin is a WebSocket (or another protocol).
                raise self.egress.refuse(
                    "websocket", origin.host, "WebSocket and other tunnels are not allowed."
                )
            if self.certificates is None or origin.origin not in approved:
                raise self.egress.refuse(
                    "off_scope", origin.host, "This origin is not in the approved scope."
                )
            self.egress.live()
        except UrlRefused:
            error = self.egress.refuse("off_scope", host[:253], "The address is refused.")
            self._reply(connection, sock, 403, "Blocked by Plumb: " + error.reason)
            return None
        except EgressRefused as error:
            self._reply(connection, sock, 403, "Blocked by Plumb: " + error.reason)
            return None
        sock.sendall(
            connection.send(
                h11.Response(status_code=200, headers=[], reason=b"Connection Established")
            )
            or b""
        )
        secure = self.certificates.context(origin.host).wrap_socket(sock, server_side=True)
        secure.settimeout(60)
        return secure, origin

    def _forward(
        self,
        connection: h11.Connection,
        sock: socket.socket,
        method: str,
        target: str,
        headers: list[tuple[str, str]],
        named: dict[str, str],
        tunnel: WebUrl | None,
        body: bytes,
        *,
        account_id: str | None = None,
    ) -> None:
        # For the record of a refusal: the host as written, even when it cannot be parsed.
        written = re.match(r"https?://([^/?#]*)", target)
        host = tunnel.host if tunnel is not None else (written[1] if written else "")
        try:
            if tunnel is not None:
                if not target.startswith("/"):
                    raise UrlRefused("origin-form expected inside a tunnel")
                url = parse_url(tunnel.origin + target)
            else:
                url = parse_url(target)
                if url.scheme != "http":
                    raise UrlRefused("plain proxy requests are http only")
            host = url.host
            if "upgrade" in named or "websocket" in named.get("connection", "").lower():
                raise self.egress.refuse(
                    "websocket", url.host, "WebSocket and other upgrades are not allowed."
                )
            sent = [(name, value) for name, value in headers if name.lower() not in _DROP_REQUEST]
            response = self.egress.send(
                method,
                url,
                sent,
                body if body or method in {"POST", "PUT", "PATCH"} else None,
                source="browser",
                account_id=account_id,
            )
        except UrlRefused:
            error = self.egress.refuse("off_scope", host[:253], "The address is refused.")
            return self._refused(connection, sock, error)
        except EgressRefused as error:
            return self._refused(connection, sock, error)
        try:
            if response.status in {301, 302, 303, 307, 308}:
                # The destination is checked here by hand; an off-scope redirect never
                # reaches the browser, so the browser never even asks for it.
                self.egress.redirect_target(url, response.header("location"))
            disposition = (response.header("content-disposition") or "").lower()
            if disposition.startswith("attachment"):
                raise self.egress.refuse("download", url.host, "Downloads are not allowed.")
            passed = [
                (name, value)
                for name, value in response.headers
                if name.lower() not in _DROP_RESPONSE
            ]
            length = response.header("content-length")
            bodiless = method == "HEAD" or response.status in {204, 304} or response.status < 200
            if length is not None and length.isdigit():
                passed.append(("Content-Length", length))
            elif not bodiless:
                passed.append(("Transfer-Encoding", "chunked"))
            sock.sendall(
                connection.send(h11.Response(status_code=response.status, headers=passed)) or b""
            )
            for chunk in response.iter_raw():
                if chunk and not bodiless:
                    sock.sendall(connection.send(h11.Data(data=chunk)) or b"")
            sock.sendall(connection.send(h11.EndOfMessage()) or b"")
        except EgressRefused as error:
            response.close()
            if connection.our_state is h11.SEND_RESPONSE:
                return self._refused(connection, sock, error)
            raise _Closed from error  # the answer was cut short; the browser sees a failed load
        except (h11.LocalProtocolError, OSError) as error:
            response.close()
            raise _Closed from error
