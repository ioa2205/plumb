"""Run a reviewed receipt/invoice probe against the hash-pinned bundled Tandir API."""

import argparse
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.contracts.verification import ChangeStatus
from backend.redaction import Redactor
from backend.settings import Settings
from eval.bench.machine import machine_state
from verification import replay
from verification.lab import PIN, receipt_spec, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--invoice", action="store_true", help="Exercise the protected lookalike")
    mode.add_argument(
        "--replay", action="store_true", help="Check the pinned receipt fix before/after"
    )
    args = parser.parse_args(argv)
    settings = Settings()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    directory = settings.data_dir / "probes" / stamp
    directory.mkdir(parents=True, exist_ok=False)
    spec = receipt_spec("PLUMB_" + uuid4().hex, invoice=args.invoice)
    record: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "spec": spec.model_dump(mode="json"),
        "runner_manifest": json.loads(PIN.read_text()),
        "machine_start": machine_state(),
        "ground_truth_case": "TANDIR-A1-L" if args.invoice else "TANDIR-A1",
    }
    try:
        if args.replay:
            result = replay.run(spec, replay.receipt_change(spec.finding_id), settings)
            record["replay"] = {
                "change": result.change.model_dump(mode="json"),
                "before": result.before.model_dump(mode="json"),
                "after": result.after.model_dump(mode="json") if result.after else None,
                "error": result.error,
            }
            print(f"Tandir receipt change: {result.change.status.value}")
            for label, observation in (("before", result.before), ("after", result.after)):
                if observation:
                    print(f"  {label}: {observation.outcome.value}")
                    for step in observation.steps:
                        print(
                            f"    {step.role.value}: {step.principal}, HTTP {step.status}, "
                            f"marker={step.marker_present}"
                        )
            return 0 if result.change.status is ChangeStatus.REPLAYED_FIXED else 1
        result = run(spec, settings)
        record["probe_run"] = result.model_dump(mode="json")
        print(f"Tandir {'invoice' if args.invoice else 'receipt'}: {result.outcome.value}")
        for step in result.steps:
            print(
                f"  {step.role.value}: {step.principal}, HTTP {step.status}, "
                f"marker={step.marker_present}"
            )
        return 0 if result.outcome.value in {"reproduced", "not_reproduced"} else 1
    except Exception as error:
        record["error"] = Redactor.configured().text(f"{type(error).__name__}: {error}")
        print("Bundled verification unavailable; see the saved manifest.")
        return 1
    finally:
        record["finished"] = datetime.now(UTC).isoformat()
        record["machine_end"] = machine_state()
        output = directory / "manifest.json"
        output.write_text(
            json.dumps(Redactor.configured().strings(record), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Record: {output}")


if __name__ == "__main__":
    raise SystemExit(main())
