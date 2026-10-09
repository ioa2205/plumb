"""Memory preflight: refuse to load a model that would page (HARDWARE.md, "Memory budget").

needed = model file + KV cache at the chosen context + margin

The model file counts in full because llama.cpp memory-maps it, and every
generated token streams the weights; if Windows evicts those pages, throughput
collapses. The margin covers what the server holds beyond the file and the KV
cache: weights repacked for the AVX-512 kernels (private copies), compute
buffers, the fixed recurrent state of hybrid models, and the server itself.
"""

from dataclasses import dataclass

from backend.memory import MemoryStatus, read_memory
from backend.setup.pins import ModelPin

GB = 1_000_000_000  # decimal, matching how model publishers state file sizes
MIB = 1024**2

# Calibrated 2026-10-03 (task M0.7) from MARGIN_SOURCE: the peak working set of
# llama-server was 2,129,747,968 bytes = model file 1,396,198,496 + KV cache at
# 8K 100,663,296 + 632,886,176 measured overhead (603.6 MiB). The margin is that
# overhead plus a 256 MiB allowance, rounded up to a multiple of 128 MiB.
# Measured for Qwen3.5-2B Q4_K_M on the CPU build only. Repacked weights grow with
# model size, so other models need their own measurement (experiment E1).
MEASURED_OVERHEAD_BYTES = 632_886_176
SAFETY_ALLOWANCE_BYTES = 256 * MIB
MARGIN_BYTES = 896 * MIB
MARGIN_SOURCE = "docs/results/2026-10-03-1032-bench-qwen3.5-2b-q4_k_m-cpu.json"


@dataclass(frozen=True)
class Requirement:
    file_bytes: int
    kv_bytes: int
    margin_bytes: int

    @property
    def total(self) -> int:
        return self.file_bytes + self.kv_bytes + self.margin_bytes


@dataclass(frozen=True)
class DeviceRequirement:
    """A measured offload profile needs headroom in two separate memory pools."""

    host_bytes: int
    device_bytes: int
    device_name: str

    @property
    def total(self) -> int:
        """RAM requirement; device memory is never added to available RAM."""
        return self.host_bytes


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    model: str
    ctx_size: int
    available_bytes: int
    requirement: Requirement | DeviceRequirement | None
    message: str
    suggestion: str | None = None


def _ctx_label(ctx_size: int) -> str:
    return f"{ctx_size // 1024}K" if ctx_size % 1024 == 0 else str(ctx_size)


def requirement(model: ModelPin, ctx_size: int, margin_bytes: int) -> Requirement | None:
    if model.kv_bytes_per_token is None:
        return None
    return Requirement(model.size, model.kv_bytes_per_token * ctx_size, margin_bytes)


def check(
    model: ModelPin,
    ctx_size: int,
    margin_bytes: int,
    memory: MemoryStatus | None = None,
    alternatives: list[ModelPin] | None = None,
) -> PreflightResult:
    """Decide whether ``model`` fits in available memory at ``ctx_size``."""
    memory = memory or read_memory()
    available = memory.available_bytes
    need = requirement(model, ctx_size, margin_bytes)
    ctx = _ctx_label(ctx_size)
    if need is None:
        return PreflightResult(
            ok=False,
            model=model.family,
            ctx_size=ctx_size,
            available_bytes=available,
            requirement=None,
            message=(
                f"{model.family} has no measured KV cache size, so Plumb cannot tell whether it "
                "fits. Measure it before using it."
            ),
        )
    if need.total <= available:
        return PreflightResult(
            ok=True,
            model=model.family,
            ctx_size=ctx_size,
            available_bytes=available,
            requirement=need,
            message=(
                f"{available / GB:.1f} GB free. {model.family} needs about "
                f"{need.total / GB:.1f} GB at an {ctx} context."
            ),
        )
    fitting = [
        alt
        for alt in alternatives or []
        if alt.id != model.id
        and (r := requirement(alt, ctx_size, margin_bytes)) is not None
        and r.total <= available
    ]
    suggestion = max(fitting, key=lambda m: m.size).family if fitting else None
    advice = f"Close other apps, or switch to {suggestion}." if suggestion else "Close other apps."
    return PreflightResult(
        ok=False,
        model=model.family,
        ctx_size=ctx_size,
        available_bytes=available,
        requirement=need,
        message=(
            f"{available / GB:.1f} GB free. {model.family} needs about "
            f"{need.total / GB:.1f} GB at an {ctx} context. {advice}"
        ),
        suggestion=suggestion,
    )
