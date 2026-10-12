"""Canonical web addresses for scope checks (ADR-0028). Ambiguity is refused, not repaired.

One parser serves the scope contract, the egress broker and both adapters, so
"what was approved" and "what is requested" can never be read differently.
A URL that would change under normalization (dot segments, encoded slashes,
odd numeric hosts, credentials, control characters) is rejected outright.
"""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_URL = 2048
_DEFAULT_PORT = {"http": 80, "https": 443}
_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
_NUMERIC_LABEL = re.compile(r"0x[0-9a-f]*|[0-9]+", re.IGNORECASE)
_BAD_ESCAPE = re.compile(r"%(?:2f|5c|2e|00|0a|0d|09|25)", re.IGNORECASE)
_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_PATH_CHARS = re.compile(r"[A-Za-z0-9\-._~!$&'()*+,;=:@/%]*")
_QUERY_CHARS = re.compile(r"[A-Za-z0-9\-._~!$&'()*+,;=:@/?%\[\]]*")


class UrlRefused(ValueError):
    """The address is malformed, ambiguous or of a kind Plumb does not handle."""


@dataclass(frozen=True)
class WebUrl:
    scheme: str
    host: str  # lowercase ASCII name, or a canonical IP literal (IPv6 without brackets)
    port: int
    path: str
    query: str = ""

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == _DEFAULT_PORT[self.scheme] else f"{host}:{self.port}"

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.authority}"

    @property
    def target(self) -> str:
        """What goes on the request line."""
        return self.path + ("?" + self.query if self.query else "")

    @property
    def url(self) -> str:
        return self.origin + self.target

    @property
    def ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        try:
            return ipaddress.ip_address(self.host)
        except ValueError:
            return None


def _host(raw: str) -> str:
    host = raw.lower()
    if host.startswith("["):
        if not host.endswith("]"):
            raise UrlRefused("malformed IPv6 host")
        try:
            address = ipaddress.IPv6Address(host[1:-1])
        except ValueError as error:
            raise UrlRefused("malformed IPv6 host") from error
        if address.scope_id is not None or str(address) != host[1:-1]:
            raise UrlRefused("an IPv6 host must be written in its canonical form")
        return str(address)
    if not host or len(host) > 253 or host.endswith(".") or ".." in host:
        raise UrlRefused("a host name is required, without a trailing dot")
    try:
        host.encode("ascii")
    except UnicodeEncodeError as error:
        # An internationalized name must be given in its ASCII (xn--) form, so that
        # what was reviewed is exactly what is connected to.
        raise UrlRefused("write the host in its ASCII form") from error
    labels = host.split(".")
    if all(_NUMERIC_LABEL.fullmatch(label) for label in labels):
        # 127.1, 0x7f.0.0.1, 2130706433 and 0177.0.0.1 all mean an address to some
        # parsers and a name to others. Only the plain dotted form is accepted.
        try:
            address4 = ipaddress.IPv4Address(host)
        except ValueError as error:
            raise UrlRefused("a numeric host must be a plain dotted IPv4 address") from error
        if str(address4) != host:
            raise UrlRefused("a numeric host must be a plain dotted IPv4 address")
        return host
    if any(_LABEL.fullmatch(label) is None for label in labels):
        raise UrlRefused("the host name has characters that are not allowed")
    return host


def check_path(path: str) -> str:
    if (
        not path.startswith("/")
        or len(path) > MAX_URL
        or _PATH_CHARS.fullmatch(path) is None
        or "//" in path
        or _BAD_ESCAPE.search(path)
        or len(_ESCAPE.findall(path)) != path.count("%")
        or any(segment in {".", ".."} for segment in path.split("/"))
    ):
        raise UrlRefused("the path is not canonical")
    return path


def parse_url(value: str) -> WebUrl:
    """Parse one absolute http(s) URL, or raise ``UrlRefused``. The fragment is dropped."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_URL
        or value != value.strip()
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
        or "\\" in value
    ):
        raise UrlRefused("the address has spaces, control characters or backslashes")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise UrlRefused("the address cannot be parsed") from error
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORT or not value.lower().startswith(scheme + "://"):
        raise UrlRefused("only http and https addresses are handled")
    netloc = parts.netloc
    if not netloc or "@" in netloc:
        raise UrlRefused("an address must name a host and carry no credentials")
    raw_host = netloc
    if port is not None or netloc.endswith(":"):
        raw_host, _, port_text = netloc.rpartition(":")
        if not port_text.isdigit() or str(int(port_text)) != port_text:
            raise UrlRefused("the port is not a plain number")
    host = _host(raw_host)
    port = _DEFAULT_PORT[scheme] if port is None else port
    if not 1 <= port <= 65535:
        raise UrlRefused("the port is out of range")
    path = check_path(parts.path or "/")
    query = parts.query
    if (
        _QUERY_CHARS.fullmatch(query) is None
        or len(_ESCAPE.findall(query)) != query.count("%")
        or re.search(r"%(?:00|0a|0d)", query, re.IGNORECASE)
    ):
        raise UrlRefused("the query is not canonical")
    return WebUrl(scheme, host, port, path, query)


def parse_origin(value: str) -> WebUrl:
    """An origin only: scheme, host and optional port, nothing after it."""
    url = parse_url(value)
    if value.rstrip("/") != url.origin or url.query:
        raise UrlRefused("write an origin as scheme://host[:port], in lowercase, nothing more")
    return url


_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


def resolve_reference(base: WebUrl, reference: str) -> WebUrl | None:
    """A link, form action or redirect against its page: canonical, or None. Never guessed.

    Anything with a scheme other than http(s) (``javascript:``, ``data:``,
    ``mailto:``...) is None, as is anything ``parse_url`` refuses.
    """
    reference = reference.strip().split("#", 1)[0]
    if not reference:
        return base
    try:
        if reference.startswith("//"):
            return parse_url(base.scheme + ":" + reference)
        if _SCHEME.match(reference):
            return parse_url(reference)
        if reference.startswith("/"):
            return parse_url(base.origin + reference)
        if reference.startswith("?"):
            return parse_url(base.origin + base.path + reference)
        return parse_url(base.origin + base.path.rsplit("/", 1)[0] + "/" + reference)
    except UrlRefused:
        return None


def path_within(path: str, prefix: str) -> bool:
    """Whole path segments only: ``/app`` covers ``/app/x`` but not ``/apple``."""
    return prefix == "/" or path == prefix or path.startswith(prefix.rstrip("/") + "/")
