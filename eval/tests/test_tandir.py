"""Frozen current Tandir workflow, budgets and corrupt acceptance records; no inference."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent.llm import JsonAnswer, ModelRequest, ModelUnavailable, Spend
from analysis.snapshot import SnapshotStore
from backend.contracts.common import Family
from backend.review import Review
from backend.settings import Settings
from eval import candidate, tandir
from eval.tests.test_plumb import Judge as ProductionJudge
from eval.tests.test_plumb import Server


class Judge:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[ModelRequest] = []
        self.fail = fail

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.requests.append(request)
        if self.fail:
            raise ModelUnavailable("Fixture transport unavailable")
        data: dict[str, Any]
        if request.name == "gather":
            data = {"look": "enough"}
        elif request.name == "sink_safety":
            data = {
                "mechanism": "allowlisted"
                if "CUSTOMER_SORTS.get(sort)" in request.user
                else "none_found",
                "line_ids": re.findall(r"(L\d+).*?def ", request.user)[:1],
            }
        elif request.name == "fix_sketch":
            data = {
                "intent": "Fixture proposal",
                "edits": [],
                "probe": {
                    "parameter": None,
                    "denied": "unsafe_value",
                    "allowed": "safe_value",
                },
            }
        else:
            raise AssertionError(request.name)
        spend.requests += 1
        spend.prompt_tokens += 10
        spend.completion_tokens += 5
        return JsonAnswer(data, json.dumps(data), 10, 5, 0)


@pytest.fixture(scope="module")
def prepared(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[candidate.Preparation, SnapshotStore, Path]:
    folder = tmp_path_factory.mktemp("tandir-inputs")
    store = SnapshotStore(folder / "snapshots")
    p = candidate.prepare(
        store,
        hypothesis="Current workflow source and request trace; software fixture",
        max_requests=30,
        max_seconds=180,
        case_ids=("TANDIR-B1", "TANDIR-B1-L"),
        machine={"software_fixture": True},
    )
    candidate.write_new(folder / "preparation.json", p)
    return p, store, folder


@pytest.fixture(scope="module")
def completed(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[tandir.Execution, Judge, Path]:
    p, store, _ = prepared
    folder = tmp_path_factory.mktemp("tandir-execution")
    judge = Judge()
    run = tandir.execute(
        p, store, folder / "execution.json", Settings(data_dir=folder / "data"), fixture_model=judge
    )
    return run, judge, folder


def test_actual_production_workflow_and_current_source_accounting(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    completed: tuple[tandir.Execution, Judge, Path],
) -> None:
    p, store, _ = prepared
    run, judge, folder = completed
    assert run.state == "completed", run.model_dump()
    projected = tandir.result(p, store, run)
    metrics: Any = candidate.account(p, projected, store)
    assert metrics["metrics"]["paired_discrimination"]["successes"] == 1
    assert projected.evidence_kind == "software_fixture"
    assert metrics["release_acceptance"] == "unassessed"
    assert {r.snapshot.id for r in run.records if r.snapshot} == {p.snapshot.id}
    assert not list((folder / "data/cache").glob("tandir-development-*"))
    assert any(r.name == "fix_sketch" for r in judge.requests)
    for request in judge.requests:
        assert all(c.id not in request.user for c in p.cases)
        assert '"label"' not in request.user
    for record in run.records:
        answer: Any = record.questions[0].answer
        assert len(answer["result"]["samples"]) == 3


@pytest.mark.parametrize(
    "change",
    [
        "driver",
        "input",
        "omitted",
        "duplicate",
        "snapshot",
        "raw",
        "sample",
        "seed",
        "citation",
        "runtime",
        "unrun",
        "question",
        "duplicate_question",
    ],
)
def test_tampered_acceptance_refuses(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    completed: tuple[tandir.Execution, Judge, Path],
    change: str,
) -> None:
    p, store, _ = prepared
    run, _, _ = completed
    raw = run.model_dump(mode="json")
    record = raw["records"][0]
    if change == "driver":
        raw["driver"] = {}
    elif change == "input":
        record["packet_sha256"] = "a" * 64
    elif change == "omitted":
        raw["records"].pop()
    elif change == "duplicate":
        raw["records"][1] = record
    elif change == "snapshot":
        record["snapshot"]["id"] = "a" * 64
    elif change == "raw":
        record["requests"][0]["raw_answer"] = "{}"
    elif change == "sample":
        record["questions"][0]["answer"]["result"]["samples"].pop()
    elif change == "seed":
        for request in record["requests"]:
            request["body"]["seed"] = 99
    elif change == "citation":
        record["questions"][0]["evidence"][0]["content_sha256"] = "a" * 64
    elif change == "runtime":
        record["questions"][0]["answer"]["finding"]["runtime_verification"] = "unavailable"
    elif change == "unrun":
        record["state"] = "unrun"
    elif change == "duplicate_question":
        record["questions"].append(record["questions"][0])
    else:
        record["questions"][0]["subject_ids"] = ["access:unrelated"]
    with pytest.raises(ValueError):
        tandir.result(p, store, tandir.Execution.model_validate(raw))


def test_budget_and_process_failure_leave_later_cases_unrun(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    tmp_path: Path,
) -> None:
    p, store, _ = prepared
    for name, model, maximum in (("budget", Judge(), 1), ("process", Judge(fail=True), 30)):
        bounded = p.model_copy(update={"max_requests": maximum})
        run = tandir.execute(
            bounded,
            store,
            tmp_path / f"{name}.json",
            Settings(data_dir=tmp_path / name),
            fixture_model=model,
        )
        assert run.state == "failed" and len(model.requests) <= maximum
        assert run.records[1].state == "unrun" and not run.records[1].requests
        tandir.result(bounded, store, run)


def test_drift_and_existing_output_refuse_before_diagnostics(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p, store, _ = prepared
    monkeypatch.setattr(
        tandir, "machine_state", lambda: pytest.fail("Diagnostics before admission")
    )
    output = tmp_path / "owner.json"
    output.write_bytes(b"owner file")
    for plan, path in (
        (p, output),
        (p.model_copy(update={"implementation": {}}), tmp_path / "drift.json"),
    ):
        with pytest.raises((ValueError, FileExistsError)):
            tandir.execute(plan, store, path, Settings(data_dir=tmp_path / "data"))
    assert output.read_bytes() == b"owner file"
    assert not (tmp_path / "drift.json").exists()


def test_real_adapter_refusal_never_loads_and_closes_owned_client(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p, store, _ = prepared

    # Config records only a redacted launch placeholder; no process or real server.
    class Config:
        def argv(self, *_: object) -> list[str]:
            return ["fixture"]

    class FakeServer(Server):
        config = Config()

    server = FakeServer(ok=False)
    monkeypatch.setattr(tandir.profiles, "create", lambda *_: server)
    monkeypatch.setattr(tandir, "machine_state", lambda: {"software_fixture": True})
    run = tandir.execute(p, store, tmp_path / "run.json", Settings(data_dir=tmp_path / "data"))
    assert run.state == "preflight_refused" and server.starts == 0 and server.stops == 1
    assert all(r.state == "unrun" for r in run.records)
    assert tandir.result(p, store, run).state == "preflight_refused"
    assert not list((tmp_path / "data/cache").glob("tandir-development-*"))


def test_offline_cli_accounts_saved_execution(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    completed: tuple[tandir.Execution, Judge, Path],
    tmp_path: Path,
) -> None:
    _, _, inputs = prepared
    _, _, saved = completed
    assert (
        tandir.main(
            [
                "account",
                str(inputs),
                str(saved / "execution.json"),
                "--output",
                str(tmp_path / "metrics.json"),
            ]
        )
        == 0
    )
    assert (
        json.loads((tmp_path / "metrics.json").read_bytes())["evidence_kind"] == "software_fixture"
    )


def test_profile_selection_refusal_retains_reason_without_launch_or_attempts(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p, store, _ = prepared

    def refused(*_: object) -> None:
        raise ValueError("Profile unavailable: Insufficient or unknown RAM/dedicated VRAM")

    monkeypatch.setattr(tandir.profiles, "create", refused)
    monkeypatch.setattr(tandir, "machine_state", lambda: {"software_fixture": True})
    run = tandir.execute(p, store, tmp_path / "run.json", Settings(data_dir=tmp_path / "data"))
    assert run.state == "failed"
    assert "RAM" in str(run.observations["profile_refusal"])
    assert all(r.state == "unrun" and not r.requests for r in run.records)
    tandir.result(p, store, run)
    assert not list((tmp_path / "data/cache").glob("tandir-development-*"))


@pytest.fixture(scope="module")
def authorization(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[candidate.Preparation, SnapshotStore, Path]:
    folder = tmp_path_factory.mktemp("tandir-callers")
    store = SnapshotStore(folder / "snapshots")
    p = candidate.prepare(
        store,
        hypothesis="Exact helper access to frozen caller selection; software fixture",
        max_requests=100,
        max_seconds=300,
        case_ids=("TANDIR-A1", "TANDIR-A1-L"),
        machine={"software_fixture": True},
    )
    return p, store, folder


@pytest.fixture(scope="module")
def caller_review(
    authorization: tuple[candidate.Preparation, SnapshotStore, Path],
) -> Iterator[Review]:
    p, store, folder = authorization
    with tandir.frozen_review(p, store, Settings(data_dir=folder / "review")) as (_, review):
        yield review


def test_exact_invoice_helper_and_receipt_selection(
    authorization: tuple[candidate.Preparation, SnapshotStore, Path], caller_review: Review
) -> None:
    p, _, _ = authorization
    for case in p.cases:
        questions, _, _ = caller_review.questions("run:" + case.input_id, [], [])
        selected = tandir.focus_questions(caller_review, case, questions)
        assert len(selected) == 1
        assert case.source in selected[0].evidence
        path = next(
            a for a in caller_review.access.accesses if a.site.id == selected[0].subject_ids[0]
        )
        assert caller_review.routes[path.site.entry_point_id].entry.span == case.source
        assert path.site.span in selected[0].evidence
        if case.id == "TANDIR-A1-L":
            assert path.site.span.path == "api/tandir/services/orders.py"
            original = next(q for q in questions if q.id == selected[0].id)
            assert not tandir.overlaps(original, case)
        # Ground truth is not dispatch context.
        changed = case.model_copy(
            update={"label": "safe" if case.label == "vulnerable" else "vulnerable"}
        )
        assert tandir.focus_questions(caller_review, changed, questions) == selected


@pytest.mark.parametrize(
    "change", ["snapshot", "caller", "subject", "citation", "family", "dependency"]
)
def test_helper_selection_refuses_unrelated_or_forged_bindings(
    authorization: tuple[candidate.Preparation, SnapshotStore, Path],
    caller_review: Review,
    change: str,
) -> None:
    p, _, _ = authorization
    invoice = p.cases[1]
    questions, _, _ = caller_review.questions("run:" + invoice.input_id, [], [])
    selected = tandir.focus_questions(caller_review, invoice, questions)
    original = next(q for q in questions if q.id == selected[0].id)
    case = invoice
    if change == "snapshot":
        case = invoice.model_copy(
            update={"source": invoice.source.model_copy(update={"snapshot_id": "a" * 64})}
        )
    elif change == "caller":
        # A legitimate access from a different caller does not become this caller's
        # merely by adding a valid caller citation.
        original = next(q for q in questions if q.id != original.id)
        original = original.model_copy(update={"evidence": [*original.evidence, invoice.source]})
    elif change == "subject":
        original = original.model_copy(update={"subject_ids": ["access:unrelated"]})
    elif change == "citation":
        original = original.model_copy(update={"evidence": [invoice.source]})
    elif change == "family":
        original = original.model_copy(update={"family": Family.INJECTION})
    else:
        sites = {p.site.id: p.site for p in caller_review.access.accesses}
        entry = sites[original.subject_ids[0]].entry_point_id
        original = next(
            q
            for q in questions
            if q.id != original.id and sites[q.subject_ids[0]].entry_point_id == entry
        )
    assert not tandir.focus_questions(caller_review, case, [original])


@pytest.fixture(scope="module")
def caller_execution(
    authorization: tuple[candidate.Preparation, SnapshotStore, Path],
) -> tuple[tandir.Execution, ProductionJudge]:
    p, store, folder = authorization
    judge = ProductionJudge()
    run = tandir.execute(
        p,
        store,
        folder / "execution.json",
        Settings(data_dir=folder / "workflow"),
        fixture_model=judge,
    )
    return run, judge


def test_helper_caller_production_fixture_accounts_exact_source(
    authorization: tuple[candidate.Preparation, SnapshotStore, Path],
    caller_execution: tuple[tandir.Execution, ProductionJudge],
) -> None:
    p, store, _ = authorization
    run, judge = caller_execution
    assert run.state == "completed", run.model_dump()
    projected = tandir.result(p, store, run)
    assert all(r.state == "completed" for r in projected.cases)
    invoice = run.records[1]
    answer: Any = invoice.questions[0].answer
    assert len(answer["result"]["samples"]) == 3
    assert invoice.requests
    assert all(case.id not in request.user for case in p.cases for request in judge.requests)


@pytest.mark.parametrize("change", ["omitted_caller", "forged_caller", "question_id"])
def test_saved_helper_accounting_rebuilds_exact_caller_binding(
    authorization: tuple[candidate.Preparation, SnapshotStore, Path],
    caller_execution: tuple[tandir.Execution, ProductionJudge],
    change: str,
) -> None:
    p, store, _ = authorization
    run, _ = caller_execution
    raw = run.model_dump(mode="json")
    question = raw["records"][1]["questions"][0]
    if change == "omitted_caller":
        question["evidence"].pop()
    elif change == "forged_caller":
        question["evidence"][-1] = p.cases[0].source.model_dump(mode="json")
    else:
        question["id"] = "question:forged"
    with pytest.raises(ValueError, match="exact caller"):
        tandir.result(p, store, tandir.Execution.model_validate(raw))


def test_unsupported_case_does_not_project_completed_reason(
    prepared: tuple[candidate.Preparation, SnapshotStore, Path],
    completed: tuple[tandir.Execution, Judge, Path],
) -> None:
    p, store, _ = prepared
    run, _, _ = completed
    raw = run.model_dump(mode="json")
    raw["state"] = "failed"
    record = raw["records"][0]
    record.update(state="unsupported", questions=[], requests=[], reason="No bound question")
    projected = tandir.result(p, store, tandir.Execution.model_validate(raw))
    assert "retains failed or unrun" in projected.reason
