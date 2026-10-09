from pathlib import Path

import pytest

from agent.priority import (
    EXPLORATION,
    Reason,
    Rule,
    Subject,
    data_class,
    queue,
    rank,
    subjects_from_map,
)
from analysis.application_map import build_map
from analysis.index import Index, index_path
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.application_map import ApplicationMap

TANDIR = Path(__file__).resolve().parents[2] / "labs" / "tandir"
SNAP = "a" * 64


def subject(name: str, *rules: Rule) -> Subject:
    return Subject(name, tuple(Reason(rule, f"{name}: {rule.value}") for rule in rules))


# --- ranking -------------------------------------------------------------------------------


def test_more_rules_rank_first_and_ties_follow_the_plans_order() -> None:
    ranked = rank(
        [
            subject("nothing"),
            subject("changed", Rule.RECENT_CHANGE),
            subject("public", Rule.PUBLIC_EXPOSURE),
            subject("data+write", Rule.SENSITIVE_DATA, Rule.WRITE_ACTION),
            subject("public+id", Rule.REQUEST_IDENTIFIER, Rule.PUBLIC_EXPOSURE),
            subject("three", Rule.WRITE_ACTION, Rule.REQUEST_IDENTIFIER, Rule.PEER_DEVIATION),
        ]
    )
    assert [item.id for item in ranked] == [
        "three",  # three rules
        "public+id",  # two rules, and public exposure comes first in the plan
        "data+write",
        "public",  # one rule each: the earlier rule wins
        "changed",
        "nothing",
    ]


def test_equal_subjects_are_ordered_by_id_and_a_rule_counts_once() -> None:
    twice = Subject(
        "b",
        (Reason(Rule.REQUEST_IDENTIFIER, "by path"), Reason(Rule.REQUEST_IDENTIFIER, "by body")),
    )
    assert twice.rules == (Rule.REQUEST_IDENTIFIER,)
    order = rank(
        [subject("c", Rule.REQUEST_IDENTIFIER), twice, subject("a", Rule.REQUEST_IDENTIFIER)]
    )
    assert [item.id for item in order] == ["a", "b", "c"]
    # The order given does not matter.
    assert rank(list(reversed(order))) == order


def test_duplicate_subjects_are_refused() -> None:
    with pytest.raises(ValueError, match="distinct IDs"):
        rank([subject("a"), subject("a", Rule.RECENT_CHANGE)])


# --- the queue and its exploration share ---------------------------------------------------


