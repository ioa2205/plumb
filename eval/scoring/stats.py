"""Interval estimates: Wilson score intervals and a cluster bootstrap.

Proportions carry Wilson 95% intervals; cluster bootstrap resamples whole
template families so that correlated variants of one handler are not
treated as independent evidence (PROJECT_PLAN §11).
"""

import math
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

Z95 = 1.959963984540054  # two-sided 95% normal quantile


@dataclass(frozen=True)
class Interval:
    low: float
    high: float


@dataclass(frozen=True)
class Proportion:
    successes: int
    trials: int
    wilson: Interval | None

    @property
    def value(self) -> float | None:
        return self.successes / self.trials if self.trials else None


def wilson(successes: int, trials: int, z: float = Z95) -> Interval | None:
    """Wilson score interval; None when there are no trials."""
    if not 0 <= successes <= trials:
        raise ValueError(f"need 0 <= successes <= trials, got {successes}/{trials}")
    if trials == 0:
        return None
    p = successes / trials
    z2 = z * z
    denom = 1 + z2 / trials
    center = (p + z2 / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials)) / denom
    return Interval(max(0.0, center - half), min(1.0, center + half))


def proportion(successes: int, trials: int) -> Proportion:
    return Proportion(successes, trials, wilson(successes, trials))


Ratio = Callable[[Mapping[str, int]], float | None]


@dataclass(frozen=True)
class BootstrapResult:
    interval: Interval | None
    resamples: int
    undefined: int  # resamples whose denominator was zero
    values: tuple[float, ...]


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of already sorted values, q in [0, 1]."""
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def cluster_bootstrap(
    clusters: Mapping[str, Mapping[str, int]],
    ratio: Ratio,
    resamples: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> BootstrapResult:
    """Percentile interval for ``ratio`` over resampled clusters.

    ``clusters`` maps a cluster (template family) to additive counts, for
    example ``{"tp": 3, "fp": 1}``. Each resample draws as many clusters as
    there are, with replacement, sums their counts, and applies ``ratio``.
    """
    names = sorted(clusters)
    if not names:
        return BootstrapResult(None, resamples, resamples, ())
    rng = random.Random(seed)  # noqa: S311 - reproducible statistics, not secrets
    values: list[float] = []
    undefined = 0
    for _ in range(resamples):
        total: Counter[str] = Counter()
        for name in rng.choices(names, k=len(names)):
            total.update(clusters[name])
        value = ratio(total)
        if value is None:
            undefined += 1
        else:
            values.append(value)
    if not values:
        return BootstrapResult(None, resamples, undefined, ())
    values.sort()
    tail = (1 - level) / 2
    interval = Interval(_percentile(values, tail), _percentile(values, 1 - tail))
    return BootstrapResult(interval, resamples, undefined, tuple(values))


def ratio_of(numerator: str, denominator: str | tuple[str, ...]) -> Ratio:
    """A ratio of summed counts; the denominator may be a sum of several counts."""
    parts = (denominator,) if isinstance(denominator, str) else denominator

    def compute(counts: Mapping[str, int]) -> float | None:
        below = sum(counts.get(p, 0) for p in parts)
        return counts.get(numerator, 0) / below if below else None

    return compute
