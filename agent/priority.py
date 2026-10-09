"""Which access sites to investigate first, and why (PROJECT_PLAN §7).

Priority answers "why look here first?" with rules a person can read, never
with an invented probability. A site is ranked by how many of the rules apply
to it; ties go to the site whose rules come earlier in the plan's list. Every
rule that applies is kept as a sentence and travels with the question.

One slot in five is reserved for exploration: it is filled from the lower
half of what is still waiting, so that a rule the ranking lacks cannot hide a
whole class of sites. The draw is seeded by the snapshot, so the same snapshot
always gives the same queue.

A query inside a check's own function, such as the session lookup of a sign-in
dependency, is ranked by what it is and not by what its route does; otherwise
every writing route would push its sign-in lookup above another route's
unguarded read.

Three rules need facts that later stages produce (peer deviations, uncertain
guards, changed files); they are passed in. The others are read from the
application map. The data rule goes by resource names, which is a guess about
what a table holds and is said to be one. It decides order, never a verdict.
"""

import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from analysis.syntax import words
from backend.contracts.application_map import ApplicationMap
from backend.contracts.code import EntryPoint, EntryPointKind, Operation
from backend.contracts.common import InputOrigin

DEFAULT_EXPLORATION_SHARE = 0.2


class Rule(StrEnum):
    """The plan's rules, in the plan's order; the order breaks ties."""

    PUBLIC_EXPOSURE = "public_exposure"
    SENSITIVE_DATA = "sensitive_data"
    WRITE_ACTION = "write_action"
    REQUEST_IDENTIFIER = "request_identifier"
    PEER_DEVIATION = "peer_deviation"
    UNCERTAIN_GUARD = "uncertain_guard"
    RECENT_CHANGE = "recent_change"
    TOOL_SIGNAL = "tool_signal"


_ORDER = {rule: place for place, rule in enumerate(Rule)}


@dataclass(frozen=True)
class Reason:
    rule: Rule
    text: str


@dataclass(frozen=True)
class Subject:
    """Something to investigate, with the rules that apply to it."""

    id: str
    reasons: tuple[Reason, ...]

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(sorted({reason.rule for reason in self.reasons}, key=_ORDER.__getitem__))


@dataclass(frozen=True)
class QueueItem:
    subject_id: str
    position: int  # place in the queue, from 1
    recommended: int  # place by the rules alone; stays visible if the queue is reordered
    reasons: tuple[str, ...]
    exploration: bool = False


def rank(subjects: Sequence[Subject]) -> list[Subject]:
    """Most rules first; among equals, the one whose rules come first in the plan's list."""
    ids = [subject.id for subject in subjects]
    if len(set(ids)) != len(ids):
        raise ValueError("subjects must have distinct IDs")

    def key(subject: Subject) -> tuple[int, tuple[int, ...], str]:
        places = tuple(_ORDER[rule] for rule in subject.rules)
        return (-len(places), places, subject.id)

    return sorted(subjects, key=key)


EXPLORATION = (
    "Exploration: a lower-ranked site, checked so that the ranking cannot hide its blind spots"
)


