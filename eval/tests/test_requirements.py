"""Frozen independent normative inputs and source bindings; no inference or target execution."""

import json
from pathlib import Path
from typing import Any

import pytest

from analysis.snapshot import SnapshotStore
from backend.contracts.code import GuardKind
from backend.contracts.policies import FrozenPolicies, PolicyInput
from backend.settings import Settings
from eval import candidate, requirements, tandir
from eval.tests.test_plumb import Judge


@pytest.fixture(scope="module")
def prepared(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[candidate.Preparation, SnapshotStore, Path]:
    folder = tmp_path_factory.mktemp("normative-tandir")
    store = SnapshotStore(folder / "snapshots")
    p = candidate.prepare(
        store,
        hypothesis="Frozen development requirements and source bindings; software fixture",
        max_requests=100,
        max_seconds=300,
        case_ids=(
            "TANDIR-D1",
            "TANDIR-D1-L",
            "TANDIR-D2",
            "TANDIR-D2-L",
            "TANDIR-D3",
            "TANDIR-D3-L",
        ),
        machine={"software_fixture": True},
        with_requirements=True,
    )
    return p, store, folder


def test_current_development_requirements_are_separate_pinned_exact_source(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
) -> None:
    p, store, folder = prepared
    assert p.requirements is not None and p.requirements_sha256 == requirements.pin()
    assert len(p.requirements.policies) == 6
    assert all(len(policy.sites) == 1 for policy in p.requirements.policies)
    assert {
        policy.required_role
        for policy in p.requirements.policies
        if policy.assertion.kind is GuardKind.ROLE
    } == {"admin"}
    assert {
        tuple(policy.forbidden_fields)
        for policy in p.requirements.policies
        if policy.forbidden_fields
    } == {("phone",)}
    text = p.requirements.model_dump_json()
    assert all(case.id not in text for case in p.cases)
    assert '"label"' not in text and '"expected"' not in text
    with tandir.frozen_review(p, store, Settings(data_dir=folder / "source-check")) as (_, review):
        assert review.policies == p.requirements
    assert not list((folder / "source-check/cache").glob("tandir-development-*"))


@pytest.mark.parametrize("change", ["pin", "role", "resource", "source", "omitted"])
def test_changed_requirement_or_binding_refuses_before_inference(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    tmp_path: Path,
    change: str,
) -> None:
    p, store, _ = prepared
    raw: Any = p.model_dump(mode="json")
    if change == "pin":
        raw["requirements_sha256"] = "a" * 64
    elif change == "role":
        raw["requirements"]["policies"][-1]["required_role"] = "manager"
    elif change == "resource":
        raw["requirements"]["policies"][-1]["sites"][0]["resource"] = "users"
    elif change == "source":
        raw["requirements"]["policies"][-1]["sites"][0]["span"]["content_sha256"] = "a" * 64
    else:
        raw["requirements"]["policies"].pop()
    with pytest.raises(ValueError):
        changed = candidate.Preparation.model_validate(raw)
        candidate.check(changed, store)
        with tandir.frozen_review(changed, store, Settings(data_dir=tmp_path)):
            pytest.fail("Forged requirements admitted")


@pytest.mark.parametrize(
    "extra", [{"expected": "supported"}, {"label": "safe"}, {"scope": "sealed_test"}]
)
def test_requirement_pack_cannot_carry_evaluator_verdicts(extra: dict[str, str]) -> None:
    raw: Any = json.loads(requirements.MANIFEST.read_bytes())
    if "scope" in extra:
        raw.update(extra)
    else:
        raw["rules"][0].update(extra)
    with pytest.raises(ValueError):
        requirements.Manifest.model_validate(raw)


def test_exact_qualified_role_input_and_negatives() -> None:
    raw = dict(
        snapshot_id="a" * 64,
        site_ids=["access:one"],
        statement="Admin required",
        author="Reviewer",
        required_guard="role",
        required_role="admin",
    )
    assert PolicyInput.model_validate(raw).required_role == "admin"
    for changes in (
        {"required_guard": "owner"},
        {"required_role": "admin; accept all"},
        {"required_role": ""},
    ):
        with pytest.raises(ValueError):
            PolicyInput.model_validate({**raw, **changes})


def test_conflicting_role_qualifiers_cannot_hide_behind_same_canonical_text(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
) -> None:
    p, _, _ = prepared
    assert p.requirements is not None
    original = p.requirements.policies[-1]
    conflicting = original.model_copy(
        update={
            "assertion": original.assertion.model_copy(update={"id": "policy:conflicting"}),
            "required_role": "manager",
        }
    )
    frozen = FrozenPolicies(snapshot_id=p.snapshot.id, policies=[original, conflicting])
    assert frozen.conflicts(original.sites[0])


def test_role_requirement_production_workflow_and_saved_accounting(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    tmp_path: Path,
) -> None:
    p, store, _ = prepared
    # Retain a complete declared pair and only its exact normative policies.
    assert p.requirements is not None
    cases = [c for c in p.cases if c.id in {"TANDIR-D3", "TANDIR-D3-L"}]
    selected = p.requirements.policies[-2:]
    scoped = p.model_copy(
        update={
            "cases": cases,
            "requirements": p.requirements.model_copy(update={"policies": selected}),
        }
    )
    judge = Judge()
    run = tandir.execute(
        scoped,
        store,
        tmp_path / "execution.json",
        Settings(data_dir=tmp_path / "data"),
        fixture_model=judge,
    )
    assert run.state == "completed", run.model_dump()
    result = tandir.result(scoped, store, run)
    assert result.evidence_kind == "software_fixture"
    assert all(c.state == "completed" for c in result.cases)
    raw: Any = run.model_dump(mode="json")
    assert [r["questions"][0]["answer"]["finding"]["conclusion"] for r in raw["records"]] == [
        "supported",
        "rejected",
    ]
    assert all(case.id not in request.user for case in p.cases for request in judge.requests)
    assert any("Human-declared requirement" in request.user for request in judge.requests)
    raw["records"][0]["questions"][0]["answer"]["finding"]["policy_basis"] = []
    with pytest.raises(ValueError):
        tandir.result(scoped, store, tandir.Execution.model_validate(raw))
