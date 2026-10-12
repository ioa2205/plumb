"""The pinned browser runner: a small fixed set of tools over a contained Chromium (ADR-0028).

Containment does not rest on anything inside the browser. Chromium is started
with the egress broker's loopback proxy as its only network path (loopback
included), its own name resolution mapped to nowhere, QUIC and non-proxied
WebRTC off, service workers and downloads blocked. Its own sandbox stays on and
is never switched off.

The tools are finite and take no script, selector or command from anyone:

    navigate · observe · follow an observed link · fill an observed field ·
    submit an observed form · export one account's session to the HTTP adapter

An element reference belongs to one observation of one page. When the page has
moved on, the reference is refused as stale and the caller observes again.
Each account has its own browser context, so cookies and storage never mix.
A secret is typed by reference; its value never leaves this module.
"""

import contextlib
import threading
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self

import psutil

from backend.contracts.web import BlockedRequest
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.browser import BrowserUnavailable, verified_executable
from backend.web_urls import UrlRefused, WebUrl, parse_url
from verification.egress import Egress, EgressRefused
from verification.web_http import HttpSession, UncertainWrite
from verification.web_pages import Bound, RawPage, build_observation
from verification.web_proxy import USER, BrowserProxy
from verification.web_secrets import SecretStore
from verification.web_tls import FrontCertificates

STEP_MS = 15_000
SETTLE_MS = 2_500
_TEXT_INPUTS = frozenset(
    {"text", "email", "password", "search", "tel", "url", "number", "textarea"}
)

# Fixed, read-only page scripts owned by the runner. Element methods are taken from
# the prototypes, so a page cannot swap them by naming a form control "querySelector".
_HELPERS = """
const q = (node, selector) => Element.prototype.querySelector.call(node, selector);
const qa = (node, selector) => Array.from(Element.prototype.querySelectorAll.call(node, selector));
const attr = (node, name) => Element.prototype.getAttribute.call(node, name) || "";
const text = (node) => (node ? (node.innerText || node.textContent || "") : "").trim();
const forms = () => Array.from(document.querySelectorAll("form")).slice(0, 12);
const fieldsOf = (form) => qa(form, "input, select, textarea").filter((item) =>
  !["submit", "button", "image", "reset"].includes(attr(item, "type").toLowerCase())).slice(0, 40);
const submitOf = (form) =>
  q(form, "button[type=submit], input[type=submit], button:not([type])");
"""
EXTRACT_JS = (
    "() => {"
    + _HELPERS
    + """
const labelOf = (item) => {
  const labels = item.labels ? Array.from(item.labels).map(text).filter(Boolean) : [];
  return labels[0] || attr(item, "aria-label") || attr(item, "placeholder");
};
return {
  title: document.title || "",
  headings: Array.from(document.querySelectorAll("h1, h2, h3")).slice(0, 12).map(text),
  text: (document.body ? document.body.innerText : "").slice(0, 20000),
  links: Array.from(document.querySelectorAll("a[href]")).slice(0, 200).map((a) => (
    { text: text(a) || attr(a, "aria-label"), href: attr(a, "href") })),
  forms: forms().map((form) => {
    const submit = submitOf(form);
    return {
      action: (submit ? attr(submit, "formaction") : "") || attr(form, "action"),
      method: (submit ? attr(submit, "formmethod") : "") || attr(form, "method") || "get",
      enctype: (submit ? attr(submit, "formenctype") : "") || attr(form, "enctype"),
      submit_name: submit ? attr(submit, "name") : "",
      submit_value: submit ? attr(submit, "value") : "",
      heading: attr(form, "aria-label") || text(q(form, "h1, h2, h3, legend")),
      submit: submit ? (text(submit) || attr(submit, "value")) : "",
      fields: fieldsOf(form).map((item) => ({
        name: attr(item, "name"),
        id: item.id || "",
        label: labelOf(item),
        type: (attr(item, "type") || item.tagName).toLowerCase(),
        required: item.required === true,
        has_value: typeof item.value === "string" && item.value.length > 0,
        autocomplete: attr(item, "autocomplete"),
      })),
    };
  }),
  frames: Array.from(document.querySelectorAll("iframe[src]")).slice(0, 20).map(
    (frame) => attr(frame, "src")),
};
}"""
)
FIND_FIELD_JS = (
    "([formIndex, fieldIndex]) => {"
    + _HELPERS
    + "const form = forms()[formIndex];"
    + " return form ? (fieldsOf(form)[fieldIndex] || null) : null; }"
)
FIND_SUBMIT_JS = (
    "(formIndex) => {" + _HELPERS + "const form = forms()[formIndex];"
    " return form ? (submitOf(form) || form) : null; }"
)
REQUEST_SUBMIT_JS = "(form) => HTMLFormElement.prototype.requestSubmit.call(form)"
FORM_VALUES_JS = (
    "(formIndex) => {"
    + _HELPERS
    + """
const form = forms()[formIndex];
if (!form) return null;
const values = fieldsOf(form).map((item, index) => ({
  index, name: attr(item, "name"), value: item.value,
  disabled: item.disabled === true,
  included: !["checkbox", "radio"].includes(attr(item, "type").toLowerCase()) || item.checked,
  unsupported: attr(item, "type").toLowerCase() === "file" || item.multiple === true,
  required: item.required === true,
}));
const submit = submitOf(form);
if (submit && attr(submit, "name")) values.push({
  index: -1, name: attr(submit, "name"), value: attr(submit, "value"),
  disabled: submit.disabled === true, included: true, unsupported: false, required: false,
});
return values;
}"""
)


