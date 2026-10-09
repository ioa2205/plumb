"""Offline fixture accounting, matched packets and negative replay boundaries."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from eval.baselines import development as base
from eval.candidate import write_new
from eval.mutation import development as corpus
from eval.mutation.corpus import build as legacy_build
from eval.mutation.extended_fixtures import FIXTURES


@pytest.fixture(scope="module")
def prepared() -> base.Preparation:
    t = next(t for t in corpus.development_templates() if t.name == "order_receipt")
    cases = [
        corpus.Case(
            id=v.id,
            template=v.template,
            operator=v.operator,
            family=v.family,
            label=v.label,
            cwe=v.cwe,
            entry=v.handler,
            sources={"api/input.py": v.source},
            control_id=f"{v.template}/original",
        )
        for v in legacy_build([t])
    ]
    return base.prepare(
        cases, hypothesis="Offline software boundary fixture only.", max_attempts=10, max_seconds=60
    )


def digest(p: base.Preparation) -> str:
    return corpus.sha(corpus.canonical(p.model_dump(mode="json")))


def result(p: base.Preparation, *, method: base.Method = "one_shot") -> base.SavedRun:
    raw = '{"findings":[]}' if method == "one_shot" else '{"results":[],"errors":[]}'
    return base.SavedRun(
        preparation_sha256=digest(p),
        method=method,
        evidence_kind="software_fixture",
        state="completed",
        records=[
            base.SavedRecord(
                case_id=c.id,
                packet_sha256=packet.sha256,
                state="completed",
                raw=raw,
                seconds=1,
                prompt_tokens=10 if method == "one_shot" else 0,
                completion_tokens=1 if method == "one_shot" else 0,
            )
            for c, packet in zip(p.cases, base.check(p), strict=True)
        ],
    )


def finding(p: base.Packet, *, path: str | None = None) -> dict[str, object]:
    return {
        "path": path or p.focus.path,
        "family": "authorization",
        "start_line": p.focus.start_line,
        "end_line": p.focus.end_line,
        "explanation": "Fixture observation",
    }


def scanner(p: base.Packet) -> dict[str, object]:
    return {
        "check_id": "plumb.authz.load-by-id-without-owner-comparison",
        "path": p.focus.path,
        "start": {"line": p.focus.start_line},
        "end": {"line": p.focus.end_line},
        "extra": {"metadata": {"family": "authorization"}},
    }


def test_public_packets_are_identical_and_do_not_carry_evaluator_labels(
    prepared: base.Preparation,
) -> None:
    for case, p in zip(prepared.cases, base.check(prepared), strict=True):
        public = json.dumps(base.request(p))
        assert case.id not in public and case.template not in public
        assert '"label"' not in public and '"control_id"' not in public
        assert p.sources == case.sources
        assert corpus.sha(corpus.canonical(p.model_dump(mode="json"))) == p.sha256
        assert base.request(p)["max_tokens"] == 600
        assert prepared.configuration["production_judgments"] == 3


def test_offline_configuration_never_creates_a_model_or_loads_a_split(
    monkeypatch: pytest.MonkeyPatch, prepared: base.Preparation
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("offline adapter started an engine or opened a split")

    monkeypatch.setattr("backend.profiles.create", forbidden)
    monkeypatch.setattr("eval.splits.load", forbidden)
    assert base.check(prepared)


@pytest.mark.parametrize("field", ["configuration", "dataset_sha256"])
def test_preparation_drift_refuses(prepared: base.Preparation, field: str) -> None:
    value = {} if field == "configuration" else "0" * 64
    with pytest.raises(ValueError):
        base.check(prepared.model_copy(update={field: value}))


def test_changed_label_source_counterpart_or_duplicate_case_refuses(
    prepared: base.Preparation,
) -> None:
    vulnerable = next(c for c in prepared.cases if c.label == "vulnerable")
    for changed in (
        vulnerable.model_copy(update={"label": "safe"}),
        vulnerable.model_copy(update={"sources": {"api/input.py": "x = 1\n"}}),
    ):
        with pytest.raises(ValueError):
            base.check(
                prepared.model_copy(
                    update={
                        "cases": [changed, *[c for c in prepared.cases if c.id != vulnerable.id]]
                    }
                )
            )
    for subset in (
        [vulnerable, vulnerable],
        [c for c in prepared.cases if c.operator != "original"],
    ):
        with pytest.raises(ValueError):
            base.check(prepared.model_copy(update={"cases": subset}))


@pytest.mark.parametrize(
    "change",
    [
        {"path": "../outside.py"},
        {"path": "C:/outside.py"},
        {"path": "api/input.py:stream"},
        {"path": "README.md"},
        {"end_line": 10000},
        {"start_line": 30, "end_line": 1},
        {"start_line": True},
        {"family": "unknown"},
        {"extra": "x"},
    ],
)
def test_model_answers_refuse_invalid_paths_ranges_types_and_extras(
    prepared: base.Preparation, change: dict[str, object]
) -> None:
    p = base.check(prepared)[0]
    with pytest.raises(ValueError):
        base.raw_predictions(json.dumps({"findings": [{**finding(p), **change}]}), "one_shot", p)


def test_empty_answers_are_valid_and_duplicate_json_or_truncation_are_unparseable(
    prepared: base.Preparation,
) -> None:
    p = base.check(prepared)[0]
    assert base.raw_predictions('{"findings":[]}', "one_shot", p) == []
    for raw in ('{"findings":[],"findings":[]}', '{"findings":', "[]", " " * 1_000_001):
        with pytest.raises(ValueError):
            base.raw_predictions(raw, "one_shot", p)


def test_scanner_records_bind_to_pinned_rules_and_merge_like_the_legacy_baseline(
    prepared: base.Preparation,
) -> None:
    p = base.check(prepared)[0]
    row = scanner(p)
    assert (
        len(base.raw_predictions(json.dumps({"results": [row, row], "errors": []}), "opengrep", p))
        == 1
    )
    for bad in (
        {**row, "check_id": "unknown-rule"},
        {**row, "extra": {"metadata": {"family": "injection"}}},
        {**row, "path": "/outside.py"},
    ):
        with pytest.raises(ValueError):
            base.raw_predictions(json.dumps({"results": [bad], "errors": []}), "opengrep", p)
    with pytest.raises(ValueError):
        base.raw_predictions('{"results":[],"errors":[{"message":"partial scan"}]}', "opengrep", p)


def test_wrong_family_or_duplicate_model_findings_remain_false_positives(
    prepared: base.Preparation,
) -> None:
    p = base.check(prepared)[0]
    row = {**finding(p), "family": "injection"}
    predictions = base.raw_predictions(json.dumps({"findings": [row, row]}), "one_shot", p)
    assert len(predictions) == 2 and all(r.family.value == "injection" for r in predictions)


def test_failure_and_unparseable_records_retain_denominators_and_raw_output(
    prepared: base.Preparation,
) -> None:
    run = result(prepared)
    rows = [
        r.model_copy(update={"raw": "{bad"}) if c.label == "vulnerable" else r
        for c, r in zip(prepared.cases, run.records, strict=True)
    ]
    accounted: Any = base.account(prepared, run.model_copy(update={"records": rows}))
    assert accounted["state"] == "failed" and accounted["release_acceptance"] == "unassessed"
    assert accounted["evidence_kind"] == "software_fixture"
    assert accounted["metrics"]["recall"]["authorization"]["trials"] == 2
    assert accounted["metrics"]["abstention_rate"]["successes"] == 2
    assert sum(row["state"] == "unparseable" for row in accounted["records"]) == 2
    assert any(row["raw_record"]["raw"] == "{bad" for row in accounted["records"])


def test_shared_controls_are_counted_once_and_pair_links_count_as_misses_if_unrun(
    prepared: base.Preparation,
) -> None:
    run = result(prepared)
    packets = base.check(prepared)
    rows = [
        r.model_copy(update={"raw": json.dumps({"findings": [finding(p)]})})
        if c.label == "vulnerable"
        else r
        for c, p, r in zip(prepared.cases, packets, run.records, strict=True)
    ]
    accounted: Any = base.account(prepared, run.model_copy(update={"records": rows}))
    assert accounted["metrics"]["paired_discrimination"]["successes"] == 2
    assert accounted["metrics"]["defended_false_positive_rate"]["trials"] == 3
    rows = [
        r.model_copy(
            update={
                "state": "unrun",
                "raw": None,
                "error": "not run",
                "seconds": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
        )
        if c.operator == "original"
        else r
        for c, r in zip(prepared.cases, rows, strict=True)
    ]
    partial: Any = base.account(
        prepared, run.model_copy(update={"records": rows, "state": "failed"})
    )
    assert partial["metrics"]["paired_discrimination"]["trials"] == 2
    assert partial["metrics"]["paired_discrimination"]["successes"] == 0


@pytest.mark.parametrize("change", ["packet", "subset", "duplicate", "preparation", "budget"])
def test_mismatched_inputs_or_omitted_results_cannot_claim_matched_completion(
    prepared: base.Preparation, change: str
) -> None:
    run = result(prepared)
    if change == "packet":
        run = run.model_copy(
            update={
                "records": [
                    run.records[0].model_copy(update={"packet_sha256": "0" * 64}),
                    *run.records[1:],
                ]
            }
        )
    elif change == "subset":
        run = run.model_copy(update={"records": run.records[:-1]})
    elif change == "duplicate":
        run = run.model_copy(update={"records": [run.records[0], *run.records[:-1]]})
    elif change == "preparation":
        run = run.model_copy(update={"preparation_sha256": "0" * 64})
    else:
        run = run.model_copy(
            update={"records": [r.model_copy(update={"seconds": 30}) for r in run.records]}
        )
    with pytest.raises(ValueError):
        base.account(prepared, run)


def test_budget_overruns_and_replay_labels_are_retained_only_as_failed_batches(
    prepared: base.Preparation,
) -> None:
    run = result(prepared).model_copy(
        update={"state": "failed", "evidence_kind": "saved_answer_replay"}
    )
    run = run.model_copy(
        update={"records": [r.model_copy(update={"seconds": 30}) for r in run.records]}
    )
    accounted: Any = base.account(prepared, run)
    assert accounted["budget_exceeded"] is True and accounted["state"] == "failed"
    assert accounted["evidence_kind"] == "saved_answer_replay"
    with pytest.raises(ValidationError):
        base.SavedRun.model_validate({**run.model_dump(), "evidence_kind": "fresh_local"})
    with pytest.raises(ValidationError):
        base.SavedRun.model_validate({**run.model_dump(), "method": "full_plumb"})


def test_multifile_nextjs_focus_and_policy_are_packet_bound_and_readme_cannot_be_a_citation() -> (
    None
):
    fixture = next(f for f in FIXTURES if f.name == "v2_client_projection")
    case = corpus.Case(
        id="v2_client_projection/original",
        template=fixture.name,
        operator="original",
        family=fixture.family,
        label="safe",
        cwe=None,
        entry=fixture.entry,
        sources=fixture.sources,
        control_id="v2_client_projection/original",
        allowed_client_fields=("id", "amount"),
    )
    p = base.packet(case)
    assert p.focus.path == "app/orders/page.tsx" and len(p.sources) == 2
    assert p.allowed_client_fields == ("id", "amount")
    assert p.sha256 != p.model_copy(update={"allowed_client_fields": ()}).sha256
    with pytest.raises(ValidationError):
        base.Packet.model_validate(
            {**p.model_dump(), "focus": {"path": "README.md", "start_line": 1, "end_line": 1}}
        )


def test_actual_cli_fixture_accounting_is_exclusive_and_cannot_open_final_or_sealed(
    tmp_path: Path, prepared: base.Preparation
) -> None:
    plan_path, run_path, output = (
        tmp_path / "preparation.json",
        tmp_path / "run.json",
        tmp_path / "account.json",
    )
    write_new(plan_path, prepared)
    write_new(run_path, result(prepared))
    assert base.main(["check", str(plan_path)]) == 0
    assert base.main(["account", str(plan_path), str(run_path), "--output", str(output)]) == 0
    actual = json.loads(output.read_bytes())
    assert (
        actual["evidence_kind"] == "software_fixture"
        and actual["release_acceptance"] == "unassessed"
    )
    assert base.main(["account", str(plan_path), str(run_path), "--output", str(output)]) == 1
    for args in (["test"], ["execute"], ["check", str(plan_path), "--open-sealed"]):
        with pytest.raises(SystemExit):
            base.main(args)
