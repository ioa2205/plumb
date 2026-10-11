"""Pinned quality-aware selection and explicit choices, with no model or network."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend import model_quality, profiles
from backend.cli import main
from backend.contracts.model_choices import ModelCatalog
from backend.contracts.setup_view import LaunchRequest
from backend.memory import MemoryStatus
from backend.model_choices import catalog
from backend.settings import Settings
from backend.tests.test_profiles import host

pytest_plugins = ["backend.tests.test_profiles"]

ROOT = Path(__file__).resolve().parents[2]


def test_recorded_quality_pins_real_reports_not_first_use_format_checks() -> None:
    for profile_id, (relative, digest) in model_quality.RECORDS.items():
        path = ROOT / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        report = json.loads(path.read_text(encoding="utf-8"))
        profile = profiles.REGISTRY[profile_id]
        assert report["run"]["model"]["file_sha256"] == profile.model_sha256
        assert report["run"]["toolchain"]["backend"] == profile.backend
        assert [f["conclusion"] for f in report["findings"]] == ["supported", "rejected"]
        assert model_quality.evidence(profile.identity())["automatic_eligible"]


def test_quality_does_not_transfer_to_another_model_runtime_or_profile() -> None:
    identity = profiles.Profile().identity()
    for changed in (
        {**identity, "model_sha256": "b" * 64},
        {**identity, "runtime_commit": "c" * 40},
        {**identity, "id": "cpu-8k-untested"},
        {**identity, "context": 16384},
        {**identity, "stateless": False},
    ):
        quality = model_quality.evidence(changed)
        assert quality["quality_state"] == "untested" and not quality["automatic_eligible"]
        assert not quality["quality_records"]


def test_auto_falls_back_to_cpu_only_when_qualified_memory_runtime_fit(
    ready: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(profiles, "inventory", lambda _: replace(host(), dedicated_free_bytes=1))
    assert profiles.select(ready).id == profiles.CPU_PROFILE_ID
    with pytest.raises(ValueError, match="Profile unavailable"):
        profiles.select(ready, profiles.PROFILE_ID)
    # Insufficient 2B RAM must not silently choose a fitting untested smaller candidate.
    tight = replace(
        host(), memory=MemoryStatus(8 * 1024**3, 2_100_000_000, 0, 0), dedicated_free_bytes=1
    )
    report = profiles.doctor(ready, tight)
    assert not report["selection_ready"]
    assert report["selected_profile"] in {profiles.PROFILE_ID, profiles.CPU_PROFILE_ID}
    assert any(
        p["estimated_memory_fit"] and not p["automatic_eligible"] for p in report["profiles"]
    )


def test_catalog_exposes_estimates_and_first_use_separately_from_quality(ready: Settings) -> None:
    value = catalog(profiles.doctor(ready))
    assert not value.model_loaded and not value.downloads_started
    assert len(value.models) == 5
    measured = value.models[0].profiles[0]
    assert measured.quality_state == "recorded_scoped" and measured.quality_records
    untested = next(m for m in value.models if m.family == "Qwen3.5-4B")
    assert untested.profiles[0].quality_state == "untested"
    assert untested.profiles[0].first_use_check == "pending"
    assert not untested.profiles[0].automatic_eligible
    unknown = next(m for m in value.models if m.family == "Gemma 4 E2B")
    assert not unknown.profiles and unknown.unavailable_reason
    raw = value.model_dump(mode="json")
    changed = json.loads(json.dumps(raw))
    changed["models"][1]["profiles"][0]["automatic_eligible"] = True
    with pytest.raises(ValidationError, match="untested"):
        ModelCatalog.model_validate(changed)
    changed = json.loads(json.dumps(raw))
    changed["models"][0]["profiles"][0]["memory_fit"] = False
    with pytest.raises(ValidationError):
        ModelCatalog.model_validate(changed)
    changed = json.loads(json.dumps(raw))
    changed["models"][0]["verified_installed"] = False
    with pytest.raises(ValidationError, match="unverified"):
        ModelCatalog.model_validate(changed)


def test_explicit_model_choice_resolves_profile_and_preserves_checks(ready: Settings) -> None:
    larger = "qwen3.5-4b-q4_k_m"
    profile_id = profiles.requested_model(ready, larger)
    assert profile_id == f"cpu-8k-{larger}"
    assert profiles.REGISTRY[profile_id].model_id == larger
    # Three GiB is below the unchanged larger model's estimate.
    with pytest.raises(ValueError, match="free memory"):
        profiles.select(ready, profile_id)
    assert profiles.requested_model(ready, profiles.Profile().model_id) == profiles.PROFILE_ID
    with pytest.raises(ValueError, match="disagree"):
        profiles.requested_model(ready, larger, profiles.CPU_PROFILE_ID)
    with pytest.raises(ValueError, match="no supported launch profile"):
        profiles.requested_model(ready, "gemma-4-e2b-it-qat-q4_0")
    with pytest.raises(ValueError):
        profiles.requested_model(ready, "download-something-else")


def test_review_profile_field_does_not_accept_path_shell_or_unbounded_names() -> None:
    base = {"inspection_id": "inspect-" + "a" * 32, "authorized": True}
    assert LaunchRequest.model_validate(base).profile == "auto"
    for name in ("../escape", "bad\nprofile", "$(command)", "A" * 129):
        with pytest.raises(ValidationError):
            LaunchRequest.model_validate({**base, "profile": name})


def test_cli_catalog_is_read_only_and_labels_untested_choices(
    ready: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(ready.data_dir))
    assert main(["models", "--json"]) == 0
    value = ModelCatalog.model_validate_json(capsys.readouterr().out)
    assert value.models[0].profiles[0].quality_records
    assert not value.models[1].profiles[0].automatic_eligible
    assert main(["models"]) == 0
    printed = capsys.readouterr().out
    assert "untested quality" in printed and "Model size never" in printed
    assert not ready.data_dir.exists()
    assert main(["review", "labs/tandir", "--model", "gemma-4-e2b-it-qat-q4_0"]) == 1
    assert "Model choice refused" in capsys.readouterr().out
    assert not ready.data_dir.exists()
    assert main(["assess", "--model", "gemma-4-e2b-it-qat-q4_0"]) == 1
    assert "Model choice refused" in capsys.readouterr().out
    assert not ready.data_dir.exists()
