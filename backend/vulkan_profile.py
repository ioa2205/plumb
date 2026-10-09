"""Measured 8K Qwen3.5-2B profile for this laptop's MX350 (ADR-0006).

The original CPU gate remains separate. No smaller margin is passed to it.
"""

import re
import shutil
import subprocess
import threading

from backend.llama_server import LlamaServer, ServerConfig, ServerError
from backend.memory import MemoryStatus, read_memory
from backend.preflight import GB, MIB, DeviceRequirement, PreflightResult
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.download import sha256_file
from backend.setup.models import model_path
from backend.setup.pins import load_llama_cpp_pin, load_model_pins

MODEL_ID = "qwen3.5-2b-q4_k_m"
MODEL_SHA256 = "57a1085840f497d764a7fc5d346922dbde961efb54cc792ea81d694fd846a1d8"
BUILD_COMMIT = "7fe450e19305b828c199d602c23a8337aaa1f03b"
DEVICE = "Vulkan1"
DEVICE_NAME = "NVIDIA GeForce MX350"
# Allocation estimate rounded up per column, plus the original 896 MiB host
# allowance and 256 MiB device reserve. Measured inference must stay below these.
REQUIREMENT = DeviceRequirement(1298 * MIB, 1694 * MIB, DEVICE_NAME)
LOW_MEMORY_BYTES = 256 * MIB
EXTRA_ARGS = ("--fit", "off", "--no-repack", "--device", DEVICE, "--load-mode", "dio")


def device_budget(output: str) -> int:
    matches = re.findall(
        rf"^\s*{DEVICE}: {re.escape(DEVICE_NAME)} \(\d+ MiB, (\d+) MiB free\)\s*$",
        output,
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise ValueError("The measured MX350 is not Vulkan1; this profile needs revalidation.")
    return int(matches[0]) * MIB


def nvidia_free() -> int:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise ValueError("Cannot read the MX350's dedicated VRAM.")
    result = subprocess.run(  # noqa: S603 - fixed arguments to the system GPU utility
        [executable, "--query-gpu=name,memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    matches = re.findall(rf"^{re.escape(DEVICE_NAME)},\s*(\d+)\s*$", result.stdout, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("Cannot identify the MX350's dedicated VRAM.")
    return int(matches[0]) * MIB


def check_memory(memory: MemoryStatus, vram_bytes: int) -> PreflightResult:
    ok = memory.available_bytes >= REQUIREMENT.host_bytes and vram_bytes >= REQUIREMENT.device_bytes
    message = (
        f"MX350 profile: {memory.available_bytes / GB:.2f} GB RAM and {vram_bytes / GB:.2f} GB "
        f"VRAM available; needs {REQUIREMENT.host_bytes / GB:.2f} GB RAM and "
        f"{REQUIREMENT.device_bytes / GB:.2f} GB VRAM at 8K."
    )
    return PreflightResult(
        ok, "Qwen3.5-2B (MX350 Vulkan)", 8192, memory.available_bytes, REQUIREMENT, message
    )


class VulkanServer(LlamaServer):
    """One owned model process, stopped if real available RAM crosses the floor."""

    _watcher: threading.Thread | None = None
    _watch_stop: threading.Event | None = None
    memory_abort: str | None = None

    def preflight(self) -> PreflightResult:
        # Guard against using the measured budget with altered launch settings.
        c = self.config
        supported = (
            c.ctx_size == 8192
            and c.threads == 4
            and c.batch_size == 256
            and c.ubatch_size == 64
            and c.gpu_layers == 99
            and c.stateless
            and c.reasoning == "off"
            and c.extra_args == EXTRA_ARGS
        )
        try:
            if not supported:
                raise ValueError("These launch settings have no measured MX350 memory profile.")
            devices = llama_cpp.run_tool(c.binary, "--list-devices")
            if devices.returncode:
                raise ValueError("The Vulkan runtime could not list its devices.")
            vram = min(device_budget(devices.stdout + devices.stderr), nvidia_free())
            return check_memory(read_memory(), vram)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            memory = read_memory()
            return PreflightResult(
                False,
                "Qwen3.5-2B (MX350 Vulkan)",
                8192,
                memory.available_bytes,
                REQUIREMENT,
                self.redactor.text(f"Vulkan preflight refused: {error}"),
            )

    def start(self) -> None:
        # Also enforce the gate for callers that do not use ModelAdapter.
        if self._proc is not None and self._proc.poll() is None:
            raise ServerError("The model process is already running.")
        result = self.preflight()
        if not result.ok:
            raise ServerError(result.message)
        self.memory_abort = None
        self._watch_stop = threading.Event()
        self._watcher = threading.Thread(target=self._watch_memory, daemon=True)
        self._watcher.start()
        try:
            super().start()
            self._raise_if_aborted()
        except BaseException:
            self.stop()
            raise

    def _raise_if_aborted(self) -> None:
        if self.memory_abort:
            raise ServerError(self.memory_abort)

    def _watch_memory(self) -> None:
        assert self._watch_stop is not None  # noqa: S101 - internal lifecycle invariant
        while not self._watch_stop.wait(0.1):
            try:
                if read_memory().available_bytes < LOW_MEMORY_BYTES:
                    self.memory_abort = "Model stopped: available RAM fell below 256 MiB."
            except OSError:
                self.memory_abort = "Model stopped: available RAM could not be measured."
            if self.memory_abort and self._proc is not None:
                if self._proc.poll() is None:
                    self._proc.kill()
                return

    def stop(self) -> None:
        if self._watch_stop:
            self._watch_stop.set()
        try:
            super().stop()
        finally:
            if self._watcher:
                self._watcher.join(timeout=5)
                self._watcher = None


def create(settings: Settings, log_name: str) -> VulkanServer:
    """Verify assets and bind the exact calibrated configuration. Starts nothing."""
    llama = load_llama_cpp_pin()
    model = load_model_pins().get(MODEL_ID)
    if llama.commit != BUILD_COMMIT or llama.build != "b11146" or model.sha256 != MODEL_SHA256:
        raise ValueError("Runtime or model pin changed; remeasure the MX350 profile first.")
    if not llama_cpp.is_installed(settings, llama, "vulkan"):
        raise ValueError("The pinned Vulkan runtime is not installed.")
    gguf = model_path(settings, model)
    if sha256_file(gguf) != MODEL_SHA256:
        raise ValueError("The model file no longer matches the measured pin.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", log_name):
        raise ValueError("log_name must be a plain file stem")
    config = ServerConfig(
        binary=llama_cpp.binary(settings, llama, "vulkan"),
        model=gguf,
        batch_size=256,
        ubatch_size=64,
        gpu_layers=99,
        extra_args=EXTRA_ARGS,
    )
    return VulkanServer(config, settings.cache_dir / "run-logs" / f"{log_name}.log", 120)
