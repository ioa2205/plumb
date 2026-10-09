"""M0.8: canary isolation test for the pinned llama.cpp build (PROJECT_PLAN §8, §9).

    uv run python -m eval.feasibility.canary --margin-bytes N [--pairs 10] [--diagnostic]

Each pair sends request A containing a fresh secret token, then request B
asking for "the secret you were given earlier". The test fails if B's output
contains the token. The production configuration is stateless; ``--diagnostic``
repeats the pairs with llama.cpp's prompt caches switched back on, to see
whether the risk the plan guards against exists in this build at all.
"""

import argparse
import secrets
import sys
from collections.abc import Sequence
from typing import Any

from backend.llama_server import LlamaServer
from backend.preflight import MARGIN_BYTES
from eval.feasibility.common import PreflightRefused, finish, start, write

SYSTEM = "You are a helpful assistant in a software test."
ASK_B = (
    "Repeat the secret code you were given earlier in this conversation, exactly. "
    "If you were not given one, reply with the single word NONE."
)


def chat(server: LlamaServer, user: str, cache_prompt: bool) -> str:
    result = server.post(
        "/v1/chat/completions",
        {
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 48,
            "temperature": 0.0,
            "cache_prompt": cache_prompt,
        },
    )
    return str(result["choices"][0]["message"]["content"])


def run_pairs(server: LlamaServer, pairs: int, cache_prompt: bool) -> list[dict[str, Any]]:
    results = []
    for _ in range(pairs):
        secret = secrets.token_hex(8)
        token = f"CANARY-{secret}"
        a = chat(
            server, f"Remember this secret code and repeat it back once: {token}", cache_prompt
        )
        b = chat(server, ASK_B, cache_prompt)
        results.append(
            {
                "token": token,
                "a_output": a,
                "a_contains_token": secret in a,
                "b_output": b,
                "leaked": secret in b or secret[:8] in b or secret[8:] in b,
            }
        )
    return results


def summary(report: dict[str, Any]) -> str:
    m = report["manifest"]
    llama, model = m["llama_cpp"], m["model"]
    setup = (
        f"{model['family']} {model['quantization']} on llama.cpp {llama['release']} "
        f"({llama['build']}, {llama['variant']})."
    )
    lines = [
        "# M0.8 canary isolation test",
        "",
        setup + " Raw outputs and the manifest: [{json_name}]({json_name}).",
        "",
        "| Configuration | Pairs | Request A echoed its token | Request B leaked a token "
        "| Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, rows in report["configurations"].items():
        leaked = sum(r["leaked"] for r in rows)
        echoed = sum(r["a_contains_token"] for r in rows)
        result = "PASS" if leaked == 0 else "FAIL"
        lines.append(f"| {name} | {len(rows)} | {echoed} | {leaked} | {result} |")
    lines += [
        "",
        "Request A echoing its token shows the secret was really processed and generated. "
        "A leak counts the full 16-hex secret or either 8-hex half appearing in request B's "
        "output.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3.5-2b-q4_k_m")
    parser.add_argument("--variant", default="cpu")
    parser.add_argument("--pairs", type=int, default=10)
    parser.add_argument("--margin-bytes", type=int, default=MARGIN_BYTES)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"configurations": {}}
    modes = [("stateless (production)", True)]
    if args.diagnostic:
        modes.append(("prompt caches on (diagnostic)", False))
    for label, stateless in modes:
        try:
            server, manifest = start(
                model_id=args.model,
                variant=args.variant,
                margin_bytes=args.margin_bytes,
                log_name=f"m0.8-canary-{'stateless' if stateless else 'cached'}",
                stateless=stateless,
            )
        except PreflightRefused:
            return 2
        try:
            report["configurations"][label] = run_pairs(server, args.pairs, not stateless)
        finally:
            finish(server, manifest)
        report.setdefault("manifest", manifest)
        report.setdefault("manifests", {})[label] = manifest
    production = report["configurations"]["stateless (production)"]
    report["passed"] = not any(r["leaked"] for r in production)
    path = write("m0.8-canary", report, summary(report))
    print(f"production configuration {'PASS' if report['passed'] else 'FAIL'}; wrote {path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
