import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.contracts import CONTRACTS, Contract, Finding, ProbeRun, SourceSpan
from backend.contracts.code import (
    ExcludedFile,
    GuardMechanism,
    PeerDeviation,
    PolicyAssertion,
    PolicyStatus,
    ProjectSnapshot,
    snapshot_id,
)
from backend.contracts.export import render, stale
from backend.contracts.investigation import (
    ChallengeCheck,
    Conclusion,
    EvidenceStrength,
    Exhibit,
    ExhibitRole,
    Question,
    QuestionStatus,
    RuntimeVerification,
)
from backend.contracts.runs import Coverage, ReviewRun, RunLifecycle, RunStage
from backend.contracts.verification import (
    ChangeStatus,
    ProbeOutcome,
    SnapshotRole,
    StepRole,
    SuggestedChange,
    derive_outcome,
)

from . import contract_examples as ex


def updated(model: Contract, **changes: object) -> dict[str, object]:
    """The model's data with changes applied, ready to re-validate."""
    return {**model.model_dump(), **changes}


# --- every contract: example, round trip, schema -------------------------------------------


def test_every_contract_has_an_example() -> None:
    assert set(ex.EXAMPLES) == set(CONTRACTS)
    assert len(CONTRACTS) == 17


@pytest.mark.parametrize("model", CONTRACTS, ids=lambda m: m.__name__)
def test_json_round_trip(model: type[Contract]) -> None:
    original = ex.EXAMPLES[model]
    assert model.model_validate_json(original.model_dump_json()) == original


@pytest.mark.parametrize("model", CONTRACTS, ids=lambda m: m.__name__)
def test_example_validates_against_exported_schema(model: type[Contract]) -> None:
    schema = json.loads(render()[f"{model.__name__}.schema.json"])
    Draft202012Validator.check_schema(schema)
    errors = list(
        Draft202012Validator(schema).iter_errors(ex.EXAMPLES[model].model_dump(mode="json"))
    )
    assert errors == []


def test_committed_schemas_are_current() -> None:
    assert stale() == [], "run: uv run python -m backend.contracts.export"


def test_contracts_are_frozen_and_closed() -> None:
    span = ex.RECEIPT
    with pytest.raises(ValidationError):
        span.start_line = 1  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError, match="Extra inputs"):
        SourceSpan.model_validate(updated(span, note="comments are not evidence"))


# --- paths and spans -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "C:secrets.txt",
        "..\\up.py",
        "api\\routes.py",
        "../outside.py",
        "api/../../outside.py",
        "./api/x.py",
        "api//x.py",
        "api/x\x00.py",
    ],
)
def test_span_paths_must_stay_inside_the_snapshot(path: str) -> None:
    with pytest.raises(ValidationError):
        SourceSpan.model_validate(updated(ex.RECEIPT, path=path))


def test_span_lines_are_ordered_and_one_based() -> None:
    with pytest.raises(ValidationError, match="end_line comes before"):
        SourceSpan.model_validate(updated(ex.RECEIPT, start_line=10, end_line=9))
    with pytest.raises(ValidationError):
        SourceSpan.model_validate(updated(ex.RECEIPT, start_line=0))


# --- snapshots ---------------------------------------------------------------------------------


def test_snapshot_id_is_its_content_address() -> None:
    snap = ex.snapshot()
    assert snap.id == snapshot_id(list(reversed(snap.files)))  # order-independent
    with pytest.raises(ValidationError, match="content hash"):
        ProjectSnapshot.model_validate(updated(snap, id=ex.h("something else")))


def test_snapshot_lists_each_path_once() -> None:
    files = [*ex.FILES, ex.FILES[0]]
    with pytest.raises(ValidationError, match="each path once"):
        ProjectSnapshot.model_validate(updated(ex.snapshot(), files=files, id=snapshot_id(files)))


def test_excluded_reasons_are_closed() -> None:
    with pytest.raises(ValidationError):
        ExcludedFile(path="x.py", reason="felt like it")  # type: ignore[arg-type]


# --- guards, peers, policy --------------------------------------------------------------------


def test_proxy_matcher_guards_are_optimistic() -> None:
    assert not ex.guard().optimistic
    proxy = ex.guard().model_copy(update={"mechanism": GuardMechanism.PROXY_MATCHER})
    assert proxy.optimistic


@pytest.mark.parametrize(
    ("applying", "total", "message"),
    [(2, 2, "fewer than 3 peers"), (5, 8, "fewer than 75%")],
)
def test_deviations_must_meet_the_predeclared_thresholds(
    applying: int, total: int, message: str
) -> None:
    group = ex.peer_group()
    weak = PeerDeviation(
        site_id="site:8", missing="OWNER", peers_applying=applying, peers_total=total
    )
    with pytest.raises(ValidationError, match=message):
        type(group).model_validate(updated(group, deviations=[weak.model_dump()]))


