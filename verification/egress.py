"""The one way out to a website, for the HTTP adapter and the browser alike (ADR-0028).

Every request passes the same checks, in this order:

1. the scope is still valid (not expired, not canceled, budget left);
2. the canonical URL lies inside the frozen list of approved origins and paths;
3. the host's addresses are validated, then *that* address is connected to: an
   owned fixture is the literal loopback address Plumb started; an external site
   must resolve to public addresses only, and the first validated answer is
   pinned for the rest of the journey;
4. the connected peer is compared with the validated address before any HTTP byte;
5. HTTPS verifies the server certificate for the requested host name (SNI);
6. the response is counted against the shared request, byte and time budgets.

Redirects are never followed here: the caller gets the 3xx and must come back
through ``send`` for the next hop, where all of the above applies again.
Environment proxies are ignored. Anything refused is recorded and stays visible.

The owned-fixture path and the external path never mix: one ``Egress`` has one
mode for its whole life.
"""

import ipaddress
import json
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import parse_qsl

import certifi
import httpcore

from backend.contracts.web import BlockedRequest, WebTarget
from backend.web_urls import WebUrl, parse_origin, path_within, resolve_reference

Mode = Literal["owned_fixture", "external"]
Kind = Literal["off_scope", "redirect", "websocket", "download", "budget", "address", "other"]
MAX_HEADER_BYTES = 64 * 1024
CONNECT_SECONDS = 10.0
READ_SECONDS = 30.0
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Headers that describe one hop and must not travel through the broker.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


class EgressRefused(Exception):
    """The request was not sent. ``kind`` says why in a fixed vocabulary."""

    def __init__(self, kind: Kind, reason: str, host: str = "") -> None:
        super().__init__(reason)
        self.kind: Kind = kind
        self.reason = reason
        self.host = host


class EgressStopped(EgressRefused):
    """Scope expired, work canceled or a shared budget used up: nothing more may be sent."""


class ActionRefused(EgressRefused):
    """Action authorization failed before any HTTP byte could leave."""


Resolver = Callable[[str, int], list[str]]
Connect = Callable[[str, int, float], socket.socket]


def system_resolver(host: str, port: int) -> list[str]:
    """Every address the operating system returns for ``host``, in its order."""
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as error:
        raise EgressRefused("address", "The host name does not resolve.", host) from error
    return list(dict.fromkeys(str(row[4][0]) for row in rows))


def tcp_connect(address: str, port: int, timeout: float) -> socket.socket:
    """A socket to the literal address. No name is resolved here."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.connect((address, port))
    except OSError:
        sock.close()
        raise
    return sock


def public_address(value: str) -> str | None:
    """None when ``value`` is a public address; otherwise why it is refused."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "not an IP address"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return "an IPv4-mapped address"
        if address.sixtofour is not None or address.teredo is not None or address in _NAT64:
            return "a translated or tunnelled address"
        if address.scope_id is not None:
            return "a scoped address"
    if address.is_loopback:
        return "this computer"
    if address.is_link_local:
        return "a link-local or cloud metadata address"
    if address.is_private:
        return "a private network address"
    if address.is_multicast or address.is_reserved or address.is_unspecified:
        return "a reserved address"
    if not address.is_global:
        return "not a public address"
    return None


@dataclass
class EgressBudget:
    """Shared by every adapter of one journey. Thread-safe."""

    max_requests: int
    max_bytes: int
    deadline: float  # on ``clock``
    clock: Callable[[], float] = time.monotonic
    requests: int = 0
    bytes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def seconds_left(self) -> float:
        return self.deadline - self.clock()

    def take_request(self) -> None:
        with self._lock:
            if self.seconds_left() <= 0:
                raise EgressStopped("budget", "The time budget is used up.")
            if self.requests >= self.max_requests:
                raise EgressStopped("budget", "The request budget is used up.")
            self.requests += 1

    def take_bytes(self, count: int) -> None:
        with self._lock:
            self.bytes += count
            if self.bytes > self.max_bytes:
                raise EgressStopped("budget", "The data budget is used up.")


@dataclass(frozen=True)
class ActionPermission:
    """One action/account selected from the reviewer's approved frozen plan."""

    step_id: str
    action: Literal["sign_in", "sign_up", "submit_form"]
    account_id: str | None


@dataclass(repr=False)
class _FormGrant:
    permission: ActionPermission
    method: str
    url: str
    # Operational values only: never included in records, exceptions or contracts.
    fields: dict[str, str] = field(repr=False)
    required: frozenset[str]
    used: bool = False


