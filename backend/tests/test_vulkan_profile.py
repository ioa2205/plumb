import json
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from backend import vulkan_profile as profile
from backend.llama_server import ServerConfig, ServerError
from backend.memory import MemoryStatus
from backend.preflight import MARGIN_BYTES, check
from backend.settings import Settings
from backend.setup.pins import load_model_pins


def memory(available: int) -> MemoryStatus:
    return MemoryStatus(8 * 1024**3, available, 0, 0)


def config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        binary=tmp_path / "llama-server.exe",
        model=tmp_path / "model.gguf",
        batch_size=256,
        ubatch_size=64,
        gpu_layers=99,
        extra_args=profile.EXTRA_ARGS,
    )


def test_gate_needs_both_pools_and_keeps_the_original_cpu_refusal() -> None:
    ram, vram = profile.REQUIREMENT.host_bytes, profile.REQUIREMENT.device_bytes
    assert profile.check_memory(memory(ram), vram).ok
    assert not profile.check_memory(memory(ram - 1), vram).ok
    assert not profile.check_memory(memory(ram), vram - 1).ok
    model = load_model_pins().get(profile.MODEL_ID)
    assert not check(model, 8192, MARGIN_BYTES, memory(ram)).ok


@pytest.mark.parametrize(
    "devices",
    [
        "",
        "Vulkan0: NVIDIA GeForce MX350 (2192 MiB, 1895 MiB free)",
        "Vulkan1: Intel(R) Iris(R) Xe Graphics (3985 MiB, 3587 MiB free)",
        "Vulkan1: NVIDIA GeForce MX350 (2192 MiB, unknown MiB free)",
        "Vulkan1: NVIDIA GeForce MX350 (2192 MiB, 1895 MiB free)\n" * 2,
    ],
)
def test_never_selects_shared_memory_or_an_unmeasured_device(devices: str) -> None:
    with pytest.raises(ValueError):
        profile.device_budget(devices)


def test_device_parser_accepts_the_recorded_mx350() -> None:
    assert (
        profile.device_budget(
            "Available devices:\n"
            "  Vulkan0: Intel(R) Iris(R) Xe Graphics (3985 MiB, 3587 MiB free)\n"
            "  Vulkan1: NVIDIA GeForce MX350 (2192 MiB, 1895 MiB free)\n"
        )
        == 1895 * 1024**2
    )


@pytest.mark.parametrize(
    "change",
    [
        {"ctx_size": 16384},
        {"threads": 8},
        {"batch_size": 2048},
        {"ubatch_size": 512},
        {"gpu_layers": 0},
        {"stateless": False},
        {"reasoning": "on"},
        {"extra_args": ()},
    ],
)
def test_changed_settings_refuse_before_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    monkeypatch.setattr(profile, "read_memory", lambda: memory(8 * 1024**3))
    server = profile.VulkanServer(replace(config(tmp_path), **change), tmp_path / "server.log")
    try:
        with pytest.raises(ServerError, match="no measured"):
            server.start()
        assert server._proc is None and server._watcher is None
        assert not server.log_path.exists()
    finally:
        server.stop()


