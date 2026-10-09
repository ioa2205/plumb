"""M3.2: count the tokens of every question type's system prompt with the pinned tokenizer.

    uv run python -m eval.feasibility.prompt_tokens

The plan caps a system prompt at about 400 tokens (PROJECT_PLAN §6). This
counts each one with ``llama-tokenize`` from the pinned llama.cpp build and the
pinned model's vocabulary, so the number is the one the model sees. The tool
reads the vocabulary only; its peak working set is recorded with the counts as
the evidence that no weights were loaded and no memory preflight is needed.

It writes the record under ``docs/results/`` and the counts that the prompt
tests check, keyed by the hash of the prompt they were measured on, so a
prompt that changes without being measured again fails its test.
"""

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from agent.questions import SYSTEM
from backend.llama_server import PeakSampler
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.download import is_verified
from backend.setup.models import model_path
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from eval.feasibility.common import write

LIMIT = 400
COUNTS = (
    Path(__file__).resolve().parents[2] / "agent" / "tests" / "snapshots" / "system_tokens.json"
)
TOKENIZE_ARGS = ("--ids", "--no-bos", "--no-parse-special", "--log-disable")
TIMEOUT_SECONDS = 60


def count_tokens(tokenizer: Path, model: Path, text: str) -> tuple[int, int]:
    """Tokens of ``text`` alone (no BOS, no chat template), and the tool's peak working set."""
    with tempfile.TemporaryDirectory() as folder:
        prompt, output = Path(folder) / "prompt.txt", Path(folder) / "ids.txt"
        prompt.write_bytes(text.encode())
        argv = [str(tokenizer), "-m", str(model), "-f", str(prompt), *TOKENIZE_ARGS]
        with output.open("wb") as out:
            process = subprocess.Popen(  # noqa: S603 - fixed argv to a pinned, verified binary
                argv, stdout=out, stderr=subprocess.DEVNULL
            )
            sampler = PeakSampler(psutil.Process(process.pid))
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while process.poll() is None:
                sampler.sample()
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait()
                    raise RuntimeError(f"llama-tokenize did not finish in {TIMEOUT_SECONDS} s")
                time.sleep(0.005)
        printed = output.read_text(encoding="utf-8", errors="replace").strip()
    if process.returncode != 0 or not printed:
        raise RuntimeError(f"llama-tokenize exited with {process.returncode}")
    ids = ast.literal_eval(printed.splitlines()[-1])
    if not isinstance(ids, list) or not all(isinstance(token, int) for token in ids):
        raise RuntimeError(f"llama-tokenize printed no token list: {printed[-300:]}")
    return len(ids), sampler.peak_working_set


def summary(report: dict[str, Any]) -> str:
    m = report["manifest"]
    rows = [
        f"| `{kind}` | {entry['tokens']} | {entry['characters']} | `{entry['sha256'][:12]}` |"
        for kind, entry in report["system_prompts"].items()
    ]
    largest = max(entry["tokens"] for entry in report["system_prompts"].values())
    return "\n".join(
        [
            "# M3.2 system prompt sizes",
            "",
            f"Tokenizer: `llama-tokenize` from llama.cpp {m['llama_cpp']['release']} "
            f"({m['llama_cpp']['build']}, {m['llama_cpp']['variant']}) with the vocabulary of "
            f"{m['model']['family']} {m['model']['quantization']} (file hash verified against "
            f"the pin). The tool reads the vocabulary only: its peak working set was "
            f"{m['peak_working_set_bytes'] / 2**20:.0f} MiB against a model file of "
            f"{m['model']['size_bytes'] / 2**20:.0f} MiB, so no weights were loaded. Counts are of "
            "the system prompt text alone, without BOS and without the chat template's own "
            "tokens. Manifest and counts: [{json_name}]({json_name}).",
            "",
            f"**Limit {report['limit']} tokens; largest prompt {largest}. "
            f"{'All within the limit.' if report['passed'] else 'Over the limit.'}**",
            "",
            "| Question type | Tokens | Characters | Prompt SHA256 |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3.5-2b-q4_k_m")
    parser.add_argument("--variant", default="cpu")
    args = parser.parse_args(argv)
    settings, llama = Settings(), load_llama_cpp_pin()
    model = load_model_pins().get(args.model)
    path = model_path(settings, model)
    if not is_verified(path, sha256=model.sha256, size=model.size):
        print(f"{path} is absent or does not match its pin")
        return 2
    tokenizer = llama_cpp.binary(settings, llama, args.variant, "llama-tokenize")
    prompts: dict[str, dict[str, Any]] = {}
    peak = 0
    for kind, text in SYSTEM.items():
        tokens, working_set = count_tokens(tokenizer, path, text)
        peak = max(peak, working_set)
        prompts[kind.value] = {
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "tokens": tokens,
            "characters": len(text),
        }
    shown_argv = ["llama-tokenize", "-m", model.file, "-f", "<prompt>", *TOKENIZE_ARGS]
    report = {
        "manifest": {
            "measured": datetime.now(UTC).isoformat(),
            "llama_cpp": {"release": llama.release, "build": llama.build, "variant": args.variant},
            "model": {
                "id": model.id,
                "family": model.family,
                "file": model.file,
                "sha256_verified": model.sha256,
                "size_bytes": model.size,
                "quantization": model.quantization,
            },
            "peak_working_set_bytes": peak,
            "tokenizer_argv": shown_argv,
        },
        "limit": LIMIT,
        "system_prompts": prompts,
        "passed": all(entry["tokens"] < LIMIT for entry in prompts.values()),
    }
    COUNTS.parent.mkdir(parents=True, exist_ok=True)
    COUNTS.write_text(
        json.dumps(
            {
                "tokenizer": {
                    "llama_cpp_build": llama.build,
                    "model": model.id,
                    "model_sha256": model.sha256,
                },
                "limit": LIMIT,
                "system_prompts": {
                    kind: {"sha256": entry["sha256"], "tokens": entry["tokens"]}
                    for kind, entry in prompts.items()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    record = write("m3.2-prompt-tokens", report, summary(report))
    for kind, entry in prompts.items():
        print(f"{kind:24} {entry['tokens']:4} tokens")
    print(f"wrote {record} and {COUNTS}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
