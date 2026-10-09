import shutil
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.ground_truth import (
    MANIFEST,
    Case,
    Kind,
    Manifest,
    build_fixed,
    fixed_problems,
    load,
    problems,
    symbol_span,
    truths,
)


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return load()


@pytest.fixture(scope="module")
def fixed_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_fixed(tmp_path_factory.mktemp("fixed") / "tandir")


def _with(manifest: Manifest, case_id: str, **changes: object) -> Manifest:
    cases = tuple(c.model_copy(update=changes) if c.id == case_id else c for c in manifest.cases)
    return manifest.model_copy(update={"cases": cases})


def test_manifest_holds_on_the_lab(manifest: Manifest) -> None:
    assert problems(manifest) == []


def test_fixed_snapshot_repairs_every_flaw_and_nothing_else(
    manifest: Manifest, fixed_root: Path
) -> None:
    assert fixed_problems(manifest, fixed_root) == []


def test_every_plan_flaw_is_declared_with_its_lookalike(manifest: Manifest) -> None:
    flaws = [c for c in manifest.cases if c.kind is Kind.FLAW]
    assert Counter(c.family.value for c in flaws) == {
        "authorization": 2,
        "injection": 2,
        "path_traversal": 1,
        "nextjs_exposure": 3,
    }
    lookalikes = {c.pair for c in manifest.cases if c.kind is Kind.LOOKALIKE}
    assert {c.pair for c in flaws} == lookalikes


def test_truths_for_scoring(manifest: Manifest) -> None:
    ts = truths(manifest)
    assert Counter(t.label for t in ts) == {"vulnerable": 8, "safe": 16}
    receipt = next(t for t in ts if t.id == "TANDIR-A1")
    assert (receipt.path, receipt.start_line, receipt.end_line) == (
        "api/tandir/routers/orders.py",
        82,
        91,
    )
    assert receipt.pair_id == receipt.template_family == "order-documents"


# Negative tests: a manifest that drifts from the code is caught.


def test_wrong_span_is_caught(manifest: Manifest) -> None:
    drifted = _with(manifest, "TANDIR-A1", lines=(80, 91))
    assert problems(drifted) == [
        "TANDIR-A1: get_receipt spans lines (82, 91), manifest says (80, 91)"
    ]


def test_missing_anchor_is_caught(manifest: Manifest) -> None:
    drifted = _with(manifest, "TANDIR-B1", anchors=("ORDER BY {nothing}",))
    assert problems(drifted) == ["TANDIR-B1: anchor not in search_orders: 'ORDER BY {nothing}'"]


def test_missing_guard_is_caught(manifest: Manifest) -> None:
    drifted = _with(manifest, "TANDIR-A1-L", guard="ensure_owner(order, user)")
    assert problems(drifted) == [
        "TANDIR-A1-L: guard not in get_invoice: 'ensure_owner(order, user)'"
    ]


def test_missing_file_and_symbol_are_caught(manifest: Manifest) -> None:
    assert problems(_with(manifest, "TANDIR-C1", path="api/tandir/routers/photos.py")) == [
        "TANDIR-C1: api/tandir/routers/photos.py does not exist"
    ]
    [problem] = problems(_with(manifest, "TANDIR-D1", symbol="issueRefund"))
    assert problem.startswith("TANDIR-D1: function issueRefund not found")


def test_guard_definition_must_exist(manifest: Manifest) -> None:
    drifted = _with(
        manifest, "TANDIR-A1-L", guard_definition="api/tandir/services/orders.py::scoped"
    )
    assert problems(drifted) == [
        "TANDIR-A1-L: guard definition not found: api/tandir/services/orders.py::scoped"
    ]


def test_a_fix_that_does_not_apply_to_the_lab_is_caught(manifest: Manifest) -> None:
    case = next(c for c in manifest.cases if c.id == "TANDIR-A2")
    assert case.fix is not None
    wrong = case.fix.model_copy(update={"adds": ("if item is None",)})
    assert problems(_with(manifest, "TANDIR-A2", fix=wrong)) == [
        "TANDIR-A2: the vulnerable lab already has what the fix adds: 'if item is None'"
    ]


def test_unrepaired_flaw_on_the_fixed_snapshot_is_caught(
    manifest: Manifest, fixed_root: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "tandir"
    shutil.copytree(fixed_root, broken)
    orders = "api/tandir/routers/orders.py"
    shutil.copyfile(manifest.lab_root() / orders, broken / orders)
    found = fixed_problems(manifest, broken)
    assert {p.split(":")[0] for p in found} == {"TANDIR-A1", "TANDIR-C1"}


def test_a_fix_that_touches_a_lookalike_is_caught(
    manifest: Manifest, fixed_root: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "tandir"
    shutil.copytree(fixed_root, broken)
    files = broken / "api/tandir/routers/files.py"
    files.write_text(
        files.read_text(encoding="utf-8").replace("Avatar not found", "No avatar"),
        encoding="utf-8",
        newline="\n",
    )
    assert fixed_problems(manifest, broken) == [
        "TANDIR-C1-L: the fixed snapshot changed a lookalike"
    ]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"expected": "rejected"}, "a flaw is supported"),
        ({"guard": "something"}, "a flaw is supported"),
        ({"fix": None}, "a flaw is supported"),
        ({"pair": None}, "come in pairs"),
        ({"path": "../api/x.py"}, "relative to the lab root"),
        ({"path": "api\\tandir\\x.py"}, "relative to the lab root"),
        ({"lines": (10, 5)}, "lines run backwards"),
    ],
)
def test_case_rules(manifest: Manifest, changes: dict[str, object], message: str) -> None:
    receipt = next(c for c in manifest.cases if c.id == "TANDIR-A1")
    with pytest.raises(ValidationError, match=message):
        Case.model_validate({**receipt.model_dump(), **changes})


def test_pairs_need_one_flaw_and_one_lookalike(manifest: Manifest) -> None:
    raw = manifest.model_dump(by_alias=True)
    raw["case"] = [c for c in raw["case"] if c["id"] != "TANDIR-A1-L"]
    with pytest.raises(ValidationError, match="pair order-documents"):
        Manifest.model_validate(raw)


def test_typescript_spans_end_at_the_closing_brace() -> None:
    source = "import x;\n\nexport async function act(a) {\n  if (a) {\n    go();\n  }\n}\n"
    assert symbol_span(source, "a.ts", "act") == (3, 7)
    with pytest.raises(LookupError):
        symbol_span(source, "a.ts", "missing")


def test_manifest_file_is_where_the_docs_say() -> None:
    assert MANIFEST.as_posix().endswith("eval/ground_truth/tandir.toml")
