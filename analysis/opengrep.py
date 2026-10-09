"""Pinned, offline pattern leads from frozen source; never findings or target execution."""

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from agent.validator import Validator
from analysis.paths import check_relative
from analysis.snapshot import SnapshotStore
from analysis.syntax import span_sha256
from backend.contracts.code import ProjectSnapshot, SourceSpan
from backend.contracts.common import Contract, Family
from backend.contracts.investigation import ObservationStatus, ToolObservation
from backend.settings import Settings
from backend.setup.opengrep import binary
from backend.setup.pins import load_opengrep_pin

RULES = Path(__file__).resolve().parent / "rules"
RULE_FAMILIES = {
    "plumb.authz.load-by-id-without-owner-comparison": Family.AUTHORIZATION,
    "plumb.injection.sql-text-from-request": Family.INJECTION,
    "plumb.injection.shell-command-from-request": Family.INJECTION,
    "plumb.injection.shell-command-not-literal": Family.INJECTION,
    "plumb.nextjs.server-action-without-session-check": Family.NEXTJS_EXPOSURE,
    "plumb.nextjs.admin-route-handler-without-role-check": Family.NEXTJS_EXPOSURE,
    "plumb.path.request-value-in-file-path": Family.PATH_TRAVERSAL,
}
MAX_OUTPUT = 8 * 1024 * 1024


class Signal(Contract):
    rule: str
    family: Family
    span: SourceSpan


class Scan(Contract):
    observation: ToolObservation
    signals: list[Signal] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def rules_identity() -> str:
    inputs = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(RULES.glob("*.yaml"))
    }
    if not inputs:
        raise ValueError("Plumb's rule pack is missing")
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def parse_signals(
    raw: object, root: Path, snapshot: ProjectSnapshot, store: SnapshotStore
) -> tuple[list[Signal], list[str]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        raise ValueError("scanner output is not a result list")
    validator = Validator(snapshot, store)
    files = {f.path for f in snapshot.files if f.language is not None}
    found: dict[tuple[str, str, int, int], Signal] = {}
    limitations = []
    paths = raw.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("scanner paths are malformed")
    if raw.get("errors") or paths.get("skipped"):
        limitations.append(
            "Opengrep reported skipped files or analysis errors; its scan is partial."
        )
    for row in raw["results"]:
        try:
            rule = row["check_id"]
            family = RULE_FAMILIES[rule]
            reported = Path(row["path"])
            relative = (
                reported.relative_to(root) if reported.is_absolute() else reported
            ).as_posix()
            check_relative(relative)
            if relative not in files:
                raise ValueError("scanner span is outside included source")
            start, end = row["start"]["line"], row["end"]["line"]
            if type(start) is not int or type(end) is not int or not 1 <= start <= end:
                raise ValueError("invalid scanner lines")
            source = store.read(snapshot, relative)
            span = SourceSpan(
                snapshot_id=snapshot.id,
                path=relative,
                start_line=start,
                end_line=end,
                content_sha256=span_sha256(source, start, end),
            )
            if validator.evidence(span):
                raise ValueError("scanner match does not cite executable frozen source")
            found[(rule, relative, start, end)] = Signal(rule=rule, family=family, span=span)
        except (KeyError, TypeError, ValueError, OSError, IndexError):
            limitations.append("An invalid or unsupported Opengrep match was ignored.")
    return [found[key] for key in sorted(found)], list(dict.fromkeys(limitations))


def scan(snapshot: ProjectSnapshot, store: SnapshotStore, settings: Settings, run_id: str) -> Scan:
    started = datetime.now(UTC)
    pin = load_opengrep_pin()
    rules_hash = rules_identity()
    signals: list[Signal] = []
    limitations = []
    status = ObservationStatus.OK
    try:
        exe = binary(settings, pin)  # Verify the installed bytes; never install implicitly.
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="opengrep-", dir=settings.cache_dir) as name:
            work = Path(name)
            root = work / "source"
            root.mkdir()
            # Only included language files. No target config, ignores, Git hooks or scripts.
            for file in snapshot.files:
                if file.language is not None:
                    target = root.joinpath(*check_relative(file.path).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(store.read(snapshot, file.path))
            argv = [
                str(exe),
                "scan",
                "--config",
                str(RULES),
                "--json",
                "--taint-intrafile",
                "--disable-version-check",
                "--no-git-ignore",
                "--no-rewrite-rule-ids",
                "--quiet",
                "--jobs",
                "1",
                "--timeout",
                "5",
                "--max-memory",
                "256",
                str(root),
            ]
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith(("OPENGREP_", "SEMGREP_"))
            }
            output = work / "output.json"
            with output.open("wb") as stdout:
                done = subprocess.run(  # noqa: S603 - pinned scanner, fixed local rules/arguments
                    argv,
                    cwd=work,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=subprocess.DEVNULL,
                    timeout=120,
                    check=False,
                )
            if done.returncode not in (0, 1) or output.stat().st_size > MAX_OUTPUT:
                raise ValueError("scanner failed or exceeded its output budget")
            signals, limitations = parse_signals(
                json.loads(output.read_bytes()), root, snapshot, store
            )
            if limitations:
                status = ObservationStatus.ERROR
    except FileNotFoundError:
        status = ObservationStatus.REFUSED
        limitations = ["Opengrep is missing or modified; pattern prioritization was unavailable."]
    except subprocess.TimeoutExpired:
        status = ObservationStatus.TIMEOUT
        limitations = ["Opengrep exceeded its time budget; pattern prioritization was unavailable."]
    except (OSError, ValueError):
        status = ObservationStatus.ERROR
        limitations = ["Opengrep failed; pattern prioritization was unavailable."]
    payload = json.dumps(
        {"signals": [s.model_dump(mode="json") for s in signals], "limitations": limitations},
        sort_keys=True,
    )
    return Scan(
        observation=ToolObservation(
            id=f"observation:{run_id}:opengrep",
            run_id=run_id,
            tool="opengrep",
            tool_version=pin.release,
            inputs={
                "snapshot_id": snapshot.id,
                "binary_sha256": pin.asset.sha256,
                "rules_sha256": rules_hash,
                "jobs": 1,
                "timeout_seconds": 120,
            },
            started_at=started,
            finished_at=datetime.now(UTC),
            status=status,
            output_sha256=hashlib.sha256(payload.encode()).hexdigest(),
        ),
        signals=signals,
        limitations=limitations,
    )