def test_deviation_must_name_a_column_and_site_of_the_group() -> None:
    group = ex.peer_group()
    stray = PeerDeviation(site_id="site:99", missing="OWNER", peers_applying=7, peers_total=8)
    with pytest.raises(ValidationError, match="not in this group"):
        type(group).model_validate(updated(group, deviations=[stray.model_dump()]))


def test_inferred_policy_has_no_confirmation_and_confirmed_has_one() -> None:
    policy = ex.policy()
    with pytest.raises(ValidationError, match="record who confirmed"):
        PolicyAssertion.model_validate(updated(policy, status=PolicyStatus.INFERRED))
    with pytest.raises(ValidationError, match="record who confirmed"):
        PolicyAssertion.model_validate(updated(policy, confirmed_by=None))


# --- questions and observations --------------------------------------------------------------


def test_answer_present_exactly_when_answered() -> None:
    q = ex.question()
    with pytest.raises(ValidationError, match="exactly when"):
        Question.model_validate(updated(q, answer=None))
    with pytest.raises(ValidationError, match="exactly when"):
        Question.model_validate(updated(q, status=QuestionStatus.PENDING))


def test_observation_times_are_ordered() -> None:
    obs = ex.observation()
    with pytest.raises(ValidationError, match="finished_at comes before"):
        type(obs).model_validate(updated(obs, started_at=ex.T1, finished_at=ex.T0))


# --- findings: the evidence rules -----------------------------------------------------------


def comment_exhibit() -> Exhibit:
    return Exhibit(
        tag="E03", span=ex.RECEIPT, role=ExhibitRole.DEVELOPER_NOTE, gloss="Says 'reviewed: safe'."
    )


def rejected(
    checks: list[ChallengeCheck], exhibits: list[Exhibit] | None = None
) -> dict[str, object]:
    f = ex.finding()
    return updated(
        f,
        conclusion=Conclusion.REJECTED,
        runtime_verification=RuntimeVerification.NOT_ATTEMPTED,
        checks=[c.model_dump() for c in checks],
        exhibits=[e.model_dump() for e in (exhibits or f.exhibits)],
    )


def test_rejection_citing_a_guard_is_accepted() -> None:
    found = ChallengeCheck(
        item="A query filter scoped to the principal",
        searched="api/services/orders.py",
        found=True,
        exhibit_tag="E02",
    )
    assert Finding.model_validate(rejected([found])).conclusion is Conclusion.REJECTED


def test_rejection_without_a_guard_is_refused() -> None:
    nothing = ChallengeCheck(item="Admin-only entry point", searched="router", found=False)
    with pytest.raises(ValidationError, match="must cite a guard"):
        Finding.model_validate(rejected([nothing]))


def test_a_comment_never_counts_as_a_found_check() -> None:
    f = ex.finding()
    by_comment = ChallengeCheck(
        item="Ownership checked elsewhere", searched="comment", found=True, exhibit_tag="E03"
    )
    with pytest.raises(ValidationError, match="comment is never evidence"):
        Finding.model_validate(rejected([by_comment], [*f.exhibits, comment_exhibit()]))


def test_found_check_must_cite_an_exhibit() -> None:
    with pytest.raises(ValidationError, match="must cite an exhibit"):
        ChallengeCheck(item="Scoped query", searched="x", found=True)


def test_unknown_or_duplicate_exhibit_tags_are_refused() -> None:
    f = ex.finding()
    ghost = ChallengeCheck(item="Scoped query", searched="x", found=True, exhibit_tag="E09")
    with pytest.raises(ValidationError, match="unknown exhibit tags"):
        Finding.model_validate(updated(f, checks=[ghost.model_dump()]))
    twice = [f.exhibits[0].model_dump()] * 2
    with pytest.raises(ValidationError, match="unique"):
        Finding.model_validate(updated(f, exhibits=twice))


def test_exhibits_must_cite_the_findings_snapshot() -> None:
    f = ex.finding()
    other = f.exhibits[0].span.model_copy(update={"snapshot_id": ex.h("other snapshot")})
    moved = f.exhibits[0].model_copy(update={"span": other})
    with pytest.raises(ValidationError, match="finding's snapshot"):
        Finding.model_validate(
            updated(f, exhibits=[moved.model_dump(), f.exhibits[1].model_dump()])
        )


def test_reproduced_requires_a_probe_run() -> None:
    with pytest.raises(ValidationError, match="probe run on record"):
        Finding.model_validate(updated(ex.finding(), probe_run_ids=[]))


def test_partial_evidence_names_its_gaps() -> None:
    with pytest.raises(ValidationError, match="name its gaps"):
        Finding.model_validate(updated(ex.finding(), strength=EvidenceStrength.THIN, gaps=[]))


