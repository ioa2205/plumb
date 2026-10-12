"""From a fetched or rendered page to a small, sanitized observation (ADR-0028).

Both adapters produce the same intermediate "raw page" (title, headings, text,
links, forms). The HTTP adapter gets it from static HTML with the standard
library parser; the browser gets it from the rendered DOM. From there one
function bounds it, removes secrets, stops on unexpected personal data and
assigns element references that belong to this one observation.

Only the rendered document and ordinary responses are read. Scripts, source
maps and bundles are never parsed for meaning.
"""

import re
import secrets as random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import unquote

from backend.contracts.web import (
    BlockedRequest,
    ObservedField,
    ObservedForm,
    ObservedLink,
    PageObservation,
)
from backend.redaction import Redactor
from backend.web_urls import WebUrl, resolve_reference

MAX_TEXT = 4000
MAX_LINKS = 60
MAX_FORMS = 12
MAX_FIELDS = 40
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{8,18}\d(?![\w.])")
_CARD = re.compile(r"(?<![\d.])(?:\d[ -]?){13,19}(?![\d.])")
_CAPTCHA = re.compile(r"recaptcha|hcaptcha|turnstile|captcha", re.IGNORECASE)
_SSO = re.compile(
    r"accounts\.google\.com|login\.microsoftonline\.com|appleid\.apple\.com|"
    r"facebook\.com/(?:v[\d.]+/)?dialog|github\.com/login/oauth|/oauth2?/authorize|/saml",
    re.IGNORECASE,
)


class PrivacyStop(Exception):
    """Unexpected personal data was seen. The content is dropped; only the kind is kept."""

    def __init__(self, kinds: list[str]) -> None:
        super().__init__("Unexpected personal data: " + ", ".join(kinds))
        self.kinds = kinds


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2:
            number = number * 2 - 9 if number > 4 else number * 2
        total += number
    return total % 10 == 0


def personal_data(text: str, expected: frozenset[str]) -> list[str]:
    """Kinds of personal data in ``text`` that the scope did not declare as synthetic or public."""
    lowered = {value.lower() for value in expected}
    kinds = []
    if any(match.lower() not in lowered for match in _EMAIL.findall(text)):
        kinds.append("email address")
    for match in _PHONE.findall(text):
        digits = re.sub(r"\D", "", match)
        looks_like_a_date = re.fullmatch(r"(?:19|20)\d{2}[\s.-]?\d{2}[\s.-]?\d{2}.*", match.strip())
        if (
            len(digits) >= 10
            and match.strip() not in expected
            and digits not in lowered
            and not looks_like_a_date
        ):
            kinds.append("phone number")
            break
    for match in _CARD.findall(text):
        digits = re.sub(r"\D", "", match)
        if 13 <= len(digits) <= 19 and _luhn(digits) and digits not in lowered:
            kinds.append("payment card number")
            break
    return kinds


