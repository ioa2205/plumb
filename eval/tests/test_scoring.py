import pytest

from backend.contracts.common import Family
from backend.contracts.investigation import Conclusion
from eval.scoring.score import Label, Prediction, Truth, cluster_counts, match, score
from eval.scoring.stats import cluster_bootstrap, ratio_of, wilson

AUTH, INJ, PATH = Family.AUTHORIZATION, Family.INJECTION, Family.PATH_TRAVERSAL
S, INC, REJ = Conclusion.SUPPORTED, Conclusion.INCONCLUSIVE, Conclusion.REJECTED


# --- Wilson intervals: reference values ------------------------------------------------------


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (8, 10, 0.49016, 0.94331),
        (0, 10, 0.0, 0.27753),
        (10, 10, 0.72247, 1.0),
        (1, 2, 0.09453, 0.90547),
    ],
)
def test_wilson_matches_reference_values(k: int, n: int, low: float, high: float) -> None:
    interval = wilson(k, n)
    assert interval is not None
    assert interval.low == pytest.approx(low, abs=1e-4)
    assert interval.high == pytest.approx(high, abs=1e-4)


def test_wilson_edge_cases() -> None:
    assert wilson(0, 0) is None
    with pytest.raises(ValueError):
        wilson(3, 2)


# --- cluster bootstrap -------------------------------------------------------------------------


def test_bootstrap_resamples_whole_clusters() -> None:
    clusters = {"good": {"tp": 2, "n": 2}, "bad": {"tp": 0, "n": 2}}
    result = cluster_bootstrap(clusters, ratio_of("tp", "n"), resamples=2000, seed=7)
    # Only three cluster combinations exist: good+good, good+bad, bad+bad.
    assert set(result.values) <= {0.0, 0.5, 1.0}
    assert result.interval is not None
    assert (result.interval.low, result.interval.high) == (0.0, 1.0)
    assert result.undefined == 0


def test_bootstrap_is_deterministic_and_degenerate_for_one_cluster() -> None:
    clusters = {"only": {"tp": 3, "n": 4}}
    a = cluster_bootstrap(clusters, ratio_of("tp", "n"), resamples=200, seed=1)
    b = cluster_bootstrap(clusters, ratio_of("tp", "n"), resamples=200, seed=1)
    assert a == b
    assert a.interval is not None
    assert (a.interval.low, a.interval.high) == (0.75, 0.75)


def test_bootstrap_counts_resamples_with_zero_denominator() -> None:
    clusters = {"empty": {"tp": 0, "n": 0}, "full": {"tp": 1, "n": 1}}
    result = cluster_bootstrap(clusters, ratio_of("tp", "n"), resamples=1000, seed=3)
    assert 0 < result.undefined < 1000  # "empty, empty" resamples have no denominator
    assert set(result.values) == {1.0}


# --- matching and metrics on a hand-scored scenario ----------------------------------------


def t(id_: str, fam: Family, label: Label, path: str, lines: tuple[int, int], tmpl: str,
      pair: str | None = None) -> Truth:  # fmt: skip
    return Truth(
        id=id_,
        family=fam,
        label=label,
        path=path,
        start_line=lines[0],
        end_line=lines[1],
        template_family=tmpl,
        pair_id=pair,
    )


def p(fam: Family, path: str, lines: tuple[int, int], conclusion: Conclusion) -> Prediction:
    return Prediction(
        family=fam, path=path, start_line=lines[0], end_line=lines[1], conclusion=conclusion
    )


TRUTHS = [
    t("T1", AUTH, "vulnerable", "a.py", (10, 12), "orders", "P1"),
    t("T2", AUTH, "safe", "a_fixed.py", (10, 12), "orders", "P1"),
    t("T3", AUTH, "vulnerable", "b.py", (5, 6), "menu", "P2"),
    t("T4", AUTH, "safe", "b_fixed.py", (5, 6), "menu", "P2"),
    t("T5", INJ, "vulnerable", "c.py", (20, 20), "search"),
    t("T6", PATH, "vulnerable", "d.py", (7, 9), "files"),
    t("T7", INJ, "safe", "e.py", (3, 3), "search"),
]
PREDICTIONS = [
    p(AUTH, "a.py", (11, 11), S),  # credits T1
    p(AUTH, "a.py", (12, 13), S),  # duplicate of T1 -> false positive
    p(AUTH, "b_fixed.py", (5, 5), S),  # alarms the defended control T4 -> false positive
    p(INJ, "c.py", (20, 20), INC),  # abstains on T5
    p(PATH, "d.py", (30, 31), S),  # outside T6 even with tolerance -> false positive, T6 missed
    p(AUTH, "b.py", (5, 5), REJ),  # negative on T3 -> T3 missed
    p(INJ, "e.py", (3, 3), S),  # alarms T7 -> false positive
    p(INJ, "a.py", (11, 11), S),  # right place, wrong root cause -> false positive
]


def test_matching_outcomes() -> None:
    m = match(TRUTHS, PREDICTIONS)
    outcomes = {o.truth.id: o.outcome for o in m.outcomes}
    assert outcomes == {
        "T1": "detected",
        "T3": "missed",
        "T5": "abstained",
        "T6": "missed",
        "T2": "cleared",
        "T4": "false_alarm",
        "T7": "false_alarm",
    }
    assert len(m.true_positives) == 1
    assert len(m.false_positives) == 5


def test_metrics_match_hand_computed_values() -> None:
    report = score(TRUTHS, PREDICTIONS, resamples=500)
    assert (report.precision.point.successes, report.precision.point.trials) == (1, 6)
    assert report.recall["authorization"].point.value == 0.5
    assert report.recall["injection"].point.value == 0.0
    assert report.recall["path_traversal"].point.value == 0.0
    assert (report.defended_false_positive_rate.point.successes,
            report.defended_false_positive_rate.point.trials) == (2, 3)  # fmt: skip
    assert report.abstention_rate.point.value == 0.25
    assert report.paired_discrimination.point.value == 0.5
    assert report.duplicate_or_unmatched_reports == 5
    precision_ci = report.precision.point.wilson
    assert precision_ci is not None and precision_ci.low < 1 / 6 < precision_ci.high


def test_line_tolerance_is_three_lines() -> None:
    truth = [t("T", AUTH, "vulnerable", "x.py", (10, 10), "f")]
    assert match(truth, [p(AUTH, "x.py", (13, 13), S)]).true_positives
    assert not match(truth, [p(AUTH, "x.py", (14, 14), S)]).true_positives


def test_unattributed_false_positives_get_their_own_cluster() -> None:
    m = match(TRUTHS, [p(AUTH, "elsewhere.py", (1, 1), S)])
    clusters = cluster_counts(TRUTHS, m)
    assert clusters["path:elsewhere.py"]["fp"] == 1


def test_pairs_need_one_vulnerable_and_one_safe_member() -> None:
    broken = [t("X1", AUTH, "vulnerable", "x.py", (1, 1), "f", "PX"),
              t("X2", AUTH, "vulnerable", "y.py", (1, 1), "f", "PX")]  # fmt: skip
    with pytest.raises(ValueError, match="one vulnerable and one safe"):
        score(broken, [])


def test_duplicate_truth_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="unique"):
        score([TRUTHS[0], TRUTHS[0]], [])