class StaleReference(Exception):
    """The reference belongs to an earlier observation, or the page changed since."""


def _signature(form: dict[str, Any]) -> tuple[object, ...]:
    return (
        form.get("action"),
        str(form.get("method", "")).lower(),
        form.get("enctype"),
        form.get("submit_name"),
        form.get("submit_value"),
        tuple((item.get("name"), item.get("type")) for item in form.get("fields", [])),
    )


@dataclass
class _Current:
    """What the latest observation of one account's page was bound to."""

    observation_id: str
    url: str
    forms: list[tuple[object, ...]]
    bound: Bound
    filled: dict[tuple[int, int], str] = field(default_factory=dict, repr=False)


class BrowserRunner:
    def __init__(
        self,
        settings: Settings,
        egress: Egress,
        *,
        secrets: SecretStore,
        redactor: Redactor,
        expected_personal: frozenset[str],
    ) -> None:
        self.settings = settings
        self.egress = egress
        self.secrets = secrets
        self.redactor = redactor
        self.expected_personal = expected_personal
        self.popups_closed = 0
        self._thread = threading.get_ident()
        self._contexts: dict[str | None, Any] = {}
        self._pages: dict[str | None, Any] = {}
        self._current: dict[str | None, _Current] = {}
        self._seen_blocked: dict[tuple[str, str, str], int] = {}
        self._pending: dict[int, set[Any]] = {}  # requests in flight, per page
        self._playwright: Any = None
        self._browser: Any = None
        self._proxy: BrowserProxy | None = None
        self._certificates: FrontCertificates | None = None
        self.launch_arguments: list[str] = []

    # --- lifecycle ---------------------------------------------------------------------------

    def __enter__(self) -> Self:
        executable = verified_executable(self.settings)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BrowserUnavailable(
                "The Playwright package is not installed. Run: uv sync --extra browser"
            ) from error
        try:
            if self.egress.policy.mode == "external":
                self._certificates = FrontCertificates(self.settings.cache_dir / "browser-front")
            self._proxy = BrowserProxy(self.egress, self._certificates)
            self.launch_arguments = [
                # No name is ever resolved by the browser itself; the broker resolves. The one
                # exception is the literal address of the broker's own loopback proxy.
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                "--disable-quic",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--disable-features=DnsOverHttps,AsyncDns,NetworkPrediction,OptimizationHints,"
                "MediaRouter,Translate,InterestFeedContentSuggestions",
                "--dns-prefetch-disable",
                "--no-pings",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-domain-reliability",
                "--disable-sync",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            if self._certificates is not None:
                # Trust for exactly this launch's key, by its hash. Not a general bypass.
                self.launch_arguments.append(
                    "--ignore-certificate-errors-spki-list=" + self._certificates.pin
                )
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                executable_path=str(executable),
                headless=True,
                chromium_sandbox=True,  # Chromium's own sandbox stays on. Never turned off.
                proxy={
                    "server": self._proxy.address,
                    "bypass": "<-loopback>",  # loopback goes through the broker too
                    "username": USER,
                    "password": self._proxy.token,
                },
                args=self.launch_arguments,
                timeout=60_000,
            )
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        for closer in (
            *[context.close for context in self._contexts.values()],
            *([self._browser.close] if self._browser is not None else []),
            *([self._playwright.stop] if self._playwright is not None else []),
            *([self._proxy.close] if self._proxy is not None else []),
            *([self._certificates.close] if self._certificates is not None else []),
        ):
            # Best-effort teardown: every part is tried, whatever an earlier one did.
            with contextlib.suppress(Exception):
                closer()
        self._contexts.clear()
        self._pages.clear()
        self._current.clear()
        self._browser = self._playwright = self._proxy = self._certificates = None

    def sandboxed(self) -> bool:
        """Whether no process of this browser was started with its sandbox switched off."""
        if self._browser is None:
            return False
        me = psutil.Process()
        commands = []
        for child in me.children(recursive=True):
            try:
                if "chrome-headless-shell" in child.name().lower():
                    commands.append(" ".join(child.cmdline()))
            except psutil.Error:
                continue
        return bool(commands) and not any("--no-sandbox" in command for command in commands)

    # --- contexts ----------------------------------------------------------------------------

    def _own_thread(self) -> None:
        if threading.get_ident() != self._thread:
            raise RuntimeError("the browser runner is used from the thread that created it")

    def _page(self, account_id: str | None, state: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        self._own_thread()
        if self._browser is None:
            raise BrowserUnavailable("The browser is not running.")
        if account_id not in self._pages:
            if self._proxy is None:
                raise BrowserUnavailable("The browser proxy is not running.")
            context = self._browser.new_context(
                service_workers="block",
                accept_downloads=False,
                storage_state=state,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
                proxy=self._proxy.proxy_for(account_id),
            )
            context.set_default_timeout(STEP_MS)
            page = context.new_page()

            def extra_page(popup: Any) -> None:  # noqa: ANN401 - a Playwright page
                if popup is not page:
                    self.popups_closed += 1
                    self.egress.refuse("other", "", "A popup window was closed, not followed.")
                    popup.close()

            pending = self._pending.setdefault(id(page), set())
            context.on("page", extra_page)
            page.on("dialog", lambda dialog: dialog.dismiss())
            page.on("request", lambda request: pending.add(request))
            page.on("requestfinished", lambda request: pending.discard(request))
            page.on("requestfailed", lambda request: pending.discard(request))
            self._contexts[account_id], self._pages[account_id] = context, page
        return self._pages[account_id]

    def state(self, account_id: str | None) -> dict[str, Any] | None:
        """This account's cookies and storage, to keep in memory across a browser restart."""
        context = self._contexts.get(account_id)
        return context.storage_state() if context is not None else None

    def restore(self, account_id: str | None, state: dict[str, Any]) -> None:
        if account_id in self._pages:
            raise ValueError("this account already has an open context")
        self._page(account_id, state)

    def forget(self, account_id: str | None) -> None:
        """Drop one account's context entirely: cookies, storage and page."""
        context = self._contexts.pop(account_id, None)
        self._pages.pop(account_id, None)
        self._current.pop(account_id, None)
        if context is not None:
            context.close()

    def session(self, account_id: str | None) -> HttpSession:
        """This account's cookies for the approved origins, handed to the HTTP adapter in memory."""
        session = HttpSession(account_id)
        context = self._contexts.get(account_id)
        if context is None:
            return session
        for target in self.egress.policy.targets:
            for cookie in context.cookies([target.origin]):
                session.cookies.setdefault(target.origin, {})[cookie["name"]] = (
                    cookie["value"],
                    cookie.get("path") or "/",
                    bool(cookie.get("secure")),
                )
        return session

    # --- tools -------------------------------------------------------------------------------

    def _timeout(self) -> float:
        left = self.egress.budget.seconds_left() * 1000
        if left <= 0:
            self.egress.live()
        return max(250.0, min(STEP_MS, left))

    def _settle(self, page: Any) -> None:  # noqa: ANN401
        """Wait, briefly and boundedly, until the page has stopped loading and requesting.

        A script that answers a click with a request and then moves to another page
        has no "load" event to wait for, so requests in flight are counted instead.
        A page that never goes quiet is observed as it is when the wait runs out.
        """
        from playwright.sync_api import Error

        pending = self._pending.setdefault(id(page), set())
        deadline = time.monotonic() + min(SETTLE_MS, self._timeout()) / 1000
        quiet_since: float | None = None
        try:
            page.wait_for_timeout(150)
            while time.monotonic() < deadline:
                try:
                    ready = page.evaluate("document.readyState") == "complete"
                except Error:
                    ready = False  # in the middle of a navigation
                if ready and not pending:
                    quiet_since = quiet_since or time.monotonic()
                    if time.monotonic() - quiet_since >= 0.4:
                        return
                else:
                    quiet_since = None
                page.wait_for_timeout(80)
        except Error:
            return

    def navigate(self, account_id: str | None, url: WebUrl) -> int | None:
        """Open one in-scope address. The scope is checked here and again by the broker."""
        from playwright.sync_api import Error

        self.egress.check(url)
        page = self._page(account_id)
        self._current.pop(account_id, None)
        try:
            response = page.goto(url.url, wait_until="load", timeout=self._timeout())
        except Error as error:
            self.egress.live()
            raise EgressRefused("other", "The page did not load.", url.host) from error
        self._settle(page)
        return response.status if response is not None else None

    def location(self, account_id: str | None) -> WebUrl | None:
        page = self._pages.get(account_id)
        try:
            return parse_url(page.url) if page is not None else None
        except UrlRefused:
            return None

    def observe(self, account_id: str | None, status: int | None = None) -> Bound:
        """Describe the page as rendered now, and bind fresh element references to it."""
        page = self._page(account_id)
        where = self.location(account_id)
        if where is None or not self.egress.in_scope(where):
            raise self.egress.refuse(
                "off_scope", where.host if where else "", "The page is not at an approved address."
            )
        raw_data = page.evaluate(EXTRACT_JS)
        raw = RawPage(
            title=str(raw_data.get("title", "")),
            headings=[str(item) for item in raw_data.get("headings", [])],
            text=str(raw_data.get("text", "")),
            links=list(raw_data.get("links", [])),
            forms=list(raw_data.get("forms", [])),
            frames=[str(item) for item in raw_data.get("frames", [])],
        )
        session = self.session(account_id)
        bound = build_observation(
            raw,
            via="browser",
            base=where,
            status=status,
            account_id=account_id,
            in_scope=self.egress.in_scope,
            redactor=Redactor((*self.redactor.secrets, *self.secrets.values(), *session.values())),
            expected_personal=self.expected_personal,
            blocked=self._new_blocked(),
        )
        self._current[account_id] = _Current(
            bound.observation.observation_id,
            page.url,
            [_signature(form) for form in raw.forms[:12]],
            bound,
        )
        return bound

    def _new_blocked(self) -> list[BlockedRequest]:
        """Refusals recorded since the previous observation, so each page shows its own."""
        fresh = []
        for row in list(self.egress.blocked):
            key = (row.kind, row.host, row.reason)
            before = self._seen_blocked.get(key, 0)
            if row.count > before:
                fresh.append(row.model_copy(update={"count": row.count - before}))
                self._seen_blocked[key] = row.count
        return fresh

    def _bound_form(self, account_id: str | None, ref: str) -> tuple[Any, int, _Current]:
        """Resolve a form reference against the current observation, or refuse it as stale."""
        current = self._current.get(account_id)
        page = self._pages.get(account_id)
        parts = ref.split("-")
        if current is None or page is None or parts[0] != current.observation_id:
            raise StaleReference("This reference belongs to an earlier observation.")
        index = int(parts[1][1:])
        if page.url != current.url:
            raise StaleReference("The page has moved since it was observed.")
        now = [_signature(form) for form in page.evaluate(EXTRACT_JS).get("forms", [])[:12]]
        if index >= len(current.forms) or now != current.forms:
            raise StaleReference("The page changed since it was observed.")
        return page, index, current

    def follow(self, account_id: str | None, ref: str) -> int | None:
        """Go to the address of an observed in-scope link."""
        current = self._current.get(account_id)
        if current is None or not ref.startswith(current.observation_id + "-l"):
            raise StaleReference("This reference belongs to an earlier observation.")
        target = current.bound.links.get(ref)
        if target is None:
            raise self.egress.refuse("off_scope", "", "That link leads outside the approved scope.")
        return self.navigate(account_id, target)

    def fill(
        self,
        account_id: str | None,
        ref: str,
        *,
        value: str | None = None,
        secret_ref: str | None = None,
    ) -> None:
        """Type a synthetic value, or a secret by its reference, into an observed field."""
        if (value is None) == (secret_ref is None):
            raise ValueError("fill takes a synthetic value or a secret reference, exactly one")
        page, form_index, current = self._bound_form(account_id, ref)
        field_index = int(ref.split("-")[2][1:])
        form = current.bound.observation.forms[form_index]
        if field_index >= len(form.fields) or form.fields[field_index].ref != ref:
            raise StaleReference("This field is not part of the current observation.")
        if form.fields[field_index].input_type not in _TEXT_INPUTS:
            raise ValueError("only text-like fields are filled")
        handle = page.evaluate_handle(FIND_FIELD_JS, [form_index, field_index]).as_element()
        if handle is None:
            raise StaleReference("The field is no longer on the page.")
        actual = self.secrets.get(secret_ref) if secret_ref is not None else str(value)
        handle.fill(actual)
        # The values are operational memory only, never part of an observation.
        current.filled[(form_index, field_index)] = actual

    def submit(self, account_id: str | None, ref: str) -> None:
        """Submit once under the broker's independently approved action/account grant."""
        from playwright.sync_api import Error

        page, form_index, current = self._bound_form(account_id, ref)
        if ref not in current.bound.forms:
            raise self.egress.refuse("off_scope", "", "That form posts outside the approved scope.")
        form = current.bound.observation.forms[form_index]
        target = current.bound.forms[ref]
        raw_values = page.evaluate(FORM_VALUES_JS, form_index)
        values: dict[str, str] = {}
        required: set[str] = set()
        if not isinstance(raw_values, list):
            raise StaleReference("The form is no longer on the page.")
        for item in raw_values:
            index, name, value = item.get("index"), item.get("name"), item.get("value")
            key = (form_index, index)
            if item.get("disabled") or not item.get("included") or not name:
                if key in current.filled:
                    raise StaleReference("A filled field is no longer part of the submission.")
                continue
            if item.get("unsupported") or not isinstance(name, str) or not isinstance(value, str):
                raise ValueError("only named scalar form fields can be submitted")
            if name in values:
                raise ValueError("duplicate form field names cannot be submitted")
            if key in current.filled and current.filled[key] != value:
                raise StaleReference("A filled field changed before submission.")
            values[name] = value
            if item.get("required") or key in current.filled:
                required.add(name)
        handle = page.evaluate_handle(FIND_SUBMIT_JS, form_index).as_element()
        if handle is None:
            raise StaleReference("The form is no longer on the page.")
        with self.egress.form_grant(
            account_id, form.method, target, values, required=frozenset(required)
        ):
            self._current.pop(account_id, None)
            try:
                if handle.evaluate("node => node.tagName") == "FORM":
                    handle.evaluate(REQUEST_SUBMIT_JS)
                else:
                    handle.click(timeout=self._timeout())
            except Error as error:
                # The click may or may not have sent the form: unknown, so never repeated.
                raise UncertainWrite("The form submission did not complete cleanly.") from error
            self._settle(page)