def queue(
    subjects: Sequence[Subject], *, seed: str, exploration_share: float = DEFAULT_EXPLORATION_SHARE
) -> list[QueueItem]:
    """The order of investigation: by rank, with exploration slots at a fixed rhythm."""
    if not 0 <= exploration_share <= 0.5:
        raise ValueError("the exploration share is between 0 and 0.5")
    ranked = rank(subjects)
    recommended = {subject.id: place for place, subject in enumerate(ranked, start=1)}
    every = round(1 / exploration_share) if exploration_share else 0
    draw = random.Random(seed)  # noqa: S311 - a reproducible draw, not a secret
    waiting = list(ranked)
    items: list[QueueItem] = []
    while waiting:
        position = len(items) + 1
        explore = bool(every) and position % every == 0 and len(waiting) > 1
        # The lower half of what is still waiting; never the item that is next anyway.
        lower_half = range((len(waiting) + 1) // 2, len(waiting))
        chosen = waiting.pop(draw.choice(lower_half) if explore else 0)
        texts = tuple(reason.text for reason in chosen.reasons)
        items.append(
            QueueItem(
                subject_id=chosen.id,
                position=position,
                recommended=recommended[chosen.id],
                reasons=(*texts, EXPLORATION) if explore else texts,
                exploration=explore,
            )
        )
    return items


# --- reading the rules from the application map --------------------------------------------

_ORIGINS = {
    InputOrigin.PATH: "the URL path",
    InputOrigin.QUERY: "the query string",
    InputOrigin.BODY: "the request body",
    InputOrigin.HEADER: "a request header",
}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_WRITE_OPERATIONS = {Operation.CREATE, Operation.UPDATE, Operation.DELETE}
_DATA_CLASSES = {
    "personal": {"user", "customer", "account", "profile", "person", "member", "employee"}
    | {"contact", "address", "phone", "email", "courier", "delivery", "patient"},
    "payment": {"order", "payment", "invoice", "receipt", "refund", "card", "transaction"}
    | {"billing", "charge", "payout", "subscription"},
    "sign-in": {"session", "token", "password", "credential", "secret"},
}


def data_class(resource: str) -> str | None:
    """A guess from the resource's name: ``order_items`` and ``OrderItem`` are payment data."""
    names = set()
    for word in words(resource).split():
        names |= {word, word.removesuffix("s"), word.removesuffix("es")}
        if word.endswith("ies"):
            names.add(word.removesuffix("ies") + "y")
    return next((kind for kind, stems in _DATA_CLASSES.items() if names & stems), None)


def _entry_words(entry: EntryPoint) -> str:
    if entry.kind is EntryPointKind.SERVER_ACTION:
        return "This Server Action"
    return f"{entry.method} {entry.route}" if entry.method and entry.route else "This entry point"


def subjects_from_map(
    application_map: ApplicationMap,
    *,
    deviations: Mapping[str, str] | None = None,
    uncertain_guards: Mapping[str, str] | None = None,
    changed_paths: Collection[str] = (),
) -> list[Subject]:
    """One subject per access site.

    ``deviations`` and ``uncertain_guards`` map a site ID to the sentence that
    explains it (from the peer check and from guard classification).
    """
    entries = {entry.id: entry for entry in application_map.entries}
    optimistic = {guard.id for guard in application_map.guards if guard.optimistic}
    # A query that runs inside a check candidate's own function, such as the session lookup
    # of a sign-in dependency, is part of that check. What the route does (it is public, it
    # writes) describes the route's own queries, not that lookup.
    check_functions = {guard.via_symbol_id for guard in application_map.guards}
    checked: dict[str, set[bool]] = {}
    part_of_a_check = set()
    for link in application_map.links:
        if link.kind == "may_check":
            checked.setdefault(link.target, set()).add(link.source in optimistic)
        elif link.kind == "access" and link.source in check_functions:
            part_of_a_check.add(link.target)
    subjects = []
    for site in application_map.access_sites:
        entry = entries[site.entry_point_id]
        reasons = []
        own_query = site.id not in part_of_a_check
        candidates = checked.get(site.id, set())
        if not own_query:
            pass
        elif not candidates:
            reasons.append(
                Reason(Rule.PUBLIC_EXPOSURE, "No sign-in check was found on the way to this query")
            )
        elif candidates == {True}:
            reasons.append(
                Reason(
                    Rule.PUBLIC_EXPOSURE,
                    "Only a proxy matcher stands before this query, and that is not a boundary",
                )
            )
        if kind := data_class(site.resource):
            reasons.append(
                Reason(Rule.SENSITIVE_DATA, f"{site.resource} holds {kind} data, going by its name")
            )
        writes = entry.kind is EntryPointKind.SERVER_ACTION or entry.method in _WRITE_METHODS
        if site.operation in _WRITE_OPERATIONS:
            reasons.append(
                Reason(Rule.WRITE_ACTION, f"The query changes {site.resource} ({site.operation})")
            )
        elif own_query and writes:
            reasons.append(Reason(Rule.WRITE_ACTION, f"{_entry_words(entry)} changes data"))
        if site.key_origin in _ORIGINS:
            reasons.append(
                Reason(
                    Rule.REQUEST_IDENTIFIER,
                    f"{site.resource} is selected by an ID from {_ORIGINS[site.key_origin]}",
                )
            )
        if deviations and site.id in deviations:
            reasons.append(Reason(Rule.PEER_DEVIATION, deviations[site.id]))
        if uncertain_guards and site.id in uncertain_guards:
            reasons.append(Reason(Rule.UNCERTAIN_GUARD, uncertain_guards[site.id]))
        if site.span.path in changed_paths:
            reasons.append(
                Reason(Rule.RECENT_CHANGE, f"{site.span.path} changed since the last review")
            )
        subjects.append(Subject(site.id, tuple(reasons)))
    return subjects
