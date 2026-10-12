"""The cheap adapter: plain HTTP requests through the egress broker (ADR-0028).

Each account has its own cookie jar; nothing is shared between accounts and no
cookie or credential is ever sent to an origin other than the one that set it.
Redirects are followed by hand, one scope-checked hop at a time. A request that
changes state is never repeated when its outcome is uncertain.
"""

import json
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlencode

from backend.redaction import Redactor
from backend.web_urls import WebUrl, path_within
from verification.egress import ActionRefused, Egress, EgressRefused, EgressStopped
from verification.web_pages import Bound, build_observation, read_html

USER_AGENT = "Plumb/0.0 (authorized security test; local)"
MAX_BODY = 512 * 1024
MAX_REDIRECTS = 5
_KEPT_HEADERS = ("content-type", "location", "cache-control", "x-frame-options",
                 "content-security-policy", "strict-transport-security",
                 "x-content-type-options", "referrer-policy")  # fmt: skip


class UncertainWrite(Exception):
    """A state-changing request may or may not have reached the server. Do not repeat it."""


@dataclass
class HttpSession:
    """One account's isolated state. ``account_id`` None is the signed-out visitor."""

    account_id: str | None
    # origin -> cookie name -> (value, path, secure)
    cookies: dict[str, dict[str, tuple[str, str, bool]]] = field(default_factory=dict)

    def header(self, url: WebUrl) -> str | None:
        jar = self.cookies.get(url.origin, {})
        pairs = [
            f"{name}={value}"
            for name, (value, path, secure) in jar.items()
            if path_within(url.path, path) and (not secure or url.scheme == "https")
        ]
        return "; ".join(pairs) or None

    def store(self, url: WebUrl, set_cookie: list[str]) -> None:
        if not set_cookie:
            return
        jar = self.cookies.setdefault(url.origin, {})
        for line in set_cookie:
            parsed: SimpleCookie = SimpleCookie()
            try:
                parsed.load(line)
            except CookieError:
                continue
            for name, morsel in parsed.items():
                # Host-only: a Domain attribute never widens where the cookie goes.
                expired = morsel["max-age"] in {"0", "-1"} or (
                    "1970" in morsel["expires"] or not morsel.value
                )
                if expired:
                    jar.pop(name, None)
                else:
                    jar[name] = (morsel.value, morsel["path"] or "/", bool(morsel["secure"]))

    def values(self) -> tuple[str, ...]:
        """Cookie values, for the redactor: they must never be saved or shown."""
        return tuple(
            value for jar in self.cookies.values() for value, _, _ in jar.values() if value
        )


@dataclass(frozen=True)
class HttpResult:
    url: WebUrl  # the final address after scope-checked redirects
    status: int
    headers: dict[str, str]  # a fixed, non-secret subset
    body: bytes
    hops: tuple[str, ...]  # paths visited, in order
    truncated: bool = False

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> object:
        try:
            return json.loads(self.body)
        except ValueError:
            return None


class HttpAdapter:
    def __init__(self, egress: Egress) -> None:
        self.egress = egress

    def _headers(self, session: HttpSession, url: WebUrl, extra: list[tuple[str, str]]) -> list:
        headers = [
            ("User-Agent", USER_AGENT),
            ("Accept", "text/html,application/json;q=0.9,*/*;q=0.5"),
            ("Accept-Encoding", "identity"),
            *extra,
        ]
        if (cookie := session.header(url)) is not None:
            headers.append(("Cookie", cookie))
        return headers

    def _once(
        self,
        session: HttpSession,
        method: str,
        url: WebUrl,
        body: bytes | None,
        extra: list[tuple[str, str]],
    ) -> tuple[int, list[tuple[str, str]], bytes, bool]:
        response = self.egress.send(
            method, url, self._headers(session, url, extra), body, account_id=session.account_id
        )
        data, truncated = bytearray(), False
        try:
            for chunk in response.iter_raw():
                room = MAX_BODY - len(data)
                if len(chunk) > room:
                    data.extend(chunk[:room])
                    truncated = True
                    break
                data.extend(chunk)
        finally:
            response.close()
        session.store(
            url, [value for name, value in response.headers if name.lower() == "set-cookie"]
        )
        return response.status, response.headers, bytes(data), truncated

    def request(
        self,
        session: HttpSession,
        method: str,
        url: WebUrl,
        *,
        form: dict[str, str] | None = None,
    ) -> HttpResult:
        """One request and its scope-checked redirects. A write is sent at most once."""
        state_changing = method != "GET"
        body = urlencode(form).encode("utf-8") if form is not None else None
        extra = (
            [("Content-Type", "application/x-www-form-urlencoded"), ("Origin", url.origin)]
            if body is not None
            else []
        )
        hops = [url.path]
        try:
            status, headers, data, truncated = self._once(session, method, url, body, extra)
        except EgressStopped:
            raise
        except EgressRefused as error:
            if state_changing and error.kind == "other" and not isinstance(error, ActionRefused):
                # Bytes may have left: the outcome is unknown, so it is not tried again.
                raise UncertainWrite(error.reason) from error
            raise
        for _ in range(MAX_REDIRECTS):
            if status not in {301, 302, 303, 307, 308}:
                break
            location = next((value for name, value in headers if name.lower() == "location"), None)
            target = self.egress.redirect_target(url, location)
            if status in {307, 308} and state_changing:
                raise self.egress.refuse(
                    "redirect",
                    target.host,
                    "A redirect asked to repeat a state-changing request; it was not repeated.",
                )
            # A cookie jar is keyed by origin, so nothing set by one origin follows the hop.
            url, state_changing = target, False
            hops.append(url.path)
            status, headers, data, truncated = self._once(session, "GET", url, None, [])
        else:
            if status in {301, 302, 303, 307, 308}:
                raise self.egress.refuse("redirect", url.host, "Too many redirects.")
        kept = {
            name.lower(): value[:500] for name, value in headers if name.lower() in _KEPT_HEADERS
        }
        return HttpResult(url, status, kept, data, tuple(hops), truncated)

    def observe(
        self,
        session: HttpSession,
        url: WebUrl,
        *,
        redactor: Redactor,
        expected_personal: frozenset[str],
    ) -> tuple[Bound, HttpResult]:
        """Fetch one page and describe it. JavaScript is not run by this adapter."""
        result = self.request(session, "GET", url)
        content_type = result.headers.get("content-type", "").lower()
        raw = read_html(result.text() if "html" in content_type or not content_type else "")
        if "html" not in content_type and content_type:
            raw.text = result.text()[:4000]
        bound = build_observation(
            raw,
            via="http",
            base=result.url,
            status=result.status,
            account_id=session.account_id,
            in_scope=self.egress.in_scope,
            redactor=Redactor((*redactor.secrets, *session.values())),
            expected_personal=expected_personal,
            blocked=[],
        )
        return bound, result
