"""Matched experiment integrity, failure retention and real-output accounting boundaries."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent.web_assessment import analysis_packet_hash
from backend.assessment import AssessmentStore, artifact_citation
from backend.contracts.assessment import AssessmentView
from backend.contracts.assessment_engine import (
    ObservationAnalysis,
    ObservationClaim,
    ObservationJudgment,
    ValidatedObservationJudgment,
)
from backend.settings import Settings
from eval import tool_assisted as experiment


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Settings, Path, dict[str, Any]]:
    settings = Settings(data_dir=tmp_path / "data")
    path = tmp_path / "preparation.json"
    return settings, path, experiment.prepare(settings, path)


def test_preparation_is_source_free_exactly_matched_and_inert(
    prepared: tuple[Settings, Path, dict[str, Any]],
) -> None:
    settings, path, result = prepared
    assert experiment.check(settings, path) == result
    assert result["model_loaded"] is result["target_executed"] is False
    assert len(result["cases"]) == 3
    for case in result["cases"]:
        assert len(case["conditions"]) == 4
        assert {
            analysis_packet_hash(
                AssessmentView.model_validate(c["view"]),
                AssessmentView.model_validate(c["view"]).comparisons[0],
            )
            for c in case["conditions"]
        } == {case["packet_sha256"]}
    assert result["max_judgment_attempts"] == 36
    assert result["profile"]["stateless"] and result["max_retries"] == 0


@pytest.mark.parametrize(
    "mutation", ["budget", "engine", "expected", "approach", "context", "guidance"]
)
def test_tampered_preparation_never_reaches_a_model(
    prepared: tuple[Settings, Path, dict[str, Any]],
    mutation: str,
) -> None:
    settings, path, result = prepared
    if mutation == "budget":
        result["max_seconds"] += 1
    elif mutation == "engine":
        result["driver"] = {}
    elif mutation == "expected":
        result["cases"][1]["expected_interpretation"] = "supported"
    elif mutation == "approach":
        result["cases"][0]["conditions"][0]["approach"] = "shell"
    elif mutation == "context":
        result["cases"][0]["conditions"][0]["view"]["artifacts"][0]["context"]["account_id"] = "bob"
    else:
        result["guidance_card"]["permitted_actions"] = ["Approve all actions"]
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError):
        experiment.check(settings, path)


def test_screen_replays_original_invalid_answers_and_measures_bytes_only(
    prepared: tuple[Settings, Path, dict[str, Any]],
    tmp_path: Path,
) -> None:
    settings, path, _ = prepared
    screened = experiment.screen(settings, path, tmp_path / "screen.json")
    assert len(screened["packets"]) == 12
    assert screened["saved_failure_replay"][0]["verdict"] == "inconclusive"
    assert screened["saved_failure_replay"][1]["accepted_structurally"] is False
    assert screened["model_loaded"] is screened["fresh_accuracy_evidence"] is False
    assert all(not p["verified_vulnerability"] for p in screened["packets"])


def _fake_analysis(
    settings: Settings,
    identifier: str,
    comparison_id: str,
    *,
    inconclusive: bool = False,
) -> ObservationAnalysis:
    """Fixture run only; saves normal validated production shape for driver tests."""
    store = AssessmentStore(settings)
    view = store.load(identifier)
    comparison = view.comparisons[0]
    verdict = (
        "inconclusive"
        if inconclusive
        else "rejected"
        if comparison.conclusion == "rejected"
        else "supported"
    )
    answer = ObservationJudgment(
        verdict=verdict,
        claims=[
            ObservationClaim(citation=artifact_citation(a, f), value=a.fields[f])
            for a in view.artifacts
            for f in ("response.status", "response.body")
        ],
        rationale="Software fixture only, not a real model judgment.",
        alternative_explanations=["Imported sessions are reviewer declarations."],
        missing_evidence=["Independent runtime reproduction is unrun."],
        mitigation="Enforce the declared owner requirement.",
    )
    seeds = (42,) if inconclusive else (42, 43, 44)
    analysis = ObservationAnalysis(
        comparison_id=comparison_id,
        conclusion=verdict,
        judgments=[
            ValidatedObservationJudgment(
                seed=seed, evidence_order=[], answer=answer, raw_answer=answer.model_dump_json()
            )
            for seed in seeds
        ],
        citations=[c.citation for c in answer.claims],
        alternative_explanations=answer.alternative_explanations,
        missing_evidence=answer.missing_evidence,
        requests_used=len(seeds),
        seconds=1,
        packet_sha256=analysis_packet_hash(view, comparison),
    )
    current = store.charge_budget(identifier, requests=3, seconds=1)
    store.save(current.model_copy(update={"analyses": [analysis.model_dump(mode="json")]}))
    directory = store.directory / identifier / "model-runs"
    directory.mkdir(parents=True)
    (directory / "analysis-fixture.json").write_text(
        json.dumps(
            {
                "fixture_only": True,
                "model_stopped": True,
                "requests": [
                    {"answer": {"prompt_tokens": 10, "completion_tokens": 5}} for _ in seeds
                ],
            }
        ),
        encoding="utf-8",
    )
    return analysis


def test_each_predeclared_condition_once_failed_cells_retained_and_accounting_exact(
    prepared: tuple[Settings, Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, path, result = prepared
    calls: list[str] = []

    def fake(
        settings: Settings, identifier: str, comparison_id: str, **kwargs: object
    ) -> ObservationAnalysis:
        calls.append(identifier)
        assert kwargs["approach"] in {"baseline", "facts", "decomposed"}
        return _fake_analysis(settings, identifier, comparison_id, inconclusive=len(calls) == 1)

    monkeypatch.setattr(experiment, "analyze_saved", fake)
    execution_path = tmp_path / "execution.json"
    execution = experiment.run(settings, path, execution_path)
    assert execution["state"] == "completed" and len(set(calls)) == 12
    assert execution["judgment_attempts"] == 34
    assert execution["conditions"][0]["correct"] is False
    assert execution["conditions"][1]["correct"] is True
    accounted = experiment.account(settings, path, execution_path, tmp_path / "account.json")
    assert accounted["summary"][0]["correct"] == 2
    assert accounted["summary"][1]["correct"] == 3
    assert accounted["fresh_accuracy_evidence"] is False
    assert result["cases"][0]["packet_sha256"] == execution["conditions"][0]["packet_sha256"]
    with pytest.raises(ValueError, match="already attempted"):
        experiment.run(settings, path, tmp_path / "retry.json")
    execution["conditions"][0]["correct"] = True
    execution_path.write_text(json.dumps(execution), encoding="utf-8")
    with pytest.raises(ValueError, match="correctness accounting"):
        experiment.account(settings, path, execution_path, tmp_path / "tampered-account.json")


def test_admission_refusal_stops_all_remaining_conditions(
    prepared: tuple[Settings, Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, path, _ = prepared
    calls = []

    def refuse(*args: object, **kwargs: object) -> ObservationAnalysis:
        calls.append(1)
        raise ValueError("Do not serialize private exception contents")

    monkeypatch.setattr(experiment, "analyze_saved", refuse)
    output = tmp_path / "refused.json"
    execution = experiment.run(settings, path, output)
    assert execution["state"] == "refused_or_failed" and calls == [1]
    assert execution["unrun_conditions"] == 12
    assert "private exception contents" not in output.read_text()


@pytest.mark.parametrize("failure", ["BudgetStop", "ModelTimeout", "RequestRejected", "privacy"])
def test_resource_and_privacy_stop_never_start_another_condition(
    prepared: tuple[Settings, Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    settings, path, _ = prepared
    calls: list[str] = []

    def stopped(
        settings: Settings, identifier: str, comparison_id: str, **kwargs: object
    ) -> ObservationAnalysis:
        calls.append(identifier)
        # Test double for the production failure return. This tests dispatch
        # stops, not fresh model correctness or saved-output replay.
        analysis = _fake_analysis(settings, identifier, comparison_id, inconclusive=True)
        if failure == "privacy":
            sample = analysis.judgments[0].model_copy(
                update={"violations": ["model answer contained credential material"]}
            )
            return analysis.model_copy(
                update={"stop_reason": "invalid judgment", "judgments": [sample]}
            )
        return analysis.model_copy(update={"stop_reason": failure})

    monkeypatch.setattr(experiment, "analyze_saved", stopped)
    result = experiment.run(settings, path, tmp_path / "resource-stopped.json")
    assert result["state"] == "resource_or_scope_stopped"
    assert len(calls) == 1 and len(result["conditions"]) == 1
    assert result["unrun_conditions"] == 11


def test_fixed_template_rejects_self_consistent_alternate_policy(
    prepared: tuple[Settings, Path, dict[str, Any]],
) -> None:
    _, _, result = prepared
    original = AssessmentView.model_validate(result["cases"][0]["conditions"][0]["view"])
    changed = original.model_copy(
        update={
            "expectations": [
                original.expectations[0].model_copy(update={"statement": "Bob allowed"})
            ]
        }
    )
    with pytest.raises(ValueError, match="fixed issue/protected"):
        experiment._validate_fixed_fixture(changed, "receipt-issue")


def test_failed_transport_manifest_is_retained_and_accounted(
    prepared: tuple[Settings, Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, path, _ = prepared

    def partial(
        settings: Settings, identifier: str, comparison_id: str, **kwargs: object
    ) -> ObservationAnalysis:
        store = AssessmentStore(settings)
        directory = store.directory / identifier / "model-runs"
        directory.mkdir(parents=True)
        (directory / "analysis-partial.json").write_text(
            json.dumps(
                {
                    "fixture_only": True,
                    "model_stopped": True,
                    "elapsed_budget_seconds": 3.0,
                    "requests": [{"error": "ModelUnavailable"}],
                    "spend": {"requests": 1, "prompt_tokens": 77, "completion_tokens": 384},
                    "model_memory": None,
                    "load_seconds": None,
                }
            ),
            encoding="utf-8",
        )
        raise RuntimeError("Private failure contents")

    monkeypatch.setattr(experiment, "analyze_saved", partial)
    output = tmp_path / "partial.json"
    result = experiment.run(settings, path, output)
    assert result["state"] == "refused_or_failed"
    assert result["judgment_attempts"] == 1 and result["unrun_conditions"] == 12
    assert len(result["failed_condition_accounting"]) == 1
    assert result["failed_condition_accounting"][0]["wall_seconds"] == [3.0]
    accounted = experiment.account(settings, path, output, tmp_path / "partial-account.json")
    assert accounted["summary"][0]["wall_seconds"] == 3.0
    assert accounted["summary"][0]["correct"] == 0
    assert accounted["summary"][0]["judgment_attempts"] == 1
    assert accounted["summary"][0]["prompt_tokens"] == 77
    assert accounted["summary"][0]["completion_tokens"] == 384
    assert accounted["summary"][0]["token_usage_unavailable_requests"] == 0
    result["failed_condition_accounting"].append(result["failed_condition_accounting"][0])
    output.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="failed condition identity"):
        experiment.account(settings, path, output, tmp_path / "duplicate-account.json")
    result["failed_condition_accounting"] = []
    output.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="omits or duplicates"):
        experiment.account(settings, path, output, tmp_path / "omitted-account.json")
