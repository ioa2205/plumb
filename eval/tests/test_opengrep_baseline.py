from pathlib import Path

import pytest

from backend.contracts.common import Family
from backend.settings import Settings
from backend.setup.opengrep import binary
from backend.setup.pins import load_opengrep_pin
from eval.baselines.common import case_path, materialize, truths
from eval.baselines.opengrep import predictions, scan
from eval.mutation.corpus import build


def result(path: Path, line: int, family: str, rule: str = "r") -> dict[str, object]:
    return {
        "check_id": rule,
        "path": str(path),
        "start": {"line": line},
        "end": {"line": line},
        "extra": {"metadata": {"family": family}},
    }


def test_results_become_supported_predictions_relative_to_the_scan_root(tmp_path: Path) -> None:
    raw = {
        "results": [
            result(tmp_path / "t" / "a.py", 18, "authorization", "rule-1"),
            result(tmp_path / "t" / "a.py", 18, "authorization", "rule-2"),  # same place, merged
            result(tmp_path / "t" / "a.py", 18, "injection"),  # other family, kept
            result(tmp_path / "t" / "b.py", 5, "injection"),
        ]
    }
    preds = predictions(raw, tmp_path)
    assert [(p.path, p.start_line, p.family) for p in preds] == [
        ("t/a.py", 18, Family.AUTHORIZATION),
        ("t/a.py", 18, Family.INJECTION),
        ("t/b.py", 5, Family.INJECTION),
    ]
    assert {p.conclusion.value for p in preds} == {"supported"}


def test_truths_point_at_the_written_case_files() -> None:
    corpus = build()
    for t, v in zip(truths(corpus), corpus, strict=True):
        assert t.path == case_path(v)
        assert (t.start_line, t.end_line) == v.handler_lines


def test_case_paths_reveal_no_label() -> None:
    corpus = build()
    paths = [case_path(v) for v in corpus]
    assert len(set(paths)) == len(paths)
    words = {v.operator for v in corpus} | {v.template for v in corpus} | {"vulnerable", "safe"}
    for path in paths:
        assert not any(word in path for word in words), path


def _opengrep() -> Path | None:
    try:
        return binary(Settings(), load_opengrep_pin())
    except FileNotFoundError:
        return None


@pytest.mark.skipif(_opengrep() is None, reason="pinned Opengrep is not installed")
def test_rules_flag_known_flaws_and_spare_the_original(tmp_path: Path) -> None:
    wanted = {
        "order_receipt/original",
        "order_receipt/drop_owner_check",
        "order_receipt/wrong_field",
        "order_receipt/move_to_dependency",
        "order_status_filter/original",
        "order_status_filter/sql_fstring",
        "order_status_filter/bound_parameters",
    }
    cases = [v for v in build() if v.id in wanted]
    materialize(cases, tmp_path)
    exe = _opengrep()
    assert exe is not None
    found = {p.path for p in predictions(scan(exe, tmp_path), tmp_path)}
    flagged = {v.id for v in cases if case_path(v) in found}
    assert "order_receipt/drop_owner_check" in flagged
    assert "order_status_filter/sql_fstring" in flagged
    assert "order_receipt/original" not in flagged
    assert "order_receipt/move_to_dependency" not in flagged
    assert "order_status_filter/original" not in flagged
    # A pattern rule cannot see that the wrong field is compared: a known scanner miss.
    assert "order_receipt/wrong_field" not in flagged
