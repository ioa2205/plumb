"""Corpus splits by template family, and the sealed test split (PROJECT_PLAN §10.2, §11).

    uv run python -m eval.splits freeze   # assign splits, hash the test split, write the manifest
    uv run python -m eval.splits check    # fail if the corpus no longer matches the manifest

Every variant of a template lands in the same split, so a model is never
scored on a handler whose siblings it was tuned on. Template families are
assigned per vulnerability family by a salted hash, which is stable and not
chosen by hand. The test split is sealed: its variant hashes and their
combined hash are committed, ``load`` refuses it unless asked by name, and
its template files are listed by ``sealed_paths`` so indexing can exclude them.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eval.mutation.corpus import ORIGINAL, Variant, build
from eval.mutation.templates import TEMPLATE_DIR, Template, load_templates

MANIFEST = Path(__file__).with_name("manifest.json")
SALT = "plumb-splits-2026-10-03"
Split = Literal["development", "validation", "test"]
SPLITS: tuple[Split, ...] = ("development", "validation", "test")
TEST_SHARE = 0.3
VALIDATION_SHARE = 0.2


class SealedError(PermissionError):
    """The sealed test split was requested without opening it explicitly."""


class StaleManifestError(RuntimeError):
    """The corpus no longer matches the committed manifest."""


def _rank(name: str) -> str:
    return hashlib.sha256(f"{SALT}:{name}".encode()).hexdigest()


def assign(templates: list[Template]) -> dict[str, Split]:
    """Template name -> split, stratified by vulnerability family."""
    by_family: dict[str, list[str]] = defaultdict(list)
    for t in templates:
        by_family[t.family.value].append(t.name)
    result: dict[str, Split] = {}
    for names in by_family.values():
        ordered = sorted(names, key=_rank)
        n = len(ordered)
        n_test = max(1, round(n * TEST_SHARE)) if n >= 3 else 0
        n_val = max(1, round(n * VALIDATION_SHARE)) if n >= 3 else 0
        for i, name in enumerate(ordered):
            result[name] = (
                "test" if i < n_test else "validation" if i < n_test + n_val else "development"
            )
    return result


def seal_hash(variants: list[Variant]) -> str:
    digest = hashlib.sha256()
    for v in sorted(variants, key=lambda v: v.id):
        digest.update(f"{v.id}\0{v.sha256}\n".encode())
    return digest.hexdigest()


def manifest_for(variants: list[Variant], assignment: dict[str, Split]) -> dict[str, object]:
    splits: dict[str, dict[str, str]] = {s: {} for s in SPLITS}
    for v in variants:
        splits[assignment[v.template]][v.id] = v.sha256
    test = [v for v in variants if assignment[v.template] == "test"]
    return {
        "salt": SALT,
        "shares": {"test": TEST_SHARE, "validation": VALIDATION_SHARE},
        "templates": dict(sorted(assignment.items())),
        "splits": {s: dict(sorted(ids.items())) for s, ids in splits.items()},
        "sealed_test_sha256": seal_hash(test),
    }


def _current() -> tuple[list[Variant], dict[str, Split]]:
    templates = load_templates()
    return build(templates), assign(templates)


def stale_reasons(manifest_path: Path = MANIFEST) -> list[str]:
    if not manifest_path.is_file():
        return [f"{manifest_path} does not exist"]
    committed = json.loads(manifest_path.read_text(encoding="utf-8"))
    variants, assignment = _current()
    expected = manifest_for(variants, assignment)
    return [key for key in expected if committed.get(key) != expected[key]]


def load(split: Split, *, open_sealed: bool = False) -> list[Variant]:
    """Variants of one split, verified against the manifest. The test split stays sealed."""
    if split == "test" and not open_sealed:
        raise SealedError("the test split is sealed; it is opened once, for the final report")
    if reasons := stale_reasons():
        raise StaleManifestError(f"corpus differs from the manifest: {reasons}")
    variants, assignment = _current()
    return [v for v in variants if assignment[v.template] == split]


def sealed_paths(manifest_path: Path = MANIFEST) -> list[Path]:
    """Template files of the sealed split, for exclusion from any index or prompt example."""
    committed = json.loads(manifest_path.read_text(encoding="utf-8"))
    return sorted(TEMPLATE_DIR / f"{name}.py" for name, split in committed["templates"].items()
                  if split == "test")  # fmt: skip


@dataclass(frozen=True)
class Fold:
    held_out: str
    train: list[Variant]
    evaluate: list[Variant]


def operator_folds(variants: list[Variant]) -> Iterator[Fold]:
    """Leave-one-operator-out folds (experiment E5). Originals always stay in training."""
    operators = sorted({v.operator for v in variants} - {ORIGINAL})
    for held_out in operators:
        yield Fold(
            held_out=held_out,
            train=[v for v in variants if v.operator != held_out],
            evaluate=[v for v in variants if v.operator == held_out],
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["freeze", "check"])
    args = parser.parse_args(argv)
    if args.command == "check":
        if reasons := stale_reasons():
            print("manifest is stale:", ", ".join(reasons))
            return 1
        print("corpus matches the manifest")
        return 0
    variants, assignment = _current()
    manifest = manifest_for(variants, assignment)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    counts = {s: sum(1 for v in variants if assignment[v.template] == s) for s in SPLITS}
    print(f"froze {counts}; sealed test sha256 {manifest['sealed_test_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