@dataclass(frozen=True)
class EgressPolicy:
    mode: Mode
    targets: tuple[WebTarget, ...]
    expires_at: datetime
    # Owned mode: the port of the fixture process that Plumb itself started and verified.
    owned_port: int | None = None
    approved_actions: tuple[ActionPermission, ...] = ()

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("an egress policy needs at least one approved origin")
        if self.expires_at.tzinfo is None:
            raise ValueError("scope expiry needs a timezone")
        if len({item.step_id for item in self.approved_actions}) != len(self.approved_actions):
            raise ValueError("approved action steps must be distinct")
        if any(
            item.action not in {"sign_in", "sign_up", "submit_form"}
            or (item.action in {"sign_in", "sign_up"} and item.account_id is None)
            for item in self.approved_actions
        ):
            raise ValueError("a write permission needs a supported action and its test account")
        for target in self.targets:
            url = parse_origin(target.origin)
            if self.mode == "owned_fixture":
                if (
                    self.owned_port is None
                    or url.scheme != "http"
                    or url.host != "127.0.0.1"
                    or url.port != self.owned_port
                    or len(self.targets) != 1
                ):
                    raise ValueError(
                        "owned mode admits exactly the loopback origin of the started fixture"
                    )
            elif self.owned_port is not None or url.scheme != "https":
                raise ValueError("external mode admits https origins and no owned port")
            elif url.ip is not None and public_address(url.host) is not None:
                raise ValueError("external mode refuses non-public addresses")


@dataclass(frozen=True)
class EgressRecord:
    """One request that was sent, without query values."""

    at: str
    method: str
    origin: str
    path: str
    query_keys: tuple[str, ...]
    peer: str
    status: int | None
    body_bytes: int
    seconds: float
    source: str  # "http" or "browser"


@dataclass
class EgressResponse:
    status: int
    headers: list[tuple[str, str]]
    peer: str
    _chunks: Iterator[bytes]
    _close: Callable[[], None]

    def header(self, name: str) -> str | None:
        return next((value for key, value in self.headers if key.lower() == name.lower()), None)

    def iter_raw(self) -> Iterator[bytes]:
        """Body bytes as the server sent them (still content-encoded), counted as they pass."""
        try:
            yield from self._chunks
        finally:
            self._close()

    def read(self, limit: int) -> bytes:
        data = bytearray()
        for chunk in self.iter_raw():
            if len(data) + len(chunk) > limit:
                raise EgressRefused("budget", "The response is larger than its limit.")
            data.extend(chunk)
        return bytes(data)

    def close(self) -> None:
        self._close()


class _Backend(httpcore.NetworkBackend):
    """Resolves, validates and connects on behalf of the pool. httpcore resolves nothing."""

    def __init__(self, egress: "Egress") -> None:
        self.egress = egress

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        if local_address is not None:
            raise httpcore.ConnectError("a local address may not be chosen")
        try:
            addresses = self.egress.addresses(host, port)
        except EgressRefused as error:
            raise httpcore.ConnectError(error.reason) from error
        last: Exception | None = None
        for address in addresses:
            try:
                sock = self.egress.connect(address, port, timeout or CONNECT_SECONDS)
            except OSError as error:
                last = error
                continue
            try:
                peer = sock.getpeername()
                # The check that binds the validated answer to the real connection.
                if ipaddress.ip_address(peer[0]) != ipaddress.ip_address(address) or (
                    peer[1] != port
                ):
                    raise httpcore.ConnectError("the connected peer is not the validated address")
            except (OSError, ValueError, httpcore.ConnectError) as error:
                sock.close()
                if isinstance(error, httpcore.ConnectError):
                    raise
                raise httpcore.ConnectError("the connected peer could not be verified") from error
            self.egress.note_peer(host, port, address)
            from httpcore._backends.sync import SyncStream

            return SyncStream(sock)
        raise httpcore.ConnectError("no validated address accepted the connection") from last

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("website egress permits no Unix socket")


