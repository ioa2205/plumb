"""What a plain-language message is asking for (ADR-0028).

Code reads what it can out of the message: addresses, folder paths, whether a
result is selected. Only the remaining judgment, what kind of request the
wording is, goes to the model as one closed question.
"""

import ipaddress
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from agent.closed import ClosedQuestion, Decision, Fact, QuestionType, Reason, by_code, one_line

MESSAGE_INTENT = QuestionType(
    name="message_intent",
    adds="What kind of request a free-text message is; wording has no fixed form to match.",
    ask="What is the user's message asking for?",
    labels=(
        (
            "general_question",
            "a question answered from general knowledge, about no particular website or code",
        ),
        ("creative_writing", "a request to write something such as a poem, story or message"),
        ("explain_result", "a question only about the selected result or its evidence"),
        (
            "general_and_result",
            "a general question together with a question about the selected result",
        ),
        ("review_folder", "a request to inspect or review source code in a folder"),
        ("test_website", "a request to test, check or investigate a website"),
        ("about_plumb", "a question about what this assistant can do or how to use it"),
    ),
    reasons=(
        Reason("unclear_request", "the message does not say what is wanted"),
        Reason("several_requests", "the message asks for several different things"),
    ),
)

_URL = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_DOMAIN = re.compile(
    r"(?<![\w@./-])(?:[^\W_](?:[^\W_]|-){0,62}[.\u3002\uff0e\uff61])+"
    r"[^\W_](?:[^\W_]|-){0,62}(?![\w-])",
    re.IGNORECASE,
)
_IP = re.compile(
    r"(?<![\w@./-])(?:\[[0-9a-f:.]+\]|[0-9a-f]{0,4}:[0-9a-f:.]*:[0-9a-f:.]*|"
    r"\d{1,3}(?:\.\d{1,3}){3})(?![\w-]|\.\d)",
    re.IGNORECASE,
)
_LOCALHOST = re.compile(r"(?<![\w@./-])localhost(?![\w-]|\.[\w])", re.IGNORECASE)
_QUOTED_PATH = re.compile(r"[\"']([^\"'\n]{3,260})[\"']")
_WINDOWS_PATH = re.compile(r"(?<![\w])[A-Za-z]:[\\/][^\n\"'<>|?*]*")
_POSIX_PATH = re.compile(r"(?<![\w:/.])(?:~|\.{1,2})?/[^\s\"'<>|?*]+(?:/[^\s\"'<>|?*]+)*")


@dataclass(frozen=True)
class Named:
    """What the message itself names, found by code and never by the model."""

    urls: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()  # existing directories only
    paths: tuple[str, ...] = ()  # path-like text, existing or not

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.urls, *self.hosts, *self.folders, *self.paths)))


def _existing_folder(candidate: str) -> str | None:
    """The longest prefix of ``candidate`` that is a directory; reads metadata only."""
    text = candidate.strip().rstrip(".,;:!?)")
    while text:
        try:
            path = Path(text).expanduser()
            if path.is_absolute() and path.is_dir():
                return str(path)
        except (OSError, ValueError, RuntimeError):
            pass
        if " " not in text:
            return None
        text = text.rsplit(" ", 1)[0].rstrip(".,;:!?)")
    return None


def _domain(candidate: str) -> str | None:
    """Plausible DNS syntax, including IDNA; this never resolves or visits it."""
    try:
        ascii_name = candidate.encode("idna").decode("ascii").lower()
        if len(ascii_name) > 253:
            return None
        labels = ascii_name.split(".")
        if len(labels) < 2 or any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None for label in labels
        ):
            return None
        if re.fullmatch(r"[a-z]{2,63}|xn--[a-z0-9-]+", labels[-1]) is None:
            return None
        # The ASCII codec alone accepts malformed xn-- spellings; decoding
        # verifies their punycode, without consulting a DNS/TLD inventory.
        ascii_name.encode("ascii").decode("idna")
        return ascii_name
    except (UnicodeError, ValueError):
        return None


def network_names(message: str) -> Named:
    """Address-shaped text only; no DNS, filesystem metadata or browsing."""
    urls = tuple(dict.fromkeys(match.rstrip(".,;:!?)") for match in _URL.findall(message)))
    without_urls = _URL.sub(" ", message)
    hosts = [host for candidate in _DOMAIN.findall(without_urls) if (host := _domain(candidate))]
    for match in _IP.findall(without_urls):
        with suppress(ValueError):
            hosts.append(str(ipaddress.ip_address(match.strip("[]").rstrip("."))))
    hosts.extend(match.lower() for match in _LOCALHOST.findall(without_urls))
    return Named(urls, tuple(dict.fromkeys(hosts)))


def named(message: str) -> Named:
    network = network_names(message)
    urls, hosts = network.urls, network.hosts
    without_urls = _URL.sub(" ", message)
    candidates = [
        *(match for match in _QUOTED_PATH.findall(without_urls) if re.search(r"[\\/]", match)),
        *_WINDOWS_PATH.findall(without_urls),
        *_POSIX_PATH.findall(without_urls),
    ]
    folders, paths = [], []
    for candidate in candidates:
        cleaned = candidate.strip().rstrip(".,;:!?)")
        if len(cleaned) < 2 or cleaned in {"/", "./", "../"}:
            continue
        folder = _existing_folder(cleaned)
        if folder is not None:
            folders.append(folder)
        paths.append(folder or cleaned.split(" ")[0])
    return Named(urls, hosts, tuple(dict.fromkeys(folders)), tuple(dict.fromkeys(paths)))


def intent_by_code(message: str, found: Named) -> Decision | None:
    """The cases the message decides alone: it is nothing but one address or one folder."""
    text = message.strip().strip("\"'")
    if len(found.urls) == 1 and text.rstrip(".,;:!?)") == found.urls[0]:
        return by_code(MESSAGE_INTENT, "test_website", "The message is only a web address.")
    if len(found.folders) == 1 and not found.urls:
        try:
            same = Path(text).expanduser() == Path(found.folders[0])
        except (OSError, ValueError, RuntimeError):
            same = False
        if same:
            return by_code(MESSAGE_INTENT, "review_folder", "The message is only a folder path.")
    return None


def intent_question(
    message: str, found: Named, *, selected: str | None, previous: str | None
) -> ClosedQuestion:
    text = one_line(message, 4096)
    facts = [Fact("message", one_line(text))]
    if len(text) > 200:
        facts.append(Fact("end of message", one_line(text[-180:])))
    facts.extend(
        [
            Fact("message names a web address", "yes" if found.urls or found.hosts else "no"),
            Fact("message names an existing folder", "yes" if found.folders else "no"),
            Fact("selected result", one_line(selected, 120) if selected else "none"),
            Fact("previous request", previous or "none"),
        ]
    )
    return ClosedQuestion(
        kind=MESSAGE_INTENT,
        facts=tuple(facts),
        user_question="What would you like to do with this message?",
    )
