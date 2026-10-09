import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.challenge import CHECKLISTS, AuthorizationChallenge, finding
from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.peers import PeerCheck
from agent.tests.test_peers import BASE, PredicateStub
from analysis.access import AccessMap, extract_accesses
from analysis.fastapi import extract_fastapi
from analysis.index import Index, index_path
from analysis.python_resolution import resolve_python
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.code import GuardKind, PolicyAssertion, PolicyStatus
from backend.contracts.common import Family
from backend.contracts.investigation import Budget, Conclusion
from backend.contracts.policies import BoundPolicy, FrozenPolicies
from backend.settings import Settings


@pytest.mark.parametrize(
    "actual,required,expected",
    [
        ("admin", "admin", Conclusion.REJECTED),
        ("branch_manager", "admin", Conclusion.SUPPORTED),
        ("admin", "branch_manager", Conclusion.SUPPORTED),
        ("admin|branch_manager", "admin", Conclusion.SUPPORTED),
    ],
)
def test_fastapi_qualified_role_uses_exact_guard_and_admin_exception(
    tmp_path: Path, actual: str, required: str, expected: Conclusion
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    arguments = ", ".join(json.dumps(role) for role in actual.split("|"))
    source = (
        BASE.replace('require_role("admin")', f"require_role({arguments})")
        .replace("user = Depends(get_user), db:", "user = Depends(admin), db:")
        .replace("{check}", "pass")
    )
    (project / "app.py").write_text(source, encoding="utf-8")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, index_path(tmp_path, snapshot.id))

    class Model(PredicateStub):
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            self.requests.append(request)
            if request.name == "intentional_exception":
                return JsonAnswer({"reason": "none_found", "line_ids": []}, "", 1, 1, 0)
            return super().ask(request, spend)

    try:
        graph = resolve_python(snapshot, store, index, tmp_path, use_ty=False)
        access = extract_accesses(
            snapshot,
            store,
            index,
            tmp_path,
            fastapi=extract_fastapi(snapshot, store, index),
            python_graph=graph,
        )
        path = next(p for p in access.accesses if p.site.resource == "Order")
        access = AccessMap(snapshot_id=snapshot.id, accesses=[path])
        model = Model()
        peers = PeerCheck(
            Classifier(
                snapshot, store, model, SummaryCache(tmp_path / "guards.sqlite"), identity="fixture"
            ),
            index,
            graph,
            Settings(),
        )
        policy = BoundPolicy(
            assertion=PolicyAssertion(
                id="policy:role",
                statement="Explicit fixture role requirement",
                resource="Order",
                kind=GuardKind.ROLE,
                canonical=f"ROLE({required})",
                status=PolicyStatus.DECLARED,
                author="Fixture reviewer",
                created_at=datetime.now(UTC),
            ),
            snapshot_id=snapshot.id,
            source_run_id="run:fixture",
            sites=[path.site],
            provenance="Fixture declaration, not guard proof",
            required_role=required,
        )
        result = AuthorizationChallenge(
            peers,
            access,
            model,
            policies=FrozenPolicies(snapshot_id=snapshot.id, policies=[policy]),
        ).investigate(path.site.id, Spend(Budget()), missing=GuardKind.ROLE)
        assert result.conclusion is expected, result.model_dump()
        assert len(result.samples) == 3
        assert any("Qualified required roles" in r.user for r in model.requests)
    finally:
        index.close()


class Judge:
    def __init__(self, reasons: list[str], *, cite: str = "predicate") -> None:
        self.reasons, self.cite = reasons, cite
        self.requests: list[ModelRequest] = []

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        reason = self.reasons[len(self.requests) % len(self.reasons)]
        self.requests.append(request)
        lines = re.findall(r"^(L\d+) \| (.*)$", request.user, re.M)
        if self.cite == "predicate":
            ids = [identity for identity, text in lines if "Order.customer_id == user.id" in text]
        elif self.cite == "name":
            ids = [
                identity
                for identity, text in lines
                if "load_order_scoped(db" in text and "def " not in text
            ]
        elif self.cite == "authn":
            ids = [identity for identity, text in lines if "status_code=401" in text]
        else:
            ids = ["L999"]
        if request.name == "guard_summary":
            return JsonAnswer(
                {
                    "guards": [
                        {
                            "kind": "owner" if reason == "scoped_elsewhere" else "unknown",
                            "subject": "user.id",
                            "object": "Order.customer_id",
                            "line_ids": ids[:4],
                        }
                    ]
                },
                "",
                1,
                1,
                0,
            )
        return JsonAnswer(
            {"reason": reason, "line_ids": ids[:4] if reason != "none_found" else []}, "", 1, 1, 0
        )


