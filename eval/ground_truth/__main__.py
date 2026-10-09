"""Validate the Tandir ground truth: ``uv run python -m eval.ground_truth check``."""

import argparse
import sys
import tempfile
from collections import Counter
from pathlib import Path

from eval.ground_truth import build_fixed, fixed_problems, load, problems


def check() -> int:
    manifest = load()
    found = problems(manifest)
    with tempfile.TemporaryDirectory(prefix="tandir-truth-", ignore_cleanup_errors=True) as tmp:
        found += fixed_problems(manifest, build_fixed(Path(tmp) / "tandir"))
    kinds = Counter(case.kind.value for case in manifest.cases)
    families = Counter(case.family.value for case in manifest.cases if case.kind == "flaw")
    print(f"{len(manifest.cases)} cases: {dict(kinds)}; flaws by family: {dict(families)}")
    for problem in found:
        print(f"PROBLEM {problem}")
    print("ground truth holds" if not found else f"{len(found)} problems")
    return 1 if found else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.parse_args()
    return check()


if __name__ == "__main__":
    sys.exit(main())
