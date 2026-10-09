"""Qwen3.5-2B on the pinned CPU build at 8K, for laptops without the measured MX350 (ADR-0024).

The launch settings are the M0.4-M0.8 CPU reference configuration and the memory
requirement is the original CPU gate in ``backend.preflight``. Neither is loosened here.
"""

import re
from pathlib import Path

from backend import vulkan_profile
from backend.llama_server import ServerConfig
from backend.memory import read_memory
from backend.preflight import (
    MARGIN_BYTES,
    MEASURED_OVERHEAD_BYTES,
    MIB,
    SAFETY_ALLOWANCE_BYTES,
    PreflightResult,
    check,
    requirement,
)
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.download import sha256_file
from backend.setup.models import model_path
from backend.setup.pins import ModelPin, load_llama_cpp_pin, load_model_pins

BACKEND = "cpu"
MODEL_ID = vulkan_profile.MODEL_ID
CONTEXT = 8192
THREADS = 4
BATCH = 2048
MICROBATCH = 512
# File 1,396,198,496 + cache at 8K 100,663,296 + the measured 896 MiB margin.
REQUIRED_BYTES = 2_436_385_888


def margin_bytes(model: ModelPin) -> int:
    """Memory held beyond the file and the cache.

    Measured for the default model only. Most of it is private copies of the weights,
    so for a larger file the measured overhead is scaled with the file size and rounded
    up as before. That is an estimate, not a measurement (ADR-0024).
    """
    default = load_model_pins().get(MODEL_ID)
    if model.size <= default.size:
        return MARGIN_BYTES
    step = 128 * MIB
    scaled = MEASURED_OVERHEAD_BYTES * model.size // default.size + SAFETY_ALLOWANCE_BYTES
    return -(-scaled // step) * step


def required_bytes(model: ModelPin) -> int | None:
    """Available RAM a review with ``model`` needs; None when its cache size is unpublished."""
    need = requirement(model, CONTEXT, margin_bytes(model))
    return None if need is None else need.total


class CpuServer(vulkan_profile.VulkanServer):
    """The same owned process and low-memory stop; only the admission check differs."""

    def __init__(
        self, config: ServerConfig, log_path: Path, startup_timeout: float, *, model: ModelPin
    ) -> None:
        super().__init__(config, log_path, startup_timeout)
        self.model = model

    def preflight(self) -> PreflightResult:
        # Guard against using the measured requirement with altered launch settings.
        c = self.config
        supported = (
            c.ctx_size == CONTEXT
            and c.threads == THREADS
            and c.batch_size == BATCH
            and c.ubatch_size == MICROBATCH
            and c.gpu_layers == 0
            and c.stateless
            and c.reasoning == "off"
            and c.extra_args == ()
        )
        if not supported:
            return PreflightResult(
                False,
                self.model.family,
                c.ctx_size,
                read_memory().available_bytes,
                None,
                "CPU preflight refused: these launch settings have no measured memory requirement.",
            )
        return check(self.model, CONTEXT, margin_bytes(self.model))


def create(settings: Settings, log_name: str, model_id: str = MODEL_ID) -> CpuServer:
    """Verify assets and bind the reference configuration. Starts nothing."""
    llama = load_llama_cpp_pin()
    model = load_model_pins().get(model_id)
    if llama.commit != vulkan_profile.BUILD_COMMIT or llama.build != "b11146":
        raise ValueError("Runtime pin changed; check the CPU profile again first.")
    if not llama_cpp.is_installed(settings, llama, BACKEND):
        raise ValueError("The pinned CPU runtime is not installed.")
    gguf = model_path(settings, model)
    if sha256_file(gguf) != model.sha256:
        raise ValueError("The model file no longer matches its pin.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", log_name):
        raise ValueError("log_name must be a plain file stem")
    config = ServerConfig(
        binary=llama_cpp.binary(settings, llama, BACKEND),
        model=gguf,
        ctx_size=CONTEXT,
        threads=THREADS,
        batch_size=BATCH,
        ubatch_size=MICROBATCH,
        gpu_layers=0,
    )
    return CpuServer(config, settings.cache_dir / "run-logs" / f"{log_name}.log", 300, model=model)
