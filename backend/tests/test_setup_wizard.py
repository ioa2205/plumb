"""Installer approval, scope and failure boundaries; no network/model in tests."""

import json
from pathlib import Path
from typing import Any

import pytest

from backend import user_config
from backend.settings import Settings
from backend.setup import __main__ as wizard


def plan(*, mode: str = "review", large: bool = False, measured: bool = True) -> dict[str, Any]:
    return {
        "mode": mode,
        "data_dir": "fixture-data-location",
        "profile": "mx350-vulkan-8k" if measured and mode == "review" else None,
        "next": "plumb setup --install",
        "missing_downloads": [],
        "requires_large_download_approval": large,
        "missing_download_bytes": 600_000_000 if large else 0,
        "doctor": {
            "recommended_profile": "mx350-vulkan-8k" if measured else None,
            "selected_profile": "mx350-vulkan-8k" if measured else None,
            "inventory": {"disk_free_bytes": 10_000_000_000},
            "profiles": [
                {
                    "id": "mx350-vulkan-8k",
                    "evaluated_capability": "Fixture scope; not real model evidence",
                },
                {"id": "cpu-8k", "evaluated_capability": "Fixture scope; no profile here"},
            ],
            "messages": [],
        },
        "typescript_helper": {
            "ready": True,
            "node_compatible": True,
            "pnpm_available": True,
            "action": "Install the missing trusted source tools",
        },
        "ready": True,
    }


def forbid(*args: object, **kwargs: object) -> None:
    pytest.fail("Unexpected installation/download/process")


