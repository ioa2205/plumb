"""Measured closed-question types, pinned to the exact local request/runtime identity.

Only a fresh capability-map run publishes a production record. Saved accounting,
fixture askers and historical answers never promote a type. Missing, stale or
failed records leave the code/user/stop rungs available.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from agent.closed import QuestionType
from backend.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
LAYER_FILES = (
    "agent/closed.py",
    "agent/asking.py",
    "agent/intent.py",
    "agent/web_questions.py",
    "agent/llm.py",
    "backend/local_model.py",
    "backend/model_qualification.py",
    "backend/llama_server.py",
    "backend/profiles.py",
)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def question_identity(kind: QuestionType) -> str:
    return digest(asdict(kind))


def layer_identity() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in LAYER_FILES}


def runtime_identity(profile: dict[str, Any]) -> dict[str, Any]:
    from backend.setup.pins import load_llama_cpp_pin, load_model_pins

    return {
        "profile": profile,
        "model": load_model_pins().get(profile["model_id"]).model_dump(mode="json"),
        "llama_cpp": {
            key: value
            for key, value in load_llama_cpp_pin().model_dump(mode="json").items()
            if key != "variants"
        },
    }


def kept(row: dict[str, Any]) -> bool:
    counts = [
        row.get(key) for key in ("cases", "asked", "correct", "wrong_accepted_on_cannot_tell_cases")
    ]
    if any(type(value) is not int or value < 0 for value in counts):
        return False
    total, asked, correct, wrong = (cast(int, value) for value in counts)
    return (
        total >= 4
        and asked == total
        and correct <= total
        and correct * 5 >= total * 4
        and wrong == 0
    )


class Qualifications:
    def __init__(self, settings: Settings, profile: dict[str, Any]) -> None:
        from backend.profiles import REGISTRY

        registered = REGISTRY.get(profile.get("id"))
        if registered is None or profile != registered.identity():
            raise ValueError("Qualification requires an exact registered profile")
        self.path = (
            settings.cache_dir / "closed-questions" / (profile["id"] + ".qualification.json")
        )
        self.pins = runtime_identity(profile)

    def read(self) -> dict[str, Any]:
        try:
            if self.path.stat().st_size > 512 * 1024:
                return {}
            value = json.loads(self.path.read_bytes())
            if (
                not isinstance(value, dict)
                or value.get("kind") != "production_closed_qualification"
                or value.get("origin") != "fresh_local_capability_map"
                or value.get("pins") != self.pins
                or value.get("implementation") != layer_identity()
                or not isinstance(value.get("types"), dict)
            ):
                return {}
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def reason(self, kind: QuestionType) -> str | None:
        row = self.read().get("types", {}).get(kind.name)
        if (
            isinstance(row, dict)
            and row.get("question_sha256") == question_identity(kind)
            and kept(row)
        ):
            return None
        return (
            f"The question type {kind.name} has no passing measurement for these exact local pins."
        )


def intent_reason(settings: Settings, requested: str, kind: QuestionType) -> str | None:
    """Check before loading; the actual selected adapter rechecks its own profile.

    For auto selection, a passing candidate permits admission; if another profile
    is selected, ModelAsker still refuses it before tokenization or completion.
    """
    from backend.profiles import REGISTRY

    selected = requested if requested != "auto" else settings.profile
    candidates = (
        [REGISTRY[selected]]
        if selected in REGISTRY
        else list(REGISTRY.values())
        if selected == "auto"
        else []
    )
    for profile in candidates:
        if Qualifications(settings, profile.identity()).reason(kind) is None:
            return None
    return (
        f"The question type {kind.name} has no passing local capability measurement; "
        "choose what you mean."
    )


def publish(
    settings: Settings,
    loaded: object,
    preparation: dict[str, Any],
    execution: dict[str, Any],
    accounting: dict[str, Any],
    kinds: dict[str, QuestionType],
) -> Path | None:
    """Publish only from the live runtime witness, never from saved/fixture accounting."""
    from backend.local_model import Loaded, verified_runtime

    if not isinstance(loaded, Loaded) or not verified_runtime(loaded):
        return None
    if (
        not execution.get("model_loaded")
        or execution.get("manifest", {}).get("model_stopped") is not True
        or execution.get("manifest", {}).get("profile") != loaded.profile.identity()
        or preparation.get("pins") != runtime_identity(loaded.profile.identity())
        or preparation.get("implementation")
        != {
            **layer_identity(),
            **{
                "eval/capability_map.py": hashlib.sha256(
                    (ROOT / "eval/capability_map.py").read_bytes()
                ).hexdigest()
            },
        }
    ):
        return None
    # Regrade the actual raw answers against the whole frozen case set. A replay
    # summary, edited counters or a subset of easier cases cannot qualify a type.
    from eval.capability_map import CANNOT_TELL, cases

    current = {case_id: (question, expected) for case_id, question, expected in cases()}
    selected = {row["question_type"] for row in preparation["closed_cases"]}
    wanted = {
        case_id for case_id, (question, _) in current.items() if question.kind.name in selected
    }
    saved = [row["case_id"] for row in preparation["closed_cases"]]
    if len(saved) != len(set(saved)) or set(saved) != wanted:
        return None
    expected = {case_id: current[case_id][1] for case_id in saved}
    if preparation["evaluator_only_expected"] != expected:
        return None
    verified: dict[str, dict[str, int]] = {
        name: {
            "cases": sum(current[case_id][0].kind.name == name for case_id in wanted),
            "asked": 0,
            "correct": 0,
            "wrong_accepted_on_cannot_tell_cases": 0,
        }
        for name in selected
    }
    seen: set[str] = set()
    for row in execution["closed"]:
        case_id = row["case_id"]
        if case_id not in wanted or case_id in seen:
            return None
        seen.add(case_id)
        question, want = current[case_id]
        if row["question_type"] != question.kind.name or row["variant"] != 0:
            return None
        count = verified[question.kind.name]
        count["asked"] += 1
        if row["error"] is not None:
            if row["value"] is not None or row["abstained"] is not None:
                return None
            continue
        try:
            raw = json.loads(row["raw"])
        except (ValueError, TypeError):
            raw = None
        value, abstained, violation = question.grade(raw)
        if (value, abstained, violation) != (row["value"], row["abstained"], row["violation"]):
            return None
        got = value if value is not None else f"{CANNOT_TELL}:{abstained}" if abstained else None
        count["correct"] += got == want
        count["wrong_accepted_on_cannot_tell_cases"] += (
            want.startswith(CANNOT_TELL) and value is not None
        )
    if any(
        any(
            accounting.get("types", {}).get(name, {}).get(key) != value
            for key, value in count.items()
        )
        for name, count in verified.items()
        if count["asked"] != 0
    ):
        return None
    catalog = Qualifications(settings, loaded.profile.identity())
    prior = catalog.read().get("types", {})
    measured = {
        name: {**row, "question_sha256": question_identity(kinds[name])}
        for name, row in verified.items()
        if name in kinds
    }
    record = {
        "kind": "production_closed_qualification",
        "origin": "fresh_local_capability_map",
        "pins": catalog.pins,
        "implementation": layer_identity(),
        "types": {**prior, **measured},
        "evidence": {
            "preparation_sha256": execution["preparation_sha256"],
            "execution_sha256": digest(execution),
            "accounting_sha256": digest(accounting),
        },
    }
    catalog.path.parent.mkdir(parents=True, exist_ok=True)
    temporary = catalog.path.with_suffix("." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(catalog.path)
    return catalog.path
