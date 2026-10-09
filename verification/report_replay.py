"""Bind a fresh pinned-lab replay to a completed review, preserving its original export."""

import ast
import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from analysis.snapshot import SnapshotStore
from backend.contracts.code import ProjectSnapshot, snapshot_id
from backend.contracts.common import Contract, Family, Sha256
from backend.contracts.investigation import Conclusion, ExhibitRole, Finding, RuntimeVerification
from backend.contracts.runs import RunLifecycle
from backend.contracts.verification import (
    ChangeStatus,
    ProbeOutcome,
    ProbeRun,
    ProbeSpec,
    RunnerKind,
    SuggestedChange,
)
from backend.jobs import WorkerLock
from backend.redaction import Redactor
from backend.reports import Format, ReportBundle, render
from backend.saved_reports import MAX_REPORT_BYTES, load
from backend.settings import Settings
from eval.bench.machine import machine_state
from verification import lab, replay

PATH = "api/" + lab.RECEIPT_PATH
LIMITATION = (
    "Receipt fix replay ran only the hash-pinned bundled API in disposable copies. "
    "The original source, finding disposition and review coverage are unchanged; "
    "this does not establish that the entire project is fixed."
)
FORMATS: tuple[tuple[str, Format], ...] = (
    ("json", "json"),
    ("html", "html"),
    ("md", "markdown"),
    ("sarif", "sarif"),
)


class Attachment(Contract):
    original_report_sha256: Sha256
    spec: ProbeSpec
    change: SuggestedChange
    before: ProbeRun
    after: ProbeRun


def source(
    bundle: ReportBundle, store: SnapshotStore, finding_id: str
) -> tuple[Finding, bytes, str]:
    """Prove the execution subset and cited receipt code match the frozen review."""
    finding = next((f for f in bundle.findings if f.id == finding_id), None)
    if (
        finding is None
        or bundle.run.lifecycle is not RunLifecycle.COMPLETED
        or finding.family is not Family.AUTHORIZATION
        or finding.conclusion is not Conclusion.SUPPORTED
        or finding.suggested_change_id is not None
    ):
        raise ValueError("Replay needs a completed, supported receipt finding without a change")
    raw_pin = lab.PIN.read_bytes()
    pin = json.loads(raw_pin)
    for path, digest in pin["files"].items():
        if hashlib.sha256(store.read(bundle.snapshot, "api/" + path)).hexdigest() != digest:
            raise ValueError("Frozen review does not match the pinned bundled API")
    original = store.read(bundle.snapshot, PATH)
    if original.count(lab.RECEIPT_BEFORE.encode()) != 1:
        raise ValueError("Receipt preimage is not unique")
    first = original[: original.index(lab.RECEIPT_BEFORE.encode())].count(b"\n") + 1
    last = first + len(lab.RECEIPT_BEFORE.splitlines()) - 1
    handler = next(
        node
        for node in ast.walk(ast.parse(original))
        if isinstance(node, ast.FunctionDef) and node.lineno <= first and node.end_lineno == last
    )
    start = min([handler.lineno, *(d.lineno for d in handler.decorator_list)])
    if not any(
        e.role is not ExhibitRole.DEVELOPER_NOTE
        and e.span.path == PATH
        and start <= e.span.start_line <= first
        and e.span.end_line == last
        for e in finding.exhibits
    ):
        raise ValueError("Finding does not cite the receipt lookup and return")
    patched = original.replace(lab.RECEIPT_BEFORE.encode(), lab.RECEIPT_AFTER.encode(), 1)
    variant = pin["variants"]["receipt_fixed"]
    if hashlib.sha256(lab.PATCH.read_bytes()).hexdigest() != variant["patch_sha256"] or variant[
        "files"
    ] != {lab.RECEIPT_PATH: hashlib.sha256(patched).hexdigest()}:
        raise ValueError("Receipt patch differs from the release pin")
    return finding, patched, hashlib.sha256(raw_pin).hexdigest()


def patched_snapshot(original: ProjectSnapshot, patched: bytes) -> ProjectSnapshot:
    files = [
        f.model_copy(update={"sha256": hashlib.sha256(patched).hexdigest(), "size": len(patched)})
        if f.path == PATH
        else f
        for f in original.files
    ]
    return ProjectSnapshot.model_validate(
        {
            **original.model_dump(),
            "id": snapshot_id(files),
            "files": files,
            "created_at": datetime.now(UTC),
            "dirty": True,
        }
    )


