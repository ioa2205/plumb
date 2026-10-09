import dataclasses
import json
import random
from collections import defaultdict
from pathlib import Path

import pytest

from eval.mutation.corpus import ORIGINAL, build
from eval.mutation.templates import load_templates
from eval.splits import (
    MANIFEST,
    SPLITS,
    SealedError,
    assign,
    load,
    manifest_for,
    operator_folds,
    sealed_paths,
    stale_reasons,
)

TEMPLATES = load_templates()
CORPUS = build(TEMPLATES)
COMMITTED = json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_no_template_family_crosses_splits() -> None:
    splits_of: dict[str, set[str]] = defaultdict(set)
    for split, ids in COMMITTED["splits"].items():
        for variant_id in ids:
            splits_of[variant_id.split("/")[0]].add(split)
    assert {t.name for t in TEMPLATES} == set(splits_of)
    leaking = {name: s for name, s in splits_of.items() if len(s) != 1}
    assert leaking == {}


def test_every_variant_is_in_exactly_one_split() -> None:
    seen = [vid for ids in COMMITTED["splits"].values() for vid in ids]
    assert len(seen) == len(set(seen)) == len(CORPUS)
    assert set(seen) == {v.id for v in CORPUS}


def test_each_vulnerability_family_is_represented_in_every_split() -> None:
    families = defaultdict(set)
    for t in TEMPLATES:
        families[t.family.value].add(COMMITTED["templates"][t.name])
    for family, splits in families.items():
        assert splits == set(SPLITS), family


def test_assignment_is_stable_under_input_order() -> None:
    shuffled = TEMPLATES[:]
    random.Random(1).shuffle(shuffled)  # noqa: S311 - test ordering, not secrets
    assert assign(shuffled) == assign(TEMPLATES) == COMMITTED["templates"]


def test_committed_manifest_matches_the_corpus() -> None:
    assert stale_reasons() == [], "run: uv run python -m eval.splits freeze (deliberately)"


def test_test_split_is_sealed() -> None:
    with pytest.raises(SealedError):
        load("test")
    development = load("development")
    assert development and all(
        COMMITTED["templates"][v.template] == "development" for v in development
    )


def test_opening_the_seal_returns_exactly_the_committed_cases() -> None:
    opened = load("test", open_sealed=True)
    assert {v.id: v.sha256 for v in opened} == COMMITTED["splits"]["test"]


def test_any_change_to_a_sealed_case_breaks_the_seal(tmp_path: Path) -> None:
    tampered = [
        dataclasses.replace(v, sha256="0" * 64) if v.id == "message_thread/original" else v
        for v in CORPUS
    ]
    changed = manifest_for(tampered, assign(TEMPLATES))
    assert changed["sealed_test_sha256"] != COMMITTED["sealed_test_sha256"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert "sealed_test_sha256" in stale_reasons(path)
    assert stale_reasons(tmp_path / "missing.json")


def test_sealed_paths_list_the_test_templates() -> None:
    paths = sealed_paths()
    expected = sorted(name for name, split in COMMITTED["templates"].items() if split == "test")
    assert [p.stem for p in paths] == expected
    assert all(p.is_file() for p in paths)


def test_operator_folds_hold_out_one_operator_at_a_time() -> None:
    development = load("development")
    folds = list(operator_folds(development))
    operators = {v.operator for v in development} - {ORIGINAL}
    assert {f.held_out for f in folds} == operators
    for fold in folds:
        assert fold.evaluate and all(v.operator == fold.held_out for v in fold.evaluate)
        assert all(v.operator != fold.held_out for v in fold.train)
        assert len(fold.train) + len(fold.evaluate) == len(development)
        assert any(v.operator == ORIGINAL for v in fold.train)
