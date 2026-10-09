"""Match predicted findings to ground truth and compute the §11 metrics.

Rules (fixed before any model is scored):

- Only ``supported`` predictions are positive reports. ``candidate`` and
  ``inconclusive`` are abstentions; ``rejected`` is a negative.
- A prediction matches a truth when the family (root cause) is the same, the
  path is the same, and the line ranges overlap after widening the truth by
  ``LINE_TOLERANCE`` lines on each side.
- Each vulnerable truth is credited once. Further supported predictions that
  match an already-credited truth, and supported predictions that match no
  vulnerable truth, are false positives (conservative: duplicate reports are
  a real cost to the reader).
- Recall counts abstentions as misses. A defended control (a ``safe`` truth)
  is a false alarm when any supported prediction matches it.
- A pair (one vulnerable and one safe truth sharing ``pair_id``) is
  discriminated when the vulnerable one is detected and the safe one is not
  falsely alarmed.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.contracts.common import Family
from backend.contracts.investigation import Conclusion
from eval.scoring.stats import (
    BootstrapResult,
    Proportion,
    cluster_bootstrap,
    proportion,
    ratio_of,
)

LINE_TOLERANCE = 3

Label = Literal["vulnerable", "safe"]


class Truth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    family: Family
    label: Label
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    template_family: str  # the bootstrap cluster
    pair_id: str | None = None


class Prediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: Family
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    conclusion: Conclusion


def overlaps(p: Prediction, t: Truth, tolerance: int = LINE_TOLERANCE) -> bool:
    return (
        p.family == t.family
        and p.path == t.path
        and p.start_line <= t.end_line + tolerance
        and p.end_line >= t.start_line - tolerance
    )


@dataclass(frozen=True)
class TruthOutcome:
    truth: Truth
    outcome: Literal["detected", "abstained", "missed", "false_alarm", "cleared"]


@dataclass(frozen=True)
class Matching:
    outcomes: list[TruthOutcome]
    true_positives: list[tuple[Prediction, Truth]]
    false_positives: list[Prediction]


def match(truths: list[Truth], predictions: list[Prediction]) -> Matching:
    vulnerable = [t for t in truths if t.label == "vulnerable"]
    safe = [t for t in truths if t.label == "safe"]
    supported = [p for p in predictions if p.conclusion is Conclusion.SUPPORTED]
    abstaining = [
        p for p in predictions if p.conclusion in (Conclusion.CANDIDATE, Conclusion.INCONCLUSIVE)
    ]

    credited: dict[str, Prediction] = {}
    false_positives: list[Prediction] = []
    true_positives: list[tuple[Prediction, Truth]] = []
    for p in sorted(supported, key=lambda p: (p.path, p.start_line, p.end_line, p.family)):
        target = next((t for t in vulnerable if t.id not in credited and overlaps(p, t)), None)
        if target is None:
            false_positives.append(p)
        else:
            credited[target.id] = p
            true_positives.append((p, target))

    outcomes: list[TruthOutcome] = []
    for t in vulnerable:
        if t.id in credited:
            outcomes.append(TruthOutcome(t, "detected"))
        elif any(overlaps(p, t) for p in abstaining):
            outcomes.append(TruthOutcome(t, "abstained"))
        else:
            outcomes.append(TruthOutcome(t, "missed"))
    for t in safe:
        alarmed = any(overlaps(p, t) for p in supported)
        outcomes.append(TruthOutcome(t, "false_alarm" if alarmed else "cleared"))
    return Matching(outcomes, true_positives, false_positives)


def cluster_counts(truths: list[Truth], matching: Matching) -> dict[str, Counter[str]]:
    """Additive counts per template family, the unit of the cluster bootstrap."""
    cluster_of_path = {t.path: t.template_family for t in truths}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for o in matching.outcomes:
        c = counts[o.truth.template_family]
        fam = o.truth.family.value
        if o.truth.label == "vulnerable":
            c["vulnerable"] += 1
            c[f"vulnerable:{fam}"] += 1
            if o.outcome == "detected":
                c["tp"] += 1
                c[f"detected:{fam}"] += 1
            elif o.outcome == "abstained":
                c["abstained"] += 1
        else:
            c["safe"] += 1
            if o.outcome == "false_alarm":
                c["false_alarm"] += 1
    for p in matching.false_positives:
        counts[cluster_of_path.get(p.path, f"path:{p.path}")]["fp"] += 1

    by_id = {o.truth.id: o for o in matching.outcomes}
    pairs: dict[str, list[TruthOutcome]] = defaultdict(list)
    for t in truths:
        if t.pair_id is not None:
            pairs[t.pair_id].append(by_id[t.id])
    for members in pairs.values():
        vuln = [m for m in members if m.truth.label == "vulnerable"]
        fixed = [m for m in members if m.truth.label == "safe"]
        if len(vuln) != 1 or len(fixed) != 1:
            raise ValueError(f"pair {members[0].truth.pair_id} needs one vulnerable and one safe")
        c = counts[vuln[0].truth.template_family]
        c["pairs"] += 1
        if vuln[0].outcome == "detected" and fixed[0].outcome == "cleared":
            c["pairs_discriminated"] += 1
    return dict(counts)


@dataclass(frozen=True)
class Metric:
    point: Proportion
    bootstrap: BootstrapResult


@dataclass(frozen=True)
class Report:
    precision: Metric
    recall: dict[str, Metric]
    defended_false_positive_rate: Metric
    abstention_rate: Metric
    paired_discrimination: Metric
    duplicate_or_unmatched_reports: int


def score(
    truths: list[Truth], predictions: list[Prediction], resamples: int = 2000, seed: int = 0
) -> Report:
    ids = [t.id for t in truths]
    if len(ids) != len(set(ids)):
        raise ValueError("truth ids must be unique")
    matching = match(truths, predictions)
    clusters = cluster_counts(truths, matching)
    total: Counter[str] = Counter()
    for c in clusters.values():
        total.update(c)

    def metric(numerator: str, denominator: str | tuple[str, ...]) -> Metric:
        parts = (denominator,) if isinstance(denominator, str) else denominator
        below = sum(total[p] for p in parts)
        return Metric(
            point=proportion(total[numerator], below),
            bootstrap=cluster_bootstrap(clusters, ratio_of(numerator, parts), resamples, seed),
        )

    families = sorted({t.family.value for t in truths if t.label == "vulnerable"})
    return Report(
        precision=metric("tp", ("tp", "fp")),
        recall={f: metric(f"detected:{f}", f"vulnerable:{f}") for f in families},
        defended_false_positive_rate=metric("false_alarm", "safe"),
        abstention_rate=metric("abstained", "vulnerable"),
        paired_discrimination=metric("pairs_discriminated", "pairs"),
        duplicate_or_unmatched_reports=total["fp"],
    )
