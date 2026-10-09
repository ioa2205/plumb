"""Inventories and negative profile boundaries; no model is loaded in these tests."""

import hashlib
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend import profiles
from backend.cli import main
from backend.contracts.runs import ModelRef, ReviewRun, RunLifecycle, RunStage, RunType, Toolchain
from backend.llama_server import ServerConfig
from backend.memory import MemoryStatus
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.pins import Asset, LlamaCppPin, Variant, load_llama_cpp_pin


def host() -> profiles.Host:
    return profiles.Host(
        "Windows",
        "AMD64",
        "11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz",
        4,
        8,
        MemoryStatus(8 * 1024**3, 3 * 1024**3, 0, 0),
        ("Intel Iris Xe Graphics", "NVIDIA GeForce MX350"),
        2 * 1024**3,
        10 * 1024**3,
    )


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(data_dir=tmp_path / "not-created")
    monkeypatch.setattr(profiles, "inventory", lambda settings: host())
    monkeypatch.setattr(profiles, "is_verified", lambda *args, **kwargs: True)
    monkeypatch.setattr(profiles, "verify_runtime", lambda *args: True)
    monkeypatch.setattr(llama_cpp, "binary", lambda *args: tmp_path / "not-executed.exe")
    monkeypatch.setattr(
        profiles,
        "_run",
        lambda binary, arg: (
            "0.5.0-dev (build 11146, commit 7fe450e19)"
            if arg == "--version"
            else "Vulkan1: NVIDIA GeForce MX350 (2192 MiB, 1895 MiB free)"
        ),
    )
    return settings


def test_inventory_separates_fit_validation_and_quality_and_writes_nothing(ready: Settings) -> None:
    report = profiles.doctor(ready)
    assert report["selection_ready"]
    assert report["recommended_profile"] == profiles.PROFILE_ID
    profile = report["profiles"][0]
    assert profile["runtime_verified"] and profile["runtime_compatible"]
    assert profile["estimated_memory_fit"] and not profile["all_security_quality_gates_met"]
    assert profile["dedicated_free_bytes"] == 1895 * 1024**2
    assert not report["model_loaded"] and not report["downloads_started"]
    assert not ready.data_dir.exists()
    assert all(c["validated_profile"] is None for c in report["model_candidates"][1:])
    assert profiles.select(ready) == profiles.select(ready, profiles.PROFILE_ID)


