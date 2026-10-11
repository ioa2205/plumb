"""Connection checks before bytes, using synthetic sockets only; no target launch."""

import httpcore
import httpx
import pytest

from verification import owned_http
from verification.owned_http import PinnedLoopbackTransport, PinnedNetworkBackend, runtime_port


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:019999",
        "http://127.1:19999",
        "http://2130706433:19999",
        "http://localhost:19999",
        "http://127.0.0.1:19999/",
        "http://127.0.0.1:19999?x=1",
        "http://127.0.0.1:19999#fragment",
        "http://127.0.0.1:19999@outside.invalid",
    ],
)
def test_noncanonical_runtime_origins_are_refused(origin: str) -> None:
    with pytest.raises(ValueError):
        runtime_port(origin)


@pytest.mark.parametrize(
    "host,port,local_address",
    [
        ("localhost", 19999, None),
        ("127.0.0.2", 19999, None),
        ("127.0.0.1", 20000, None),
        ("127.0.0.1", 19999, "127.0.0.1"),
    ],
)
def test_destination_refused_before_socket_creation(
    monkeypatch: pytest.MonkeyPatch, host: str, port: int, local_address: str | None
) -> None:
    def socket(*args: object) -> None:
        pytest.fail("an unapproved destination must never create a socket")

    monkeypatch.setattr(owned_http.socket, "socket", socket)
    with pytest.raises(httpcore.ConnectError):
        PinnedNetworkBackend(19999).connect_tcp(host, port, local_address=local_address)


@pytest.mark.parametrize("peer", [("203.0.113.5", 19999), ("127.0.0.1", 20000)])
def test_peer_mismatch_closes_before_http_write(
    monkeypatch: pytest.MonkeyPatch, peer: tuple[str, int]
) -> None:
    operations: list[object] = []

    class Socket:
        def settimeout(self, value: object) -> None:
            pass

        def setsockopt(self, *args: object) -> None:
            pass

        def connect(self, address: object) -> None:
            operations.append(address)

        def getpeername(self) -> tuple[str, int]:
            return peer

        def close(self) -> None:
            operations.append("closed")

        def sendall(self, data: bytes) -> None:
            pytest.fail("unapproved peer must not receive any HTTP bytes")

    monkeypatch.setattr(owned_http.socket, "socket", lambda *args: Socket())
    with pytest.raises(httpcore.ConnectError, match="connected peer"):
        PinnedNetworkBackend(19999).connect_tcp("127.0.0.1", 19999)
    assert operations == [("127.0.0.1", 19999), "closed"]


def test_literal_socket_avoids_dns_and_applies_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    operations: list[object] = []

    def dns(*args: object, **kwargs: object) -> None:
        pytest.fail("owned numeric sockets must never resolve DNS")

    class Socket:
        def settimeout(self, value: object) -> None:
            operations.append(value)

        def setsockopt(self, *args: object) -> None:
            pass

        def connect(self, address: object) -> None:
            operations.append(address)

        def getpeername(self) -> tuple[str, int]:
            return ("127.0.0.1", 19999)

        def close(self) -> None:
            operations.append("closed")

    monkeypatch.setattr(owned_http.socket, "getaddrinfo", dns)
    monkeypatch.setattr(owned_http.socket, "socket", lambda *args: Socket())
    stream = PinnedNetworkBackend(19999).connect_tcp("127.0.0.1", 19999, timeout=0.25)
    stream.close()
    assert operations == [0.25, ("127.0.0.1", 19999), "closed"]


@pytest.mark.parametrize(
    "url,headers",
    [
        ("http://localhost:19999/health", {}),
        ("http://127.0.0.1:20000/health", {}),
        ("https://127.0.0.1:19999/health", {}),
        ("http://127.0.0.1:19999/health", {"host": "outside.invalid"}),
        ("http://user:password@127.0.0.1:19999/health", {}),
    ],
)
def test_transport_refuses_authority_changes_without_network(
    url: str, headers: dict[str, str]
) -> None:
    with (
        PinnedLoopbackTransport("http://127.0.0.1:19999") as transport,
        pytest.raises(httpx.ConnectError),
    ):
        transport.handle_request(httpx.Request("GET", url, headers=headers))
