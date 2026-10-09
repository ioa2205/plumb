from pathlib import Path

from backend.llama_server import LOOPBACK, ServerConfig
from eval.bench.run import markdown, spread, summarize, synthetic_code


def test_server_argv_is_loopback_keyed_and_stateless() -> None:
    argv = ServerConfig(binary=Path("llama-server.exe"), model=Path("m.gguf")).argv(8123, "k")
    pairs = dict(zip(argv[1::2], argv[2::2], strict=False))
    assert argv[argv.index("--host") + 1] == LOOPBACK
    assert argv[argv.index("--api-key") + 1] == "k"
    assert argv[argv.index("--parallel") + 1] == "1"
    assert argv[argv.index("--cache-ram") + 1] == "0"  # the default is an 8 GiB host cache
    assert argv[argv.index("--ctx-checkpoints") + 1] == "0"
    assert argv[argv.index("--reasoning") + 1] == "off"
    for flag in ("--no-cache-prompt", "--no-webui", "--no-slots", "--offline"):
        assert flag in argv
    assert "0.0.0.0" not in argv  # noqa: S104 - asserting it is absent
    assert pairs  # argv is well formed: flag/value pairs after the binary


def test_synthetic_code_is_deterministic_and_long_enough() -> None:
    a, b = synthetic_code(5000), synthetic_code(5000)
    assert a == b
    assert len(a) >= 5000
    assert "def get_item_1(" in a


def test_spread_and_summary() -> None:
    assert spread([3.0, 1.0, 2.0]) == {"median": 2.0, "min": 1.0, "max": 3.0}
    runs = [
        {"prefill_tokens_per_s": p, "decode_tokens_per_s": d, "wall_seconds": w}
        for p, d, w in [(100.0, 10.0, 2.0), (110.0, 11.0, 1.8), (90.0, 9.0, 2.2)]
    ]
    s = summarize(runs)
    assert s["prefill_tokens_per_s"]["median"] == 100.0
    assert s["wall_seconds"] == {"median": 2.0, "min": 1.8, "max": 2.2}


def test_markdown_lists_every_thread_and_prompt_size() -> None:
    summary = {
        "prefill_tokens_per_s": {"median": 100.0, "min": 90.0, "max": 110.0},
        "decode_tokens_per_s": {"median": 10.0, "min": 9.0, "max": 11.0},
        "wall_seconds": {"median": 2.0, "min": 1.8, "max": 2.2},
    }
    report = {
        "json_name": "x.json",
        "manifest": {
            "started": "s",
            "finished": "f",
            "model": {"family": "Qwen3.5-2B", "quantization": "Q4_K_M", "sha256_verified": "ab"},
            "llama_cpp": {"release": "v0.5.0", "build": "b11146", "variant": "cpu"},
            "settings": {
                "ctx_size": 8192,
                "batch_size": 2048,
                "ubatch_size": 512,
                "gpu_layers": 0,
                "decode_tokens": 128,
                "runs": 3,
            },
            "machine_start": {
                "power_plugged": True,
                "power_mode": {"name": "Balanced"},
                "memory": {"available_bytes": 4 * 1024**3},
            },
        },
        "threads": [
            {
                "threads": t,
                "load_seconds": 3.0,
                "peak_working_set_bytes": 2 * 1024**3,
                "peak_private_bytes": 1024**3,
                "by_prompt": {"512": {"summary": summary}, "2048": {"summary": summary}},
            }
            for t in (4, 8)
        ],
    }
    text = markdown(report)
    assert text.count("| 4 |") == 2 and text.count("| 8 |") == 2
    assert "100.0 (90.0-110.0)" in text
    assert "4.00 GiB" in text