@pytest.fixture
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr(user_config, "user_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(wizard, "_run", forbid)
    monkeypatch.setattr(wizard, "fetch", forbid)
    monkeypatch.setattr(wizard.llama_cpp, "install", forbid)
    monkeypatch.setattr(wizard.opengrep, "install", forbid)
    return settings


def test_preview_does_not_install(offline: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())
    assert wizard.main([]) == 0
    assert not offline.data_dir.exists()


def test_large_approval_is_rechecked_against_fresh_inventory(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan(large=True))
    with pytest.raises(ValueError, match="explicitly approve"):
        wizard.install(offline, plan(large=False))
    assert not offline.data_dir.exists()


def test_a_system_without_a_review_profile_is_refused_before_installs(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan(measured=False))
    with pytest.raises(ValueError, match="No review profile exists for this system"):
        wizard.install(offline, plan())


def test_inspect_only_has_no_model_download_requirement(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wizard, "preview", lambda *args, **kwargs: plan(mode="inspect-only", measured=False)
    )
    result = wizard.install(offline, plan(mode="inspect-only"))
    assert result["ready"] and result["installation_attempted"]
    assert not offline.data_dir.exists()


@pytest.mark.parametrize("missing", ["node", "pnpm", "disk"])
def test_prerequisite_failure_does_not_start_installation(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    current = plan()
    if missing == "node":
        current["typescript_helper"].update(node_compatible=False, action="Node missing")
    elif missing == "pnpm":
        current["typescript_helper"].update(ready=False, pnpm_available=False)
    else:
        current.update(missing_download_bytes=20)
        current["doctor"]["inventory"]["disk_free_bytes"] = 1
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: current)
    with pytest.raises(ValueError):
        wizard.install(offline, current)
    assert not offline.data_dir.exists()


def test_target_path_is_not_a_setup_destination(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside"):
        wizard.preview(Settings(data_dir=wizard.ROOT / "tmp/disallowed-data"))


def test_invalid_destination_leaves_no_setup_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wizard, "preview", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad path"))
    )
    target = tmp_path / "data"
    assert wizard.main(["--install", "--data-dir", str(target)]) == 1
    assert not target.exists()


def test_changed_model_cannot_trigger_an_unapproved_download(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan(large=False))
    monkeypatch.setattr(wizard, "verify_runtime", lambda *args: True)
    monkeypatch.setattr(wizard, "is_verified", lambda *args, **kwargs: False)
    with pytest.raises(ValueError, match="approval is required"):
        wizard.install(offline, plan())


def test_failure_record_is_redacted_and_no_exception_input_is_printed(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["private fixture"]')
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())

    def fail(*args: object, **kwargs: object) -> None:
        raise ValueError("private fixture")

    monkeypatch.setattr(wizard, "install", fail)
    assert wizard.main(["--install", "--json"]) == 1
    assert "private fixture" not in capsys.readouterr().out
    record = next((offline.cache_dir / "setup").glob("*.json"))
    assert "private fixture" not in record.read_text()
    assert json.loads(record.read_text())["exit_code"] == 1


@pytest.mark.parametrize("operation", ["mkdir", "write"])
def test_outcome_record_failure_refuses_without_printing_ready(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["private fixture"]')
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())
    monkeypatch.setattr(wizard, "install", lambda *args, **kwargs: plan())
    folder = offline.cache_dir / "setup"
    mkdir, write = Path.mkdir, Path.write_text

    def denied_mkdir(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == folder and operation == "mkdir":
            raise PermissionError("private fixture")
        mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def denied_write(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if path.parent == folder and operation == "write":
            raise PermissionError("private fixture")
        return write(path, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "mkdir", denied_mkdir)
    monkeypatch.setattr(Path, "write_text", denied_write)
    assert wizard.main(["--install", "--json"]) == 1
    output = capsys.readouterr()
    assert "private fixture" not in output.out + output.err
    result = json.loads(output.out)
    assert "setup_refused" in result and not result.get("ready", False)
    assert "PLUMB_DATA_DIR" in result["action"] and "preview" in result["action"]
    assert not result["model_loaded"]
    assert not list(folder.glob("*.json"))


def test_record_failure_keeps_original_installation_refusal(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["private fixture"]')
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())

    def fail_install(*args: object, **kwargs: object) -> None:
        raise ValueError("approval required: private fixture")

    monkeypatch.setattr(wizard, "install", fail_install)
    folder = offline.cache_dir / "setup"
    folder.parent.mkdir(parents=True)
    folder.write_text("preserve existing user content")
    assert wizard.main(["--install", "--json"]) == 1
    output = capsys.readouterr()
    assert "private fixture" not in output.out + output.err
    result = json.loads(output.out)
    assert "approval required" in result["installation_error"]
    assert folder.read_text() == "preserve existing user content"


def test_ready_result_waits_for_successful_outcome_record(
    offline: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())
    monkeypatch.setattr(wizard, "install", lambda *args, **kwargs: plan())
    write = Path.write_text

    def check_write(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        assert not capsys.readouterr().out, "Success was printed before its record was saved"
        return write(path, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", check_write)
    assert wizard.main(["--install", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"]
    record = next((offline.cache_dir / "setup").glob("*.json"))
    saved = json.loads(record.read_text())
    assert saved["exit_code"] == 0 and saved["result"]["ready"]
    location = user_config.read_location()
    assert location is not None and location.data_dir == offline.data_dir


def test_human_preview_discloses_exact_download_and_requires_consent(
    offline: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    current = plan(large=True)
    current["ready"] = False
    current["missing_downloads"] = [
        {
            "kind": "model",
            "size_bytes": 600_000_000,
            "license": "fixture-license",
            "source": "https://example.invalid/pinned",
            "sha256": "a" * 64,
        }
    ]
    current["next"] += " --approve-large-downloads"
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: current)
    assert wizard.main([]) == 0
    output = capsys.readouterr().out
    for disclosure in (
        "600,000,000 bytes",
        "fixture-license",
        "https://example.invalid/pinned",
        "a" * 64,
        "explicit large-download approval",
        "--approve-large-downloads",
    ):
        assert disclosure in output
    assert "Ready for" not in output and not offline.data_dir.exists()


def test_human_summary_without_a_profile_has_source_only_next_action() -> None:
    current = plan(measured=False)
    current["ready"] = False
    output = wizard.human_summary(current, installing=False)
    assert "AI review is not available on this system" in output
    assert "Review profile: none for this system" in output
    assert "Next: plumb setup --install --inspect-only" in output
    assert "Ready for the scoped AI review" not in output


def test_human_record_failure_is_actionable_and_redacted(
    offline: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["private fixture"]')
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())
    monkeypatch.setattr(wizard, "install", lambda *args, **kwargs: plan())
    folder = offline.cache_dir / "setup"
    folder.parent.mkdir(parents=True)
    folder.write_text("preserve existing content")
    assert wizard.main(["--install"]) == 1
    output = capsys.readouterr().out
    assert "Setup could not finish" in output and "writable external" in output
    assert "Ready for" not in output and "private fixture" not in output
    assert folder.read_text() == "preserve existing content"
    assert not user_config.location_file().exists()


def test_preference_failure_does_not_announce_ready_and_records_incomplete_setup(
    offline: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["private fixture"]')
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())
    monkeypatch.setattr(wizard, "install", lambda *args, **kwargs: plan())

    def refused(data_dir: Path) -> Path:
        raise PermissionError("private fixture")

    monkeypatch.setattr(wizard, "remember_location", refused)
    assert wizard.main(["--install", "--json"]) == 1
    output = capsys.readouterr().out
    result = json.loads(output)
    assert "remember the data folder" in result["setup_refused"]
    assert "private fixture" not in output and not result.get("ready")
    record = next((offline.cache_dir / "setup").glob("*.json"))
    saved = json.loads(record.read_text())
    assert saved["exit_code"] == 1 and "setup_refused" in saved["result"]


def test_incomplete_setup_does_not_change_remembered_location(
    offline: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = offline.data_dir.parent / "first"
    preferences = user_config.remember_location(first)
    before = preferences.read_bytes()
    monkeypatch.setenv("PLUMB_DATA_DIR", str(offline.data_dir))
    monkeypatch.setattr(wizard, "preview", lambda *args, **kwargs: plan())
    current = plan()
    current["ready"] = False
    monkeypatch.setattr(wizard, "install", lambda *args, **kwargs: current)
    assert wizard.main(["--install", "--json"]) == 2
    assert preferences.read_bytes() == before
