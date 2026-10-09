"""M0.7a / E6: bounded profile calibration using existing pinned assets (ADR-0006).

Run with ``uv run python -m eval.feasibility.memory_profile``. This experiment does
not change the production CPU gate or automatically select a runtime profile.
"""

import argparse
import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from backend.llama_server import LlamaServer, ServerConfig
from backend.memory import read_memory
from backend.preflight import MARGIN_BYTES, MIB, SAFETY_ALLOWANCE_BYTES
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.download import sha256_file
from backend.setup.models import model_path
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from eval.bench.machine import machine_state
from eval.bench.run import measure, prompt_tokens, summarize
from eval.feasibility.canary import run_pairs
from eval.feasibility.common import RESULTS_DIR
from eval.feasibility.constrained_answers import SNIPPETS, run_one


def parse_estimate(output: str, *, cuda: bool = True, device: str = "CUDA0") -> dict[str, int]:
    """Only accept the pinned single-GPU estimator's complete allocation table.

    Its MiB columns are rounded down. Add one MiB per column, including zeroes,
    so rounding cannot make the gate undercount the underlying allocations.
    """
    result: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[0] not in {"Host", device} or parts[0] in result:
            raise ValueError("unexpected estimator output")
        if any(not value.isascii() or not value.isdecimal() for value in parts[1:]):
            raise ValueError("invalid allocation estimate")
        result[parts[0]] = sum(int(value) + 1 for value in parts[1:]) * MIB
    expected = {"Host", device} if cuda else {"Host"}
    if set(result) != expected or any(value <= 3 * MIB for value in result.values()):
        raise ValueError("incomplete allocation estimate")
    return result


def gate(
    estimate: dict[str, int], ram: int, vram: int, *, device: str = "CUDA0"
) -> dict[str, int | bool]:
    host_need = estimate["Host"] + MARGIN_BYTES
    gpu_need = estimate[device] + SAFETY_ALLOWANCE_BYTES
    return {
        "ok": ram >= host_need and vram >= gpu_need,
        "available_ram_bytes": ram,
        "available_vram_bytes": vram,
        "required_ram_bytes": host_need,
        "required_vram_bytes": gpu_need,
    }


def cpu_gate(output: str, file_bytes: int, available: int) -> dict[str, Any]:
    allocations = parse_estimate(output, cuda=False)
    columns = output.split()
    # Keep the full file resident even when the estimator omits unused tensors.
    need = max(file_bytes, (int(columns[1]) + 1) * MIB)
    need += (int(columns[2]) + int(columns[3]) + 2) * MIB + SAFETY_ALLOWANCE_BYTES
    return {
        "ok": available >= need,
        "required_ram_bytes": need,
        "available_ram_bytes": available,
        "estimated_allocations": allocations,
    }