def squeeze(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass
class RawPage:
    """What an adapter read off a page before bounding and sanitizing."""

    title: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""
    links: list[dict[str, str]] = field(default_factory=list)  # text, href
    forms: list[dict[str, Any]] = field(default_factory=list)
    frames: list[str] = field(default_factory=list)  # iframe addresses


class _Reader(HTMLParser):
    """Static HTML only: structure and visible text. Script and style content is skipped."""

    _SKIP = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page = RawPage()
        self._skip = 0
        self._text: list[str] = []
        self._capture: list[tuple[str, list[str]]] = []
        self._form: dict[str, Any] | None = None
        self._labels: dict[str, str] = {}
        self._link: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag in self._SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in {"title", "h1", "h2", "h3", "label", "button", "legend", "option"}:
            self._capture.append((tag + "\0" + values.get("for", ""), []))
        if tag == "a" and values.get("href"):
            self._link = {"href": values["href"], "text": values.get("aria-label", "")}
            self._capture.append(("a\0", []))
        elif tag == "iframe" and values.get("src"):
            self.page.frames.append(values["src"])
        elif tag == "form":
            self._form = {
                "action": values.get("action", ""),
                "method": values.get("method", "get"),
                "heading": values.get("aria-label", ""),
                "submit": "",
                "fields": [],
            }
        elif tag in {"input", "select", "textarea"} and self._form is not None:
            kind = values.get("type", "text" if tag == "input" else tag).lower()
            if kind in {"submit", "image"}:
                self._form["submit"] = self._form["submit"] or values.get("value", "")
                return
            if kind in {"button", "reset"}:
                return
            self._form["fields"].append(
                {
                    "name": values.get("name", ""),
                    "id": values.get("id", ""),
                    "label": values.get("aria-label", "") or values.get("placeholder", ""),
                    "type": kind,
                    "required": "required" in values,
                    "has_value": bool(values.get("value")),
                    "autocomplete": values.get("autocomplete", ""),
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if self._capture and self._capture[-1][0].split("\0")[0] == tag:
            key, parts = self._capture.pop()
            text = " ".join(" ".join(parts).split())
            target = key.split("\0")[1]
            if tag == "title":
                self.page.title = text
            elif tag in {"h1", "h2", "h3"}:
                self.page.headings.append(text)
                if self._form is not None and not self._form["heading"]:
                    self._form["heading"] = text
            elif tag == "label":
                if target:
                    self._labels[target] = text
                elif self._form is not None and self._form["fields"]:
                    last = self._form["fields"][-1]
                    last["label"] = last["label"] or text
                else:
                    self._labels["\0next"] = text
            elif tag in {"button", "legend"} and self._form is not None:
                if tag == "legend":
                    self._form["heading"] = self._form["heading"] or text
                else:
                    self._form["submit"] = self._form["submit"] or text
            elif tag == "a" and self._link is not None:
                self._link["text"] = self._link["text"] or text
                self.page.links.append(self._link)
                self._link = None
        if tag == "form" and self._form is not None:
            for item in self._form["fields"]:
                item["label"] = item["label"] or self._labels.get(item["id"], "")
            self.page.forms.append(self._form)
            self._form = None
        if tag in {"p", "div", "li", "tr", "br", "section", "h1", "h2", "h3"}:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        for _, parts in self._capture:
            parts.append(data)
        if not self._capture or self._capture[-1][0].split("\0")[0] != "title":
            self._text.append(data)


def read_html(markup: str) -> RawPage:
    reader = _Reader()
    reader.feed(markup[: 2 * 1024 * 1024])
    reader.close()
    reader.page.text = "".join(reader._text)
    return reader.page


resolve = resolve_reference


@dataclass
class Bound:
    """An observation plus the private map from its references to real addresses."""

    observation: PageObservation
    links: dict[str, WebUrl]
    forms: dict[str, WebUrl]


def new_observation_id() -> str:
    return "o" + random.token_hex(4)


def build_observation(
    raw: RawPage,
    *,
    via: Literal["http", "browser"],
    base: WebUrl,
    status: int | None,
    account_id: str | None,
    in_scope: Callable[[WebUrl], bool],
    redactor: Redactor,
    expected_personal: frozenset[str],
    blocked: list[BlockedRequest] | None = None,
) -> Bound:
    """Bound, sanitize and reference one page. Raises ``PrivacyStop`` and keeps nothing then."""
    everything = "\n".join(
        [raw.title, *raw.headings, raw.text, *[link.get("text", "") for link in raw.links]]
    )
    if kinds := personal_data(everything, expected_personal):
        raise PrivacyStop(kinds)
    identifier = new_observation_id()

    def clean(value: object, limit: int) -> str:
        return squeeze(redactor.text(str(value or "")), limit)

    def address(value: str, limit: int) -> str:
        # A URL-encoded token is still a token. These are display strings only;
        # the private Bound maps retain the exact addresses for transport.
        if redactor.text(unquote(value)) != unquote(value):
            return "[REDACTED]"
        return clean(value, limit)

    text = redactor.text("\n".join(line.strip() for line in raw.text.splitlines() if line.strip()))
    truncated = len(text) > MAX_TEXT
    links: list[ObservedLink] = []
    link_map: dict[str, WebUrl] = {}
    seen: set[tuple[str, str]] = set()
    for link in raw.links:
        target = resolve(base, link.get("href", ""))
        if target is None:
            continue
        shown = target.path + ("?…" if target.query else "")
        label = clean(link.get("text"), 120)
        if (target.origin + shown, label) in seen:
            continue
        seen.add((target.origin + shown, label))
        if len(links) >= MAX_LINKS:
            truncated = True
            break
        ref = f"{identifier}-l{len(links)}"
        inside = bool(in_scope(target))
        links.append(
            ObservedLink(
                ref=ref,
                text=label,
                path=address(shown if target.origin == base.origin else target.origin + shown, 512),
                in_scope=inside,
            )
        )
        if inside:
            link_map[ref] = target
    forms: list[ObservedForm] = []
    form_map: dict[str, WebUrl] = {}
    for raw_form in raw.forms[:MAX_FORMS]:
        target = resolve(base, str(raw_form.get("action", "")))
        ref = f"{identifier}-f{len(forms)}"
        inside = target is not None and bool(in_scope(target))
        fields = [
            ObservedField(
                ref=f"{ref}-i{index}",
                name=clean(item.get("name"), 80),
                label=clean(item.get("label"), 120),
                input_type=clean(item.get("type") or "text", 24).lower(),
                hint=clean(item.get("autocomplete"), 40).lower(),
                required=bool(item.get("required")),
                has_value=bool(item.get("has_value")),
            )
            for index, item in enumerate(raw_form.get("fields", [])[:MAX_FIELDS])
        ]
        method = str(raw_form.get("method", "get")).upper()
        forms.append(
            ObservedForm(
                ref=ref,
                method="POST" if method == "POST" else "GET",
                action_path=address(target.path if target is not None else "", 512),
                in_scope=inside,
                heading=clean(raw_form.get("heading"), 120),
                submit_label=clean(raw_form.get("submit"), 120),
                fields=fields,
            )
        )
        if inside and target is not None:
            form_map[ref] = target
    codes = [
        item
        for raw_form in raw.forms
        for item in raw_form.get("fields", [])
        if "one-time-code" in str(item.get("autocomplete", "")).lower()
        or re.search(
            r"\b(otp|totp|mfa|2fa|one[- ]time|verification code)\b",
            f"{item.get('name', '')} {item.get('label', '')}",
            re.IGNORECASE,
        )
    ]
    frames = " ".join(raw.frames)
    outward = " ".join(link.get("href", "") for link in raw.links)
    challenge: Literal["none", "captcha", "one_time_code", "single_sign_on"] = "none"
    if _CAPTCHA.search(frames) or re.search(r"\bcaptcha\b", everything, re.IGNORECASE):
        challenge = "captcha"
    elif codes:
        challenge = "one_time_code"
    elif _SSO.search(outward + " " + frames) and not any(
        item.input_type == "password" for form in forms for item in form.fields
    ):
        challenge = "single_sign_on"
    observation = PageObservation(
        observation_id=identifier,
        via=via,
        account_id=account_id,
        origin=address(base.origin, 300),
        path=address(base.path, 512),
        status=status,
        title=clean(raw.title, 160),
        headings=[clean(item, 160) for item in raw.headings[:12] if item.strip()],
        text=text[:MAX_TEXT],
        links=links,
        forms=forms,
        blocked=[
            row.model_copy(
                update={"host": address(row.host, 253), "reason": clean(row.reason, 300)}
            )
            for row in list(blocked or [])[:40]
        ],
        challenge=challenge,
        collected_at=datetime.now(UTC),
        truncated=truncated,
    )
    return Bound(observation, link_map, form_map)
