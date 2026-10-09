"""Peer arithmetic and source-bound propagation; fixture labels are not model evidence."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.peers import PeerCheck, SiteChecks, consensus
from analysis.access import AccessMap, AccessPath, extract_accesses
from analysis.fastapi import extract_fastapi
from analysis.index import Index, index_path
from analysis.nextjs import NextJSMap
from analysis.python_resolution import resolve_python
from analysis.resolution import CallGraph, LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.code import (
    AccessSite,
    DataLayer,
    Guard,
    GuardKind,
    GuardMechanism,
    Operation,
    SourceSpan,
)
from backend.contracts.common import InputOrigin
from backend.settings import Settings

SNAPSHOT = "a" * 64
SPAN = SourceSpan(
    snapshot_id=SNAPSHOT, path="source.py", start_line=1, end_line=2, content_sha256="b" * 64
)


def vote_fixture(count: int, protected: int) -> tuple[AccessMap, list[SiteChecks]]:
    paths = []
    facts = []
    for number in range(count):
        identity = f"site:{number}"
        site = AccessSite(
            id=identity,
            snapshot_id=SNAPSHOT,
            entry_point_id=f"entry:{number}",
            resource="Order",
            operation=Operation.READ,
            key_origin=InputOrigin.PATH,
            data_layer=DataLayer.SQLALCHEMY,
            span=SPAN,
        )
        paths.append(
            AccessPath(
                site=site,
                owner_symbol_id="symbol:x",
                key_expression="id",
                possible_origins=[InputOrigin.PATH],
                via_symbol_ids=["symbol:x"],
                status=LinkStatus.INFERRED,
                reason="test",
            )
        )
        guards = []
        if number < protected:
            guards.append(
                Guard(
                    id=f"guard:{number}",
                    snapshot_id=SNAPSHOT,
                    kind=GuardKind.OWNER,
                    canonical="OWNER(Order.customer_id = principal.id)",
                    mechanism=GuardMechanism.COMPARISON,
                    span=SPAN,
                    confirmed=True,
                )
            )
        facts.append(SiteChecks(site_id=identity, guards=guards))
    return AccessMap(snapshot_id=SNAPSHOT, accesses=paths), facts


@pytest.mark.parametrize(
    "count,protected,flagged",
    [(5, 3, True), (6, 3, False), (4, 2, False), (4, 3, True), (3, 3, False)],
)
def test_peer_threshold_boundaries(count: int, protected: int, flagged: bool) -> None:
    access, facts = vote_fixture(count, protected)
    groups = consensus(access, facts, Settings())
    assert bool(groups[0].deviations) is flagged
    if flagged:
        assert all(
            d.peers_total == count - 1 and d.peers_applying == protected
            for d in groups[0].deviations
        )


def test_unknowns_remain_in_denominator_and_duplicate_guards_vote_once() -> None:
    access, facts = vote_fixture(6, 3)
    facts[0].guards.append(facts[0].guards[0])
    facts[-1].issues.append("unresolved helper")
    group = consensus(access, facts, Settings())[0]
    assert not group.deviations
    assert len(group.site_ids) == 6 and len(group.columns[0].applied_site_ids) == 3


def test_cited_exclusion_changes_only_voters_and_keeps_site_visible() -> None:
    access, facts = vote_fixture(6, 3)
    facts[-1] = facts[-1].model_copy(update={"exclusion": "admin-only", "evidence": [SPAN]})
    group = consensus(access, facts, Settings())[0]
    assert len(group.site_ids) == 6 and len(group.excluded) == 1
    assert {d.site_id for d in group.deviations} == {"site:3", "site:4"}
    assert all(d.peers_total == 4 for d in group.deviations)
    facts[-1] = facts[-1].model_copy(update={"evidence": []})
    with pytest.raises(ValueError, match="evidence"):
        consensus(access, facts, Settings())


def test_invalid_or_optimistic_guards_and_missing_records_refused() -> None:
    access, facts = vote_fixture(4, 3)
    with pytest.raises(ValueError, match="exactly one"):
        consensus(access, facts[:-1], Settings())
    for update in (
        {"confirmed": False},
        {"snapshot_id": "c" * 64},
        {"mechanism": GuardMechanism.PROXY_MATCHER},
    ):
        invalid = facts[0].model_copy(
            update={"guards": [facts[0].guards[0].model_copy(update=update)]}
        )
        with pytest.raises(ValueError, match="confirmed"):
            consensus(access, [invalid, *facts[1:]], Settings())


def test_peer_thresholds_are_configurable_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_PEER_MIN_PEERS", "4")
    monkeypatch.setenv("PLUMB_PEER_MIN_SHARE", "0.9")
    assert Settings().peer_min_peers == 4 and Settings().peer_min_share == 0.9
    for key, value in [
        ("PLUMB_PEER_MIN_PEERS", "0"),
        ("PLUMB_PEER_MIN_SHARE", "0"),
        ("PLUMB_PEER_MIN_SHARE", "1.1"),
    ]:
        monkeypatch.setenv(key, value)
        with pytest.raises(ValidationError):
            Settings()
        monkeypatch.delenv(key)


class PredicateStub:
    """Test semantic answers only. Real-model acceptance uses the separately recorded runner."""

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        fields = request.schema["properties"]["guards"]["items"]["properties"]
        kinds = fields["kind"]["enum"]
        kind = (
            "authenticated"
            if "authenticated" in kinds
            else "role"
            if "role" in kinds
            else "tenant"
            if any("branch_id" in str(s) for s in fields["subject"].get("enum", []))
            else "owner"
        )
        subject = next(
            (s for s in fields["subject"].get("enum", []) if s and s.startswith("user.")), None
        )
        object = next((s for s in fields["object"].get("enum", []) if s and s != subject), None)
        if kind in ("authenticated", "role"):
            subject = object = None
        line_ids = list(dict.fromkeys(re.findall(r"\bL\d+\b", request.user)))
        return JsonAnswer(
            {
                "guards": [
                    {"kind": kind, "subject": subject, "object": object, "line_ids": line_ids}
                ]
            },
            "",
            1,
            1,
            0,
        )


def python_peers(tmp_path: Path, source: str) -> tuple[AccessMap, list[SiteChecks]]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text(source, encoding="utf-8")
    cache = tmp_path / "cache"
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        fastapi = extract_fastapi(snapshot, store, index)
        graph = resolve_python(snapshot, store, index, cache, use_ty=False)
        nextjs = NextJSMap(
            snapshot_id=snapshot.id,
            entries=[],
            components=[],
            client_props=[],
            data_modules=[],
            proxies=[],
            issues=[],
        )
        ts = CallGraph(
            snapshot_id=snapshot.id, language="typescript", resolver_version="unused", edges=[]
        )
        access = extract_accesses(
            snapshot,
            store,
            index,
            cache,
            fastapi=fastapi,
            nextjs=nextjs,
            python_graph=graph,
            typescript_graph=ts,
        )
        classifier = Classifier(
            snapshot,
            store,
            PredicateStub(),
            SummaryCache(cache / "guards.sqlite"),
            identity="fixture",
        )
        result = PeerCheck(classifier, index, graph, Settings()).build(access)
        return access, result.checks
    finally:
        index.close()


BASE = """from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
class Order: pass
class User: pass
app = FastAPI()
def get_user(db: Session = None):
    user = db.get(User, 1)
    if user is None:
        raise HTTPException(status_code=401)
    return user