def tls_context(extra_ca_pem: str | None = None) -> ssl.SSLContext:
    """Certificate and host-name verification on, TLS 1.2 or newer. Never relaxed."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    if extra_ca_pem is not None:
        context.load_verify_locations(cadata=extra_ca_pem)
    return context


class Egress:
    def __init__(
        self,
        policy: EgressPolicy,
        budget: EgressBudget,
        *,
        cancel: Callable[[], bool] = lambda: False,
        resolver: Resolver = system_resolver,
        connect: Connect = tcp_connect,
        context: ssl.SSLContext | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.policy = policy
        self.budget = budget
        self.cancel = cancel
        self.resolver = resolver
        self.connect = connect
        self.now = now
        self.blocked: list[BlockedRequest] = []
        self.records: list[EgressRecord] = []
        self._pins: dict[tuple[str, int], list[str]] = {}
        self._peers: dict[tuple[str, int], str] = {}
        self._lock = threading.Lock()
        self._active_action: ActionPermission | None = None
        self._form_grant: _FormGrant | None = None
        self._origins = {target.origin: target for target in policy.targets}
        self._pool = httpcore.ConnectionPool(
            ssl_context=context or tls_context(),
            max_connections=8,
            max_keepalive_connections=8,
            keepalive_expiry=15.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_Backend(self),
        )

    # --- checks ---------------------------------------------------------------------------

    def refuse(self, kind: Kind, host: str, reason: str) -> EgressRefused:
        """Record a refusal so it stays visible, and return the error to raise."""
        with self._lock:
            for index, row in enumerate(self.blocked):
                if (row.kind, row.host, row.reason) == (kind, host[:253], reason[:300]):
                    self.blocked[index] = row.model_copy(update={"count": row.count + 1})
                    break
            else:
                if len(self.blocked) < 200:
                    self.blocked.append(
                        BlockedRequest(kind=kind, host=host[:253], reason=reason[:300])
                    )
        error = EgressStopped if kind == "budget" else EgressRefused
        return error(kind, reason, host)

    def live(self) -> None:
        if self.cancel():
            raise EgressStopped("other", "The work was stopped.")
        if self.now() >= self.policy.expires_at:
            raise EgressStopped("other", "The approved scope has expired.")
        if self.budget.seconds_left() <= 0:
            raise self.refuse("budget", "", "The time budget is used up.")

    def in_scope(self, url: WebUrl) -> bool:
        target = self._origins.get(url.origin)
        return target is not None and any(path_within(url.path, prefix) for prefix in target.paths)

    def check(self, url: WebUrl) -> None:
        """Scope and budget; raises a recorded refusal. Called again for every redirect hop."""
        self.live()
        if self.budget.requests >= self.budget.max_requests:
            raise self.refuse("budget", url.host, "The request budget is used up.")
        if url.origin not in self._origins:
            raise self.refuse("off_scope", url.host, "This origin is not in the approved scope.")
        if not self.in_scope(url):
            raise self.refuse(
                "off_scope", url.host, "This path is outside the approved paths of its origin."
            )

    def addresses(self, host: str, port: int) -> list[str]:
        """The validated addresses for ``host``; pinned after the first answer."""
        key = (host, port)
        with self._lock:
            if key in self._pins:
                return list(self._pins[key])
        if self.policy.mode == "owned_fixture":
            if host != "127.0.0.1" or port != self.policy.owned_port:
                raise self.refuse(
                    "address", host, "Only the started fixture's address is admitted."
                )
            found = ["127.0.0.1"]
        else:
            try:
                literal: str | None = str(ipaddress.ip_address(host))
            except ValueError:
                literal = None
            found = [literal] if literal else self.resolver(host, port)
            if not found:
                raise self.refuse("address", host, "The host name does not resolve.")
            for address in found:
                # One private answer among public ones is how a name is turned inward.
                if (why := public_address(address)) is not None:
                    raise self.refuse(
                        "address", host, f"The host resolves to {why}; external mode refuses it."
                    )
        with self._lock:
            self._pins.setdefault(key, found)
            return list(self._pins[key])

    def note_peer(self, host: str, port: int, address: str) -> None:
        with self._lock:
            self._peers[(host, port)] = address

    # --- action authorization -------------------------------------------------------------

    def _action_refused(self, host: str, reason: str) -> ActionRefused:
        self.refuse("other", host, reason)
        return ActionRefused("other", reason, host)

    @contextmanager
    def action(self, step_id: str, account_id: str | None) -> Iterator[None]:
        """Activate one already-approved step. No page or model can add a permission."""
        self.live()
        permission = next(
            (
                item
                for item in self.policy.approved_actions
                if item.step_id == step_id and item.account_id == account_id
            ),
            None,
        )
        if permission is None:
            raise self._action_refused("", "This action and account have no approved plan step.")
        with self._lock:
            if self._active_action is not None:
                raise ValueError("an approved action is already active")
            self._active_action = permission
        try:
            yield
        finally:
            with self._lock:
                self._form_grant = None
                self._active_action = None

    @contextmanager
    def form_grant(
        self,
        account_id: str | None,
        method: str,
        url: WebUrl,
        fields: dict[str, str],
        *,
        required: frozenset[str] | None = None,
    ) -> Iterator[None]:
        """One submission to an observed endpoint with finite, runner-bound field values.

        The active plan action is required independently of observing a form. The
        grant lasts only for the submission and is consumed before a byte is sent.
        Normal reads/cookies remain available; other page writes remain refused.
        """
        self.check(url)
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            raise self._action_refused(url.host, "Only an approved write can have a form grant.")
        if len(fields) > 40 or any(
            not name or not isinstance(value, str) for name, value in fields.items()
        ):
            raise ValueError("a form grant needs at most forty named string fields")
        required = frozenset(fields) if required is None else required
        if not required <= fields.keys():
            raise ValueError("required fields must be part of the observed form")
        with self._lock:
            permission = self._active_action
            if permission is None or permission.account_id != account_id:
                permission = None
            elif self._form_grant is not None:
                raise ValueError("a form submission grant is already active")
            else:
                self._form_grant = _FormGrant(permission, method, url.url, dict(fields), required)
        if permission is None:
            raise self._action_refused(url.host, "A form needs its approved action and account.")
        try:
            yield
        finally:
            with self._lock:
                self._form_grant = None

    @staticmethod
    def _payload(headers: list[tuple[str, str]], body: bytes | None) -> dict[str, str] | None:
        """Read only supported scalar form encodings; never return an unbounded payload."""
        if len(body or b"") > 1024 * 1024:
            return None
        types = [value for name, value in headers if name.lower() == "content-type"]
        if len(types) != 1 or any(name.lower() == "content-encoding" for name, _ in headers):
            return None
        kind = types[0].split(";", 1)[0].strip().lower()
        try:
            text = (body or b"").decode("utf-8")
            if kind == "application/x-www-form-urlencoded":
                pairs = parse_qsl(
                    text,
                    keep_blank_values=True,
                    strict_parsing=True,
                    encoding="utf-8",
                    errors="strict",
                    max_num_fields=40,
                )
                if len({name for name, _ in pairs}) != len(pairs):
                    return None
                return dict(pairs)
            if kind == "application/json":
                pairs = json.loads(text, object_pairs_hook=lambda items: items)
                if not isinstance(pairs, list) or len(pairs) > 40:
                    return None
                if any(
                    not isinstance(pair, tuple)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or not isinstance(pair[1], str)
                    for pair in pairs
                ):
                    return None
                if len({name for name, _ in pairs}) != len(pairs):
                    return None
                return dict(pairs)
        except (UnicodeError, ValueError):
            pass
        return None

    def _authorize_request(
        self,
        method: str,
        url: WebUrl,
        headers: list[tuple[str, str]],
        body: bytes | None,
        account_id: str | None,
    ) -> None:
        if method in {"GET", "HEAD", "OPTIONS"} and not body:
            return
        payload = self._payload(headers, body)
        with self._lock:
            grant = self._form_grant
            allowed = (
                grant is not None
                and not grant.used
                and grant.permission == self._active_action
                and grant.permission.account_id == account_id
                and grant.method == method
                and grant.url == url.url
                and payload is not None
                and grant.required <= payload.keys()
                and all(
                    name in grant.fields and grant.fields[name] == value
                    for name, value in payload.items()
                )
            )
            if allowed and grant is not None:
                grant.used = True
        if not allowed:
            raise self._action_refused(
                url.host,
                "No unused grant covers this request's action, account, endpoint and fields.",
            )

    # --- sending --------------------------------------------------------------------------

    def send(
        self,
        method: str,
        url: WebUrl,
        headers: list[tuple[str, str]],
        body: bytes | None = None,
        *,
        source: str = "http",
        account_id: str | None = None,
    ) -> EgressResponse:
        """One hop. The caller iterates or closes the response."""
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            raise self.refuse("other", url.host, "This request method is not handled.")
        self.check(url)
        names = {name.lower() for name, _ in headers}
        if names & HOP_BY_HOP or "host" in names or "content-length" in names:
            raise self.refuse("other", url.host, "Hop-by-hop and framing headers are set here.")
        self._authorize_request(method, url, headers, body, account_id)
        try:
            self.budget.take_request()
        except EgressStopped as error:
            raise self.refuse("budget", url.host, error.reason) from error
        wire: list[tuple[bytes, bytes]] = [(b"Host", url.authority.encode("ascii"))]
        try:
            wire.extend((name.encode("ascii"), value.encode("latin-1")) for name, value in headers)
        except UnicodeEncodeError as error:
            raise self.refuse("other", url.host, "A request header is not sendable.") from error
        if body is not None or method in {"POST", "PUT", "PATCH"}:
            wire.append((b"Content-Length", str(len(body or b"")).encode("ascii")))
        started = time.monotonic()
        timeout = max(0.05, min(READ_SECONDS, self.budget.seconds_left()))
        request = httpcore.Request(
            method=method.encode("ascii"),
            url=httpcore.URL(
                scheme=url.scheme.encode("ascii"),
                host=url.host.encode("ascii"),
                port=url.port,
                target=url.target.encode("ascii"),
            ),
            headers=wire,
            content=body or b"",
            extensions={
                "timeout": {
                    "connect": min(CONNECT_SECONDS, timeout),
                    "read": timeout,
                    "write": timeout,
                    "pool": timeout,
                }
            },
        )
        try:
            response = self._pool.handle_request(request)
        except httpcore.ConnectError as error:
            raise self.refuse(
                "address", url.host, str(error) or "The connection failed."
            ) from error
        except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as error:
            self._record(method, url, None, 0, started, source)
            raise EgressRefused(
                "other", f"No response ({type(error).__name__}).", url.host
            ) from error
        response_headers = [
            (name.decode("latin-1"), value.decode("latin-1")) for name, value in response.headers
        ]
        header_bytes = sum(len(name) + len(value) + 4 for name, value in response.headers)
        closed = threading.Event()
        counted = [0]

        def close() -> None:
            if not closed.is_set():
                closed.set()
                response.close()
                self._record(method, url, response.status, counted[0], started, source)

        try:
            if header_bytes > MAX_HEADER_BYTES:
                raise self.refuse("budget", url.host, "The response headers are too large.")
            self.budget.take_bytes(header_bytes)
        except EgressRefused:
            close()
            raise

        def chunks() -> Iterator[bytes]:
            stream = response.stream
            if not isinstance(stream, Iterable):
                return
            try:
                for chunk in stream:
                    counted[0] += len(chunk)
                    try:
                        self.budget.take_bytes(len(chunk))
                        self.live()
                    except EgressStopped as error:
                        if error.kind == "budget":
                            self.refuse("budget", url.host, error.reason)
                        raise
                    yield chunk
            except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as e:
                raise EgressRefused("other", f"The response broke off ({type(e).__name__}).") from e

        return EgressResponse(
            status=response.status,
            headers=response_headers,
            peer=self._peers.get((url.host, url.port), ""),
            _chunks=chunks(),
            _close=close,
        )

    def _record(
        self, method: str, url: WebUrl, status: int | None, size: int, started: float, source: str
    ) -> None:
        keys = tuple(
            dict.fromkeys(part.split("=", 1)[0][:60] for part in url.query.split("&") if part)
        )
        with self._lock:
            if len(self.records) < 5000:
                self.records.append(
                    EgressRecord(
                        at=self.now().isoformat(),
                        method=method,
                        origin=url.origin,
                        path=url.path,
                        query_keys=keys,
                        peer=self._peers.get((url.host, url.port), ""),
                        status=status,
                        body_bytes=size,
                        seconds=round(time.monotonic() - started, 4),
                        source=source,
                    )
                )

    def redirect_target(self, current: WebUrl, location: str | None) -> WebUrl:
        """Where a 3xx points, parsed and scope-checked by hand before any next hop."""
        if not location or not location.strip():
            raise self.refuse("redirect", current.host, "A redirect named no destination.")
        target = resolve_reference(current, location)
        if target is None:
            raise self.refuse(
                "redirect", current.host, "A redirect named an address that is refused."
            )
        if not self.in_scope(target):
            raise self.refuse(
                "redirect",
                target.host,
                "A redirect pointed outside the approved scope and was not followed.",
            )
        return target

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def open(self) -> Iterator["Egress"]:
        try:
            yield self
        finally:
            self.close()
