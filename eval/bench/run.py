"""Benchmark one model on one llama.cpp build (HARDWARE.md benchmark protocol).

    uv run python -m eval.bench.run --model qwen3.5-2b-q4_k_m --variant cpu

For each thread count the server is started fresh (the first start of the
session is the "first load"; later starts are warm loads). Each prompt size
gets one discarded warm-up request and then ``--runs`` measured requests.
Prefill and decode speeds come from llama-server's own per-request timings;
"seconds per question" is the client-side wall time of one request with the
question-sized prompt. Requests are stateless (no prompt cache).

Writes ``docs/results/<date>-bench-<model>-<variant>.json`` (manifest and raw
measurements) and a Markdown summary next to it.
"""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.llama_server import LlamaServer, ServerConfig
from backend.memory import read_memory
from backend.preflight import MARGIN_BYTES, check
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.download import sha256_file
from backend.setup.models import model_path
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from eval.bench.machine import machine_state

RESULTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "results"


_CODE = """\
@router.get("/orders/{{order_id}}/items/{n}")
def get_item_{n}(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="not found")
    item = db.scalars(select(Item).where(Item.order_id == order.id).limit({n})).first()
    return {{"order": order.id, "item": item.name if item else None, "count": {n}}}

"""


def synthetic_code(min_chars: int) -> str:
    """Deterministic, realistic Python route code, at least ``min_chars`` long."""
    parts, n = [], 1
    while sum(len(p) for p in parts) < min_chars:
        parts.append(_CODE.format(n=n))
        n += 1
    return "".join(parts)


def prompt_tokens(server: LlamaServer, count: int) -> list[int]:
    tokens = server.tokenize(synthetic_code(count * 6))
    if len(tokens) < count:
        raise RuntimeError(f"synthetic prompt produced only {len(tokens)} tokens")
    return tokens[:count]


def measure(server: LlamaServer, tokens: list[int], decode: int) -> dict[str, Any]:
    started = time.perf_counter()
    commit_before = read_memory().commit_used_bytes
    body = {
        "prompt": tokens,
        "n_predict": decode,
        "ignore_eos": True,
        "cache_prompt": False,
        "temperature": 0.0,
        "seed": 42,
    }
    result = server.post("/completion", body)
    wall = time.perf_counter() - started
    timings = result.get("timings")
    if not isinstance(timings, dict):
        raise RuntimeError("llama-server returned no timings")
    return {
        "prompt_n": timings["prompt_n"],
        "prefill_tokens_per_s": timings["prompt_per_second"],
        "predicted_n": timings["predicted_n"],
        "decode_tokens_per_s": timings["predicted_per_second"],
        "wall_seconds": wall,
        "commit_used_bytes": max(commit_before, read_memory().commit_used_bytes),
    }


def spread(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "prefill_tokens_per_s": spread([r["prefill_tokens_per_s"] for r in runs]),
        "decode_tokens_per_s": spread([r["decode_tokens_per_s"] for r in runs]),
        "wall_seconds": spread([r["wall_seconds"] for r in runs]),
    }


def bench_threads(
    config: ServerConfig, log: Path, prompts: list[int], decode: int, runs: int
) -> dict[str, Any]:
    with LlamaServer(config, log) as server:
        memory_before = server.memory_before
        entry: dict[str, Any] = {
            "threads": config.threads,
            "load_seconds": server.load_seconds,
            "available_bytes_before_load": memory_before.available_bytes if memory_before else None,
            "by_prompt": {},
        }
        for size in prompts:
            tokens = prompt_tokens(server, size)
            warmup = measure(server, tokens, decode)
            measured = [measure(server, tokens, decode) for _ in range(runs)]
            entry["by_prompt"][str(size)] = {
                "warmup_discarded": warmup,
                "runs": measured,
                "summary": summarize(measured),
            }
        sampler = server.sampler
        if sampler is not None:
            sampler.sample()
        entry["peak_working_set_bytes"] = sampler.peak_working_set if sampler else None
        entry["peak_private_bytes"] = sampler.peak_private if sampler else None
        entry["peak_commit_used_bytes"] = max(
            r["commit_used_bytes"]
            for p in entry["by_prompt"].values()
            for r in [p["warmup_discarded"], *p["runs"]]
        )
    return entry


