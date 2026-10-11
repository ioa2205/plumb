"""The bounded Task 2 driver prepares only fixture data until an explicit stage."""

import json
from pathlib import Path

import pytest

from backend.assessment import AssessmentStore, artifact_citation
from backend.contracts.assessment_engine import (
    ObservationAnalysis,
    ObservationClaim,
    ObservationJudgment,
    ValidatedObservationJudgment,
)
from backend.settings import Settings
from eval import task2_development


def _fixture_analysis(
    settings: Settings, assessment_id: str, comparison_id: str
) -> ObservationAnalysis:
    """Offline driver fixture; no model launch or fresh accuracy evidence."""
    view = AssessmentStore(settings).load(assessment_id)
    verdict = "rejected" if view.comparisons[0].conclusion == "rejected" else "supported"
    answer = ObservationJudgment.model_validate(
        {
            "verdict": verdict,
            "claims": [
                ObservationClaim(
                    citation=artifact_citation(artifact, field), value=artifact.fields[field]
                )
                for artifact in view.artifacts
                for field in artifact.fields
            ],
            "rationale": "Offline synthetic driver fixture, not model evidence",
            "alternative_explanations": ["Independent collection remains unknown"],
            "missing_evidence": ["Runtime reproduction is untested"],
            "mitigation": "Apply the declared owner policy",
        }
    )
    return ObservationAnalysis(
        comparison_id=comparison_id,
        conclusion=answer.verdict,
        judgments=[
            ValidatedObservationJudgment(
                seed=seed,
                evidence_order=[],
                answer=answer,
                raw_answer=answer.model_dump_json(),
            )
            for seed in (42, 43, 44)
        ],
        citations=[claim.citation for claim in answer.claims],
        alternative_explanations=answer.alternative_explanations,
        missing_evidence=answer.missing_evidence,
        requests_used=3,
        seconds=1,
        packet_sha256="a" * 64,
    )


def test_prepare_has_issue_and_protected_fixture_and_never_executes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("prepare cannot load a model or collect HTTP")

    monkeypatch.setattr(task2_development, "analyze_saved", forbidden)
    monkeypatch.setattr(task2_development, "collect_saved", forbidden)
    settings = Settings(data_dir=tmp_path / "data")
    output = tmp_path / "preparation.json"
    prepared = task2_development.prepare(settings, output)
    assert prepared["model_loaded"] is prepared["target_executed"] is False
    assert prepared["max_judgment_attempts"] == 6 and prepared["max_seconds"] == 600
    store = AssessmentStore(settings)
    for case, expected in zip(prepared["cases"], ("candidate", "rejected"), strict=True):
        view = store.load(case["assessment_id"])
        assert view.comparisons[0].conclusion == expected
        assert view.scope.budget.max_requests == 3
        assert not view.analyses
        assert all("not human acceptance" in item.review.reviewed_by for item in view.artifacts)
        assert all("no live request" in item.provenance for item in view.artifacts)
    assert prepared["driver"] == task2_development.identity()
    with pytest.raises(ValueError, match="already exists"):
        task2_development.prepare(settings, output)


@pytest.mark.parametrize(
    "field,value", [("max_seconds", 601), ("driver", {}), ("max_judgment_attempts", 7)]
)
def test_changed_pin_or_budget_never_reaches_local_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    preparation = tmp_path / "preparation.json"
    prepared = task2_development.prepare(settings, preparation)
    prepared[field] = value
    preparation.write_text(json.dumps(prepared), encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("changed inputs cannot load a model")

    monkeypatch.setattr(task2_development, "analyze_saved", forbidden)
    with pytest.raises(ValueError):
        task2_development.run(settings, preparation, tmp_path / "execution.json")


def test_refusal_is_recorded_without_second_case_or_output_driven_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    preparation = tmp_path / "preparation.json"
    task2_development.prepare(settings, preparation)
    calls: list[str] = []

    def refuse(
        settings: Settings, assessment_id: str, comparison_id: str, **kwargs: object
    ) -> None:
        calls.append(assessment_id)
        raise ValueError("password=do-not-serialize-exception")

    monkeypatch.setattr(task2_development, "analyze_saved", refuse)
    output = tmp_path / "execution.json"
    execution = task2_development.run(settings, preparation, output)
    assert execution["state"] == "refused_or_failed" and len(calls) == 1
    assert execution["error"] == "ValueError"
    assert execution["judgment_attempts"] == 0
    assert "do-not-serialize" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "failure",
    [
        "citation_violation",
        "disagreement",
        "wrong_matching_verdict",
        "partial_judgments",
        "missing_answer",
        "duplicate_seed",
        "budget_stop",
        "judgment_error",
        "inconclusive",
    ],
)
def test_failed_case_stops_before_protected_case_and_retains_exact_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    preparation = tmp_path / "preparation.json"
    prepared = task2_development.prepare(settings, preparation)
    calls: list[str] = []
    recorded: list[ObservationAnalysis] = []

    def analyze(
        settings: Settings, assessment_id: str, comparison_id: str, **kwargs: object
    ) -> ObservationAnalysis:
        calls.append(assessment_id)
        analysis = _fixture_analysis(settings, assessment_id, comparison_id)
        samples = list(analysis.judgments)
        if failure == "citation_violation":
            samples[0] = samples[0].model_copy(update={"violations": ["Invalid exact citation"]})
        elif failure == "disagreement":
            assert samples[1].answer is not None
            samples[1] = samples[1].model_copy(
                update={"answer": samples[1].answer.model_copy(update={"verdict": "rejected"})}
            )
        elif failure == "wrong_matching_verdict" or failure == "inconclusive":
            verdict = "rejected" if failure == "wrong_matching_verdict" else "inconclusive"
            samples = [
                sample.model_copy(
                    update={"answer": sample.answer.model_copy(update={"verdict": verdict})}
                )
                for sample in samples
                if sample.answer is not None
            ]
            analysis = analysis.model_copy(update={"conclusion": verdict})
        elif failure == "partial_judgments":
            samples = samples[:2]
        elif failure == "missing_answer":
            samples[0] = samples[0].model_copy(update={"answer": None})
        elif failure == "duplicate_seed":
            samples[1] = samples[1].model_copy(update={"seed": samples[0].seed})
        elif failure == "budget_stop":
            analysis = analysis.model_copy(update={"stop_reason": "seconds budget exhausted"})
        elif failure == "judgment_error":
            samples[0] = samples[0].model_copy(update={"error": "ModelError"})
        analysis = analysis.model_copy(update={"judgments": samples, "requests_used": len(samples)})
        recorded.append(analysis)
        return analysis

    monkeypatch.setattr(task2_development, "analyze_saved", analyze)
    output = tmp_path / "execution.json"
    execution = task2_development.run(settings, preparation, output)
    assert execution["state"] == "failed"
    assert calls == [prepared["cases"][0]["assessment_id"]]
    assert len(execution["case_results"]) == 1
    assert execution["case_results"][0]["analysis"] == recorded[0].model_dump(mode="json")
    assert execution["case_results"][0]["acceptance_passed"] is False
    assert execution["judgment_attempts"] == len(recorded[0].judgments)
    assert json.loads(output.read_text())["case_results"] == execution["case_results"]
    assert execution["max_judgment_attempts"] == 6 and execution["max_seconds"] == 600
    protected = AssessmentStore(settings).load(prepared["cases"][1]["assessment_id"])
    assert not protected.analyses and protected.spent_requests == protected.spent_seconds == 0


