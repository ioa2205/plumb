"""Cited impact rules use actual source; fixture judgments are not model-quality evidence."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent.challenge import ChallengeResult
from agent.challenge import finding as access_finding
from agent.families import SinkInvestigator, finding
from agent.guards import Classifier, SummaryCache
from agent.llm import Spend
from agent.peers import PeerCheck, consensus
from agent.severity import authorization, sink
from agent.tests.test_families import Model
from agent.tests.test_peers import PredicateStub
from analysis.fastapi import extract_fastapi
from analysis.index import Index, index_path
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.code import GuardKind
from backend.contracts.investigation import Budget, Conclusion, Severity
from backend.review import Review
from backend.settings import Settings

SOURCE = b"""from fastapi import FastAPI
import subprocess
app = FastAPI()
@app.get("/operation")
def handle(value: str):
    subprocess.run(f"print {value}", shell=True)
"""


@pytest.mark.parametrize(
    "change,expected",
    [
        ("none", Severity.HIGH),
        ("not_exposed", Severity.UNKNOWN),
        ("rejected", Severity.UNKNOWN),
        ("inconclusive", Severity.UNKNOWN),
        ("wrong_snapshot", Severity.UNKNOWN),
        ("bad_citation", Severity.UNKNOWN),
        ("wrong_signal", Severity.UNKNOWN),
        ("other_signal", Severity.UNKNOWN),
        ("missing_citation", Severity.UNKNOWN),
        ("unresolved", Severity.UNKNOWN),
        ("candidate", Severity.UNKNOWN),
    ],
)
def test_shell_impact_requires_supported_source_and_http_exposure(
    tmp_path: Path,
    change: str,
    expected: Severity,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "operation.py").write_bytes(
        SOURCE
        + SOURCE[SOURCE.index(b"@app.get") :]
        .replace(b"handle", b"other")
        .replace(b"/operation", b"/other")
    )
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(tmp_path / "cache", snapshot.id))
    try:
        investigator = SinkInvestigator(snapshot, store, index)
        routes = extract_fastapi(snapshot, store, index)
        signal = next(iter(investigator.facts))
        result = investigator.investigate(signal, Model(["none_found"] * 3), Spend(Budget()))
        case = finding(result, run_id="run:severity", display_id="F-01")
        assert case.conclusion.value == "supported"
        if change == "not_exposed":
            routes = routes.model_copy(update={"routes": []})
        elif change in ("rejected", "inconclusive", "candidate"):
            case = case.model_copy(update={"conclusion": Conclusion(change)})
        elif change == "wrong_snapshot":
            routes = routes.model_copy(update={"snapshot_id": "0" * 64})
        elif change == "bad_citation":
            result = result.model_copy(
                update={
                    "evidence": [
                        result.evidence[0].model_copy(
                            update={"content_sha256": "0" * 64},
                        )
                    ]
                }
            )
        elif change == "wrong_signal":
            result = result.model_copy(update={"signal_id": "missing"})
        elif change == "other_signal":
            result = result.model_copy(update={"signal_id": list(investigator.facts)[1]})
        elif change == "missing_citation":
            result = result.model_copy(update={"evidence": []})
        elif change == "unresolved":
            from analysis.resolution import LinkStatus

            routes = routes.model_copy(
                update={
                    "routes": [
                        r.model_copy(update={"mount_status": LinkStatus.UNRESOLVED})
                        for r in routes.routes
                    ]
                }
            )
        rated = sink(case, result, investigator, routes)
        assert rated.severity is expected
        assert rated.conclusion is case.conclusion
        assert rated.runtime_verification is case.runtime_verification
        if expected is Severity.HIGH:
            assert (
                "process" in rated.severity_rationale and "Evidence: E" in rated.severity_rationale
            )
            assert "Administrator privileges" in rated.severity_rationale
            assert not investigator.validator.finding(rated)
    finally:
        index.close()


ACCESS_SOURCE = """from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
class Order: pass
class User: pass
app = FastAPI()
def get_user(db: Session = None):
    user = db.get(User, 1)
    if user is None:
        raise HTTPException(status_code=401)
    return user