def sustained(
    config: ServerConfig, log: Path, tokens_n: int, decode: int, minutes: float
) -> dict[str, Any]:
    """Repeat question-sized requests for ``minutes`` and record throughput and temperatures."""
    samples = []
    with LlamaServer(config, log) as server:
        tokens = prompt_tokens(server, tokens_n)
        end = time.monotonic() + minutes * 60
        while time.monotonic() < end:
            m = measure(server, tokens, decode)
            state = machine_state()
            samples.append(
                {
                    "time": state["time"],
                    "prefill_tokens_per_s": m["prefill_tokens_per_s"],
                    "decode_tokens_per_s": m["decode_tokens_per_s"],
                    "gpu_celsius": state["gpu"].get("temperature.gpu"),
                    "thermal_zones": state.get("thermal_zones"),
                    "cpu": state.get("cpu"),
                }
            )
    return {"minutes": minutes, "prompt_tokens": tokens_n, "samples": samples}


def _fmt_spread(s: dict[str, float], digits: int = 1) -> str:
    return f"{s['median']:.{digits}f} ({s['min']:.{digits}f}-{s['max']:.{digits}f})"


def markdown(report: dict[str, Any]) -> str:
    m = report["manifest"]
    lines = [
        f"# Benchmark: {m['model']['family']} {m['model']['quantization']} on llama.cpp "
        f"{m['llama_cpp']['release']} ({m['llama_cpp']['build']}, {m['llama_cpp']['variant']})",
        "",
        f"Run {m['started']} → {m['finished']}. Raw data and the full manifest: "
        f"[{report['json_name']}]({report['json_name']}).",
        "",
        "| Setting | Value |",
        "| --- | --- |",
        f"| Model file SHA256 | `{m['model']['sha256_verified']}` |",
        f"| Context / batch / ubatch | {m['settings']['ctx_size']} / "
        f"{m['settings']['batch_size']} / {m['settings']['ubatch_size']} |",
        f"| GPU layers | {m['settings']['gpu_layers']} |",
        f"| Decode tokens per request | {m['settings']['decode_tokens']} (EOS ignored) |",
        f"| Runs | 1 discarded warm-up + {m['settings']['runs']} measured |",
        f"| Power | plugged in: {m['machine_start']['power_plugged']}; "
        f"mode: {m['machine_start']['power_mode'].get('name')} |",
        f"| Available RAM at start | "
        f"{m['machine_start']['memory']['available_bytes'] / 1024**3:.2f} GiB |",
        "",
        "| Threads | Load (s) | Prompt tokens | Prefill tok/s | Decode tok/s | Seconds/request "
        "| Peak working set | Peak private |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for t in report["threads"]:
        for size, p in t["by_prompt"].items():
            s = p["summary"]
            lines.append(
                f"| {t['threads']} | {t['load_seconds']:.1f} | {size} | "
                f"{_fmt_spread(s['prefill_tokens_per_s'])} | "
                f"{_fmt_spread(s['decode_tokens_per_s'])} | "
                f"{_fmt_spread(s['wall_seconds'], 2)} | "
                f"{t['peak_working_set_bytes'] / 1024**3:.2f} GiB | "
                f"{t['peak_private_bytes'] / 1024**3:.2f} GiB |"
            )
    lines += [
        "",
        "Values are median (min-max). Load time is from process start until `/health` is ready; "
        "the first row's load is the first load in this session, later rows are warm loads. "
        "Whether the model file was already in the Windows file cache at the first load is "
        "not known.",
        "",
    ]
    if report.get("sustained"):
        samples = report["sustained"]["samples"]
        decode = [s["decode_tokens_per_s"] for s in samples]
        lines += [
            f"Sustained run: {report['sustained']['minutes']} minutes, {len(samples)} requests; "
            f"decode tok/s first {decode[0]:.1f}, last {decode[-1]:.1f}, "
            f"min {min(decode):.1f}. GPU temperatures and ACPI zones are in the JSON.",
            "",
        ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3.5-2b-q4_k_m")
    parser.add_argument("--variant", default="cpu")
    parser.add_argument("--threads", type=int, nargs="+", default=[4, 8])
    parser.add_argument("--prompt-tokens", type=int, nargs="+", default=[512, 2048])
    parser.add_argument("--decode-tokens", type=int, default=128)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--ctx-size", type=int, default=8192)
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--sustained-minutes", type=float, default=0)
    parser.add_argument("--margin-bytes", type=int, default=MARGIN_BYTES)
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    settings, pins, llama = Settings(), load_model_pins(), load_llama_cpp_pin()
    model = pins.get(args.model)
    gguf = model_path(settings, model)
    if not gguf.is_file():
        parser.error(f"{gguf} is missing; install it with backend.setup.models")
    pre = check(model, args.ctx_size, args.margin_bytes, alternatives=pins.models)
    print(pre.message, flush=True)
    if not pre.ok:
        return 2

    started = datetime.now(UTC)
    stamp = started.strftime("%Y-%m-%d-%H%M")
    name = f"{stamp}-bench-{model.id}-{args.variant}"
    logs = settings.cache_dir / "bench-logs" / name
    machine_start = machine_state()
    binary = llama_cpp.binary(settings, llama, args.variant)
    report: dict[str, Any] = {"threads": []}
    for threads in args.threads:
        print(f"threads={threads}", flush=True)
        config = ServerConfig(
            binary=binary,
            model=gguf,
            ctx_size=args.ctx_size,
            threads=threads,
            gpu_layers=args.gpu_layers,
        )
        report["threads"].append(
            bench_threads(
                config, logs / f"t{threads}.log", args.prompt_tokens, args.decode_tokens, args.runs
            )
        )
    if args.sustained_minutes > 0:
        question = str(max(args.prompt_tokens))
        best = min(
            report["threads"],
            key=lambda t: t["by_prompt"][question]["summary"]["wall_seconds"]["median"],
        )
        config = ServerConfig(
            binary=binary, model=gguf, ctx_size=args.ctx_size, threads=best["threads"]
        )
        print(f"sustained {args.sustained_minutes} min at threads={best['threads']}", flush=True)
        report["sustained"] = sustained(
            config,
            logs / "sustained.log",
            max(args.prompt_tokens),
            args.decode_tokens,
            args.sustained_minutes,
        )
    # Hash after the load measurements so reading the file does not warm the cache first.
    verified = sha256_file(gguf)
    if verified != model.sha256:
        raise RuntimeError(f"{gguf} hash {verified} does not match the pin")
    report["manifest"] = {
        "started": started.isoformat(),
        "finished": datetime.now(UTC).isoformat(),
        "llama_cpp": {
            "release": llama.release,
            "build": llama.build,
            "commit": llama.commit,
            "variant": args.variant,
        },
        "model": {
            "id": model.id,
            "family": model.family,
            "repo": model.repo,
            "revision": model.revision,
            "file": model.file,
            "quantization": model.quantization,
            "sha256_verified": verified,
        },
        "settings": {
            "ctx_size": args.ctx_size,
            "batch_size": ServerConfig.batch_size,
            "ubatch_size": ServerConfig.ubatch_size,
            "gpu_layers": args.gpu_layers,
            "threads": args.threads,
            "prompt_tokens": args.prompt_tokens,
            "decode_tokens": args.decode_tokens,
            "runs": args.runs,
            "server_argv": ServerConfig(binary=binary, model=gguf).argv(0, "<per-launch key>"),
        },
        "preflight": {"margin_bytes": args.margin_bytes, "message": pre.message},
        "machine_start": machine_start,
        "machine_end": machine_state(),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / f"{name}.json"
    report["json_name"] = json_path.name
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    (args.out / f"{name}.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