def combine(original: ReportBundle, store: SnapshotStore, attachment: Attachment) -> ReportBundle:
    """Derive the only permitted changes; never accept a caller-supplied merged report."""
    finding, patched, manifest = source(original, store, attachment.spec.finding_id)
    spec = attachment.spec
    if spec != lab.receipt_spec(spec.marker, finding_id=finding.id):
        raise ValueError("Attachment must use the pinned receipt probe")
    expected = patched_snapshot(original.snapshot, patched)
    if (
        store.load(expected.id).model_dump(exclude={"created_at"})
        != expected.model_dump(exclude={"created_at"})
        or store.read(expected, PATH) != patched
    ):
        raise ValueError("Patched snapshot does not preserve the original file domain")
    before, after = attachment.before, attachment.after
    if before.snapshot_id != original.snapshot.id or after.snapshot_id != expected.id:
        raise ValueError("Replay does not belong to this original and patched snapshot pair")
    if before.outcome is not ProbeOutcome.REPRODUCED or before.finished_at > after.started_at:
        raise ValueError("Replay needs a reproduced baseline followed by its patched probe")
    for observation in (before, after):
        if (
            observation.runner is not RunnerKind.BUNDLED_LAB
            or observation.runner_manifest_sha256 != manifest
        ):
            raise ValueError("Replay runner does not match the pinned release")
        if len(observation.steps) != len(spec.requests):
            raise ValueError("Replay is missing probe steps")
        for step, request in zip(observation.steps, spec.requests, strict=True):
            pattern = re.escape(request.path).replace(re.escape("{order_id}"), r"[1-9][0-9]*")
            if (
                step.role != request.role
                or step.principal != request.principal
                or step.method != request.method
                or step.expected_if_safe != request.expected_if_safe
                or re.fullmatch(pattern, step.path) is None
            ):
                raise ValueError("Replay observations do not match the receipt probe")
        if observation.steps[1].path != observation.steps[2].path:
            raise ValueError("Attack and control must address the same receipt")
    result = replay.conclude(replay.receipt_change(finding.id), before, after)
    if result.change != attachment.change:
        raise ValueError("Suggested change differs from its pinned diff or observed proof")
    updated = finding.model_copy(
        update={
            "probe_run_ids": [*finding.probe_run_ids, before.id],
            "suggested_change_id": result.change.id,
            "runtime_verification": RuntimeVerification.REPRODUCED,
        }
    )
    return ReportBundle.model_validate(
        {
            **original.model_dump(),
            "findings": [updated if f.id == finding.id else f for f in original.findings],
            "probe_runs": [*original.probe_runs, before, after],
            "suggested_changes": [*original.suggested_changes, result.change],
            "limitations": [*original.limitations, LIMITATION],
        }
    )


def _read(directory: Path, name: str) -> bytes:
    path = directory / name
    if path.resolve(strict=True).parent != directory.resolve(strict=True):
        raise ValueError("Attachment file leaves its directory")
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Attachment file exceeds the saved-report limit")
    return path.read_bytes()


def load_attachment(
    directory: Path, original: ReportBundle, store: SnapshotStore, secrets: Sequence[str]
) -> tuple[ReportBundle, Path]:
    root = (directory / "receipt-replay").resolve(strict=True)
    if root.parent != directory:
        raise ValueError("Attachment leaves the saved review directory")
    attachment = Attachment.model_validate_json(_read(root, "attachment.json"))
    if (
        attachment.original_report_sha256
        != hashlib.sha256(_read(directory, "report.json")).hexdigest()
    ):
        raise ValueError("Original report changed after the replay was attached")
    bundle = combine(original, store, attachment)
    for suffix, format in FORMATS[:2]:
        name = "report." + suffix
        if _read(root, name) != render(bundle, store, format, secrets=secrets).encode("utf-8"):
            raise ValueError("Replay export differs from validated evidence")
    return ReportBundle.model_validate_json(_read(root, "report.json")), root / "report.html"