def test_dismissal_records_a_reason() -> None:
    with pytest.raises(ValidationError, match="records its reason"):
        Finding.model_validate(updated(ex.finding(), disposition="dismissed"))


def test_display_id_and_cwe_shape() -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(updated(ex.finding(), display_id="F7"))
    with pytest.raises(ValidationError):
        Finding.model_validate(updated(ex.finding(), cwe=[]))


# --- probes: outcome is derived from observations -----------------------------------------


@pytest.mark.parametrize(
    ("role", "attack_status", "attack_marker", "expected"),
    [
        (SnapshotRole.VULNERABLE, 200, True, ProbeOutcome.REPRODUCED),
        (SnapshotRole.VULNERABLE, 404, False, ProbeOutcome.NOT_REPRODUCED),
        (SnapshotRole.PATCHED, 403, False, ProbeOutcome.FIXED),
        (SnapshotRole.PATCHED, 200, False, ProbeOutcome.FIXED),  # empty result, no leak
        (SnapshotRole.PATCHED, 200, True, ProbeOutcome.NOT_FIXED),
        (SnapshotRole.PATCHED, 500, False, ProbeOutcome.INCONCLUSIVE),  # a 500 is never a fix
        (SnapshotRole.PATCHED, 422, False, ProbeOutcome.INCONCLUSIVE),
    ],
)
def test_derive_outcome(
    role: SnapshotRole, attack_status: int, attack_marker: bool, expected: ProbeOutcome
) -> None:
    assert derive_outcome(role, ex.steps(attack_status, attack_marker)) is expected


def test_a_failing_control_makes_any_probe_inconclusive() -> None:
    broken = [
        s.model_copy(update={"status": 500}) if s.role is StepRole.CONTROL else s
        for s in ex.steps(200, True)
    ]
    assert derive_outcome(SnapshotRole.VULNERABLE, broken) is ProbeOutcome.INCONCLUSIVE
    with pytest.raises(ValidationError, match="contradicts the observed steps"):
        ProbeRun.model_validate(updated(ex.probe_run(), steps=[s.model_dump() for s in broken]))


def test_a_probe_without_control_or_attack_proves_nothing() -> None:
    steps = ex.steps(200, True)
    no_control = [s for s in steps if s.role is not StepRole.CONTROL]
    no_attack = [s for s in steps if s.role is not StepRole.ATTACK]
    assert derive_outcome(SnapshotRole.VULNERABLE, no_control) is ProbeOutcome.INCONCLUSIVE
    assert derive_outcome(SnapshotRole.VULNERABLE, no_attack) is ProbeOutcome.INCONCLUSIVE


def test_a_timeout_is_never_a_fix() -> None:
    steps = [
        s.model_copy(update={"status": None, "marker_present": None, "error": "timeout"})
        if s.role is StepRole.ATTACK
        else s
        for s in ex.steps(200, True)
    ]
    assert derive_outcome(SnapshotRole.PATCHED, steps) is ProbeOutcome.INCONCLUSIVE


# --- suggested changes and runs ---------------------------------------------------------------


def test_suggested_change_needs_a_unified_diff_and_replay_evidence() -> None:
    change = ex.suggested_change()
    with pytest.raises(ValidationError, match="unified diff"):
        SuggestedChange.model_validate(updated(change, diff="replace line 44"))
    with pytest.raises(ValidationError, match="requires its probe runs"):
        SuggestedChange.model_validate(updated(change, replay_probe_run_ids=[]))
    proposed = updated(change, status=ChangeStatus.PROPOSED, replay_probe_run_ids=[])
    assert SuggestedChange.model_validate(proposed).status is ChangeStatus.PROPOSED


def test_run_lifecycle_stage_and_finish_time_are_consistent() -> None:
    run = ex.review_run()
    with pytest.raises(ValidationError, match="stage is set exactly"):
        ReviewRun.model_validate(updated(run, stage=None))
    with pytest.raises(ValidationError, match="stage is set exactly"):
        ReviewRun.model_validate(updated(run, lifecycle=RunLifecycle.COMPLETED, finished_at=ex.T1))
    with pytest.raises(ValidationError, match="finished_at is set exactly"):
        ReviewRun.model_validate(updated(run, lifecycle=RunLifecycle.COMPLETED, stage=None))
    canceled_in_queue = updated(
        run, lifecycle=RunLifecycle.CANCELED, stage=None, started_at=None, finished_at=ex.T1
    )
    assert ReviewRun.model_validate(canceled_in_queue).started_at is None
    with pytest.raises(ValidationError, match="records when it started"):
        ReviewRun.model_validate(updated(run, started_at=None, stage=RunStage.INDEXING))


def test_coverage_counts_every_question() -> None:
    with pytest.raises(ValidationError, match="must equal total"):
        Coverage(total=10, completed=3, pending=3)
