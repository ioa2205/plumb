from backend.memory import MemoryStatus, read_memory
from backend.preflight import GB, check, requirement
from backend.setup.pins import load_model_pins

PINS = load_model_pins()
QWEN_2B = PINS.get("qwen3.5-2b-q4_k_m")
QWEN_08B = PINS.get("qwen3.5-0.8b-q4_k_m")
GEMMA = PINS.get("gemma-4-e2b-it-qat-q4_0")
MARGIN = 500 * 1024**2
CTX = 8192


def memory(available: int) -> MemoryStatus:
    return MemoryStatus(
        total_bytes=8 * 1024**3,
        available_bytes=available,
        commit_limit_bytes=22 * 1024**3,
        commit_used_bytes=15 * 1024**3,
    )


def test_requirement_is_file_plus_kv_plus_margin() -> None:
    need = requirement(QWEN_2B, CTX, MARGIN)
    assert need is not None
    assert need.file_bytes == QWEN_2B.size
    assert need.kv_bytes == 12 * 1024 * CTX  # 96 MiB at 8K, as in HARDWARE.md
    assert need.total == QWEN_2B.size + 12 * 1024 * CTX + MARGIN


def test_passes_when_everything_fits() -> None:
    need = requirement(QWEN_2B, CTX, MARGIN)
    assert need is not None
    result = check(QWEN_2B, CTX, MARGIN, memory(need.total))
    assert result.ok
    assert result.suggestion is None


def test_refuses_one_byte_short_and_says_what_to_do() -> None:
    need = requirement(QWEN_2B, CTX, MARGIN)
    assert need is not None
    result = check(QWEN_2B, CTX, MARGIN, memory(need.total - 1), alternatives=PINS.models)
    assert not result.ok
    assert result.message.startswith(f"{(need.total - 1) / GB:.1f} GB free. Qwen3.5-2B needs about")
    assert "at an 8K context" in result.message
    assert result.suggestion == "Qwen3.5-0.8B"
    assert result.message.endswith("Close other apps, or switch to Qwen3.5-0.8B.")


def test_refuses_at_observed_everyday_free_memory() -> None:
    # 0.80 GiB available was observed while writing this test (HARDWARE.md: 0.7-1.7 GiB).
    result = check(QWEN_2B, CTX, MARGIN, memory(int(0.80 * 1024**3)), alternatives=PINS.models)
    assert not result.ok
    assert result.suggestion is None
    assert result.message.endswith("Close other apps.")


def test_suggests_the_largest_model_that_fits() -> None:
    fits_2b = requirement(QWEN_2B, CTX, MARGIN)
    assert fits_2b is not None
    result = check(
        PINS.get("qwen3.5-4b-q4_k_m"), CTX, MARGIN, memory(fits_2b.total), alternatives=PINS.models
    )
    assert not result.ok
    assert result.suggestion == "Qwen3.5-2B"


def test_unknown_kv_size_is_refused_not_guessed() -> None:
    assert GEMMA.kv_bytes_per_token is None
    result = check(GEMMA, CTX, MARGIN, memory(64 * 1024**3))
    assert not result.ok
    assert result.requirement is None
    assert "no measured KV cache size" in result.message


def test_longer_context_needs_more_memory() -> None:
    short = requirement(QWEN_2B, 8192, MARGIN)
    long = requirement(QWEN_2B, 32768, MARGIN)
    assert short is not None and long is not None
    assert long.kv_bytes - short.kv_bytes == 12 * 1024 * (32768 - 8192)


def test_reads_real_memory_status() -> None:
    status = read_memory()
    assert 0 < status.available_bytes <= status.total_bytes


def test_margin_is_derived_from_the_recorded_benchmark() -> None:
    import json
    import math
    from pathlib import Path

    from backend.preflight import (
        MARGIN_BYTES,
        MARGIN_SOURCE,
        MEASURED_OVERHEAD_BYTES,
        MIB,
        SAFETY_ALLOWANCE_BYTES,
    )

    report = json.loads((Path(__file__).resolve().parents[2] / MARGIN_SOURCE).read_text())
    assert report["manifest"]["model"]["sha256_verified"] == QWEN_2B.sha256
    ctx = report["manifest"]["settings"]["ctx_size"]
    peak = max(t["peak_working_set_bytes"] for t in report["threads"])
    assert QWEN_2B.kv_bytes_per_token is not None
    overhead = peak - QWEN_2B.size - QWEN_2B.kv_bytes_per_token * ctx
    assert overhead == MEASURED_OVERHEAD_BYTES
    step = 128 * MIB
    assert math.ceil((overhead + SAFETY_ALLOWANCE_BYTES) / step) * step == MARGIN_BYTES


def test_calibrated_margin_admits_the_2b_model_at_measured_session_memory() -> None:
    from backend.preflight import MARGIN_BYTES

    # 2.62 GiB was available before the calibration run's first load.
    result = check(QWEN_2B, CTX, MARGIN_BYTES, memory(int(2.62 * 1024**3)))
    assert result.ok
