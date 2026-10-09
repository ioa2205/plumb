"""The CPU profile and its first-use check (ADR-0024); no model is loaded in these tests."""

import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend import acceptance, cpu_profile, profiles
from backend.cli import main
from backend.llama_server import ServerConfig, ServerError
from backend.memory import MemoryStatus
from backend.preflight import MARGIN_BYTES, PreflightResult, requirement
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.pins import load_model_pins

CPU = profiles.REGISTRY[profiles.CPU_PROFILE_ID]
GIB = 1024**3


def other_laptop(available: int = 16 * GIB) -> profiles.Host:
    """A stronger laptop than the measured one, with a different processor and card."""
    return profiles.Host(
        "Windows",
        "AMD64",
        "AMD Ryzen 7 7840HS",
        8,
        16,
        MemoryStatus(32 * GIB, available, 0, 0),
        ("NVIDIA GeForce RTX 4060 Laptop GPU",),
        None,
        100 * GIB,
    )


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Verified assets and a runner that reports the pinned build; nothing is executed."""
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr(profiles, "inventory", lambda settings: other_laptop())
    monkeypatch.setattr(profiles, "is_verified", lambda *args, **kwargs: True)
    monkeypatch.setattr(profiles, "verify_runtime", lambda *args: True)
    monkeypatch.setattr(llama_cpp, "binary", lambda *args: tmp_path / "not-executed.exe")
    monkeypatch.setattr(
        profiles, "_run", lambda binary, arg: "0.5.0-dev (build 11146, commit 7fe450e19)"
    )
    return settings


def test_the_measured_profile_identity_and_gates_are_unchanged() -> None:
    # Saved reviews compare this exactly on resume; any difference refuses them.
    assert profiles.REGISTRY[profiles.PROFILE_ID].identity() == {
        "id": "mx350-vulkan-8k",
        "model_id": "qwen3.5-2b-q4_k_m",
        "model_sha256": "57a1085840f497d764a7fc5d346922dbde961efb54cc792ea81d694fd846a1d8",
        "runtime_commit": "7fe450e19305b828c199d602c23a8337aaa1f03b",
        "backend": "vulkan",
        "context": 8192,
        "threads": 4,
        "batch": 256,
        "microbatch": 64,
        "offload_layers": 99,
        "host_required_bytes": 1_361_051_648,
        "device_required_bytes": 1_776_287_744,
        "device": "Vulkan1",
        "device_name": "NVIDIA GeForce MX350",
        "extra_args": ["--fit", "off", "--no-repack", "--device", "Vulkan1", "--load-mode", "dio"],
        "stateless": True,
        "reasoning": "off",
    }
    assert list(profiles.REGISTRY)[:2] == [profiles.PROFILE_ID, profiles.CPU_PROFILE_ID]


def test_the_cpu_profile_keeps_the_original_cpu_gate() -> None:
    model = load_model_pins().get(CPU.model_id)
    need = requirement(model, 8192, MARGIN_BYTES)
    assert need is not None and need.total == cpu_profile.REQUIRED_BYTES == 2_436_385_888
    assert CPU.host_required_bytes == need.total and CPU.device_required_bytes == 0
    assert (CPU.backend, CPU.offload_layers, CPU.device_name) == ("cpu", 0, "")
    assert (CPU.context, CPU.threads, CPU.batch, CPU.microbatch) == (8192, 4, 2048, 512)
    assert CPU.model_sha256 == model.sha256 and CPU.stateless and CPU.reasoning == "off"


def test_another_windows_laptop_is_offered_the_cpu_profile(installed: Settings) -> None:
    report = profiles.doctor(installed)
    assert [p["id"] for p in report["profiles"]] == list(profiles.REGISTRY)
    measured, cpu = report["profiles"][:2]
    assert not measured["compatible_measured_host"] and not measured["ready"]
    assert cpu["compatible_measured_host"] and cpu["ready"] and cpu["runtime_compatible"]
    assert cpu["dedicated_free_bytes"] is None and cpu["first_use_check"] == "pending"
    assert report["recommended_profile"] == report["selected_profile"] == "cpu-8k"
    assert report["selection_ready"] and not report["model_loaded"]
    assert not any("MX350" in message for message in report["messages"])
    assert any("first review on this computer" in message for message in report["messages"])
    assert profiles.select(installed) == CPU
    assert not installed.data_dir.exists()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"memory": MemoryStatus(32 * GIB, cpu_profile.REQUIRED_BYTES - 1, 0, 0)}, "free memory"),
        ({"os": "Linux"}, "64-bit Windows"),
        ({"os": "Darwin"}, "64-bit Windows"),
        ({"architecture": "ARM64"}, "64-bit Windows"),
        ({"disk_free_bytes": None}, "Profile unavailable"),
    ],
)
def test_the_cpu_profile_refuses_what_it_cannot_run_on(
    installed: Settings, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], reason: str
) -> None:
    monkeypatch.setattr(profiles, "inventory", lambda settings: replace(other_laptop(), **change))
    for requested in ("auto", profiles.CPU_PROFILE_ID):
        with pytest.raises(ValueError, match=reason):
            profiles.select(installed, requested)


def test_a_system_without_a_profile_recommends_none(
    installed: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(profiles, "inventory", lambda s: replace(other_laptop(), os="Linux"))
    report = profiles.doctor(installed)
    assert report["recommended_profile"] is None and report["selected_profile"] is None
    assert not report["selection_ready"]
    assert "AI review needs 64-bit Windows on an x64 processor" in report["messages"]


def test_the_measured_laptop_still_prefers_its_measured_profile(
    installed: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    measured_host = replace(
        other_laptop(3 * GIB),
        cpu="11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz",
        gpu_names=("Intel Iris Xe Graphics", "NVIDIA GeForce MX350"),
        dedicated_free_bytes=2 * GIB,
    )
    monkeypatch.setattr(profiles, "inventory", lambda settings: measured_host)
    monkeypatch.setattr(
        profiles,
        "_run",
        lambda binary, arg: (
            "0.5.0-dev (build 11146, commit 7fe450e19)"
            if arg == "--version"
            else "Vulkan1: NVIDIA GeForce MX350 (2192 MiB, 1895 MiB free)"
        ),
    )
    report = profiles.doctor(installed)
    assert report["recommended_profile"] == profiles.PROFILE_ID
    # 2 GiB free is enough for the measured profile, so its model is not passed over
    # for a smaller one that happens to fit the CPU formula.
    tight = replace(measured_host, memory=MemoryStatus(8 * GIB, 2 * GIB, 0, 0))
    advice = profiles.doctor(installed, tight)["model_recommendation"]
    assert advice["default_fits"] and advice["largest_fitting_model"] == CPU.model_id
    assert profiles.select(installed).id == profiles.PROFILE_ID
    # Both fit the host; the CPU profile is an explicit choice there.
    assert profiles.select(installed, profiles.CPU_PROFILE_ID) == CPU
    chosen = Settings(data_dir=installed.data_dir, profile=profiles.CPU_PROFILE_ID)
    assert profiles.doctor(chosen)["selected_profile"] == profiles.CPU_PROFILE_ID
    assert profiles.select(chosen) == CPU
    with pytest.raises(ValueError, match="unknown profile"):
        profiles.doctor(Settings(data_dir=installed.data_dir, profile="larger-is-better"))


def test_each_profile_is_started_by_its_own_runner(
    installed: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ServerConfig(binary=tmp_path / "not-executed.exe", model=tmp_path / "not-loaded.gguf")
    model = load_model_pins().get(CPU.model_id)
    server = cpu_profile.CpuServer(config, tmp_path / "unused.log", 300, model=model)

    def forbidden(*args: object) -> None:
        pytest.fail("The CPU profile reached the MX350 launch")

    monkeypatch.setattr(profiles.vulkan_profile, "create", forbidden)
    monkeypatch.setattr(profiles.cpu_profile, "create", lambda *args: server)
    try:
        assert profiles.create(installed, "test", CPU).config == config
        assert "--n-gpu-layers" in config.argv(0, "k") and "--device" not in config.argv(0, "k")
        with pytest.raises(ValueError, match="unmeasured"):
            profiles.create(installed, "test", replace(CPU, threads=16))
        server.config = replace(config, ctx_size=16384)
        with pytest.raises(ValueError, match="drifted"):
            profiles.create(installed, "test", CPU)
        assert not server.log_path.exists() and server._proc is None
    finally:
        server.stop()


def test_cpu_launch_rechecks_memory_and_refuses_altered_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = load_model_pins().get(CPU.model_id)
    config = ServerConfig(binary=tmp_path / "not-executed.exe", model=tmp_path / "not-loaded.gguf")
    free = [cpu_profile.REQUIRED_BYTES]
    monkeypatch.setattr(
        "backend.preflight.read_memory", lambda: MemoryStatus(32 * GIB, free[0], 0, 0)
    )
    server = cpu_profile.CpuServer(config, tmp_path / "unused.log", 300, model=model)
    altered = cpu_profile.CpuServer(
        replace(config, batch_size=256), tmp_path / "other.log", 300, model=model
    )
    try:
        assert server.preflight().ok
        free[0] -= 1
        refused = server.preflight()
        assert not refused.ok and refused.requirement is not None
        assert refused.requirement.total == cpu_profile.REQUIRED_BYTES
        with pytest.raises(ServerError, match=re.escape("needs about 2.4 GB")):
            server.start()
        assert server._proc is None
        assert not altered.preflight().ok and "no measured" in altered.preflight().message
    finally:
        server.stop()
        altered.stop()


class FakeServer:
    """Answers the two checks without a model."""

    def __init__(self, tmp_path: Path, *, fits: bool = True, leak: bool = False) -> None:
        self.config = ServerConfig(binary=tmp_path / "x.exe", model=tmp_path / "x.gguf")
        self.redactor = SimpleNamespace(text=lambda text: text)
        self.sampler = None
        self.memory_abort: str | None = None
        self.load_seconds = 1.0
        self.fits, self.leak, self.started, self.stopped = fits, leak, False, False

    def preflight(self) -> PreflightResult:
        message = "9.0 GB free." if self.fits else "1.0 GB free. Close other apps."
        return PreflightResult(self.fits, "Qwen3.5-2B", 8192, 0, None, message)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def checks(monkeypatch: pytest.MonkeyPatch) -> None:
    from eval.feasibility import canary, constrained_answers

    monkeypatch.setattr("eval.bench.machine.machine_state", lambda: {"software_fixture": True})
    monkeypatch.setattr(
        constrained_answers,
        "run_one",
        lambda server, name, *rest: {"snippet": name, "parsed": True, "invalid_citations": []},
    )
    monkeypatch.setattr(
        canary,
        "run_pairs",
        lambda server, pairs, cache: [{"a_contains_token": True, "leaked": server.leak}],
    )


def check(settings: Settings, server: FakeServer) -> dict[str, Any]:
    """The real check on the stand-in server, for the laptop the fixtures describe."""
    return acceptance.run(settings, CPU, other_laptop(), cast("Any", server), say=lambda line: None)


def test_a_passing_first_use_check_is_saved_for_this_profile_and_computer(
    installed: Settings, tmp_path: Path, checks: None
) -> None:
    host = other_laptop()
    assert acceptance.state(installed, CPU, host) == "pending"
    server = FakeServer(tmp_path)
    record = check(installed, server)
    assert record["outcome"] == "passed" and server.started and server.stopped
    saved = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    assert saved["profile"] == CPU.identity() and saved["host"]["cpu"] == host.cpu
    assert len(saved["answers"]) == 3 and len(saved["canary"]) == 10
    assert set(saved["host"]) == {
        "os",
        "architecture",
        "cpu",
        "physical_cores",
        "logical_cores",
        "total_memory_bytes",
    }
    assert acceptance.state(installed, CPU, host) == "passed"
    # A pass belongs to one computer and one exact profile.
    assert acceptance.state(installed, CPU, replace(host, cpu="Another processor")) == "pending"
    assert acceptance.state(installed, replace(CPU, threads=8), host) == "pending"
    assert acceptance.state(installed, profiles.REGISTRY[profiles.PROFILE_ID], host) == "not needed"
    assert profiles.doctor(installed)["profiles"][1]["first_use_check"] == "passed"


def test_a_failed_first_use_check_blocks_review_until_it_passes(
    installed: Settings, tmp_path: Path, checks: None
) -> None:
    failed = check(installed, FakeServer(tmp_path, leak=True))
    assert failed["outcome"] == "failed" and "plumb calibrate" in acceptance.explain(failed)
    report = profiles.doctor(installed)
    assert not report["selection_ready"] and report["profiles"][1]["prerequisites_ready"]
    with pytest.raises(ValueError, match="failed its first-use check"):
        profiles.select(installed)
    assert profiles.select(installed, rechecking=True) == CPU
    check(installed, FakeServer(tmp_path))
    assert profiles.select(installed) == CPU


def test_a_memory_refusal_neither_qualifies_nor_blocks(
    installed: Settings, tmp_path: Path, checks: None
) -> None:
    host = other_laptop()
    server = FakeServer(tmp_path, fits=False)
    refused = check(installed, server)
    assert refused["outcome"] == "refused" and not server.started and server.stopped
    assert not refused["model_loaded"] and "Nothing was decided" in acceptance.explain(refused)
    assert acceptance.state(installed, CPU, host) == "pending"
    stopped = FakeServer(tmp_path, leak=True)
    stopped.memory_abort = "Model stopped: available RAM fell below 256 MiB."
    assert check(installed, stopped)["outcome"] == "refused"
    assert acceptance.state(installed, CPU, host) == "pending"
    assert profiles.select(installed) == CPU


def test_a_forged_or_unreadable_record_for_another_key_is_ignored(installed: Settings) -> None:
    folder = acceptance.folder(installed)
    folder.mkdir(parents=True)
    (folder / "cpu-8k-1.json").write_text("not json", encoding="utf-8")
    (folder / "cpu-8k-2.json").write_text(
        json.dumps({"key": "0" * 64, "outcome": "passed"}), encoding="utf-8"
    )
    (folder / "cpu-8k-3.json").write_text(json.dumps(["passed"]), encoding="utf-8")
    assert acceptance.state(installed, CPU, other_laptop()) == "pending"


def test_calibrate_command_runs_the_check_and_reports_each_outcome(
    installed: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend import cli

    monkeypatch.setenv("PLUMB_DATA_DIR", str(installed.data_dir))
    outcomes = iter(
        [
            {"outcome": "passed", "path": "saved-record.json"},
            {"outcome": "failed", "path": "saved-record.json"},
            {"outcome": "refused", "reason": "1.0 GB free.", "path": "saved-record.json"},
        ]
    )
    requested: list[str] = []

    def check(settings: Settings, profile: profiles.Profile, log_name: str) -> dict[str, Any]:
        requested.append(profile.id)
        return next(outcomes)

    monkeypatch.setattr(cli, "first_use_check", check)
    assert main(["calibrate"]) == 0
    assert "Passed" in capsys.readouterr().out
    assert main(["calibrate", "--profile", "cpu-8k"]) == 1
    assert "failed its first-use check" in capsys.readouterr().out
    assert main(["calibrate"]) == 2
    assert "Nothing was decided" in capsys.readouterr().out
    assert requested == ["cpu-8k"] * 3
    # The measured profile is refused on this hardware, so no check starts for it.
    assert main(["calibrate", "--profile", profiles.PROFILE_ID]) == 1
    assert "Check could not start" in capsys.readouterr().out and len(requested) == 3


def test_setup_previews_the_cpu_runner_and_model_for_another_laptop(
    installed: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.setup import __main__ as wizard

    monkeypatch.setattr(wizard, "helper_status", lambda settings: {"ready": True})
    monkeypatch.setattr(profiles, "is_verified", lambda *args, **kwargs: False)
    monkeypatch.setattr(profiles, "verify_runtime", lambda *args: False)
    plan = wizard.preview(installed)
    assert plan["profile"] == "cpu-8k" and not plan["ready"]
    assert [item["kind"] for item in plan["missing_downloads"]] == [
        "model",
        "runtime",
        "pattern scanner",
    ]
    assert "win-cpu-x64" in plan["missing_downloads"][1]["source"]
    assert plan["requires_large_download_approval"]
    with pytest.raises(ValueError, match="explicitly approve"):
        wizard.install(installed, plan)
    assert not installed.models_dir.exists()


def test_browser_readiness_shows_the_cpu_profile_without_graphics_memory(
    installed: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend import setup_reads
    from backend.setup import __main__ as wizard

    monkeypatch.setattr(wizard, "helper_status", lambda settings: {"ready": True})
    monkeypatch.setattr(wizard, "is_verified", lambda *args, **kwargs: True)
    view = setup_reads.readiness(installed)
    assert view.profile_id == "cpu-8k" and view.ready and view.memory_fit and view.measured_host
    assert view.required_ram_bytes == cpu_profile.REQUIRED_BYTES
    assert view.required_vram_bytes == 0 and view.available_vram_bytes is None
    assert any("first review on this computer" in text for text in view.limitations)
    monkeypatch.setattr(profiles, "inventory", lambda settings: other_laptop(GIB))
    short = setup_reads.readiness(installed)
    assert not short.ready and not short.memory_fit
    message = next(c.message for c in short.conditions if c.kind.value == "model_too_large")
    assert "2.44 GB RAM." in message and "VRAM" not in message


# --- A.2: recommending and installing a pinned model (fixtures only; nothing is downloaded) ---

LARGER = "qwen3.5-4b-q4_k_m"
SMALLER = "qwen3.5-0.8b-q4_k_m"
UNJUDGED = "gemma-4-e2b-it-qat-q4_0"
HELPER = {"ready": True, "node_compatible": True, "pnpm_available": True, "action": "fixture"}


def test_only_the_default_models_margin_is_measured_and_larger_ones_are_scaled_up() -> None:
    pins = load_model_pins()
    assert cpu_profile.margin_bytes(pins.get(CPU.model_id)) == MARGIN_BYTES
    assert cpu_profile.margin_bytes(pins.get(SMALLER)) == MARGIN_BYTES
    larger = pins.get(LARGER)
    assert cpu_profile.margin_bytes(larger) == 1_744_830_464 > MARGIN_BYTES
    assert cpu_profile.required_bytes(larger) == 5_026_293_728
    assert cpu_profile.required_bytes(pins.get(UNJUDGED)) is None
    assert list(profiles.REGISTRY)[:2] == [profiles.PROFILE_ID, profiles.CPU_PROFILE_ID]
    assert f"cpu-8k-{UNJUDGED}" not in profiles.REGISTRY
    assert profiles.REGISTRY[f"cpu-8k-{LARGER}"].model_sha256 == larger.sha256


@pytest.mark.parametrize(
    ("free", "largest", "label"),
    [
        (16 * GIB, LARGER, profiles.NOT_COMPARED),
        (3 * GIB, CPU.model_id, None),
        (2 * GIB, SMALLER, profiles.NOT_COMPARED),
        (GIB, None, None),
    ],
)
def test_doctor_ranks_pinned_models_by_fit_and_never_calls_a_larger_one_better(
    installed: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    free: int,
    largest: str | None,
    label: str | None,
) -> None:
    monkeypatch.setattr(profiles, "inventory", lambda settings: other_laptop(free))
    report = profiles.doctor(installed)
    advice = report["model_recommendation"]
    assert advice["default_model"] == CPU.model_id
    assert (advice["largest_fitting_model"], advice["label"]) == (largest, label)
    by_id = {c["id"]: c for c in report["model_candidates"]}
    assert by_id[CPU.model_id]["default"] and by_id[CPU.model_id]["requirement_measured"]
    for candidate in report["model_candidates"]:
        if not candidate["default"]:
            assert candidate["quality"] == "quality not yet compared with the default"
            assert not candidate["requirement_measured"]
    assert by_id[UNJUDGED]["fits_available_ram"] is None and by_id[UNJUDGED]["cpu_profile"] is None
    # Whatever fits, the default profile and the default model are what "auto" selects.
    assert report["recommended_profile"] == "cpu-8k"
    said = json.dumps({k: v for k, v in report.items() if k != "profiles"}).lower()
    assert not any(claim in said for claim in ("better", "more accurate", "finds more"))
    monkeypatch.setenv("PLUMB_DATA_DIR", str(installed.data_dir))
    main(["doctor"])
    printed = capsys.readouterr().out
    assert f"Default model: {CPU.model_id}" in printed
    if label:
        assert f"{largest} (quality not yet compared with the default)" in printed
        assert f"plumb setup --install --model {largest}" in printed


def test_a_larger_model_is_an_explicit_choice_with_its_own_first_use_check(
    installed: Settings, tmp_path: Path, checks: None
) -> None:
    larger = profiles.REGISTRY[f"cpu-8k-{LARGER}"]
    check(installed, FakeServer(tmp_path))  # the default profile passes its check
    assert profiles.select(installed) == CPU
    assert acceptance.state(installed, larger, other_laptop()) == "pending"
    assert profiles.select(installed, larger.id) == larger
    judged = profiles.chosen(profiles.doctor(installed), larger.id)
    assert "quality not yet compared with the default" in judged["evaluated_capability"]


def test_setup_installs_a_named_pinned_model_only_with_approval(
    installed: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend import user_config
    from backend.setup import __main__ as wizard

    larger = load_model_pins().get(LARGER)
    present: set[str] = {CPU.model_id}
    fetched: list[tuple[str, str, int]] = []

    models = {m.sha256: m.id for m in load_model_pins().models}

    def verified(path: Path, *, sha256: str, size: int) -> bool:
        # Runner archives are present; a model only once it is "downloaded".
        return models.get(sha256, CPU.model_id) in present

    def fetch(url: str, dest: Path, *, sha256: str, size: int, client: object) -> Path:
        fetched.append((url, sha256, size))
        present.add(LARGER)
        return dest

    monkeypatch.setattr(user_config, "user_dir", lambda: installed.data_dir.parent / "user")
    monkeypatch.setattr(wizard, "helper_status", lambda settings: HELPER)
    monkeypatch.setattr(profiles, "is_verified", verified)
    monkeypatch.setattr(wizard, "is_verified", verified)
    monkeypatch.setattr(wizard, "verify_runtime", lambda *args: True)
    monkeypatch.setattr(wizard, "fetch", fetch)
    monkeypatch.setenv("PLUMB_DATA_DIR", str(installed.data_dir))

    plan = wizard.preview(installed, model_id=LARGER)
    assert plan["profile"] == f"cpu-8k-{LARGER}" and plan["requires_large_download_approval"]
    assert [(m["kind"], m["sha256"]) for m in plan["missing_downloads"]] == [
        ("model", larger.sha256)
    ]
    assert plan["model_note"].endswith("quality not yet compared with the default")
    assert wizard.main(["--install", "--model", LARGER]) == 1
    assert not fetched and "explicitly approve" in capsys.readouterr().out
    assert wizard.main(["--install", "--model", LARGER, "--approve-large-downloads"]) == 0
    assert fetched == [(larger.url, larger.sha256, larger.size)]
    printed = capsys.readouterr().out
    assert "quality not yet compared with the default" in printed
    assert f"--profile cpu-8k-{LARGER}" in printed
    # The default installation is untouched by the option, and it stays the default.
    assert wizard.preview(installed)["profile"] == "cpu-8k"
    with pytest.raises(ValueError, match="cannot be used with --inspect-only"):
        wizard.preview(installed, inspect_only=True, model_id=LARGER)
    with pytest.raises(ValueError, match="Unknown or unsupported model"):
        wizard.preview(installed, model_id=UNJUDGED)
    with pytest.raises(SystemExit):
        wizard.main(["--install", "--model", "anything-bigger"])


# --- A.6: public setup installs the pattern scanner (stand-in download) ---


def test_setup_previews_and_installs_the_pattern_scanner_and_doctor_shows_it(
    installed: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend import user_config
    from backend.setup import __main__ as wizard
    from backend.setup.pins import load_opengrep_pin

    pin = load_opengrep_pin()
    present: list[str] = []
    installs: list[str] = []

    def verified(path: Path, *, sha256: str, size: int) -> bool:
        # Model and runner are present; the scanner only once it is "downloaded".
        return sha256 != pin.asset.sha256 or bool(present)

    def install(settings: Settings, scanner: object, client: object) -> Path:
        installs.append(pin.asset.sha256)
        present.append("scanner")
        return Path("not-written")

    monkeypatch.setattr(user_config, "user_dir", lambda: installed.data_dir.parent / "user")
    monkeypatch.setattr(wizard, "helper_status", lambda settings: HELPER)
    monkeypatch.setattr(profiles, "is_verified", verified)
    monkeypatch.setattr(wizard, "is_verified", verified)
    monkeypatch.setattr(wizard, "verify_runtime", lambda *args: True)
    monkeypatch.setattr(wizard.opengrep, "install", install)
    monkeypatch.setenv("PLUMB_DATA_DIR", str(installed.data_dir))

    report = profiles.doctor(installed)
    # A missing scanner is reported, and does not stop a review.
    assert report["pattern_scanner"]["verified_installed"] is False and report["selection_ready"]
    plan = wizard.preview(installed)
    assert [(m["kind"], m["sha256"]) for m in plan["missing_downloads"]] == [
        ("pattern scanner", pin.asset.sha256)
    ]
    assert plan["missing_download_bytes"] == pin.asset.size
    assert not plan["requires_large_download_approval"]
    assert "Install it with: plumb setup --install" in wizard.human_summary(plan, installing=False)
    # Source inspection does not use the scanner.
    assert wizard.preview(installed, inspect_only=True)["missing_downloads"] == []
    main(["doctor"])
    assert "Pattern scanner (Opengrep v1.30.0): not installed" in capsys.readouterr().out

    assert wizard.main(["--install"]) == 0
    assert installs == [pin.asset.sha256]
    assert wizard.preview(installed)["missing_downloads"] == []
    assert profiles.doctor(installed)["pattern_scanner"]["verified_installed"] is True
    assert wizard.main(["--install"]) == 0 and len(installs) == 1
    main(["doctor"])
    assert "Pattern scanner (Opengrep v1.30.0): installed" in capsys.readouterr().out
