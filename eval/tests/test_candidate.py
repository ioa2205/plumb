"""Offline harness fixtures cannot impersonate fresh quality or final acceptance."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from analysis.snapshot import SnapshotStore
from eval import candidate
from eval.candidate import CaseResult, Preparation, RequestRecord, Result

IDS = ("TANDIR-A1", "TANDIR-A1-L")


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Preparation, SnapshotStore]:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("offline preparation opened a model or mutation/sealed inputs")

    monkeypatch.setattr("backend.profiles.create", forbidden)
    monkeypatch.setattr("eval.splits.load", forbidden)
    store = SnapshotStore(tmp_path / "snapshots")
    plan = candidate.prepare(
        store,
        hypothesis="Receipt/invoice software regression, no inference.",
        max_requests=6,
        max_seconds=60,
        case_ids=IDS,
        machine={"software_fixture": True},
    )
    return plan, store


def result(plan: Preparation, *, state: Literal["completed", "failed"] = "completed") -> Result:
    cases = [
        CaseResult(
            case_id=c.id,
            state="completed" if state == "completed" else "unrun",
            predictions=[],
            reason="Software accounting fixture",
        )
        for c in plan.cases
    ]
    requests = (
        [
            RequestRecord(
                case_id=c.id,
                body={"fixture": True},
                answer={"verdict": "fixture"},
                raw_answer="fixture",
                prompt_tokens=1,
                completion_tokens=1,
                seconds=0.1,
            )
            for c in plan.cases
        ]
        if state == "completed"
        else []
    )
    return Result(
        preparation_sha256=candidate.digest(plan),
        method="full_plumb",
        evidence_kind="software_fixture",
        state=state,
        reason="Software only",
        started_at=plan.created_at,
        finished_at=plan.created_at + timedelta(seconds=1),
        implementation=plan.implementation,
        model=plan.model,
        runtime=plan.runtime,
        profile=plan.profile,
        machine_start={"fixture": True},
        machine_end={"fixture": True},
        judgments=3,
        requests=requests,
        cases=cases,
    )


def test_source_inputs_are_frozen_paired_opaque_and_ground_truth_stays_evaluator_only(
    prepared: tuple[Preparation, SnapshotStore],
) -> None:
    plan, store = prepared
    candidate.check(plan, store)
    assert [c.id for c in plan.cases] == list(IDS)
    assert {c.label for c in plan.cases} == {"safe", "vulnerable"}
    assert len({c.input_id for c in plan.cases}) == 2
    assert all(c.input_id != c.id and c.file_sha256 for c in plan.cases)
    assert not plan.final_candidate and plan.production_judgments == 3
    assert plan.scope == "tandir_development_preparation" and len(plan.methods) == 8
    assert plan.model["sha256"] == plan.profile["model_sha256"]


@pytest.mark.parametrize("ids", [("TANDIR-A1",), ("TANDIR-A1", "TANDIR-A1"), ("sealed-test",)])
def test_unpaired_duplicate_or_unknown_selection_refuses(
    tmp_path: Path, ids: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        candidate.prepare(
            SnapshotStore(tmp_path / "snapshots"),
            hypothesis="Negative fixture",
            max_requests=3,
            max_seconds=30,
            case_ids=ids,
            machine={},
        )


@pytest.mark.parametrize(
    "field",
    ["implementation", "harness", "ground_truth_sha256", "split_manifest_sha256", "profile"],
)
def test_identity_drift_refuses_before_any_execution(
    prepared: tuple[Preparation, SnapshotStore], field: str
) -> None:
    plan, store = prepared
    value: Any = (
        {"changed": "a" * 64} if field in {"implementation", "harness", "profile"} else "a" * 64
    )
    with pytest.raises(ValueError):
        candidate.check(plan.model_copy(update={field: value}), store)


def test_label_or_source_identity_tampering_refuses(
    prepared: tuple[Preparation, SnapshotStore],
) -> None:
    plan, store = prepared
    changed = plan.cases[0].model_copy(update={"input_id": "a" * 64})
    with pytest.raises(ValueError, match="ground truth"):
        candidate.check(plan.model_copy(update={"cases": [changed, plan.cases[1]]}), store)
    swapped = [
        c.model_copy(update={"label": "safe" if c.label == "vulnerable" else "vulnerable"})
        for c in plan.cases
    ]
    with pytest.raises(ValueError, match="ground truth"):
        candidate.check(plan.model_copy(update={"cases": swapped}), store)


def test_failed_refused_and_unrun_cases_preserve_denominators_and_fixture_label(
    prepared: tuple[Preparation, SnapshotStore],
) -> None:
    plan, store = prepared
    failed = result(plan, state="failed")
    accounted: Any = candidate.account(plan, failed, store)
    assert (
        accounted["release_acceptance"] == "unassessed"
        and accounted["evidence_kind"] == "software_fixture"
    )
    assert set(accounted["unprocessed_cases"]) == set(IDS)
    assert accounted["metrics"]["recall"]["authorization"]["trials"] == 1
    assert accounted["metrics"]["recall"]["authorization"]["successes"] == 0
    assert accounted["metrics"]["paired_discrimination"]["trials"] == 1
    refused = failed.model_copy(
        update={"state": "preflight_refused", "preflight": {"ok": False, "reason": "RAM gate"}}
    )
    assert candidate.account(plan, refused, store)["state"] == "preflight_refused"


@pytest.mark.parametrize(
    "change",
    [
        "missing_case",
        "wrong_pin",
        "wrong_digest",
        "wrong_judgments",
        "unknown_request",
        "budget",
        "failed_request",
    ],
)
def test_mismatched_matched_runs_cannot_be_scored(
    prepared: tuple[Preparation, SnapshotStore], change: str
) -> None:
    plan, store = prepared
    value = result(plan).model_dump(mode="json")
    if change == "missing_case":
        value["cases"].pop()
    elif change == "wrong_pin":
        value["profile"]["context"] = 4096
    elif change == "wrong_digest":
        value["preparation_sha256"] = "a" * 64
    elif change == "wrong_judgments":
        value["judgments"] = 1
    elif change == "unknown_request":
        value["requests"][0]["case_id"] = "unknown"
    elif change == "budget":
        value["requests"][0]["seconds"] = 61
    else:
        value["requests"][0].update(answer=None, raw_answer=None, error="failed")
    with pytest.raises(ValueError):
        candidate.account(plan, Result.model_validate(value), store)


def test_budget_overrun_is_retained_as_a_failed_run_not_discarded(
    prepared: tuple[Preparation, SnapshotStore],
) -> None:
    plan, store = prepared
    attempted = result(plan).model_copy(
        update={"state": "failed", "finished_at": plan.created_at + timedelta(seconds=61)}
    )
    accounted = candidate.account(plan, attempted, store)
    assert accounted["budget_exceeded"] is True and accounted["state"] == "failed"


def test_adjacent_focused_cases_keep_their_own_predictions(
    prepared: tuple[Preparation, SnapshotStore],
) -> None:
    from backend.contracts.investigation import Conclusion
    from eval.scoring.score import Prediction

    plan, store = prepared
    saved = result(plan)
    rows = []
    for case, row in zip(plan.cases, saved.cases, strict=True):
        rows.append(
            row.model_copy(
                update={
                    "predictions": [
                        Prediction(
                            family=case.family,
                            path=case.source.path,
                            start_line=case.source.start_line,
                            end_line=case.source.end_line,
                            conclusion=Conclusion.SUPPORTED
                            if case.label == "vulnerable"
                            else Conclusion.REJECTED,
                        )
                    ]
                }
            )
        )
    matched = saved.model_copy(update={"cases": rows})
    metrics: Any = candidate.account(plan, matched, store)["metrics"]
    assert metrics["paired_discrimination"]["successes"] == 1
    assert metrics["defended_false_positive_rate"]["successes"] == 0
    # A report from the safe input at the flaw's lines is an unmatched false
    # positive, not credit for a different input that the runner failed to find.
    broken = [
        rows[0].model_copy(update={"predictions": []}),
        rows[1].model_copy(
            update={
                "predictions": [rows[0].predictions[0]],
            }
        ),
    ]
    off_scope: Any = candidate.account(plan, saved.model_copy(update={"cases": broken}), store)[
        "metrics"
    ]
    assert off_scope["recall"]["authorization"]["successes"] == 0
    assert off_scope["duplicate_or_unmatched_reports"] == 1


@pytest.mark.parametrize(
    "field,value",
    [("final_candidate", True), ("scope", "sealed_test"), ("production_judgments", 1)],
)
def test_final_sealed_or_weakened_production_claims_refuse(
    prepared: tuple[Preparation, SnapshotStore], field: str, value: object
) -> None:
    plan, _ = prepared
    with pytest.raises(ValidationError):
        Preparation.model_validate({**plan.model_dump(), field: value})


def test_new_records_never_overwrite_and_budget_large_inputs(
    tmp_path: Path, prepared: tuple[Preparation, SnapshotStore]
) -> None:
    plan, _ = prepared
    path = tmp_path / "preparation.json"
    candidate.write_new(path, plan)
    assert candidate.read(path, Preparation) == plan
    with pytest.raises(FileExistsError):
        candidate.write_new(path, plan)
    oversized = tmp_path / "large.json"
    oversized.write_bytes(b" " * (candidate.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="size"):
        candidate.read(oversized, Result)
    assert json.loads(path.read_bytes())["final_candidate"] is False


def test_saved_account_cli_is_offline_and_retains_fixture_identity(
    prepared: tuple[Preparation, SnapshotStore], tmp_path: Path
) -> None:
    plan, _ = prepared
    candidate.write_new(tmp_path / "preparation.json", plan)
    path = tmp_path / "result.json"
    candidate.write_new(path, result(plan))
    output = tmp_path / "account.json"
    assert candidate.main(["account", str(tmp_path), str(path), "--output", str(output)]) == 0
    data = json.loads(output.read_bytes())
    assert (
        data["evidence_kind"] == "software_fixture" and data["release_acceptance"] == "unassessed"
    )
    assert candidate.main(["account", str(tmp_path), str(path), "--output", str(output)]) == 1
    for forbidden in (["freeze"], ["prepare", "--split", "test"]):
        with pytest.raises(SystemExit):
            candidate.main(forbidden)


def test_fresh_completion_or_refused_preflight_cannot_omit_observations(
    prepared: tuple[Preparation, SnapshotStore],
) -> None:
    plan, _ = prepared
    value = result(plan).model_dump(mode="json")
    for update in (
        {"evidence_kind": "fresh_local", "preflight": None},
        {"state": "preflight_refused", "preflight": {"ok": True}},
        {"state": "unrun"},
    ):
        with pytest.raises(ValidationError):
            Result.model_validate({**value, **update})


def test_saved_schemas_are_current() -> None:
    for name, model in (("preparation", Preparation), ("result", Result)):
        expected = model.model_json_schema()
        expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        assert (
            json.loads((candidate.ROOT / f"eval/schemas/candidate-{name}.schema.json").read_bytes())
            == expected
        )