"""
for number in range(3):
    ACCESS_SOURCE += f"""
@app.get("/peer{number}/{{id}}")
def peer{number}(id: int, user = Depends(get_user), db: Session = None):
    order = db.get(Order, id)
    if order.customer_id != user.id:
        raise HTTPException(status_code=404)
    return order
"""
ACCESS_SOURCE += """
@app.get("/read/{id}")
def read(id: int, db: Session = None):
    return db.get(Order, id)
@app.post("/update/{id}")
def update(id: int, db: Session = None):
    return db.execute("UPDATE Order SET total=0 WHERE id=:id", {"id": id})
@app.delete("/delete/{id}")
def delete(id: int, db: Session = None):
    return db.execute("DELETE FROM Order WHERE id=:id", {"id": id})
"""


@pytest.fixture
def scoped(tmp_path: Path) -> Iterator[tuple[Review, PeerCheck]]:
    root = tmp_path / "project"
    root.mkdir()
    (root / "access.py").write_text(ACCESS_SOURCE, encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", peer_min_share=0.5)
    snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
    review = Review(settings, snapshot.id)
    classifier = Classifier(
        snapshot,
        review.store,
        PredicateStub(),
        SummaryCache(tmp_path / "guards.sqlite"),
        identity="fixture",
    )
    checker = PeerCheck(classifier, review.index, review.python, settings)
    try:
        yield review, checker
    finally:
        review.close()


@pytest.mark.parametrize(
    "operation,expected",
    [("read", Severity.MEDIUM), ("update", Severity.HIGH), ("delete", Severity.HIGH)],
)
def test_scoped_operation_and_exposure_are_cited(
    scoped: tuple[Review, PeerCheck],
    operation: str,
    expected: Severity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review, checker = scoped
    peers = checker.build(review.access)
    path = next(
        p
        for p in review.access.accesses
        if review.routes[p.site.entry_point_id].entry.route == f"/{operation}/{{id}}"
    )
    group = next(g for g in peers.groups if path.site.id in g.site_ids)
    result = ChallengeResult(
        snapshot_id=review.snapshot.id,
        site_id=path.site.id,
        resource=path.site.resource,
        missing=GuardKind.OWNER,
        conclusion=Conclusion.SUPPORTED,
        rationale="Fixture judgment for severity software acceptance",
        searches=[],
        samples=[],
        guards=[],
        evidence=[path.site.span],
        issues=[],
        peer_group_id=group.id,
    )
    case = access_finding(result, run_id="run:severity", display_id="F-01")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Severity requested model inference")

    monkeypatch.setattr(checker.classifier.model, "ask", forbidden)
    rated = authorization(case, result, review.access, peers, review.routes, checker)
    assert rated.severity is expected
    assert (
        rated.conclusion is case.conclusion
        and rated.runtime_verification is case.runtime_verification
    )
    assert rated.strength is case.strength
    assert "Evidence: E" in rated.severity_rationale
    assert path.site.span in [e.span for e in rated.exhibits]
    assert not checker.classifier.validator.finding(rated)


@pytest.mark.parametrize(
    "change",
    [
        "wrong_site",
        "wrong_resource",
        "group_snapshot",
        "duplicate_votes",
        "mixed_kinds",
        "subject_votes",
        "bad_citation",
        "excluded_subject",
        "wrong_entry",
        "read_post",
        "unresolved",
        "missing_checks",
        "candidate",
        "rejected",
        "inconclusive",
    ],
)
def test_scope_rating_refuses_unbound_or_insufficient_facts(
    scoped: tuple[Review, PeerCheck], change: str
) -> None:
    from analysis.resolution import LinkStatus

    review, checker = scoped
    peers = checker.build(review.access)
    path = next(
        p
        for p in review.access.accesses
        if review.routes[p.site.entry_point_id].entry.route == "/read/{id}"
    )
    group = next(g for g in peers.groups if path.site.id in g.site_ids)
    result = ChallengeResult(
        snapshot_id=review.snapshot.id,
        site_id=path.site.id,
        resource=path.site.resource,
        missing=GuardKind.OWNER,
        conclusion=Conclusion.SUPPORTED,
        rationale="Fixture judgment",
        searches=[],
        samples=[],
        guards=[],
        evidence=[path.site.span],
        issues=[],
        peer_group_id=group.id,
    )
    case = access_finding(result, run_id="run:severity", display_id="F-01")
    routes = dict(review.routes)
    if change == "wrong_site":
        protected = [c for c in peers.checks if any(g.kind is GuardKind.OWNER for g in c.guards)]
        first, second = protected[:2]
        peers = peers.model_copy(
            update={
                "checks": [
                    c.model_copy(update={"guards": second.guards})
                    if c.site_id == first.site_id
                    else c
                    for c in peers.checks
                ]
            }
        )
    elif change in ("wrong_resource", "group_snapshot"):
        altered = group.model_copy(
            update={"resource": "Unrelated"}
            if change == "wrong_resource"
            else {"snapshot_id": "0" * 64}
        )
        peers = peers.model_copy(
            update={"groups": [altered if g.id == group.id else g for g in peers.groups]}
        )
    elif change == "duplicate_votes":
        peers = peers.model_copy(update={"checks": [*peers.checks, peers.checks[0]]})
    elif change in ("mixed_kinds", "subject_votes", "bad_citation", "excluded_subject"):
        checks = []
        count = 0
        for c in peers.checks:
            owners = [g for g in c.guards if g.kind is GuardKind.OWNER]
            if owners and change == "mixed_kinds":
                count += 1
                if count <= 2:
                    c = c.model_copy(
                        update={
                            "guards": [
                                g.model_copy(update={"kind": GuardKind.TENANT})
                                if g.kind is GuardKind.OWNER
                                else g
                                for g in c.guards
                            ]
                        }
                    )
            elif owners and change == "bad_citation":
                c = c.model_copy(
                    update={
                        "guards": [
                            g.model_copy(
                                update={
                                    "span": g.span.model_copy(update={"content_sha256": "0" * 64})
                                }
                            )
                            for g in c.guards
                        ]
                    }
                )
            if c.site_id == path.site.id:
                if change == "subject_votes":
                    c = c.model_copy(
                        update={
                            "guards": next(
                                c.guards
                                for c in peers.checks
                                if any(g.kind is GuardKind.OWNER for g in c.guards)
                            )
                        }
                    )
                elif change == "excluded_subject":
                    c = c.model_copy(
                        update={
                            "exclusion": "Fixture excluded policy",
                            "evidence": [path.site.span],
                        }
                    )
            checks.append(c)
        peers = peers.model_copy(
            update={"checks": checks, "groups": consensus(review.access, checks, checker.settings)}
        )
    elif change == "missing_checks":
        peers = peers.model_copy(update={"checks": []})
    elif change in ("candidate", "rejected", "inconclusive"):
        case = case.model_copy(update={"conclusion": Conclusion(change)})
    else:
        route = routes[path.site.entry_point_id]
        if change == "wrong_entry":
            route = route.model_copy(
                update={"entry": route.entry.model_copy(update={"id": "entry:other"})}
            )
        elif change == "read_post":
            route = route.model_copy(
                update={"entry": route.entry.model_copy(update={"method": "POST"})}
            )
        elif change == "unresolved":
            route = route.model_copy(update={"mount_status": LinkStatus.UNRESOLVED})
        routes[path.site.entry_point_id] = route
    rated = authorization(case, result, review.access, peers, routes, checker)
    assert rated.severity is Severity.UNKNOWN
    assert (
        rated.conclusion is case.conclusion
        and rated.runtime_verification is case.runtime_verification
    )
