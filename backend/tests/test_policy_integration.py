"""Exact policy/software integration. Fixture judgments are not fresh model evidence."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.challenge import AuthorizationChallenge, ChallengeResult, finding
from agent.guards import Classifier, SummaryCache
from agent.llm import Spend
from agent.peers import PeerCheck
from analysis.access import AccessMap
from backend import cli
from backend.app import create_app
from backend.contracts.code import GuardKind, PolicyStatus
from backend.contracts.investigation import Budget, Conclusion
from backend.contracts.policies import BoundPolicy, FrozenPolicies, PolicyInput
from backend.contracts.runs import ReviewRun, RunLifecycle, RunType
from backend.map_store import MapStore
from backend.policy_store import PolicyConflict, PolicyStore
from backend.profiles import Profile
from backend.project_reads import ProjectReads
from backend.reports import ReportBundle, render
from backend.review import Review, write_json
from backend.run_store import RunStore
from backend.settings import Settings
from backend.tests.support import ORIGIN, PORT, signed_in, visitor
from backend.tests.test_peer_api import saved_peers as saved_peers
from backend.tests.test_peer_records import recorded as recorded
from backend.tests.test_project_view import project as project
from backend.tests.test_review import ROUTES, Model
from backend.tests.test_review import review as review


def request(review: Review, *, guard: GuardKind = GuardKind.OWNER) -> PolicyInput:
    site = next(
        p.site
        for p in review.access.accesses
        if p.site.resource == "Order"
        and review.routes.get(p.site.entry_point_id) is not None
        and review.routes[p.site.entry_point_id].entry.route == ROUTES[0]
    )
    return PolicyInput(
        snapshot_id=review.snapshot.id,
        site_ids=[site.id],
        statement="This exact receipt access requires its owner",
        author="Reviewer",
        required_guard=guard,
    )


def test_qualified_role_survives_declaration_and_freeze(
    project: tuple[Settings, ReportBundle, Path],
    review: Review,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, bundle, _ = project
    reads = ProjectReads(settings)
    declaration = request(review, guard=GuardKind.ROLE).model_copy(
        update={"required_role": "admin"}
    )
    bound = reads.declare(bundle.run.id, declaration)
    assert bound.required_role == "admin" and bound.assertion.canonical == "ROLE(admin)"
    assert (
        bound
        in PolicyStore(settings.cache_dir / "policies.sqlite")
        .freeze(bundle.snapshot, review.map.access_sites)
        .policies
    )
    body = declaration.model_dump(mode="json")
    client = signed_in(create_app(settings, port=PORT))
    response = client.post(
        f"/api/runs/{bundle.run.id}/project/rules", json=body, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 201 and response.json()["required_role"] == "admin"
    monkeypatch.setenv("PLUMB_DATA_DIR", str(settings.data_dir))
    assert (
        cli.main(
            [
                "policy",
                bundle.run.id,
                "--snapshot",
                review.snapshot.id,
                "--site",
                body["site_ids"][0],
                "--guard",
                "role",
                "--required-role",
                "admin",
                "--statement",
                "Admin required",
                "--author",
                "CLI reviewer",
            ]
        )
        == 0
    )


def test_protected_declaration_shared_cli_and_exact_source_negatives(
    project: tuple[Settings, ReportBundle, Path],
    review: Review,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, bundle, directory = project
    reads = ProjectReads(settings)
    body = request(review).model_dump(mode="json")
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    app = create_app(settings, port=PORT)
    path = f"/api/runs/{bundle.run.id}/project/rules"
    client = signed_in(app)
    assert visitor(app).post(path, json=body, headers={"Origin": ORIGIN}).status_code == 401
    assert client.post(path, json=body).status_code == 403
    assert (
        client.post(path, json=body, headers={"Origin": "http://foreign.invalid"}).status_code
        == 403
    )
    client.headers["Origin"] = ORIGIN
    assert client.post(path, json={**body, "snapshot_id": "a" * 64}).status_code == 409
    assert client.post(path, json={**body, "site_ids": ["access:unrelated"]}).status_code == 409
    assert client.post(path, json={**body, "author": ""}).status_code == 422
    response = client.post(path, json=body)
    assert response.status_code == 201
    declared = BoundPolicy.model_validate(response.json())
    assert declared.assertion.status is PolicyStatus.DECLARED
    assert declared.assertion.author == "Reviewer" and not declared.assertion.evidence
    assert declared in reads.page(bundle.run.id).bound_policies
    monkeypatch.setenv("PLUMB_DATA_DIR", str(settings.data_dir))
    assert (
        cli.main(
            [
                "policy",
                bundle.run.id,
                "--snapshot",
                review.snapshot.id,
                "--site",
                body["site_ids"][0],
                "--guard",
                "owner",
                "--statement",
                "Owner required",
                "--author",
                "CLI reviewer",
            ]
        )
        == 0
    )
    assert len(reads.page(bundle.run.id).bound_policies) == 2
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    sites = review.map.access_sites
    wrong = sites[0].model_copy(update={"resource": "Unrelated"})
    store = PolicyStore(settings.cache_dir / "policies.sqlite")
    exact = store.freeze(bundle.snapshot, sites)
    assert not exact.for_site(wrong)
    changed = bundle.snapshot.model_copy(update={"id": "e" * 64})
    assert not store.freeze(changed, sites).policies
    changed_site = declared.sites[0].model_copy(update={"entry_point_id": "entry:foreign"})
    with pytest.raises(PolicyConflict, match="binding changed"):
        store.freeze(
            bundle.snapshot, [changed_site if s.id == changed_site.id else s for s in sites]
        )
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE bound_policies SET digest=?", ("0" * 64,))
    with pytest.raises(PolicyConflict, match="integrity"):
        store.freeze(bundle.snapshot, sites)


def test_one_unguarded_site_is_supported_only_with_a_requirement_and_no_votes(
    project: tuple[Settings, ReportBundle, Path],
    review: Review,
    tmp_path: Path,
) -> None:
    settings, bundle, _ = project
    reads = ProjectReads(settings)
    declared = reads.declare(bundle.run.id, request(review))
    path = next(p for p in review.access.accesses if p.site.id == declared.sites[0].id)
    access = AccessMap(snapshot_id=review.snapshot.id, accesses=[path], issues=[])

    def investigate(policies: FrozenPolicies) -> tuple[AuthorizationChallenge, ChallengeResult]:
        model = Model()
        classifier = Classifier(
            review.snapshot,
            review.store,
            model,
            SummaryCache(tmp_path / "guards.sqlite"),
            identity="policy-test",
        )
        challenge = AuthorizationChallenge(
            PeerCheck(
                classifier,
                review.index,
                review.python,
                settings,
                typescript_graph=review.typescript,
            ),
            access,
            model,
            policies=policies,
        )
        result = challenge.investigate(path.site.id, Spend(Budget(max_prompt_tokens=20000)))
        return challenge, result

    empty = FrozenPolicies(snapshot_id=review.snapshot.id)
    challenge, raw = investigate(empty)
    result = ChallengeResult.model_validate(raw.model_dump())
    assert result.conclusion is Conclusion.CANDIDATE
    frozen = reads.policies.freeze(bundle.snapshot, review.map.access_sites)
    challenge, raw = investigate(frozen)
    result = ChallengeResult.model_validate(raw.model_dump())
    assert result.conclusion is Conclusion.SUPPORTED and len(result.samples) == 3
    assert not any(g.deviations for g in challenge.result.groups)
    assert result.policies == [declared] and not any(
        g.kind is GuardKind.OWNER for g in result.guards
    )
    case = finding(result, run_id="run:declared", display_id="F-01")
    run = ReviewRun(
        id=case.run_id,
        snapshot_id=bundle.snapshot.id,
        run_type=RunType.SAVED,
        lifecycle=RunLifecycle.COMPLETED,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        finding_ids=[case.id],
    )
    output = ReportBundle(
        run=run,
        snapshot=bundle.snapshot,
        findings=[case],
        guards=result.guards,
        policies=frozen.policies,
    )
    for kind in ("json", "sarif", "html", "markdown"):
        text = render(output, review.store, kind)
        assert "Reviewer" in text and "requirement" in text.lower()
        if kind == "json":
            assert ReportBundle.model_validate_json(text).findings[0].policy_basis == [declared]
        if kind == "sarif":
            assert json.loads(text)["runs"][0]["results"][0]["properties"]["finding"][
                "policy_basis"
            ]
    reads.declare(bundle.run.id, request(review, guard=GuardKind.NONE))
    _, raw = investigate(reads.policies.freeze(bundle.snapshot, review.map.access_sites))
    conflict = ChallengeResult.model_validate(raw.model_dump())
    assert (
        conflict.conclusion is Conclusion.INCONCLUSIVE and "conflict" in conflict.issues[0].lower()
    )

    invoice = next(
        p
        for p in review.access.accesses
        if p.site.resource == "Order"
        and review.routes.get(p.site.entry_point_id) is not None
        and review.routes[p.site.entry_point_id].entry.route == ROUTES[1]
    )
    rule = reads.declare(
        bundle.run.id,
        PolicyInput(
            snapshot_id=review.snapshot.id,
            site_ids=[invoice.site.id],
            required_guard=GuardKind.OWNER,
            statement="Invoice owner required",
            author="Reviewer",
        ),
    )
    model = Model()
    peers = PeerCheck(
        Classifier(
            review.snapshot,
            review.store,
            model,
            SummaryCache(tmp_path / "protected.sqlite"),
            identity="protected-policy",
        ),
        review.index,
        review.python,
        settings,
        typescript_graph=review.typescript,
    )
    protected = AuthorizationChallenge(
        peers,
        AccessMap(snapshot_id=review.snapshot.id, accesses=[invoice], issues=[]),
        model,
        policies=FrozenPolicies(snapshot_id=review.snapshot.id, policies=[rule]),
    ).investigate(invoice.site.id, Spend(Budget(max_prompt_tokens=20000)))
    assert protected.conclusion is Conclusion.REJECTED
    assert any(g.kind is GuardKind.OWNER and g.confirmed for g in protected.guards)


@pytest.mark.parametrize(
    "changes",
    [
        {"required_guard": "parameterized"},
        {"required_guard": None},
        {"forbidden_fields": ["path.escape"]},
        {"author": "\n"},
        {"site_ids": ["access:1", "access:1"]},
    ],
)
def test_policy_input_rejects_unknown_or_ambiguous_requirements(changes: dict[str, object]) -> None:
    from pydantic import ValidationError

    raw = {
        "snapshot_id": "a" * 64,
        "site_ids": ["access:1"],
        "statement": "Required",
        "author": "Reviewer",
        "required_guard": "owner",
    }
    with pytest.raises(ValidationError):
        PolicyInput.model_validate({**raw, **changes})


def test_confirmed_rules_are_consumed_including_legacy_confirmation(
    project: tuple[Settings, ReportBundle, Path],
    review: Review,
) -> None:
    settings, bundle, _ = project
    reads = ProjectReads(settings)
    rule = next(r for r in reads.page(bundle.run.id).rules if r.assertion.kind is GuardKind.OWNER)
    # Old confirmation path does not write bound_policies.
    confirmed = reads.policies.confirm(rule, rule.proposal_sha256)
    frozen = reads.policies.freeze(bundle.snapshot, review.map.access_sites)
    assert frozen.policies[0].assertion == confirmed.assertion
    assert reads.confirm(bundle.run.id, rule.assertion.id, rule.proposal_sha256) == confirmed
    assert reads.policies.freeze(bundle.snapshot, review.map.access_sites) == frozen


def test_cli_freezes_policy_resume_ignores_new_rule_and_refuses_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from analysis.snapshot import SnapshotStore, take_snapshot

    settings = Settings(data_dir=tmp_path / "data")
    root = Path(__file__).resolve().parents[2] / "labs/tandir"
    snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
    context = Review(settings, snapshot.id)
    run_id = "review-" + "d" * 32
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    source = ReviewRun(
        id="run:policy",
        snapshot_id=snapshot.id,
        run_type=RunType.SAVED,
        lifecycle=RunLifecycle.COMPLETED,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    runs.create(source, [])
    MapStore(settings.cache_dir / "application_maps.sqlite").save(context.map)
    reads = ProjectReads(settings)
    policy = reads.declare(source.id, request(context))
    context.close()
    closed = []

    class Adapter(Model):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__()

        def close(self) -> None:
            closed.append("adapter")

    monkeypatch.setenv("PLUMB_DATA_DIR", str(settings.data_dir))
    monkeypatch.setattr(cli, "select", lambda *args: Profile())
    monkeypatch.setattr(
        cli,
        "create",
        lambda *args: SimpleNamespace(
            config=SimpleNamespace(argv=lambda *args: ["software-fixture"]),
            stop=lambda: closed.append("server"),
            memory_abort=False,
        ),
    )
    monkeypatch.setattr(cli, "ModelAdapter", Adapter)
    monkeypatch.setattr(cli, "machine_state", lambda: {"software_fixture": True})
    import argparse

    args = argparse.Namespace(
        command="review",
        folder=root,
        resource=["Order"],
        route=ROUTES,
        family=None,
        guard_cache=None,
        profile=None,
        limit=1,
        open_report=False,
    )
    # The public CLI returns 2 for a paused run with pending checks.
    assert cli.execute_review(args, settings, requested_id=run_id) == 2
    directory = settings.data_dir / "reviews" / run_id
    frozen_bytes = (directory / "policies.json").read_bytes()
    assert FrozenPolicies.model_validate_json(frozen_bytes).policies == [policy]
    config = json.loads((directory / "context.json").read_bytes())
    assert config["policies_sha256"] == hashlib.sha256(frozen_bytes).hexdigest()
    reads.declare(source.id, request_from_policy(policy, GuardKind.NONE))
    assert cli.main(["resume", run_id, "--limit", "10"]) == 0
    assert (directory / "policies.json").read_bytes() == frozen_bytes
    saved = ReportBundle.model_validate_json((directory / "report.json").read_bytes())
    assert saved.policies == [policy] and len(closed) == 4
    write_json(directory / "policies.json", {"snapshot_id": snapshot.id, "policies": []})
    assert cli.main(["resume", run_id]) == 1
    assert len(closed) == 4  # refusal before server/adapter construction


def request_from_policy(policy: BoundPolicy, kind: GuardKind) -> PolicyInput:
    return PolicyInput(
        snapshot_id=policy.snapshot_id,
        site_ids=[s.id for s in policy.sites],
        statement="Conflicting later requirement",
        author="Later reviewer",
        required_guard=kind,
    )
