"""Who may talk to the local API (PROJECT_PLAN §8).

The API listens on loopback only, and that is not enough: any web page the user
visits can make their browser send requests to it, and a DNS-rebinding page can
give Plumb's socket a name of its own. Every request passes four checks.

1. **Host.** It must name this server's own address and port. A rebinding page
   arrives under its own host name and is refused.
2. **Origin.** A request that says it comes from another origin, in ``Origin``
   or in ``Sec-Fetch-Site``, is refused, whatever it asks for; another port on
   the same machine is another origin. A request that changes state must say
   where it comes from. No CORS header is ever sent.
3. **Session.** Everything except the bootstrap needs the session cookie.
4. **Response headers.** A strict Content-Security-Policy, no sniffing, no
   framing, no referrer, and no caching of API answers.

A session starts from the bootstrap link printed at launch. The link works
once: its token is exchanged for an HttpOnly, SameSite=Strict cookie and the
browser is sent on to ``/``, so the session token is never in a URL. Both
tokens live in memory for one launch and are never logged.

Known limit: browsers scope cookies by host, not by port, so another server on
127.0.0.1 is sent this cookie and could replay it. Run nothing untrusted on
loopback next to Plumb.
"""

import hmac
import logging
import re
import secrets

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.redaction import Redactor

LOOPBACK = "127.0.0.1"
COOKIE = "plumb_session"
BOOTSTRAP_PATH = "/bootstrap"

CSP_SCRIPT_HASHES = "plumb.workbench.script_hashes"  # internal ASGI scope key, never a header


def content_security_policy(script_hashes: tuple[str, ...] = ()) -> str:
    """Add only exact build-script digests to the original policy."""
    if len(script_hashes) > 64 or any(
        re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", item) is None for item in script_hashes
    ):
        raise ValueError("invalid workbench script hashes")
    scripts = "script-src 'self'" + "".join(f" '{item}'" for item in sorted(set(script_hashes)))
    return "; ".join(
        [
            "default-src 'none'",
            scripts,
            "script-src-attr 'none'",
            "style-src 'self'",
            "style-src-attr 'none'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


CONTENT_SECURITY_POLICY = content_security_policy()
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

NO_SESSION = (
    "This browser has no Plumb session. Open the link printed in the terminal where Plumb started."
)
USED_LINK = "This link has been used or is not valid. Restart Plumb to get a new one."
INTERNAL_ERROR = (
    "Plumb could not complete this request. The terminal where it runs has the details."
)

_LOG = logging.getLogger("plumb.api")


def _same(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


class Gate:
    """The address, the one-time bootstrap token and the session of one launch."""

    def __init__(self, port: int, *, redactor: Redactor | None = None) -> None:
        if not 0 < port < 65536:
            raise ValueError("the gate needs the port the server is bound to")
        self.host = f"{LOOPBACK}:{port}"
        self.origin = f"http://{self.host}"
        self._bootstrap: str | None = secrets.token_urlsafe(32)
        self._session: str | None = None
        policy = redactor or Redactor.configured()
        self.redactor = Redactor((*policy.secrets, self._bootstrap))

    @property
    def bootstrap_url(self) -> str | None:
        """The link to open once; None after it has been used."""
        if self._bootstrap is None:
            return None
        return f"{self.origin}{BOOTSTRAP_PATH}?token={self._bootstrap}"

    def exchange(self, token: str) -> str | None:
        """The session token for a correct, unused bootstrap token. The link then stops working."""
        if self._bootstrap is None or not _same(token, self._bootstrap):
            return None
        self._bootstrap = None
        self._session = secrets.token_urlsafe(32)
        self.redactor = Redactor((*self.redactor.secrets, self._session))
        return self._session

    def has_session(self, cookie_header: str | None) -> bool:
        """Whether any ``plumb_session`` cookie sent is this launch's session.

        Any, because another local server can plant a cookie of the same name
        for this host; that must not lock the user out.
        """
        if self._session is None or not cookie_header:
            return False
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and _same(value, self._session):
                return True
        return False


class Guarded:
    """ASGI wrapper that applies the four checks to every request of ``app``."""

    def __init__(self, app: ASGIApp, gate: Gate) -> None:
        self.app = app
        self.gate = gate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # No WebSocket endpoint exists; a browser page elsewhere must not open one.
            await send({"type": "websocket.close", "code": 1008})
            return

        started = False

        async def protected(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if CSP_SCRIPT_HASHES in scope:
                    headers["Content-Security-Policy"] = content_security_policy(
                        scope[CSP_SCRIPT_HASHES]
                    )
                headers.setdefault("Cache-Control", "no-store")
            await send(message)

        refusal = self._refusal(scope)
        if refusal is not None:
            await refusal(scope, receive, protected)
            return
        try:
            await self.app(scope, receive, protected)
        except Exception as error:
            # Answered here so that even a failure leaves with the security headers.
            # The request line is not logged: a bootstrap link carries its token there.
            self.gate.redactor.exception(_LOG, "a request handler failed", error)
            if not started:
                await PlainTextResponse(INTERNAL_ERROR, status_code=500)(scope, receive, protected)

    def _refusal(self, scope: Scope) -> Response | None:
        headers = Headers(scope=scope)
        method, path = scope["method"], scope["path"]
        if headers.getlist("host") != [self.gate.host]:
            return PlainTextResponse("This address is not Plumb's.", status_code=421)
        site = headers.get("sec-fetch-site")
        origin = headers.get("origin")
        # "none" is a link typed or opened by the user; it never carries a write.
        foreign_site = site is not None and (
            site not in ("same-origin", "none") or (site == "none" and method not in _SAFE_METHODS)
        )
        foreign_origin = origin is not None and origin != self.gate.origin
        unnamed_write = origin is None and method not in _SAFE_METHODS
        if foreign_site or foreign_origin or unnamed_write:
            return PlainTextResponse("Plumb answers only its own pages.", status_code=403)
        if path == BOOTSTRAP_PATH and method == "GET":
            return None
        if not self.gate.has_session(headers.get("cookie")):
            if path.startswith("/api/"):
                return JSONResponse({"detail": NO_SESSION}, status_code=401)
            return PlainTextResponse(NO_SESSION, status_code=401)
        return None


def bootstrap(gate: Gate, token: str | None, cookie_header: str | None) -> Response:
    """Exchange the one-time token for the session cookie, then leave the link behind."""
    if gate.has_session(cookie_header):
        return RedirectResponse("/", status_code=303)  # the link reopened from history
    session = gate.exchange(token or "")
    if session is None:
        return PlainTextResponse(USED_LINK, status_code=403)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, session, httponly=True, samesite="strict", path="/")
    return response