def many(count: int) -> list[Subject]:
    """Subjects s01..sNN in rank order: every one has fewer or later rules than the one before."""
    return [
        subject(f"s{n:02}", *list(Rule)[: max(0, len(Rule) - n // 3)]) for n in range(1, count + 1)
    ]


def test_the_queue_follows_the_ranking_and_keeps_every_reason() -> None:
    items = queue(many(4), seed=SNAP)
    assert [(item.subject_id, item.position, item.recommended) for item in items] == [
        ("s01", 1, 1),
        ("s02", 2, 2),
        ("s03", 3, 3),
        ("s04", 4, 4),
    ]
    assert not any(item.exploration for item in items)
    assert items[0].reasons == tuple(f"s01: {rule.value}" for rule in Rule)
    assert items[3].reasons == tuple(f"s04: {rule.value}" for rule in list(Rule)[:-1])


def test_one_slot_in_five_explores_the_lower_half_of_what_is_waiting() -> None:
    subjects = many(23)
    items = queue(subjects, seed=SNAP)
    assert sorted(item.subject_id for item in items) == [s.id for s in subjects]
    assert [item.position for item in items] == list(range(1, 24))
    explored = [item for item in items if item.exploration]
    assert [item.position for item in explored] == [5, 10, 15, 20]
    waiting = list(range(1, 24))  # recommended places not yet queued
    for item in items:
        if item.exploration:
            lower_half = waiting[(len(waiting) + 1) // 2 :]
            assert item.recommended in lower_half
            assert item.reasons[-1] == EXPLORATION
            assert item.reasons[:-1] == next(
                tuple(r.text for r in s.reasons) for s in subjects if s.id == item.subject_id
            )
        else:
            assert item.recommended == waiting[0]
            assert EXPLORATION not in item.reasons
        waiting.remove(item.recommended)
    assert waiting == []


def test_the_share_holds_at_every_prefix_of_the_queue() -> None:
    items = queue(many(40), seed=SNAP)
    for cut in range(5, 40, 5):
        assert sum(item.exploration for item in items[:cut]) == cut // 5


def test_the_last_waiting_item_is_never_called_exploration() -> None:
    items = queue(many(5), seed=SNAP)
    assert [item.subject_id for item in items] == ["s01", "s02", "s03", "s04", "s05"]
    assert not any(item.exploration for item in items)
    assert queue([], seed=SNAP) == []


def test_the_same_snapshot_gives_the_same_queue() -> None:
    subjects = many(40)
    first = queue(subjects, seed=SNAP)
    assert queue(list(reversed(subjects)), seed=SNAP) == first
    other = queue(subjects, seed="b" * 64)
    assert [item.subject_id for item in other] != [item.subject_id for item in first]
    assert sorted(item.subject_id for item in other) == sorted(item.subject_id for item in first)


def test_the_exploration_share_is_a_setting_with_limits() -> None:
    subjects = many(12)
    assert not any(item.exploration for item in queue(subjects, seed=SNAP, exploration_share=0))
    half = queue(subjects, seed=SNAP, exploration_share=0.5)
    assert [item.position for item in half if item.exploration] == [2, 4, 6, 8, 10]
    for share in (-0.1, 0.51, 1.0):
        with pytest.raises(ValueError, match="exploration share"):
            queue(subjects, seed=SNAP, exploration_share=share)


# --- rules read from the application map ---------------------------------------------------


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("User", "personal"),
        ("users", "personal"),
        ("phone_changes", "personal"),
        ("CustomerAddress", "personal"),
        ("addresses", "personal"),
        ("deliveries", "personal"),
        ("Order", "payment"),
        ("orders", "payment"),
        ("order_items", "payment"),
        ("OrderItem", "payment"),
        ("LoginSession", "sign-in"),
        ("api_tokens", "sign-in"),
        ("MenuItem", None),
        ("Branch", None),
        ("reorder_points", None),  # "order" is not a word of this name
    ],
)
def test_the_data_class_is_guessed_from_whole_words_of_the_name(
    resource: str, expected: str | None
) -> None:
    assert data_class(resource) == expected


def span(path: str, line: int) -> dict[str, object]:
    return {
        "snapshot_id": SNAP,
        "path": path,
        "start_line": line,
        "end_line": line,
        "content_sha256": "0" * 64,
    }


def small_map() -> ApplicationMap:
    """Four sites: a customer route, a public one, a Server Action behind a proxy, a login load."""

    def entry(name: str, kind: str, method: str | None, route: str | None, path: str) -> dict:
        return {
            "id": f"ep:{name}",
            "snapshot_id": SNAP,
            "kind": kind,
            "framework": "nextjs" if kind == "server_action" else "fastapi",
            "method": method,
            "route": route,
            "handler_symbol_id": f"sym:{name}",
            "span": span(path, 1),
        }

    def symbol(name: str, path: str) -> dict:
        return {
            "id": f"sym:{name}",
            "snapshot_id": SNAP,
            "name": name,
            "qualified_name": name,
            "kind": "function",
            "language": "python",
            "span": span(path, 1),
        }

    def site(name: str, owner: str, resource: str, operation: str, key: str, path: str) -> dict:
        return {
            "id": f"site:{name}",
            "snapshot_id": SNAP,
            "entry_point_id": f"ep:{owner}",
            "resource": resource,
            "operation": operation,
            "key_origin": key,
            "data_layer": "sqlalchemy",
            "span": span(path, 5),
        }

    def guard(name: str, mechanism: str, path: str) -> dict:
        return {
            "id": f"g:{name}",
            "snapshot_id": SNAP,
            "kind": "unknown",
            "canonical": "candidate",
            "mechanism": mechanism,
            "span": span(path, 9),
        }

    def owns(symbol_name: str, site_name: str) -> dict:
        return {
            "id": f"link:{symbol_name}-owns-{site_name}",
            "source": f"sym:{symbol_name}",
            "target": f"site:{site_name}",
            "kind": "access",
            "status": "resolved",
            "reason": "query in this function",
            "span": span("api/orders.py", 5),
        }

    def check(guard_name: str, site_name: str, optimistic: bool = False) -> dict:
        return {
            "id": f"link:{guard_name}-{site_name}",
            "source": f"g:{guard_name}",
            "target": f"site:{site_name}",
            "kind": "may_check",
            "status": "unresolved",
            "reason": "candidate",
            "span": span("api/security.py", 9),
            "optimistic": optimistic,
        }

    return ApplicationMap.model_validate(
        {
            "snapshot_id": SNAP,
            "entries": [
                entry(
                    "receipt", "http_route", "GET", "/orders/{order_id}/receipt", "api/orders.py"
                ),
                entry("menu", "http_route", "GET", "/branches/{branch_id}/menu", "api/menu.py"),
                entry("refund", "server_action", "POST", None, "web/actions.ts"),
            ],
            "symbols": [
                symbol("receipt", "api/orders.py"),
                symbol("menu", "api/menu.py"),
                symbol("refund", "web/actions.ts"),
                symbol("current_user", "api/security.py"),
            ],
            "guards": [
                {
                    **guard("signed-in", "dependency", "api/security.py"),
                    "via_symbol_id": "sym:current_user",
                },
                guard("proxy", "proxy_matcher", "web/proxy.ts"),
            ],
            "access_sites": [
                site("receipt", "receipt", "Order", "read", "path", "api/orders.py"),
                site("session", "receipt", "LoginSession", "read", "unknown", "api/security.py"),
                site("menu", "menu", "MenuItem", "read", "path", "api/menu.py"),
                site("refund", "refund", "orders", "update", "body", "web/dal.ts"),
            ],
            "unknown_targets": [],
            "links": [
                check("signed-in", "receipt"),
                check("signed-in", "session"),
                check("proxy", "refund", optimistic=True),
                owns("receipt", "receipt"),
                owns("current_user", "session"),
                owns("menu", "menu"),
                owns("refund", "refund"),
            ],
        }
    )


def reasons(subjects: list[Subject]) -> dict[str, list[tuple[Rule, str]]]:
    return {s.id: [(reason.rule, reason.text) for reason in s.reasons] for s in subjects}


def test_rules_are_read_from_the_map_as_sentences() -> None:
    assert reasons(subjects_from_map(small_map())) == {
        "site:receipt": [
            (Rule.SENSITIVE_DATA, "Order holds payment data, going by its name"),
            (Rule.REQUEST_IDENTIFIER, "Order is selected by an ID from the URL path"),
        ],
        "site:session": [
            (Rule.SENSITIVE_DATA, "LoginSession holds sign-in data, going by its name"),
        ],
        "site:menu": [
            (Rule.PUBLIC_EXPOSURE, "No sign-in check was found on the way to this query"),
            (Rule.REQUEST_IDENTIFIER, "MenuItem is selected by an ID from the URL path"),
        ],
        "site:refund": [
            (
                Rule.PUBLIC_EXPOSURE,
                "Only a proxy matcher stands before this query, and that is not a boundary",
            ),
            (Rule.SENSITIVE_DATA, "orders holds payment data, going by its name"),
            (Rule.WRITE_ACTION, "The query changes orders (update)"),
            (Rule.REQUEST_IDENTIFIER, "orders is selected by an ID from the request body"),
        ],
    }


def test_facts_from_later_stages_are_added_as_given() -> None:
    subjects = subjects_from_map(
        small_map(),
        deviations={"site:receipt": "7 of 8 Order sites check the owner; this one does not"},
        uncertain_guards={"site:menu": "The check on this path could not be classified"},
        changed_paths={"api/orders.py"},
    )
    found = reasons(subjects)
    assert found["site:receipt"][2:] == [
        (Rule.PEER_DEVIATION, "7 of 8 Order sites check the owner; this one does not"),
        (Rule.RECENT_CHANGE, "api/orders.py changed since the last review"),
    ]
    assert found["site:menu"][-1] == (
        Rule.UNCERTAIN_GUARD,
        "The check on this path could not be classified",
    )
    assert [item.subject_id for item in queue(subjects, seed=SNAP)] == [
        "site:refund",  # four rules, the first of them public exposure
        "site:receipt",  # four rules, the first of them sensitive data
        "site:menu",  # three rules
        "site:session",  # one rule
    ]


def test_a_write_entry_marks_its_read_queries_too() -> None:
    data = small_map().model_dump(mode="json")
    data["entries"][0]["method"] = "POST"
    data["entries"][0]["route"] = "/orders/{order_id}/cancel"
    found = reasons(subjects_from_map(ApplicationMap.model_validate(data)))
    wrote = (Rule.WRITE_ACTION, "POST /orders/{order_id}/cancel changes data")
    assert wrote in found["site:receipt"]
    # The sign-in dependency's own lookup on that route is not what the route writes.
    assert [rule for rule, _ in found["site:session"]] == [Rule.SENSITIVE_DATA]
    data["access_sites"][2]["entry_point_id"] = "ep:refund"
    found = reasons(subjects_from_map(ApplicationMap.model_validate(data)))
    assert (Rule.WRITE_ACTION, "This Server Action changes data") in found["site:menu"]


# --- the Tandir lab ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tandir(tmp_path_factory: pytest.TempPathFactory) -> ApplicationMap:
    cache = tmp_path_factory.mktemp("priority")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(TANDIR, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        return build_map(snapshot, store, index, cache, use_ty=False)
    finally:
        index.close()


def test_the_tandir_queue_puts_request_selected_orders_before_session_loads(
    tandir: ApplicationMap,
) -> None:
    subjects = subjects_from_map(tandir)
    items = queue(subjects, seed=tandir.snapshot_id)
    sites = {site.id: site for site in tandir.access_sites}
    entries = {entry.id: entry for entry in tandir.entries}
    assert sorted(item.subject_id for item in items) == sorted(sites)
    assert sum(item.exploration for item in items) == (len(items) - 1) // 5

    def place(route: str, resource: str) -> int:
        return next(
            item.recommended
            for item in items
            if sites[item.subject_id].resource == resource
            and entries[sites[item.subject_id].entry_point_id].route == route
        )

    receipt = place("/orders/{order_id}/receipt", "Order")
    session_loads = [
        item.recommended
        for item in items
        if sites[item.subject_id].resource in ("User", "LoginSession")
    ]
    assert session_loads and receipt < min(session_loads)
    # The Server Actions that update orders behind the proxy alone lead the queue.
    first = sites[items[0].subject_id]
    assert (first.resource, first.operation.value) == ("orders", "update")
    assert len(items[0].reasons) == 4