def free_vram() -> int:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise RuntimeError("nvidia-smi unavailable")
    result = subprocess.run(  # noqa: S603 - fixed arguments to the system GPU utility
        [executable, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    value = result.stdout.strip()
    if not value.isascii() or not value.isdecimal():
        raise ValueError("expected exactly one GPU memory reading")
    return int(value) * MIB


def acceptance_passed(report: dict[str, Any]) -> bool:
    answers, pairs = report.get("answers", []), report.get("canary", [])
    return (
        len(answers) == len(SNIPPETS)
        and all(row.get("parsed") and not row.get("invalid_citations") for row in answers)
        and len(pairs) == 10
        and all(row["a_contains_token"] and not row["leaked"] for row in pairs)
        and "error" not in report
        and not report.get("abort_reason")
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--profile",
        choices=["cpu-no-repack", "vulkan", "cuda-experimental"],
        default="cpu-no-repack",
    )
    args = parser.parse_args(argv)
    cuda = args.profile == "cuda-experimental"
    vulkan = args.profile == "vulkan"
    variant = "cuda-12.4" if cuda else "vulkan" if vulkan else "cpu"
    device = "Vulkan1"
    settings, pins, llama = Settings(), load_model_pins(), load_llama_cpp_pin()
    model = pins.get("qwen3.5-2b-q4_k_m")
    gguf = model_path(settings, model)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    name = f"{stamp}-m0.7a-{args.profile}"
    output = RESULTS_DIR / f"{name}.json"
    config = ServerConfig(
        binary=llama_cpp.binary(settings, llama, variant),
        model=gguf,
        batch_size=256,
        ubatch_size=64,
        gpu_layers=99 if cuda or vulkan else 0,
        extra_args=(
            "--fit",
            "off",
            *(("--no-repack",) if not cuda else ()),
            *(("--device", device, "--load-mode", "dio") if vulkan else ()),
        ),
    )
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "adr": "ADR-0006",
        "llama_cpp": llama.model_dump(mode="json"),
        "variant": variant,
        "model": model.model_dump(mode="json"),
        "server_argv": config.argv(0, "<per-launch key>"),
        "answers": [],
        "canary": [],
        "benchmark": {},
        "model_loaded": False,
    }
    server = LlamaServer(config, settings.cache_dir / "run-logs" / f"{name}.log", 120)
    stop = threading.Event()
    watcher: threading.Thread | None = None

    def monitor() -> None:
        deadline = time.monotonic() + 900
        try:
            while not stop.wait(0.1):
                available = read_memory().available_bytes
                report["minimum_available_ram_bytes"] = min(
                    report.get("minimum_available_ram_bytes", available), available
                )
                if server.sampler:
                    server.sampler.sample()
                reason = (
                    "available RAM below 256 MiB"
                    if available < SAFETY_ALLOWANCE_BYTES
                    else "experiment exceeded 900 seconds"
                    if time.monotonic() > deadline
                    else None
                )
                if reason:
                    report["abort_reason"] = reason
                    if server._proc and server._proc.poll() is None:
                        server._proc.kill()
                    return
        except Exception as error:
            report["abort_reason"] = f"monitor failed: {type(error).__name__}"
            if server._proc and server._proc.poll() is None:
                server._proc.kill()

    try:
        if cuda:
            raise RuntimeError(
                "this CUDA profile failed on this machine; see ADR-0006 before retrying"
            )
        if not llama_cpp.is_installed(settings, llama, variant):
            raise RuntimeError("pinned installation marker missing or mismatched")
        gpu_budget = 0
        if vulkan:
            devices = llama_cpp.run_tool(config.binary, "--list-devices")
            report["devices"] = devices.stdout + devices.stderr
            matched = re.search(
                rf"{device}: NVIDIA GeForce MX350 \(\d+ MiB, (\d+) MiB free\)", report["devices"]
            )
            if devices.returncode or matched is None:
                raise RuntimeError("Vulkan1 is not the measured MX350; do not select Iris Xe")
            gpu_budget = int(matched.group(1)) * MIB
        actual = sha256_file(gguf)
        report["model_sha256_actual"] = actual
        if actual != model.sha256:
            raise RuntimeError("model hash does not match pin")
        estimate_args = [
            "-m",
            str(gguf),
            "-c",
            "8192",
            "-b",
            "256",
            "-ub",
            "64",
            "-ngl",
            str(config.gpu_layers),
            "--parallel",
            "1",
            "--fit-print",
            "on",
            "--offline",
            "--no-repack",
            *(("--device", device, "--load-mode", "dio") if vulkan else ()),
        ]
        estimate = llama_cpp.run_tool(
            llama_cpp.binary(settings, llama, variant, "llama-fit-params"), *estimate_args
        )
        report["estimator"] = {
            "args": estimate_args,
            "returncode": estimate.returncode,
            "stdout": estimate.stdout,
            "stderr": estimate.stderr,
        }
        if estimate.returncode:
            raise RuntimeError("allocation estimator failed")
        report["machine_start"] = machine_state()
        if vulkan:
            allocations = parse_estimate(estimate.stdout, device=device)
            vram = min(gpu_budget, free_vram())
            report["preflight"] = gate(
                allocations, read_memory().available_bytes, vram, device=device
            )
        else:
            report["preflight"] = cpu_gate(
                estimate.stdout, model.size, read_memory().available_bytes
            )
        print(f"Preflight: {report['preflight']}", flush=True)
        if not report["preflight"]["ok"]:
            report["refused"] = True
            return 2
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        if report.get("abort_reason"):
            raise RuntimeError("memory monitor refused startup")
        server.start()
        report["model_loaded"] = True
        report["load_seconds"] = server.load_seconds
        print(f"Model ready in {server.load_seconds:.2f}s", flush=True)
        for snippet in SNIPPETS:
            row = run_one(server, *snippet)
            report["answers"].append(row)
            print(f"Schema {snippet[0]}: parsed={row['parsed']}", flush=True)
        for index in range(10):
            report["canary"].extend(run_pairs(server, 1, False))
            print(f"Canary pair {index + 1}/10: {report['canary'][-1]['leaked']=}", flush=True)
        if not acceptance_passed(report):
            raise RuntimeError("schema or stateless isolation acceptance failed")
        for size in (512, 2048):
            tokens = prompt_tokens(server, size)
            entry: dict[str, Any] = {"warmup_discarded": measure(server, tokens, 128), "runs": []}
            report["benchmark"][str(size)] = entry
            for index in range(3):
                entry["runs"].append(measure(server, tokens, 128))
                print(f"Benchmark {size} tokens, run {index + 1}/3", flush=True)
            entry["summary"] = summarize(entry["runs"])
        report["gpu_after_requests"] = free_vram()
    except Exception as error:
        report["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
        print(report["error"], flush=True)
    finally:
        stop.set()
        if watcher:
            watcher.join(timeout=5)
        if server.sampler:
            server.sampler.sample()
            report["peak_working_set_bytes"] = server.sampler.peak_working_set
            report["peak_private_bytes"] = server.sampler.peak_private
        try:
            server.stop()
        except Exception as error:
            report["error"] = server.redactor.text(f"cleanup failed: {type(error).__name__}")
        report["server_log"] = (
            server.log_path.read_text(encoding="utf-8") if server.log_path.exists() else None
        )
        report["finished"] = datetime.now(UTC).isoformat()
        report["memory_after"] = asdict(read_memory())
        report["machine_end"] = machine_state()
        report["passed"] = acceptance_passed(report)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Saved {output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
