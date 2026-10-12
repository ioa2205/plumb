"""The capability map's preparation, pin checks and scoring. No model is loaded here."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent.closed import CANNOT_TELL
from backend.settings import Settings
from eval import capability_map
from eval.capability_map import account, cases, check, prepare

PROFILE = "cpu-8k"


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Settings, Path]:
    settings = Settings(data_dir=tmp_path / "data")
    path = tmp_path / "preparation.json"
    prepare(settings, path, profile=PROFILE)
    return settings, path


def test_every_relied_on_type_has_cases_including_cannot_tell_ones() -> None:
    by_type: dict[str, list[str]] = {}
    for _, question, expected in cases():
        by_type.setdefault(question.kind.name, []).append(expected)
    assert set(by_type) == {
        "message_intent",
        "field_meaning",
        "form_purpose",
        "page_kind",
        "next_step",
        "rule_covers",
    }
    for name, expected in by_type.items():
        assert len(expected) >= 4, name
        assert any(answer.startswith(CANNOT_TELL) for answer in expected), name
    # Every expected answer is one the request allows, so a label typo cannot hide.
    for case_id, question, expected in cases():
        if question.kind.menu and not expected.startswith(CANNOT_TELL):
            assert expected in {item.key for item in question.menu}, case_id
        else:
            assert expected in question.allowed(0), case_id
    ids = [case_id for case_id, _, _ in cases()]
    assert len(ids) == len(set(ids)) == 43


def test_preparation_freezes_requests_pins_and_budgets_and_keeps_labels_apart(
    prepared: tuple[Settings, Path],
) -> None:
    settings, path = prepared
    value = json.loads(path.read_bytes())
    assert value["model_loaded"] is False and value["hypothesis"] and value["stop_condition"]
    assert (value["max_requests"], value["max_seconds"]) == (70, 2700)
    assert value["pins"]["profile"]["id"] == PROFILE and value["pins"]["model"]["sha256"]
    assert set(value["implementation"]) >= {"agent/closed.py", "eval/capability_map.py"}
    for row in value["closed_cases"]:
        assert set(row) == {
            "case_id",
            "question_type",
            "system",
            "user",
            "allowed",
            "seed",
            "request_sha256",
        }
        # The fixed text comes first and is the same for every case of a type.
        assert row["system"].startswith("You answer one closed question.")
    systems = {row["question_type"]: set() for row in value["closed_cases"]}
    for row in value["closed_cases"]:
        systems[row["question_type"]].add(row["system"])
    assert all(len(texts) == 1 for texts in systems.values())
    assert len(value["evaluator_only_expected"]) == len(value["closed_cases"])
    assert check(settings, path)["created"] == value["created"]
    with pytest.raises(FileExistsError):
        prepare(settings, path, profile=PROFILE)


def test_a_changed_request_label_or_implementation_fails_the_check(
    prepared: tuple[Settings, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, path = prepared
    value = json.loads(path.read_bytes())
    changed = json.loads(json.dumps(value))
    changed["closed_cases"][0]["request_sha256"] = "0" * 64
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from its prepared request"):
        check(settings, path)
    changed = json.loads(json.dumps(value))
    changed["evaluator_only_expected"]["intent-general"] = "creative_writing"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="evaluator labels changed"):
        check(settings, path)
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(capability_map, "identity", lambda: {"agent/closed.py": "changed"})
    with pytest.raises(ValueError, match="request layer changed"):
        check(settings, path)


def test_a_saved_execution_is_scored_per_type_and_marked_as_replay(
    prepared: tuple[Settings, Path], tmp_path: Path
) -> None:
    import hashlib

    _, path = prepared
    value = json.loads(path.read_bytes())
    expected = value["evaluator_only_expected"]
    rows = []
    for index, row in enumerate(value["closed_cases"]):
        want = expected[row["case_id"]]
        base = {
            "case_id": row["case_id"],
            "question_type": row["question_type"],
            "variant": 0,
            "raw": "{}",
            "value": None,
            "abstained": None,
            "violation": None,
            "error": None,
            "prompt_tokens": 200 + index,
            "completion_tokens": 6,
            "seconds": 4.0 + index % 3,
            "prompt_ms": 3000.0,
            "predicted_ms": 600.0,
        }
        if row["question_type"] == "rule_covers" and want == "forbidden":
            # A wrong accepted answer.
            rows.append({**base, "value": "allowed", "outcome": "answered"})
        elif row["case_id"] == "intent-unclear":
            # A decisive answer where the right answer was "cannot tell".
            rows.append({**base, "value": "general_question", "outcome": "answered"})
        elif row["case_id"] == "form-unclear":
            rows.append({**base, "violation": "refused by a check", "outcome": "refused"})
        elif want.startswith(CANNOT_TELL):
            rows.append({**base, "abstained": want.split(":", 1)[1], "outcome": "abstained"})
        else:
            rows.append({**base, "value": want, "outcome": "answered"})
    execution = tmp_path / "execution.json"
    execution.write_text(
        json.dumps(
            {
                "preparation_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "seconds": 300.0,
                "stop": None,
                "closed": rows,
                "texts": [],
                "unrun_cases": [],
            }
        ),
        encoding="utf-8",
    )
    result = account(path, execution, tmp_path / "accounting.json")
    assert result["fresh"] is False and "Replay" in result["note"]
    types = result["types"]
    assert types["field_meaning"]["kept"] is True
    assert (types["field_meaning"]["asked"], types["field_meaning"]["correct"]) == (8, 8)
    assert types["field_meaning"]["abstained"] == 1
    # One decisive answer on a "cannot tell" case is enough to drop a type.
    assert types["message_intent"]["wrong_accepted_on_cannot_tell_cases"] == 1
    assert types["message_intent"]["kept"] is False and types["message_intent"]["correct"] == 9
    assert types["rule_covers"]["kept"] is False and types["rule_covers"]["correct"] == 5
    assert types["form_purpose"]["refused"] == 1 and types["form_purpose"]["kept"] is True
    assert types["next_step"]["median_seconds"] is not None
    assert types["page_kind"]["suggested_prompt_limit"] > types["page_kind"]["max_prompt_tokens"]
    other = tmp_path / "other.json"
    other.write_text(json.dumps({**json.loads(execution.read_bytes()), "preparation_sha256": "x"}))
    with pytest.raises(ValueError, match="another preparation"):
        account(path, other, tmp_path / "accounting-2.json")


def test_a_focused_measurement_keeps_all_cases_and_cannot_change_evaluator_labels(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    path = tmp_path / "focused.json"
    value = prepare(
        settings,
        path,
        profile=PROFILE,
        question_types=("next_step",),
        max_requests=6,
        max_seconds=600,
    )
    assert {row["question_type"] for row in value["closed_cases"]} == {"next_step"}
    assert len(value["closed_cases"]) == 4 and value["texts"] == value["explanations"] == []
    assert check(settings, path)["max_seconds"] == 600
    changed = json.loads(json.dumps(value))
    changed["closed_cases"].pop()
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="complete, distinct case set"):
        check(settings, path)
    changed = json.loads(json.dumps(value))
    changed["evaluator_only_expected"]["step-label"] = "invented"
    changed["evaluator_only_expected_sha256"] = capability_map._hash(
        changed["evaluator_only_expected"]
    )
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="evaluator labels changed"):
        check(settings, path)


def test_focused_preparation_cannot_raise_budgets_or_invent_a_type(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    invalid: list[dict[str, Any]] = [
        {"question_types": ("invented",)},
        {"max_requests": 71},
        {"max_seconds": 2701},
    ]
    for kwargs in invalid:
        with pytest.raises(ValueError):
            prepare(settings, tmp_path / "refused.json", profile=PROFILE, **kwargs)