def test_two_matching_valid_fixture_cases_complete_without_relaxing_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    preparation = tmp_path / "preparation.json"
    prepared = task2_development.prepare(settings, preparation)
    calls: list[str] = []

    def analyze(
        settings: Settings, assessment_id: str, comparison_id: str, **kwargs: object
    ) -> ObservationAnalysis:
        calls.append(assessment_id)
        return _fixture_analysis(settings, assessment_id, comparison_id)

    monkeypatch.setattr(task2_development, "analyze_saved", analyze)
    execution = task2_development.run(settings, preparation, tmp_path / "execution.json")
    assert execution["state"] == "completed"
    assert calls == [case["assessment_id"] for case in prepared["cases"]]
    assert execution["judgment_attempts"] == execution["max_judgment_attempts"] == 6
    assert execution["max_seconds"] == 600
    assert all(row["acceptance_passed"] for row in execution["case_results"])
    assert [row["analysis"]["conclusion"] for row in execution["case_results"]] == [
        "supported",
        "rejected",
    ]
    assert execution["runtime_verification"] == "not_attempted"


def test_collection_refusal_retains_pending_human_review_and_no_auto_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")

    def refuse(*args: object, **kwargs: object) -> None:
        raise ValueError("Pinned lab unavailable")

    monkeypatch.setattr(task2_development, "lab_preview", refuse)
    result = task2_development.collect(settings, tmp_path / "collection.json")
    assert result["state"] == "refused_or_failed"
    assert result["human_attachment_review"] == "pending"
    assert result["automatic_import"] is result["model_loaded"] is False
    assert not AssessmentStore(settings).load(result["assessment_id"]).artifacts


@pytest.mark.parametrize(
    "change", ["label", "expected", "swapped", "duplicated", "renamed_artifact", "changed_body"]
)
def test_generic_two_hash_valid_cases_cannot_replace_fixed_exercise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    preparation = tmp_path / "preparation.json"
    prepared = task2_development.prepare(settings, preparation)
    case = prepared["cases"][0]
    if change == "label":
        case["case_id"] = "easier-replacement"
    elif change == "expected":
        case["expected_interpretation"] = "inconclusive"
    elif change == "swapped":
        prepared["cases"].reverse()
    elif change == "duplicated":
        prepared["cases"][1] = dict(case)
    else:
        store = AssessmentStore(settings)
        original = store.load(case["assessment_id"])
        replacement_scope = task2_development._scope("replacement-fixture")
        store.create(replacement_scope)
        records = task2_development._fixture_records(replacement_scope, protected=False)
        if change == "renamed_artifact":
            records[0]["provenance"] = "Replacement fixture"
        else:
            records[0]["response"] = {
                "status": 200,
                "headers": {},
                "body": "A generic public response",
            }
        from datetime import UTC, datetime

        review = original.artifacts[0].review.model_copy(update={"reviewed_at": datetime.now(UTC)})
        store.import_records("replacement-fixture", json.dumps({"records": records}), review)
        store.add_expectation("replacement-fixture", original.expectations[0])
        comparison = store.add_comparison("replacement-fixture", original.comparisons[0].request)
        changed = store.load("replacement-fixture")
        case["assessment_id"] = "replacement-fixture"
        case["comparison_id"] = comparison.comparison_id
        case["input_sha256"] = task2_development._hash(changed.model_dump(mode="json"))
    preparation.write_text(json.dumps(prepared), encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("a substituted two-case exercise cannot load a model")

    monkeypatch.setattr(task2_development, "analyze_saved", forbidden)
    with pytest.raises(ValueError):
        task2_development.run(settings, preparation, tmp_path / "execution.json")