@pytest.mark.parametrize(
    "change",
    [
        {"memory": MemoryStatus(8 * 1024**3, profiles.Profile().host_required_bytes - 1, 0, 0)},
        {"dedicated_free_bytes": profiles.Profile().device_required_bytes - 1},
        {"dedicated_free_bytes": None},
        {"os": "Linux"},
        {"architecture": "ARM64"},
    ],
)
def test_auto_and_explicit_override_cannot_promote_unready_hardware(
    ready: Settings, monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    monkeypatch.setattr(profiles, "inventory", lambda settings: replace(host(), **change))
    for requested in ("auto", profiles.PROFILE_ID):
        with pytest.raises(ValueError, match="Profile unavailable"):
            profiles.select(ready, requested)


@pytest.mark.parametrize(
    "change",
    [
        {"gpu_names": ("Intel Iris Xe Graphics",)},
        {"cpu": "A different CPU with more RAM"},
        {"cpu": None},
    ],
)
def test_the_measured_profile_never_starts_on_other_hardware(
    ready: Settings, monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    # ADR-0024: other Windows hardware gets the CPU profile; the MX350 one stays refused.
    monkeypatch.setattr(profiles, "inventory", lambda settings: replace(host(), **change))
    with pytest.raises(ValueError, match="measured only on an i5-1135G7 with an MX350"):
        profiles.select(ready, profiles.PROFILE_ID)
    assert profiles.select(ready).id == profiles.CPU_PROFILE_ID


@pytest.mark.parametrize("mode", ["missing-model", "missing-runtime", "bad-runtime", "disk"])
def test_assets_runtime_and_disk_are_independent_readiness_gates(
    ready: Settings, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    if mode in {"missing-model", "disk"}:
        monkeypatch.setattr(profiles, "is_verified", lambda *args, **kwargs: False)
    if mode == "missing-runtime":
        monkeypatch.setattr(profiles, "verify_runtime", lambda *args: False)
    if mode == "bad-runtime":
        monkeypatch.setattr(profiles, "_run", lambda *args: "Vulkan1: Intel Iris Xe Graphics")
    if mode == "disk":
        monkeypatch.setattr(
            profiles, "inventory", lambda settings: replace(host(), disk_free_bytes=1)
        )
    report = profiles.doctor(ready)
    assert not report["selection_ready"]
    with pytest.raises(ValueError, match="Profile unavailable"):
        profiles.select(ready, profiles.PROFILE_ID)
    assert not ready.data_dir.exists()


def test_unknown_or_changed_profiles_never_reach_the_server(
    ready: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object) -> None:
        pytest.fail("Unmeasured profile reached the server")

    monkeypatch.setattr(profiles.vulkan_profile, "create", forbidden)
    with pytest.raises(ValueError, match="Unknown profile"):
        profiles.select(ready, "larger-is-better")
    with pytest.raises(ValueError, match="unmeasured"):
        profiles.create(ready, "test", replace(profiles.Profile(), context=16384))


def test_factory_preserves_calibrated_settings_and_refuses_runtime_drift(
    ready: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ServerConfig(
        binary=tmp_path / "not-executed.exe",
        model=tmp_path / "not-loaded.gguf",
        batch_size=256,
        ubatch_size=64,
        gpu_layers=99,
        extra_args=profiles.vulkan_profile.EXTRA_ARGS,
    )
    server = profiles.vulkan_profile.VulkanServer(config, tmp_path / "unused.log")
    monkeypatch.setattr(profiles.vulkan_profile, "create", lambda *args: server)
    try:
        assert profiles.create(ready, "test", profiles.Profile()).config == config
        server.config = replace(config, ctx_size=16384)
        with pytest.raises(ValueError, match="drifted"):
            profiles.create(ready, "test", profiles.Profile())
        assert not server.log_path.exists() and server._proc is None
    finally:
        server.stop()


def runtime_fixture(tmp_path: Path) -> tuple[Settings, LlamaCppPin, Path, Path]:
    settings = Settings(data_dir=tmp_path)
    archive = tmp_path / "cache/downloads/runtime.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("llama-server.exe", b"trusted-fixture-not-executable")
        bundle.writestr("ggml.dll", b"trusted-fixture-not-executable")
    pin = load_llama_cpp_pin().model_copy(
        update={
            "variants": {
                "vulkan": Variant(
                    description="test",
                    assets=[
                        Asset(
                            name=archive.name,
                            url="https://github.com/example/runtime.zip",
                            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                            size=archive.stat().st_size,
                        )
                    ],
                )
            }
        }
    )
    root = llama_cpp.install_dir(settings, pin, "vulkan")
    root.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(root)  # only the two fixed, locally authored fixture files
    marker = {"build": pin.build, "assets": {archive.name: pin.variants["vulkan"].assets[0].sha256}}
    (root / llama_cpp.MARKER).write_text(json.dumps(marker), encoding="utf-8")
    return settings, pin, root, archive


@pytest.mark.parametrize("change", ["exe", "dll", "extra-dll", "archive", "marker"])
def test_install_marker_cannot_hide_changed_runtime_bytes(tmp_path: Path, change: str) -> None:
    settings, pin, root, archive = runtime_fixture(tmp_path)
    assert profiles.verify_runtime(settings, pin, "vulkan")
    changed = {
        "exe": root / "llama-server.exe",
        "dll": root / "ggml.dll",
        "extra-dll": root / "unknown.dll",
        "archive": archive,
        "marker": root / llama_cpp.MARKER,
    }[change]
    changed.write_bytes(b"changed")
    assert not profiles.verify_runtime(settings, pin, "vulkan")


def test_cli_doctor_does_not_create_run_store_and_redacts(
    ready: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(ready.data_dir))
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["i5-1135G7"]')
    for arguments in (["doctor"], ["doctor", "--json"]):
        assert main(arguments) == 0
        output = capsys.readouterr().out
        assert "i5-1135G7" not in output
    assert not ready.data_dir.exists()


def test_resume_requires_identical_profile_model_and_runtime() -> None:
    profile = profiles.Profile()
    pin = load_llama_cpp_pin()
    run = ReviewRun(
        id="run:test",
        snapshot_id="a" * 64,
        run_type=RunType.LIVE,
        lifecycle=RunLifecycle.PAUSED,
        stage=RunStage.INVESTIGATING,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        model=ModelRef(
            id=profile.model_id, file_sha256=profile.model_sha256, quantization="Q4_K_M"
        ),
        toolchain=Toolchain(
            llama_cpp_release=pin.release, llama_cpp_build=pin.build, backend="vulkan"
        ),
    )
    saved = json.loads(json.dumps(profile.identity()))
    profiles.validate_resume(profile, saved, run)
    for changed in (None, {**saved, "context": 16384}, {**saved, "stateless": 1}):
        with pytest.raises(ValueError, match="Profile changed"):
            profiles.validate_resume(profile, changed, run)
    assert run.model and run.toolchain
    for changed in (
        run.model_copy(update={"model": None}),
        run.model_copy(update={"model": run.model.model_copy(update={"file_sha256": "b" * 64})}),
        run.model_copy(update={"toolchain": run.toolchain.model_copy(update={"backend": "cpu"})}),
        run.model_copy(
            update={"toolchain": run.toolchain.model_copy(update={"llama_cpp_build": "b1"})}
        ),
    ):
        with pytest.raises(ValueError, match="Stored run"):
            profiles.validate_resume(profile, saved, changed)