def _attach(
    settings: Settings,
    run_id: str,
    finding_key: str,
    record: dict[str, Any],
    redactor: Redactor,
) -> int:
    try:
        with WorkerLock(settings.cache_dir / "review.lock"):
            original, report_path = load(
                settings, run_id, include_replay=False, include_dispositions=False
            )
            directory = report_path.parent
            finding = next(
                (f for f in original.findings if finding_key in {f.id, f.display_id}), None
            )
            if finding is None:
                raise ValueError("No finding matches this saved review")
            store = SnapshotStore(settings.cache_dir / "snapshots")
            try:
                store.load(original.snapshot.id)
            except FileNotFoundError:
                store = SnapshotStore(settings.cache_dir)
            source(original, store, finding.id)
            if (directory / "receipt-replay").exists():
                existing, path = load(settings, run_id)
                if not any(c.finding_id == finding.id for c in existing.suggested_changes):
                    raise ValueError("The existing receipt replay belongs to another finding")
                recorded_change = next(
                    c for c in existing.suggested_changes if c.finding_id == finding.id
                )
                record["status"] = "existing_" + recorded_change.status.value
                record["message"] = "Validated existing replay; no new execution"
                record["report_path"] = str(path)
                return 0 if recorded_change.status is ChangeStatus.REPLAYED_FIXED else 1
            spec = lab.receipt_spec("PLUMB_" + uuid4().hex, finding_id=finding.id)
            change = replay.receipt_change(finding.id)
            replay.admit_change(spec, change)
            files, manifest = lab.verified_files()
            patched_files, _ = lab.verified_files(variant="receipt_fixed")
            # Both executed byte sets were pinned and matched against the frozen report first.
            patched = patched_snapshot(original.snapshot, patched_files[lab.RECEIPT_PATH])
            store.blobs.put(patched_files[lab.RECEIPT_PATH])
            patched = store.save(patched)
            digest = hashlib.sha256(_read(directory, "report.json")).hexdigest()
            record.update(
                spec=spec.model_dump(mode="json"),
                machine_start=machine_state(),
                model_loaded=False,
                runner_manifest=json.loads(lab.PIN.read_bytes()),
                implementation={
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (Path(__file__), Path(lab.__file__), Path(replay.__file__))
                },
            )
            before = lab._probe(spec, settings, files, manifest, original.snapshot.id, "vulnerable")
            record["before"] = before.model_dump(mode="json")
            if before.outcome is not ProbeOutcome.REPRODUCED:
                raise ValueError("Baseline did not reproduce; no fix replay was attached")
            after = lab._probe(spec, settings, patched_files, manifest, patched.id, "receipt_fixed")
            record["after"] = after.model_dump(mode="json")
            result = replay.conclude(change, before, after)
            attachment = Attachment(
                original_report_sha256=digest,
                spec=spec,
                change=result.change,
                before=before,
                after=after,
            )
            bundle = combine(original, store, attachment)
            formats = {
                "report." + suffix: render(bundle, store, format, secrets=redactor.secrets)
                for suffix, format in FORMATS
            }
            formats["attachment.json"] = attachment.model_dump_json(indent=2)
            with TemporaryDirectory(prefix=".receipt-replay-", dir=directory) as staging:
                for name, content in formats.items():
                    (Path(staging) / name).write_text(content, encoding="utf-8", newline="\n")
                if digest != hashlib.sha256(_read(directory, "report.json")).hexdigest():
                    raise ValueError("Original report changed during replay; attachment refused")
                Path(staging).rename(directory / "receipt-replay")
            record["attachment"] = attachment.model_dump(mode="json")
            record["status"] = result.change.status.value
            record["message"] = (
                f"{finding.display_id}: {result.change.status.value}; original source preserved"
            )
            record["report_path"] = str(directory / "receipt-replay" / "report.html")
            return 0 if result.change.status is ChangeStatus.REPLAYED_FIXED else 1
    except Exception as error:
        record["error"] = redactor.text(f"{type(error).__name__}: {error}")
        return 1


def attach(settings: Settings, run_id: str, finding_key: str) -> int:
    """Public command: record failures, publish a complete sidecar atomically, load no model."""
    record: dict[str, Any] = {"started": datetime.now(UTC).isoformat(), "run_id": run_id}
    attempt = settings.data_dir / "probes" / ("report-replay-" + uuid4().hex)
    redactor = Redactor.configured(settings)
    code = _attach(settings, run_id, finding_key, record, redactor)
    record["finished"] = datetime.now(UTC).isoformat()
    if "machine_start" in record:
        record["machine_end"] = machine_state()
    try:
        attempt.mkdir(parents=True, exist_ok=False)
        (attempt / "manifest.json").write_text(
            json.dumps(redactor.strings(record), indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    except OSError:
        print(
            "Replay outcome record could not be saved. Existing reports are preserved. "
            "Check write access to the Plumb data directory; command incomplete."
        )
        return 1
    print(f"Replay unavailable: {record['error']}" if "error" in record else record["message"])
    if "report_path" in record:
        print(f"Report: {record['report_path']}")
    print(f"Record: {attempt / 'manifest.json'}")
    return code
