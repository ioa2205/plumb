"""Closed-type admission and fresh publication boundaries; no real model is loaded."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.intent import MESSAGE_INTENT
from backend.local_model import Loaded
from backend.model_qualification import (
    Qualifications,
    intent_reason,
    kept,
    layer_identity,
    publish,
    question_identity,
)
from backend.profiles import REGISTRY
from backend.settings import Settings
from eval.capability_map import cases, identity, prepare


def record(catalog: Qualifications, **changes: object) -> None:
    value = {
        "kind": "production_closed_qualification",
        "origin": "fresh_local_capability_map",
        "pins": catalog.pins,
        "implementation": layer_identity(),
        "types": {
            MESSAGE_INTENT.name: {
                "cases": 10,
                "asked": 10,
                "correct": 10,
                "wrong_accepted_on_cannot_tell_cases": 0,
                "question_sha256": question_identity(MESSAGE_INTENT),
            },
        },
        **changes,
    }
    catalog.path.parent.mkdir(parents=True, exist_ok=True)
    catalog.path.write_text(json.dumps(value))


def test_missing_failed_or_changed_identity_cannot_admit_a_production_type(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    catalog = Qualifications(settings, REGISTRY["cpu-8k"].identity())
    assert catalog.reason(MESSAGE_INTENT) is not None
    record(catalog)
    assert catalog.reason(MESSAGE_INTENT) is None
    assert intent_reason(settings, "cpu-8k", MESSAGE_INTENT) is None
    assert catalog.reason(replace(MESSAGE_INTENT, ask="A different question?")) is not None
    value = json.loads(catalog.path.read_bytes())
    value["types"][MESSAGE_INTENT.name]["correct"] = 4
    catalog.path.write_text(json.dumps(value))
    assert catalog.reason(MESSAGE_INTENT) is not None
    record(catalog, implementation={})
    assert catalog.reason(MESSAGE_INTENT) is not None
    record(catalog, pins={})
    assert catalog.reason(MESSAGE_INTENT) is not None
    record(catalog, origin="replay")
    assert catalog.reason(MESSAGE_INTENT) is not None


@pytest.mark.parametrize(
    "bad",
    [
        {"cases": 3, "asked": 3, "correct": 3, "wrong_accepted_on_cannot_tell_cases": 0},
        {"cases": 10, "asked": 10, "correct": 4, "wrong_accepted_on_cannot_tell_cases": 0},
        {"cases": 10, "asked": 9, "correct": 9, "wrong_accepted_on_cannot_tell_cases": 0},
        {"cases": 10, "asked": 10, "correct": 9, "wrong_accepted_on_cannot_tell_cases": 1},
        {"cases": 10, "asked": 10, "correct": 11, "wrong_accepted_on_cannot_tell_cases": 0},
    ],
)
def test_qualification_keep_rule_rejects_failed_or_incomplete_measurements(bad: dict) -> None:
    assert kept(bad) is False


def test_a_fixture_loaded_object_or_replay_summary_cannot_publish(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    loaded = Loaded(object(), REGISTRY["cpu-8k"])  # ty: ignore[invalid-argument-type]
    assert publish(settings, loaded, {}, {}, {}, {}) is None
    assert not (settings.cache_dir / "closed-questions").exists()


def test_publication_regrades_raw_answers_and_binds_exact_pins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only this temporary unit fixture substitutes the live witness. It measures
    # no model and never writes to a user's production data directory.
    monkeypatch.setattr("backend.local_model.verified_runtime", lambda _: True)
    settings = Settings(data_dir=tmp_path / "data")
    prepared = prepare(
        settings,
        tmp_path / "prep.json",
        profile="cpu-8k",
        question_types=("next_step",),
    )
    selected = [
        (case_id, question, want)
        for case_id, question, want in cases()
        if question.kind.name == "next_step"
    ]
    rows = []
    for case_id, question, want in selected:
        answer = (
            want
            if want.startswith("cannot_tell:")
            else str(
                next(index for index, item in enumerate(question.menu, start=1) if item.key == want)
            )
        )
        value, abstained, violation = question.grade({"answer": answer})
        rows.append(
            {
                "case_id": case_id,
                "question_type": question.kind.name,
                "variant": 0,
                "raw": json.dumps({"answer": answer}),
                "value": value,
                "abstained": abstained,
                "violation": violation,
                "error": None,
            }
        )
    profile = REGISTRY["cpu-8k"]
    loaded = Loaded(object(), profile)  # ty: ignore[invalid-argument-type]
    executed = {
        "model_loaded": True,
        "manifest": {"model_stopped": True, "profile": profile.identity()},
        "closed": rows,
        "preparation_sha256": "test",
    }
    accounting = {
        "types": {
            "next_step": {
                "cases": 4,
                "asked": 4,
                "correct": 4,
                "wrong_accepted_on_cannot_tell_cases": 0,
            }
        }
    }
    kinds = {question.kind.name: question.kind for _, question, _ in selected}
    path = publish(settings, loaded, prepared, executed, accounting, kinds)
    assert (
        path is not None
        and Qualifications(settings, profile.identity()).reason(kinds["next_step"]) is None
    )
    rows[0]["raw"] = '{"answer":"cannot_tell:no_item_fits"}'
    assert publish(settings, loaded, prepared, executed, accounting, kinds) is None
    rows[0]["raw"] = '{"answer":"2"}'
    prepared["implementation"] = identity() | {"agent/closed.py": "changed"}
    assert publish(settings, loaded, prepared, executed, accounting, kinds) is None