def ensure_owner(order, user):
    if order.customer_id != user.id:
        raise HTTPException(status_code=404)
def require_role(*roles):
    def check(user = Depends(get_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403)
        return user
    return check
admin = require_role("admin")
@app.get("/orders/{id}")
def route(id: int, user = Depends(get_user), db: Session = None):
    order = db.get(Order, id)
    {check}
    return render(order)
"""


@pytest.mark.parametrize(
    "check,protected",
    [
        ("ensure_owner(order, user)", True),
        ("ensure_owner(user=user, order=order)", True),
        ("ensure_owner(order, user=user)", True),
        ("ensure_owner(order=other, user=user)", False),
        ("ensure_owner(order=order, user=other)", False),
        ("ensure_owner(order, order=other, user=user)", False),
        ("if id > 0:\n        ensure_owner(order, user)", False),
        ("ensure_owner(other, user)", False),
        ("ensure_owner(order, other)", False),
        ("render(order)\n    ensure_owner(order, user)", False),
        ("try:\n        ensure_owner(order, user)\n    except Exception:\n        pass", False),
        ("order = other\n    ensure_owner(order, user)", False),
    ],
)
def test_helper_must_check_this_record_unconditionally_before_exposure(
    tmp_path: Path, check: str, protected: bool
) -> None:
    _, facts = python_peers(tmp_path, BASE.replace("{check}", check))
    orders = [f for f in facts if any(g.kind is GuardKind.OWNER for g in f.guards)]
    assert bool(orders) is protected


@pytest.mark.parametrize(
    "binding,excluded",
    [('"admin"', True), ('"admin", "branch_manager"', False), ("unknown", False)],
)
def test_only_actual_single_admin_binding_can_exempt(
    tmp_path: Path, binding: str, excluded: bool
) -> None:
    source = (
        BASE.replace('require_role("admin")', f"require_role({binding})")
        .replace("user = Depends(get_user), db:", "user = Depends(admin), db:")
        .replace("{check}", "pass")
    )
    _, facts = python_peers(tmp_path, source)
    assert any(f.exclusion is not None for f in facts) is excluded


@pytest.mark.parametrize(
    "setup,protected",
    [("", True), ("order = other\n    ", False), ("out = render(order)\n    ", False)],
)
def test_local_check_cannot_use_a_rebound_or_exposed_record(
    tmp_path: Path, setup: str, protected: bool
) -> None:
    check = setup + "if order.customer_id != user.id:\n        raise HTTPException(status_code=404)"
    _, facts = python_peers(tmp_path, BASE.replace("{check}", check))
    assert any(g.kind is GuardKind.OWNER for f in facts for g in f.guards) is protected


@pytest.mark.parametrize(
    "filter,scoped",
    [
        ("Order.branch_id == branch_id", True),
        ("or_(Order.branch_id == branch_id, Order.public == True)", False),
    ],
)
def test_tenant_selector_requires_unconditional_executed_equality(
    tmp_path: Path, filter: str, scoped: bool
) -> None:
    source = BASE[: BASE.index("@app.get")].replace(
        'admin = require_role("admin")', 'manager = require_role("branch_manager")'
    )
    source += f"""@app.get("/branches/{{branch_id}}/orders")
def route(branch_id: int, user = Depends(manager), db: Session = None):
    if user.branch_id != branch_id:
        raise HTTPException(status_code=403)
    orders = db.scalars(select(Order).where({filter}))
    return render(orders)
"""
    _, facts = python_peers(tmp_path, source)
    assert any(f.exclusion for f in facts) is scoped


def test_query_must_scope_the_loaded_resource_not_an_unrelated_table(tmp_path: Path) -> None:
    source = BASE[: BASE.index("@app.get")].replace(
        "class Order: pass", "class Order: pass\nclass Other: pass"
    )
    source += """@app.get("/orders/{id}")
def route(id: int, user = Depends(get_user), db: Session = None):
    orders = db.scalars(select(Order).where(Order.id == id, Other.customer_id == user.id))
    return render(orders)
"""
    _, facts = python_peers(tmp_path, source)
    assert not any(g.kind is GuardKind.OWNER for f in facts for g in f.guards)


@pytest.mark.parametrize(
    "predicate,guarded",
    [
        ("id=id, customer_id=user.id", True),
        ("id=id, customer_id=other.id", False),
        ("id=id, **claimed", False),
    ],
)
def test_executed_keyed_filter_binds_the_actual_principal(
    tmp_path: Path, predicate: str, guarded: bool
) -> None:
    source = BASE[: BASE.index("@app.get")]
    source += f"""@app.get("/orders/{{id}}")
def route(id: int, user = Depends(get_user), db: Session = None):
    order = db.scalar(select(Order).filter_by({predicate}))
    return order
"""
    access, facts = python_peers(tmp_path, source)
    orders = [p for p in access.accesses if p.site.resource == "Order"]
    assert len(orders) == 1 and orders[0].site.key_origin.value == "path"
    assert any(g.kind is GuardKind.OWNER for f in facts for g in f.guards) is guarded


@pytest.mark.parametrize(
    "caller,guarded",
    [
        ("service(id=id, who=user, db=db)", True),
        ("service(id=id, who=other, db=db)", False),
        ("service(id=id, who=user, **extras)", False),
    ],
)
def test_keyword_principal_binding_follows_the_exact_caller(
    tmp_path: Path, caller: str, guarded: bool
) -> None:
    source = BASE[: BASE.index("@app.get")]
    source += f"""def service(id: int, *, who, db: Session):
    order = db.get(Order, id)
    ensure_owner(order=order, user=who)
    return order
@app.get("/orders/{{id}}")
def route(id: int, user = Depends(get_user), db: Session = None):
    return {caller}
"""
    _, facts = python_peers(tmp_path, source)
    assert any(g.kind is GuardKind.OWNER for f in facts for g in f.guards) is guarded
