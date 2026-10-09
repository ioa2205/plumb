"""Experimental toggles and actual production defaults, with software judgments only."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent.families import SinkInvestigator
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.tests import test_families as family_fixtures
from agent.tests.test_boundary_policies import (
    ACTION,
    CLIENT,
    PAGE,
    context,
    declare,
    investigator,
)
from agent.tests.test_boundary_policies import (
    Judge as BoundaryJudge,
)
from agent.tests.test_families import Model as SinkJudge
from backend.contracts.common import Family
from backend.contracts.investigation import Budget, Conclusion
from backend.contracts.runs import ReviewRun, RunLifecycle, RunType
from backend.review import Review, Workflow
from backend.run_store import RunStore
from backend.settings import Settings
from backend.tests import test_review as review_fixtures
from backend.tests.test_review import Model
from eval import plumb
from eval.ablations import METHODS, Method, StudyWorkflow, request_without_grammar
from eval.baselines import development as base
from eval.candidate import digest, write_new
from eval.tests import test_plumb as plumb_fixtures
from eval.tests.test_plumb import Judge, Server

prepared = plumb_fixtures.prepared
review = review_fixtures.review
sink_context = family_fixtures.investigator


@pytest.mark.parametrize("method", ["no_peer", "no_challenge", "no_grammar", "no_self_consistency"])
def test_matched_experiments_remove_only_the_selected_mechanism(
    prepared: base.Preparation,
    tmp_path: Path,
    method: Method,
) -> None:
    plan = plumb.prepare(prepared, 40, method=method)
    judge = Judge()
    result = plumb.execute(
        prepared,
        plan,
        tmp_path / "run.json",
        Settings(data_dir=tmp_path / "data"),
        fixture_model=judge,
    )
    assert result.state == "completed", result.model_dump()
    assert plan.preparation_sha256 == digest(prepared)
    metrics: Any = plumb.account(prepared, plan, result)
    assert metrics["experimental_method"] and metrics["release_acceptance"] == "unassessed"
    assert metrics["metrics"]["paired_discrimination"]["trials"] == 1
    expected = 0 if method == "no_challenge" else 1 if method == "no_self_consistency" else 3
    assert plan.judgments == expected
    for record in result.records:
        assert record.questions[0].answer
        answer: Any = record.questions[0].answer
        samples = answer["result"]["samples"]
        assert len(samples) == expected
        assert [s["seed"] for s in samples] == [42 + n for n in range(expected)]
        assert answer["finding"]["runtime_verification"] == "not_attempted"
        if method == "no_challenge":
            assert "Experimental" in answer["result"]["rationale"]
        assert all(
            ("response_format" in r.body) is (method != "no_grammar") for r in record.requests
        )
    assert len([r for r in judge.requests if r.name == "sink_safety"]) == expected * 2
    assert not list((tmp_path / "data/cache").glob("plumb-packet-*"))


def test_unavailable_verification_stays_unrun_without_diagnostics_or_assets(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plumb, "machine_state", lambda: pytest.fail("Diagnostics for unavailable experiment")
    )
    monkeypatch.setattr(
        plumb.profiles, "create", lambda *_: pytest.fail("Model for unavailable experiment")
    )
    plan = plumb.prepare(prepared, 40, method="no_verification")
    result = plumb.execute(
        prepared, plan, tmp_path / "run.json", Settings(data_dir=tmp_path / "data")
    )
    assert result.state == "unrun" and result.finished_at and result.observations["unavailable"]
    assert all(r.state == "unrun" and not r.requests and not r.snapshot for r in result.records)
    metrics: Any = plumb.account(prepared, plan, result)
    assert metrics["state"] == "unrun" and len(metrics["unprocessed_cases"]) == 2
    assert metrics["metrics"]["recall"]["injection"]["successes"] == 0
    with pytest.raises(ValueError, match="unrun"):
        plumb.account(prepared, plan, result.model_copy(update={"state": "failed"}))
    assert not (tmp_path / "data").exists()


def test_grammar_omission_keeps_every_other_request_option_and_parsing_contract() -> None:
    request = ModelRequest(
        name="fixture",
        system="JSON only",
        user="source",
        schema={"type": "object"},
        thinking=False,
        seed=44,
        temperature=0.1,
    )
    expected = request.body()
    expected.pop("response_format")
    unconstrained = request_without_grammar(request)
    assert unconstrained.body() == expected and unconstrained.schema == request.schema
    assert "response_format" in request.body()  # Original never mutated.


@pytest.mark.parametrize("method", METHODS)
def test_method_and_judgment_tampering_refuse(
    prepared: base.Preparation,
    method: Method,
) -> None:
    plan = plumb.prepare(prepared, 20, method=method)
    changed = plan.model_copy(update={"judgments": 3 if plan.judgments != 3 else 1})
    with pytest.raises(ValueError, match="judgment"):
        plumb.check(prepared, changed)
    assert plumb.prepare(prepared, 20).method == "full_plumb"
    assert plumb.prepare(prepared, 20).judgments == 3


def test_peer_omission_never_votes_or_classifies_other_accesses(
    review: Review,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run:peer-ablation"
    questions, coverage, _ = review.questions(run_id, ["Order"], ["/orders/{order_id}/receipt"])
    assert len(questions) == 1
    runs = RunStore(tmp_path / "runs.sqlite")
    runs.create(
        ReviewRun(
            id=run_id,
            snapshot_id=review.snapshot.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.QUEUED,
            created_at=datetime.now(UTC),
            coverage=coverage,
        ),
        questions,
    )
    monkeypatch.setattr(
        "agent.peers.consensus", lambda *_: pytest.fail("Peer consensus in no-peer experiment")
    )
    model = Model()
    workflow = StudyWorkflow(
        review, runs, run_id, model, tmp_path / "guard.sqlite", "no-peer fixture", 1
    )
    workflow.method = "no_peer"
    challenge = workflow.challenge
    assert not challenge.result.groups
    assert [f.site_id for f in challenge.result.checks] == questions[0].subject_ids
    assert {p.site.id for p in challenge.access.accesses} == set(questions[0].subject_ids)
    result = challenge.investigate(
        questions[0].subject_ids[0], Spend(Budget(max_prompt_tokens=16000))
    )
    assert len(result.samples) == 3 and result.peer_group_id is None
    assert result.conclusion is Conclusion.CANDIDATE  # No inferred owner policy from omitted peers.


@pytest.mark.parametrize("judgments", [1, 3])
def test_sink_counts_with_source_validator_and_default_production_three(
    sink_context: SinkInvestigator,
    judgments: int,
) -> None:
    signal = next(
        s for s, (_, fact) in sink_context.facts.items() if fact.function == "command_good"
    )
    model = SinkJudge(["parameterized"] * judgments)
    result = sink_context.investigate(signal, model, Spend(Budget()), judgments=judgments)
    assert len(result.samples) == judgments and result.conclusion is Conclusion.REJECTED
    assert [r.seed for r in model.requests] == [42 + n for n in range(judgments)]


@pytest.mark.parametrize("judgments", [0, 2, True])
def test_arbitrary_sample_counts_never_weaken_an_investigator(
    sink_context: SinkInvestigator, judgments: int
) -> None:
    signal = next(iter(sink_context.facts))
    model = SinkJudge([])
    with pytest.raises(ValueError):
        sink_context.investigate(signal, model, Spend(Budget()), judgments=judgments)
    assert not model.requests


@pytest.mark.parametrize("policy", [False, True])
def test_nextjs_single_sample_covers_both_policy_dispatches(tmp_path: Path, policy: bool) -> None:
    with context(tmp_path, {"app/actions.ts": ACTION.replace("'./", "'../")}) as frozen:
        judge = BoundaryJudge()
        if policy:
            from backend.contracts.code import GuardKind

            entry = declare(frozen, required=GuardKind.AUTHENTICATED)
        else:
            entry = next(e.entry.id for e in frozen.nextjs.entries)
        result = investigator(frozen, judge).investigate(
            entry, judge, Spend(Budget(max_prompt_tokens=16000)), judgments=1
        )
        assert len(result.samples) == 1
        assert all(r.seed == 42 for r in judge.requests)


def test_no_challenge_boundary_has_explicit_unknown_instead_of_empty_safe_result(
    tmp_path: Path,
) -> None:
    with context(tmp_path, {"app/page.tsx": PAGE, "app/Client.tsx": CLIENT}) as frozen:
        run_id = "run:no-boundary-challenge"
        questions, coverage, _ = frozen.questions(run_id, [], [], (Family.NEXTJS_EXPOSURE,))
        runs = RunStore(tmp_path / "runs.sqlite")
        runs.create(
            ReviewRun(
                id=run_id,
                snapshot_id=frozen.snapshot.id,
                run_type=RunType.LIVE,
                lifecycle=RunLifecycle.QUEUED,
                created_at=datetime.now(UTC),
                coverage=coverage,
            ),
            questions,
        )
        workflow = StudyWorkflow(
            frozen,
            runs,
            run_id,
            BoundaryJudge(),
            tmp_path / "guards.sqlite",
            "no-challenge fixture",
            10,
        )
        workflow.method = "no_challenge"
        workflow.run()
        rows = runs.questions(run_id)
        assert rows and all(q.answer for q in rows)
        for row in rows:
            answer: Any = row.answer
            assert answer["finding"]["conclusion"] == "inconclusive"
            assert not answer["result"]["samples"] and answer["result"]["issues"]


def test_public_workflow_default_still_requires_three_and_does_not_select_experiments(
    review: Review,
    tmp_path: Path,
) -> None:
    workflow = Workflow(
        review,
        RunStore(tmp_path / "unused.sqlite"),
        "run:unused",
        Model(),
        tmp_path / "guards.sqlite",
        "fixture",
        1,
    )
    assert workflow.judgments == 3 and not hasattr(workflow, "method")


def test_offline_cli_selects_an_explicit_pinned_experiment(
    prepared: base.Preparation, tmp_path: Path
) -> None:
    source, output = tmp_path / "preparation.json", tmp_path / "plan.json"
    write_new(source, prepared)
    assert (
        plumb.main(
            [
                "prepare",
                str(source),
                "--method",
                "no_self_consistency",
                "--max-requests",
                "20",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    plan = plumb.Plan.model_validate_json(output.read_bytes())
    assert plan.method == "no_self_consistency" and plan.judgments == 1
    assert json.loads(output.read_bytes())["final_candidate"] is False


def test_authorization_without_challenge_retains_source_peer_lead_and_no_judgments(
    review: Review,
    tmp_path: Path,
) -> None:
    class SourceModel(Model):
        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            if request.name == "intentional_exception":
                pytest.fail("Acquittal request in the no-challenge experiment")
            return super().ask(request, spend)

    run_id = "run:authorization-no-challenge"
    questions, coverage, _ = review.questions(run_id, ["Order"], ["/orders/{order_id}/receipt"])
    runs = RunStore(tmp_path / "runs.sqlite")
    runs.create(
        ReviewRun(
            id=run_id,
            snapshot_id=review.snapshot.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.QUEUED,
            created_at=datetime.now(UTC),
            coverage=coverage,
        ),
        questions,
    )
    workflow = StudyWorkflow(
        review, runs, run_id, SourceModel(), tmp_path / "guards.sqlite", "no-challenge fixture", 1
    )
    workflow.method = "no_challenge"
    workflow.run()
    answer: Any = runs.questions(run_id)[0].answer
    assert answer and not answer["result"]["samples"]
    assert answer["finding"]["conclusion"] == "supported"
    assert answer["finding"]["runtime_verification"] == "not_attempted"
    assert "Experimental" in answer["result"]["rationale"]
    assert answer["peer_result"]["groups"]


def test_without_grammar_actual_adapter_still_refuses_malformed_raw_json(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = Server(ok=True)
    monkeypatch.setattr(plumb.profiles, "create", lambda *_: fake)
    monkeypatch.setattr(plumb, "machine_state", lambda: {"software_fixture": True})
    plan = plumb.prepare(prepared, 40, method="no_grammar")
    result = plumb.execute(
        prepared, plan, tmp_path / "run.json", Settings(data_dir=tmp_path / "data")
    )
    assert result.state == "failed" and fake.starts == fake.stops == 1
    for record in result.records:
        assert record.state == "failed"
        assert record.requests[0].raw_answer == "not JSON"
        assert "response_format" not in record.requests[0].body
    metrics: Any = plumb.account(prepared, plan, result)
    assert metrics["metrics"]["paired_discrimination"]["successes"] == 0
