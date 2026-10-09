"""Shared pieces for baselines: materializing a split, building truths, writing reports."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.mutation.corpus import Variant
from eval.scoring.score import Metric, Prediction, Report, Truth, match

RESULTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "results"


def case_path(v: Variant) -> str:
    """Where a variant is written for a baseline: an opaque, label-free name.

    Template and operator names must never appear in what a baseline sees; a file
    called ``drop_owner_check.py`` would give the label away.
    """
    return f"case-{v.sha256[:16]}.py"


def materialize(variants: list[Variant], root: Path) -> None:
    for v in variants:
        path = root / case_path(v)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(v.source, encoding="utf-8", newline="\n")


def truths(variants: list[Variant]) -> list[Truth]:
    return [
        Truth(
            id=v.id,
            family=v.family,
            label=v.label,
            path=case_path(v),
            start_line=v.handler_lines[0],
            end_line=v.handler_lines[1],
            template_family=v.template,
        )
        for v in variants
    ]


def tree_sha256(paths: list[Path], root: Path) -> str:
    """Hash of files by relative path and content, for the run manifest."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return digest.hexdigest()


def _metric(m: Metric) -> dict[str, Any]:
    point = m.point
    boot = m.bootstrap
    return {
        "successes": point.successes,
        "trials": point.trials,
        "value": point.value,
        "wilson95": asdict(point.wilson) if point.wilson else None,
        "cluster_bootstrap95": asdict(boot.interval) if boot.interval else None,
        "bootstrap_resamples": boot.resamples,
        "bootstrap_undefined": boot.undefined,
    }


def report_dict(report: Report) -> dict[str, Any]:
    return {
        "precision": _metric(report.precision),
        "recall": {family: _metric(m) for family, m in report.recall.items()},
        "defended_false_positive_rate": _metric(report.defended_false_positive_rate),
        "abstention_rate": _metric(report.abstention_rate),
        "paired_discrimination": _metric(report.paired_discrimination),
        "duplicate_or_unmatched_reports": report.duplicate_or_unmatched_reports,
    }


def outcomes(variants: list[Variant], predictions: list[Prediction]) -> list[dict[str, Any]]:
    """One row per case: label, operator, and what happened to it."""
    matching = match(truths(variants), predictions)
    by_id = {o.truth.id: o.outcome for o in matching.outcomes}
    flagged = {p.path for p in predictions if p.conclusion.value == "supported"}
    return [
        {
            "id": v.id,
            "template": v.template,
            "operator": v.operator,
            "family": v.family.value,
            "label": v.label,
            "outcome": by_id[v.id],
            "flagged_anywhere": case_path(v) in flagged,
        }
        for v in variants
    ]


def fmt(m: dict[str, Any]) -> str:
    if m["value"] is None:
        return "n/a (no cases)"
    w, b = m["wilson95"], m["cluster_bootstrap95"]
    boot = f"; bootstrap {b['low']:.2f}-{b['high']:.2f}" if b else ""
    return (
        f"{m['successes']}/{m['trials']} = {m['value']:.2f} "
        f"(Wilson {w['low']:.2f}-{w['high']:.2f}{boot})"
    )


def write(name: str, data: dict[str, Any], markdown: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    json_path = RESULTS_DIR / f"{stamp}-{name}.json"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    (RESULTS_DIR / f"{stamp}-{name}.md").write_text(
        markdown.replace("{json_name}", json_path.name), encoding="utf-8", newline="\n"
    )
    return json_path
