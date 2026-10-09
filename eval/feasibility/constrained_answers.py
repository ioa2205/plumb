"""M0.6: answer ``guard_summary`` with JSON-schema constrained output on 3 snippets.

    uv run python -m eval.feasibility.constrained_answers

Done when 3 of 3 answers parse and every cited line ID exists. The expected
guard kinds per snippet are recorded too, as a first look at judgment quality;
they are not part of the pass condition.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent import questions
from agent.evidence import Cut, EvidencePacket
from agent.llm import AnswerError, ask_json
from agent.questions import GuardSummary
from backend.contracts.common import Language
from backend.llama_server import LlamaServer
from backend.preflight import MARGIN_BYTES
from eval.feasibility.common import PreflightRefused, finish, start, write

SNIPPET_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "snippets"

# Expected guard kinds, written down before any model run.
SNIPPETS: list[tuple[str, set[str], str]] = [
    ("receipt_authn_only.py", {"authenticated"}, "signed in only; loads any order by ID"),
    ("invoice_owner_check.py", {"authenticated", "owner"}, "checks order.customer_id == user.id"),
    (
        "menu_role_without_branch.py",
        {"authenticated", "role"},
        "role checked; item.branch_id is compared with the path, not the caller's branch",
    ),
]


def run_one(server: LlamaServer, name: str, expected: set[str], note: str) -> dict[str, Any]:
    source = (SNIPPET_DIR / name).read_bytes()
    packet = EvidencePacket.build(Cut.whole("function", name, Language.PYTHON, source))
    prompt = questions.guard_summary(packet)
    entry: dict[str, Any] = {"snippet": name, "expected_kinds": sorted(expected), "note": note}
    try:
        answer = ask_json(server, prompt.system, prompt.user, prompt.schema, name=prompt.type)
        parsed = GuardSummary.model_validate(answer.data)
    except (AnswerError, ValueError) as error:
        entry.update(parsed=False, error=str(error))
        return entry
    cited = parsed.cited()
    kinds = {guard.kind.value for guard in parsed.guards}
    entry.update(
        parsed=True,
        answer=answer.data,
        cited=cited,
        cited_lines={i: packet.location(i)[1] for i in cited if i in packet.line_ids},
        # Comment-only and blank lines have no ID, so only an unknown ID can be invalid.
        invalid_citations=[i for i in cited if i not in packet.line_ids],
        kinds=sorted(kinds),
        kinds_match=kinds == expected,
        prompt_tokens=answer.prompt_tokens,
        completion_tokens=answer.completion_tokens,
        seconds=answer.seconds,
    )
    return entry


def summary(report: dict[str, Any]) -> str:
    m = report["manifest"]
    llama, model, cfg = m["llama_cpp"], m["model"], m["settings"]
    total = len(report["answers"])
    rows = []
    for e in report["answers"]:
        cited = ", ".join(e.get("cited", [])) or "-"
        invalid = ", ".join(e.get("invalid_citations", [])) or "none"
        kinds = ", ".join(e.get("kinds", [])) or "-"
        expected = ", ".join(e["expected_kinds"])
        parsed = "yes" if e["parsed"] else "no"
        rows.append(
            f"| `{e['snippet']}` | {parsed} | {cited} | {invalid} | {kinds} | {expected} | "
            f"{e.get('prompt_tokens', '-')} | {e.get('seconds', 0):.1f} |"
        )
    setup = (
        f"{model['family']} {model['quantization']} on llama.cpp {llama['release']} "
        f"({llama['build']}, {llama['variant']}), {cfg['threads']} threads, "
        f"context {cfg['ctx_size']}, thinking off, temperature 0."
    )
    verdict = (
        f"**Pass condition (parse + cited IDs exist): {report['passed']}/{total}.** "
        f"Guard kinds matching the expectation written before the run: "
        f"{report['kinds_matched']}/{total} (informative, not a pass condition)."
    )
    return "\n".join(
        [
            "# M0.6 constrained answers: guard_summary on 3 snippets",
            "",
            setup + " Raw answers and the manifest: [{json_name}]({json_name}).",
            "",
            verdict,
            "",
            "| Snippet | Parsed | Cited | Invalid citations | Kinds answered | Kinds expected "
            "| Prompt tokens | Seconds |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3.5-2b-q4_k_m")
    parser.add_argument("--variant", default="cpu")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--margin-bytes", type=int, default=MARGIN_BYTES)
    args = parser.parse_args(argv)
    try:
        server, manifest = start(
            model_id=args.model,
            variant=args.variant,
            margin_bytes=args.margin_bytes,
            log_name="m0.6-constrained",
            threads=args.threads,
        )
    except PreflightRefused:
        return 2
    try:
        answers = [run_one(server, *s) for s in SNIPPETS]
    finally:
        finish(server, manifest)
    passed = sum(1 for a in answers if a["parsed"] and not a["invalid_citations"])
    report = {
        "manifest": manifest,
        "answers": answers,
        "passed": passed,
        "kinds_matched": sum(1 for a in answers if a.get("kinds_match")),
    }
    path = write("m0.6-constrained-answers", report, summary(report))
    print(f"{passed}/{len(answers)} passed; wrote {path}")
    return 0 if passed == len(answers) else 1


if __name__ == "__main__":
    sys.exit(main())
