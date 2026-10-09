"""M1.8: the Opengrep-only baseline on a corpus split.

    uv run python -m eval.baselines.opengrep [--split development]

Writes the split's cases to a temporary folder, scans them with the pinned
Opengrep and Plumb's rules in ``analysis/rules``, turns each result into a
``supported`` prediction, and scores it with ``eval.scoring``. Results from
different rules at the same family, file, and line are merged into one
report, as a scanner's UI would show them.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.contracts.common import Family
from backend.contracts.investigation import Conclusion
from backend.settings import Settings
from backend.setup.opengrep import binary
from backend.setup.pins import load_opengrep_pin
from eval.baselines.common import (
    fmt,
    materialize,
    outcomes,
    report_dict,
    tree_sha256,
    truths,
    write,
)
from eval.mutation.corpus import Variant
from eval.scoring.score import Prediction, score
from eval.splits import MANIFEST, Split, load

RULES_DIR = Path(__file__).resolve().parents[2] / "analysis" / "rules"


def scan(exe: Path, target: Path, rules: Path = RULES_DIR) -> dict[str, Any]:
    argv = [
        str(exe), "scan",
        "--config", str(rules),
        "--json",
        "--taint-intrafile",
        "--disable-version-check",
        "--no-git-ignore",
        "--quiet",
        "--jobs", "2",
        str(target),
    ]  # fmt: skip
    done = subprocess.run(  # noqa: S603 - fixed argv to the pinned, hash-verified Opengrep
        argv, capture_output=True, text=True, encoding="utf-8", timeout=600, check=False
    )
    if done.returncode not in (0, 1):  # 1 means findings were reported
        raise RuntimeError(f"opengrep exited {done.returncode}: {done.stderr[-2000:]}")
    return json.loads(done.stdout)


def predictions(results: dict[str, Any], root: Path) -> list[Prediction]:
    seen: set[tuple[str, str, int]] = set()
    out = []
    for r in results.get("results", []):
        family = Family(r["extra"]["metadata"]["family"])
        path = Path(r["path"]).resolve().relative_to(root.resolve()).as_posix()
        start, end = r["start"]["line"], r["end"]["line"]
        key = (family.value, path, start)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Prediction(
                family=family,
                path=path,
                start_line=start,
                end_line=end,
                conclusion=Conclusion.SUPPORTED,
            )
        )
    return out


def summary(data: dict[str, Any]) -> str:
    m, r = data["manifest"], data["metrics"]
    per_operator: Counter[tuple[str, str, str]] = Counter(
        (c["operator"], c["label"], c["outcome"]) for c in data["cases"]
    )
    operators = sorted({c["operator"] for c in data["cases"]})
    rows = []
    for op in operators:
        cases = [c for c in data["cases"] if c["operator"] == op]
        label = cases[0]["label"]
        hits = sum(per_operator[(op, label, o)] for o in ("detected", "false_alarm"))
        what = "detected" if label == "vulnerable" else "falsely flagged"
        rows.append(f"| `{op}` | {label} | {len(cases)} | {hits} {what} |")
    recall = "\n".join(f"| Recall: {fam} | {fmt(v)} |" for fam, v in r["recall"].items())
    return "\n".join(
        [
            f"# Baseline: Opengrep only, {m['split']} split",
            "",
            f"Opengrep {m['opengrep']['release']} (`{m['opengrep']['sha256'][:12]}…`) with "
            f"Plumb's {m['rules']['count']} rules (rules hash `{m['rules']['sha256'][:12]}…`), "
            f"`--taint-intrafile`. {m['cases']} cases from {m['templates']} template families. "
            "Raw results, per-case outcomes, and the manifest: [{json_name}]({json_name}).",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Precision | {fmt(r['precision'])} |",
            recall,
            f"| Defended-control false-positive rate | {fmt(r['defended_false_positive_rate'])} |",
            f"| Abstention rate | {fmt(r['abstention_rate'])} |",
            f"| Paired discrimination | {fmt(r['paired_discrimination'])} |",
            f"| Duplicate or unmatched reports | {r['duplicate_or_unmatched_reports']} |",
            "",
            "| Operator | Label | Cases | Result |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
            "Intervals are 95%: Wilson for the proportion, cluster bootstrap over template "
            "families. With this few template families the intervals are wide; see task M1.6a. "
            "Paired discrimination is not defined for the mutation corpus yet (no fixed pairs).",
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="development", choices=["development", "validation"])
    args = parser.parse_args(argv)
    split: Split = args.split
    settings, pin = Settings(), load_opengrep_pin()
    exe = binary(settings, pin)
    variants: list[Variant] = load(split)
    rule_files = sorted(RULES_DIR.glob("*.yaml"))

    with tempfile.TemporaryDirectory(prefix="plumb-opengrep-") as tmp:
        root = Path(tmp)
        materialize(variants, root)
        started = datetime.now(UTC)
        raw = scan(exe, root)
        finished = datetime.now(UTC)
        preds = predictions(raw, root)

    report = score(truths(variants), preds)
    manifest_hash = json.loads(MANIFEST.read_text(encoding="utf-8"))["sealed_test_sha256"]
    rule_ids = _rule_ids(rule_files)
    data = {
        "manifest": {
            "started": started.isoformat(),
            "finished": finished.isoformat(),
            "split": split,
            "cases": len(variants),
            "templates": len({v.template for v in variants}),
            "split_manifest_sealed_test_sha256": manifest_hash,
            "opengrep": {
                "release": pin.release,
                "commit": pin.commit,
                "sha256": pin.asset.sha256,
                "version_reported": raw.get("version"),
            },
            "rules": {
                "files": [p.name for p in rule_files],
                "ids": rule_ids,
                "count": len(rule_ids),
                "sha256": tree_sha256(rule_files, RULES_DIR),
            },
            "raw_result_count": len(raw.get("results", [])),
            "errors": raw.get("errors", []),
        },
        "metrics": report_dict(report),
        "predictions": [p.model_dump(mode="json") for p in preds],
        "cases": outcomes(variants, preds),
    }
    path = write(f"baseline-opengrep-{split}", data, summary(data))
    print(f"wrote {path}")
    return 0


def _rule_ids(files: list[Path]) -> list[str]:
    ids = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("- id: "):
                ids.append(stripped.removeprefix("- id: "))
    return ids


if __name__ == "__main__":
    sys.exit(main())
