"""Export a validated report bundle using the local content-addressed snapshot store."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from analysis.snapshot import SnapshotStore
from backend.reports import Format, ReportBundle, render
from backend.settings import Settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bundle", type=Path, help="JSON ReportBundle with the run and its evidence records"
    )
    parser.add_argument(
        "--format", choices=("markdown", "html", "json", "sarif"), default="markdown"
    )
    parser.add_argument("--output", type=Path, help="new output file; stdout if omitted")
    args = parser.parse_args(argv)
    try:
        bundle = ReportBundle.model_validate_json(args.bundle.read_text(encoding="utf-8"))
        cache = Settings().cache_dir
        store = SnapshotStore(cache / "snapshots")
        try:
            store.load(bundle.snapshot.id)
        except FileNotFoundError:
            # Earlier standalone exporters stored manifests directly under cache.
            # A present but corrupt newer snapshot must fail, never silently fall back.
            store = SnapshotStore(cache)
        output = render(bundle, store, cast(Format, args.format))
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(output)
        else:
            sys.stdout.write(output)
    except (OSError, ValueError) as error:
        # Validation errors can contain the original input and credentials. Do not echo them.
        print(
            f"Report export refused ({type(error).__name__}). "
            "Check the bundle, snapshot and output path.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