@pytest.fixture(scope="module")
def context(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[PeerCheck, AccessMap, dict[str, str]]]:
    cache = tmp_path_factory.mktemp("challenge")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(Path(__file__).resolve().parents[2] / "labs" / "tandir", store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    fastapi = extract_fastapi(snapshot, store, index)
    graph = resolve_python(snapshot, store, index, cache, use_ty=False)
    access = extract_accesses(snapshot, store, index, cache, fastapi=fastapi, python_graph=graph)
    access = AccessMap(
        snapshot_id=snapshot.id, accesses=[a for a in access.accesses if a.site.resource == "Order"]
    )
    peers = PeerCheck(
        Classifier(
            snapshot,
            store,
            PredicateStub(),
            SummaryCache(cache / "guards.sqlite"),
            identity="unit fixture labels",
        ),
        index,
        graph,
        Settings(),
    )
    entries = {r.entry.id: r.entry.route for r in fastapi.routes}
    names = {entries[a.site.entry_point_id] or "": a.site.id for a in access.accesses}
    try:
        yield peers, access, names
    finally:
        index.close()


def test_invoice_rejected_with_scoped_helper_evidence(context: tuple) -> None:
    peers, access, names = context
    judge = Judge(["scoped_elsewhere"])
    challenge = AuthorizationChallenge(peers, access, judge)
    result = challenge.investigate(names["/orders/{order_id}/invoice"], Spend(Budget()))
    assert result.conclusion is Conclusion.REJECTED
    assert len(judge.requests) == 3
    assert [r.seed for r in judge.requests] == [42, 43, 44]
    assert len({tuple(s.evidence_order) for s in result.samples}) > 1
    report = finding(result, run_id="run:test", display_id="F-08")
    assert not peers.classifier.validator.finding(report, guards=result.guards)
    assert any(check.found and "services/orders.py" in check.searched for check in report.checks)
    assert report.runtime_verification.value == "not_attempted"


def test_receipt_supported_with_bounded_negative_evidence(context: tuple) -> None:
    peers, access, names = context
    result = AuthorizationChallenge(peers, access, Judge(["none_found"])).investigate(
        names["/orders/{order_id}/receipt"], Spend(Budget())
    )
    assert result.conclusion is Conclusion.SUPPORTED
    assert len(result.searches) == 5
    assert result.searches[0].status == "not_found"
    assert result.searches[-1].status == "unsupported"
    assert all(s.searched for s in result.searches)


@pytest.mark.parametrize(
    "reasons,cite",
    [
        (["scoped_elsewhere", "none_found", "scoped_elsewhere"], "predicate"),
        (["scoped_elsewhere"], "name"),
        (["scoped_elsewhere"], "authn"),
        (["scoped_elsewhere"], "invalid"),
        (["none_found"], "predicate"),
        (["public_resource"], "predicate"),
        (["admin_only"], "predicate"),
    ],
)
def test_unproven_or_disagreeing_exceptions_are_inconclusive(
    context: tuple, reasons: list[str], cite: str
) -> None:
    peers, access, names = context
    result = AuthorizationChallenge(peers, access, Judge(reasons, cite=cite)).investigate(
        names["/orders/{order_id}/invoice"], Spend(Budget())
    )
    assert result.conclusion is Conclusion.INCONCLUSIVE
    assert len(result.samples) == 3


def test_each_family_has_a_fixed_acquittal_checklist() -> None:
    assert set(CHECKLISTS) == set(Family)
    assert all(len(items) >= 3 and len(set(items)) == len(items) for items in CHECKLISTS.values())


@pytest.mark.parametrize("reason", ["scoped_elsewhere", "admin_only", "public_resource"])
def test_receipt_cannot_be_acquitted_by_sign_in_alone(context: tuple, reason: str) -> None:
    peers, access, names = context
    result = AuthorizationChallenge(peers, access, Judge([reason], cite="authn")).investigate(
        names["/orders/{order_id}/receipt"], Spend(Budget())
    )
    assert result.conclusion is Conclusion.INCONCLUSIVE
    assert all(s.violations for s in result.samples)


def test_recorded_real_judgments_revalidate_after_final_hardening(context: tuple) -> None:
    peers, access, names = context
    record = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/results/2026-10-05-142716-m3.6-challenge.json"
        ).read_text(encoding="utf-8")
    )
    answers = iter(record["requests"])

    class Replay:
        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            row = next(answers)
            assert request.name == row["request"]["response_format"]["json_schema"]["name"]
            return JsonAnswer(**row["answer"])

    challenge = AuthorizationChallenge(peers, access, Replay())
    for case in record["cases"]:
        result = challenge.investigate(names[case["route"]], Spend(Budget()))
        assert result.conclusion.value == case["expected"]
        assert all(not s.violations for s in result.samples)
