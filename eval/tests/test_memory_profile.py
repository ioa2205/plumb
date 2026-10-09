import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend.llama_server import ServerConfig
from backend.memory import MemoryStatus
from backend.preflight import MARGIN_BYTES, MIB, SAFETY_ALLOWANCE_BYTES
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.pins import load_model_pins
from eval.feasibility import memory_profile
from eval.feasibility.memory_profile import acceptance_passed, cpu_gate, gate, parse_estimate


@pytest.mark.parametrize(
    "output",
    [
        "",
        "Host 10 1 1",
        "CUDA0 10 1 1",
        "Host 0 0 0\nCUDA0 10 1 1",
        "Host -1 2 3\nCUDA0 10 1 1",
        "Host 1.5 2 3\nCUDA0 10 1 1",
        "Host 10 1 1\nCUDA0 10 1 1\nHost 10 1 1",
        "Host 10 1 1\nCUDA1 10 1 1",
        "Host 10 1 1 extra\nCUDA0 10 1 1",
    ],
)
def test_estimator_rejects_incomplete_or_ambiguous_output(output: str) -> None:
    with pytest.raises(ValueError):
        parse_estimate(output)


def test_cuda_gate_preserves_reserves_on_both_devices() -> None:
    estimate = parse_estimate("CUDA0 1259 115 61 \nHost 397 0 2 \n")
    ram, vram = 402 * MIB + MARGIN_BYTES, 1438 * MIB + SAFETY_ALLOWANCE_BYTES
    assert gate(estimate, ram, vram)["ok"]
    assert not gate(estimate, ram - 1, vram)["ok"]
    assert not gate(estimate, ram, vram - 1)["ok"]


def test_cpu_calibration_counts_whole_file_and_rounds_up_each_buffer() -> None:
    output, size = "Host 1259 115 62 \n", 1_396_198_496
    required = size + (116 + 63) * MIB + SAFETY_ALLOWANCE_BYTES
    assert cpu_gate(output, size, required)["ok"]
    assert not cpu_gate(output, size, required - 1)["ok"]
    # Do not undercount if a different estimate is larger than the file.
    assert cpu_gate("Host 2000 115 62", size, required)["required_ram_bytes"] > required
    with pytest.raises(ValueError):
        cpu_gate("Host 1259 115 62\nCUDA0 1 1 1", size, required)


def passing_report() -> dict[str, Any]:
    return {
        "answers": [{"parsed": True, "invalid_citations": []} for _ in range(3)],
        "canary": [{"a_contains_token": True, "leaked": False} for _ in range(10)],
    }


def test_acceptance_requires_all_checks_and_an_exercised_secret() -> None:
    report = passing_report()
    assert acceptance_passed(report)
    for field, index, key, value in [
        ("answers", 0, "parsed", False),
        ("answers", 1, "invalid_citations", ["L999"]),
        ("canary", 0, "a_contains_token", False),
        ("canary", 9, "leaked", True),
    ]:
        broken = copy.deepcopy(report)
        broken[field][index][key] = value
        assert not acceptance_passed(broken)
    assert not acceptance_passed({**report, "canary": report["canary"][:9]})
    assert not acceptance_passed({**report, "answers": report["answers"][:2]})
    assert not acceptance_passed({**report, "error": "crashed"})
    assert not acceptance_passed({**report, "abort_reason": "low memory"})
    assert not acceptance_passed({})


@pytest.mark.parametrize("failure", ["ram", "hash", "estimator", "startup", "cleanup"])
def test_failed_runs_save_a_manifest_and_refusal_never_starts_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    calls: list[str] = []

    class FailedServer:
        sampler = None

        def __init__(self, config: ServerConfig, log_path: Path, timeout: int) -> None:
            self.log_path = log_path
            self.redactor = Redactor()

        def start(self) -> None:
            calls.append("start")
            raise RuntimeError("test startup failure")

        def stop(self) -> None:
            calls.append("stop")
            if failure == "cleanup":
                raise RuntimeError("test cleanup failure")

    monkeypatch.setattr(memory_profile, "Settings", lambda: Settings(data_dir=tmp_path))
    monkeypatch.setattr(memory_profile, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(memory_profile, "LlamaServer", FailedServer)
    monkeypatch.setattr(memory_profile.llama_cpp, "binary", lambda *args: tmp_path / "llama.exe")
    monkeypatch.setattr(memory_profile.llama_cpp, "is_installed", lambda *args: True)
    model = load_model_pins().get("qwen3.5-2b-q4_k_m")
    monkeypatch.setattr(
        memory_profile, "sha256_file", lambda *args: "bad" if failure == "hash" else model.sha256
    )
    monkeypatch.setattr(
        memory_profile.llama_cpp,
        "run_tool",
        lambda *args: subprocess.CompletedProcess(
            [], 0, "bad" if failure == "estimator" else "Host 1259 115 62", ""
        ),
    )
    monkeypatch.setattr(memory_profile, "machine_state", lambda: {})
    monkeypatch.setattr(
        memory_profile,
        "read_memory",
        lambda: MemoryStatus(8 * 1024**3, 1 if failure == "ram" else 4 * 1024**3, 0, 0),
    )
    assert memory_profile.main([]) in (1, 2)
    report = json.loads(next(tmp_path.glob("*-m0.7a-*.json")).read_text(encoding="utf-8"))
    assert not report["passed"] and not report["model_loaded"]
    assert report.get("refused") or "error" in report
    assert ("start" in calls) == (failure in ("startup", "cleanup"))
    assert "stop" in calls
