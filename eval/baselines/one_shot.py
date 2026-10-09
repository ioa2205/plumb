"""M1.9: the one-shot model baseline: "review this file" on the same cases as Opengrep.

    uv run python -m eval.baselines.one_shot [--split development]

The model sees one whole file with line numbers, nothing else (no file name,
no label), and answers in a JSON schema so its claims can be scored like any
other prediction. This is the baseline Plumb's small typed questions must beat
(ADR-0004).
"""

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from agent.llm import AnswerError, ask_json
from backend.contracts.common import Family
from backend.contracts.investigation import Conclusion
from backend.preflight import MARGIN_BYTES
from eval.baselines.common import case_path, fmt, outcomes, report_dict, truths, write
from eval.feasibility.common import PreflightRefused, finish, start
from eval.mutation.corpus import Variant
from eval.scoring.score import Prediction, score
from eval.splits import Split, load

SYSTEM = """\
You are a security reviewer. Review the Python file for security vulnerabilities in four
categories:
- authorization: a user can read or change data that belongs to someone else;
- injection: SQL injection or OS command injection;
- path_traversal: a request value reaches a file path without containment;
- nextjs_exposure: a Next.js endpoint or Server Action without authorization, or private
  fields sent to the browser.
Report only vulnerabilities you can point to in the code, with the line range of the
vulnerable code. If there are none, return an empty list. Answer in JSON.
"""


def numbered(source: str) -> str:
    return "\n".join(f"{i:>3} | {line}" for i, line in enumerate(source.splitlines(), start=1))


def schema(line_count: int) -> dict[str, Any]:
    line = {"type": "integer", "minimum": 1, "maximum": line_count}
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "family": {"type": "string", "enum": [f.value for f in Family]},
                        "start_line": line,
                        "end_line": line,
                        "explanation": {"type": "string", "maxLength": 300},
                    },
                    "required": ["family", "start_line", "end_line", "explanation"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


def to_predictions(v: Variant, answer: dict[str, Any]) -> list[Prediction]:
    preds = []
    for f in answer.get("findings", []):
        start, end = sorted((int(f["start_line"]), int(f["end_line"])))
        preds.append(
            Prediction(
                family=Family(f["family"]),
                path=case_path(v),
                start_line=start,
                end_line=end,
                conclusion=Conclusion.SUPPORTED,
            )
        )
    return preds


def summary(data: dict[str, Any]) -> str:
    m, r = data["manifest"], data["metrics"]
    recall = "\n".join(f"| Recall: {fam} | {fmt(v)} |" for fam, v in r["recall"].items())
    rows = []
    for op in sorted({c["operator"] for c in data["cases"]}):
        cases = [c for c in data["cases"] if c["operator"] == op]
        label = cases[0]["label"]
        hits = sum(c["outcome"] in ("detected", "false_alarm") for c in cases)
        any_flag = sum(c["flagged_anywhere"] for c in cases)
        what = "detected" if label == "vulnerable" else "falsely flagged"
        rows.append(f"| `{op}` | {label} | {len(cases)} | {hits} {what} | {any_flag} |")
    seconds = [a["seconds"] for a in data["answers"] if "seconds" in a]
    tokens = [a["prompt_tokens"] for a in data["answers"] if "prompt_tokens" in a]
    return "\n".join(
        [
            f"# Baseline: one-shot model review, {m['split']} split",
            "",
            f"{m['model']['family']} {m['model']['quantization']} on llama.cpp "
            f"{m['llama_cpp']['release']} ({m['llama_cpp']['build']}, "
            f"{m['llama_cpp']['variant']}), "
            "thinking off, temperature 0, JSON-schema constrained answer. "
            f"{m['cases']} cases. Raw answers and the manifest: [{{json_name}}]({{json_name}}).",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Precision | {fmt(r['precision'])} |",
            recall,
            f"| Defended-control false-positive rate | {fmt(r['defended_false_positive_rate'])} |",
            f"| Duplicate or unmatched reports | {r['duplicate_or_unmatched_reports']} |",
            f"| Unparseable answers | {data['unparseable']} |",
            f"| Seconds per case | median {sorted(seconds)[len(seconds) // 2]:.1f}, "
            f"total {sum(seconds):.0f} |"
            if seconds
            else "| Seconds per case | n/a |",
            f"| Prompt tokens per case | median {sorted(tokens)[len(tokens) // 2]} |"
            if tokens
            else "| Prompt tokens per case | n/a |",
            "",
            "| Operator | Label | Cases | Result at the right place | Cases with any finding |",
            "| --- | --- | --- | --- | --- |",
            *rows,
            "",
            "Intervals are 95%: Wilson for the proportion, cluster bootstrap over template "
            "families (see task M1.6a on the small corpus).",
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="development", choices=["development", "validation"])
    parser.add_argument("--model", default="qwen3.5-2b-q4_k_m")
    parser.add_argument("--variant", default="cpu")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--margin-bytes", type=int, default=MARGIN_BYTES)
    args = parser.parse_args(argv)
    split: Split = args.split
    variants = load(split)
    try:
        server, manifest = start(
            model_id=args.model,
            variant=args.variant,
            margin_bytes=args.margin_bytes,
            log_name=f"m1.9-one-shot-{split}",
            threads=args.threads,
        )
    except PreflightRefused:
        return 2
    answers: list[dict[str, Any]] = []
    preds: list[Prediction] = []
    try:
        for v in variants:
            source = numbered(v.source)
            entry: dict[str, Any] = {"id": v.id, "path": case_path(v)}
            try:
                answer = ask_json(
                    server,
                    SYSTEM,
                    f"Review this file.\n\n<file>\n{source}\n</file>",
                    schema(len(v.source.splitlines())),
                    name="review",
                    max_tokens=600,
                )
            except AnswerError as error:
                entry["error"] = str(error)
            else:
                entry.update(
                    answer=answer.data,
                    prompt_tokens=answer.prompt_tokens,
                    completion_tokens=answer.completion_tokens,
                    seconds=answer.seconds,
                )
                preds += to_predictions(v, answer.data)
            answers.append(entry)
            print(
                f"{v.id}: {len(entry.get('answer', {}).get('findings', []))} findings", flush=True
            )
    finally:
        finish(server, manifest)
    report = score(truths(variants), preds)
    manifest.update(split=split, cases=len(variants))
    data = {
        "manifest": manifest,
        "metrics": report_dict(report),
        "unparseable": sum(1 for a in answers if "error" in a),
        "answers": answers,
        "predictions": [p.model_dump(mode="json") for p in preds],
        "cases": outcomes(variants, preds),
    }
    path = write(f"baseline-one-shot-{split}", data, summary(data))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