def test_preflight_uses_lower_vram_measurement_and_fresh_ram(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(profile, "read_memory", lambda: memory(8 * 1024**3))
    monkeypatch.setattr(
        profile.llama_cpp,
        "run_tool",
        lambda *args: subprocess.CompletedProcess(
            [], 0, "Vulkan1: NVIDIA GeForce MX350 (2192 MiB, 1895 MiB free)", ""
        ),
    )
    server = profile.VulkanServer(config(tmp_path), tmp_path / "server.log")
    try:
        monkeypatch.setattr(profile, "nvidia_free", lambda: 100 * 1024**2)
        assert not server.preflight().ok
        monkeypatch.setattr(profile, "nvidia_free", lambda: 2000 * 1024**2)
        assert server.preflight().ok
        monkeypatch.setattr(profile, "read_memory", lambda: memory(1))
        assert not server.preflight().ok
    finally:
        server.stop()


@pytest.mark.parametrize("reading_fails", [False, True])
def test_live_watchdog_stops_the_owned_child_and_joins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reading_fails: bool
) -> None:
    def read() -> MemoryStatus:
        if reading_fails:
            raise OSError("test memory reader failure")
        return memory(profile.LOW_MEMORY_BYTES - 1)

    monkeypatch.setattr(profile, "read_memory", read)
    server = profile.VulkanServer(config(tmp_path), tmp_path / "server.log")
    try:
        server._proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
        )
        server._watch_stop = threading.Event()
        server._watcher = threading.Thread(target=server._watch_memory)
        server._watcher.start()
        server._proc.wait(timeout=5)
        assert server.memory_abort is not None
        assert server._proc.returncode != 0
    finally:
        if server._proc and server._proc.stdout:
            server._proc.stdout.close()
        server.stop()
    assert server._watcher is None


def test_factory_refuses_changed_assets_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(profile.llama_cpp, "is_installed", lambda *args: True)
    monkeypatch.setattr(profile, "sha256_file", lambda *args: "0" * 64)
    with pytest.raises(ValueError, match="model file"):
        profile.create(settings, "test")


def test_vulkan_pin_is_small_and_publisher_hashed() -> None:
    pin = profile.load_llama_cpp_pin()
    asset = pin.variants["vulkan"].assets[0]
    assert asset.size == 32_127_004 < 500_000_000
    assert asset.sha256 == "55a378aa095b466979d85075234f66d7655c7a7483222af0c006c0e55b4d7bd6"


def test_budget_is_tied_to_the_successful_recorded_run() -> None:
    root = Path(__file__).resolve().parents[2]
    report = json.loads(
        (root / "docs/results/2026-10-04-090731-m0.7a-vulkan.json").read_text(encoding="utf-8")
    )
    assert report["passed"] and report.get("abort_reason") is None
    assert report["model_sha256_actual"] == profile.MODEL_SHA256
    assert report["llama_cpp"]["commit"] == profile.BUILD_COMMIT
    assert report["variant"] == "vulkan"
    assert profile.REQUIREMENT.host_bytes == report["preflight"]["required_ram_bytes"]
    assert profile.REQUIREMENT.device_bytes == report["preflight"]["required_vram_bytes"]
    assert (
        report["peak_working_set_bytes"] + profile.LOW_MEMORY_BYTES
        <= profile.REQUIREMENT.host_bytes
    )
    assert report["minimum_available_ram_bytes"] > profile.LOW_MEMORY_BYTES
    for name, value in [
        ("--ctx-size", "8192"),
        ("--batch-size", "256"),
        ("--ubatch-size", "64"),
        ("--n-gpu-layers", "99"),
        ("--load-mode", "dio"),
        ("--device", profile.DEVICE),
    ]:
        assert report["server_argv"][report["server_argv"].index(name) + 1] == value
    assert "--no-repack" in report["server_argv"]


def test_factory_binds_measured_settings_and_checks_log_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(profile.llama_cpp, "is_installed", lambda *args: True)
    monkeypatch.setattr(profile.llama_cpp, "binary", lambda *args: tmp_path / "llama.exe")
    monkeypatch.setattr(profile, "sha256_file", lambda *args: profile.MODEL_SHA256)
    with pytest.raises(ValueError, match="plain file stem"):
        profile.create(Settings(data_dir=tmp_path), "../outside")
    server = profile.create(Settings(data_dir=tmp_path), "safe-log")
    try:
        assert server.config.extra_args == profile.EXTRA_ARGS
        assert (server.config.ctx_size, server.config.batch_size, server.config.ubatch_size) == (
            8192,
            256,
            64,
        )
        assert server.config.gpu_layers == 99 and server.config.stateless
        assert server._proc is None
    finally:
        server.stop()
