"""Report attachment boundaries; probe answers here are software fixtures, not accuracy evidence."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.validator import span_sha256
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.app import create_app
from backend.case_reads import CaseReads
from backend.cli import main
from backend.contracts.code import SourceSpan
from backend.contracts.investigation import DispositionUpdate, Exhibit, Finding
from backend.contracts.runs import Coverage, ReviewRun
from backend.contracts.verification import (
    ProbeRun,
    ProbeSpec,
    ProbeStep,
    SnapshotRole,
    derive_outcome,
)
from backend.reports import ReportBundle, render
from backend.saved_reports import load
from backend.settings import Settings
from backend.tests.support import PORT, signed_in, visitor
from verification import lab, report_replay

RUN = "review-" + "b" * 32
FINDING = "finding:receipt"
type SavedReceipt = tuple[Settings, ReportBundle, Path, list[str]]


def test_dispositions_overlay_replay_without_rewriting_attachment(
    saved_receipt: SavedReceipt,
) -> None:
    settings, original, directory, calls = saved_receipt
    reader = CaseReads(settings)
    finding = original.findings[0]
    reader.update_disposition(
        RUN,
        FINDING,
        DispositionUpdate(
            snapshot_id=finding.snapshot_id,
            expected_version=0,
            previous_disposition="open",
            disposition="dismissed",
            reason="Reviewer disposition is separate",
            actor="Reviewer",
        ),
    )
    assert main(["replay", RUN, "--finding", FINDING]) == 0
    paths = [*directory.glob("report.*"), *(directory / "receipt-replay").iterdir()]
    original_bytes = {str(p): p.read_bytes() for p in paths}
    detail = reader.case(RUN, FINDING)
    assert detail.finding.disposition.value == "dismissed"
    assert detail.finding.runtime_verification.value == "reproduced"
    assert (
        detail.suggested_change is not None
        and detail.suggested_change.status.value == "replayed_fixed"
    )
    assert [p.outcome.value for p in detail.probe_runs] == ["reproduced", "fixed"]
    assert reader.export(RUN, "json")
    reader.update_disposition(
        RUN,
        FINDING,
        DispositionUpdate(
            snapshot_id=finding.snapshot_id,
            expected_version=1,
            previous_disposition="dismissed",
            disposition="open",
            reason="Revisit later",
            actor="Reviewer",
        ),
    )
    assert main(["replay", RUN, "--finding", FINDING]) == 0
    assert calls == ["vulnerable", "receipt_fixed"]
    assert {str(p): p.read_bytes() for p in paths} == original_bytes
    assert reader.case(RUN, FINDING).finding.disposition.value == "open"


@pytest.fixture
def saved_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SavedReceipt:
    settings = Settings(data_dir=tmp_path / "data")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    pin = json.loads(lab.PIN.read_bytes())
    files = {name: (lab.LAB / "api" / name).read_bytes() for name in pin["files"]}
    project = tmp_path / "source"
    for name, data in {
        **{"api/" + k: v for k, v in files.items()},
        "web/unchanged.ts": b"export const x = 1;\n",
    }.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    snapshot = take_snapshot(project, store)
    data = files[lab.RECEIPT_PATH]
    first = data[: data.index(lab.RECEIPT_BEFORE.encode())].count(b"\n") + 1
    last = first + len(lab.RECEIPT_BEFORE.splitlines()) - 1
    finding = Finding(
        id=FINDING,
        display_id="F-02",
        run_id=RUN,
        snapshot_id=snapshot.id,
        family="authorization",
        cwe=[639],
        title="Receipt fixture",
        lede="Software fixture",
        conclusion="supported",
        severity="unknown",
        severity_rationale="Fixture only",
        strength="partial",
        gaps=["Software fixture, not model acceptance"],
        exhibits=[
            Exhibit(
                tag="E01",
                role="evidence",
                gloss="Receipt lookup",
                span=SourceSpan(
                    snapshot_id=snapshot.id,
                    path=report_replay.PATH,
                    start_line=first,
                    end_line=last,
                    content_sha256=span_sha256(data, first, last),
                ),
            )
        ],
    )
    run = ReviewRun(
        id=RUN,
        snapshot_id=snapshot.id,
        run_type="saved",
        lifecycle="completed",
        created_at=snapshot.created_at,
        started_at=snapshot.created_at,
        finished_at=snapshot.created_at,
        finding_ids=[FINDING],
        coverage=Coverage(total=1, completed=1),
    )
    bundle = ReportBundle(
        run=run, snapshot=snapshot, findings=[finding], limitations=["Fixture only"]
    )
    directory = settings.data_dir / "reviews" / RUN
    directory.mkdir(parents=True)
    for suffix, format in report_replay.FORMATS:
        (directory / ("report." + suffix)).write_text(
            render(bundle, store, format), encoding="utf-8", newline="\n"
        )
    calls: list[str] = []

    def pinned(*, variant: str = "vulnerable") -> tuple[dict[str, bytes], str]:
        result = dict(files)
        if variant == "receipt_fixed":
            result[lab.RECEIPT_PATH] = data.replace(
                lab.RECEIPT_BEFORE.encode(), lab.RECEIPT_AFTER.encode()
            )
        return result, hashlib.sha256(lab.PIN.read_bytes()).hexdigest()

    def probe(
        spec: ProbeSpec,
        settings: Settings,
        files: dict[str, bytes],
        manifest: str,
        snapshot_id: str,
        variant: str,
    ) -> ProbeRun:
        calls.append(variant)
        role = SnapshotRole.PATCHED if variant == "receipt_fixed" else SnapshotRole.VULNERABLE
        steps = [
            ProbeStep(
                role=request.role,
                principal=request.principal,
                method=request.method,
                path=request.path.replace("{order_id}", "1"),
                expected_if_safe=request.expected_if_safe,
                status=404
                if role is SnapshotRole.PATCHED and request.role.value == "attack"
                else 200,
                marker_present=not (
                    role is SnapshotRole.PATCHED and request.role.value == "attack"
                ),
            )
            for request in spec.requests
        ]
        return ProbeRun(
            id="probe:" + variant,
            finding_id=spec.finding_id,
            runner="bundled_lab",
            runner_manifest_sha256=manifest,
            snapshot_id=snapshot_id,
            snapshot_role=role,
            steps=steps,
            outcome=derive_outcome(role, steps),
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )

    monkeypatch.setattr(lab, "verified_files", pinned)
    monkeypatch.setattr(lab, "_probe", probe)
    monkeypatch.setattr(report_replay, "machine_state", lambda: {"software_fixture": True})
    monkeypatch.setenv("PLUMB_DATA_DIR", str(settings.data_dir))
    return settings, bundle, directory, calls


def test_public_command_preserves_original_and_serves_matching_proof(
    saved_receipt: SavedReceipt,
) -> None:
    settings, original, directory, calls = saved_receipt
    originals = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert main(["replay", RUN, "--finding", "F-02"]) == 0
    assert calls == ["vulnerable", "receipt_fixed"]
    loaded, path = load(settings, RUN)
    assert path == directory / "receipt-replay" / "report.html"
    assert loaded.run == original.run and loaded.snapshot == original.snapshot
    finding = loaded.findings[0]
    assert finding.model_dump(
        exclude={"probe_run_ids", "suggested_change_id", "runtime_verification"}
    ) == original.findings[0].model_dump(
        exclude={"probe_run_ids", "suggested_change_id", "runtime_verification"}
    )
    assert loaded.suggested_changes[0].status.value == "replayed_fixed"
    assert [p.outcome.value for p in loaded.probe_runs] == ["reproduced", "fixed"]
    store = SnapshotStore(settings.cache_dir / "snapshots")
    after = store.load(loaded.probe_runs[1].snapshot_id)
    assert {f.path for f in after.files} == {f.path for f in original.snapshot.files}
    assert [
        a.path for a, b in zip(after.files, original.snapshot.files, strict=True) if a != b
    ] == [report_replay.PATH]
    app = create_app(settings, port=PORT)
    endpoint = f"/api/runs/{RUN}/findings/{FINDING}"
    assert visitor(app).get(endpoint).status_code == 401
    client = signed_in(app)
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json()["suggested_change"]["replay_probe_run_ids"] == ["probe:receipt_fixed"]
    assert client.get(endpoint + "/exhibits/E01").status_code == 200
    assert main(["replay", RUN, "--finding", FINDING]) == 0
    assert calls == ["vulnerable", "receipt_fixed"]  # idempotent; no second execution
    assert originals == {name: (directory / name).read_bytes() for name in originals}


@pytest.mark.parametrize(
    "mutation",
    [
        "original_snapshot",
        "patched_snapshot",
        "finding",
        "missing_after",
        "missing_control",
        "runner",
        "diff",
        "path",
        "outcome",
        "html",
        "original_report",
    ],
)
def test_modified_or_missing_proof_is_refused(saved_receipt: SavedReceipt, mutation: str) -> None:
    settings, _, directory, _ = saved_receipt
    assert report_replay.attach(settings, RUN, FINDING) == 0
    root = directory / "receipt-replay"
    path = root / "attachment.json"
    data = json.loads(path.read_bytes())
    if mutation == "original_snapshot":
        data["before"]["snapshot_id"] = "f" * 64
    elif mutation == "patched_snapshot":
        data["after"]["snapshot_id"] = data["before"]["snapshot_id"]
    elif mutation == "finding":
        data["after"]["finding_id"] = "finding:other"
    elif mutation == "missing_after":
        del data["after"]
    elif mutation == "missing_control":
        data["after"]["steps"].pop()
        data["after"]["outcome"] = "inconclusive"
    elif mutation == "runner":
        data["after"]["runner_manifest_sha256"] = "f" * 64
    elif mutation == "diff":
        data["change"]["diff"] += "\n# unrelated patch"
    elif mutation == "path":
        data["after"]["steps"][1]["path"] = "/orders/1/invoice"
    elif mutation == "outcome":
        data["after"]["steps"][1].update(status=500, marker_present=False)
    elif mutation == "html":
        (root / "report.html").write_text("untrusted markup", encoding="utf-8")
    else:
        base = directory / "report.json"
        base.write_bytes(base.read_bytes() + b"\n")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        load(settings, RUN)


@pytest.mark.parametrize("mutation", ["source", "finding", "citation", "note", "unfinished"])
def test_mismatch_refuses_before_any_execution(saved_receipt: SavedReceipt, mutation: str) -> None:
    settings, bundle, directory, calls = saved_receipt
    store = SnapshotStore(settings.cache_dir / "snapshots")
    key = FINDING
    if mutation == "source":
        entry = next(f for f in bundle.snapshot.files if f.path == report_replay.PATH)
        store.blobs._path(entry.sha256).write_bytes(b"wrong source")
    elif mutation == "finding":
        key = "finding:other"
    else:
        data = bundle.model_dump(mode="json")
        if mutation == "unfinished":
            data["run"].update(lifecycle="paused", stage="investigating", finished_at=None)
        elif mutation == "note":
            data["findings"][0]["exhibits"][0]["role"] = "developer_note"
        else:
            data["findings"][0]["exhibits"][0]["span"]["start_line"] = 1
        # Exercise receipt admission itself, independently of the existing HTML guard.
        altered = ReportBundle.model_validate(data)
        with pytest.raises(ValueError):
            report_replay.source(altered, store, FINDING)
        (directory / "report.json").write_text(json.dumps(data), encoding="utf-8")
    originals = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert report_replay.attach(settings, RUN, key) == 1
    assert calls == [] and not (directory / "receipt-replay").exists()
    assert originals == {name: (directory / name).read_bytes() for name in originals}


def test_failed_patch_retains_baseline_record_without_publishing(
    saved_receipt: SavedReceipt, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _, directory, calls = saved_receipt
    previous = lab._probe

    def fail(
        spec: ProbeSpec,
        settings: Settings,
        files: dict[str, bytes],
        manifest: str,
        snapshot_id: str,
        variant: lab.Variant,
    ) -> ProbeRun:
        if variant == "receipt_fixed":
            raise OSError("Fixture: patched runner unavailable")
        return previous(spec, settings, files, manifest, snapshot_id, variant)

    monkeypatch.setattr(lab, "_probe", fail)
    assert report_replay.attach(settings, RUN, FINDING) == 1
    assert calls == ["vulnerable"] and not (directory / "receipt-replay").exists()
    manifest = next((settings.data_dir / "probes").glob("*/manifest.json"))
    record = json.loads(manifest.read_bytes())
    assert record["before"]["outcome"] == "reproduced" and "error" in record
    assert "after" not in record
    assert load(settings, RUN)[0].suggested_changes == []


def test_record_failure_is_actionable_without_false_success(
    saved_receipt: SavedReceipt, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, _, _, _ = saved_receipt
    original = Path.mkdir

    def denied(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path.name.startswith("report-replay-"):
            raise PermissionError("Private fixture path")
        original(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", denied)
    assert report_replay.attach(settings, RUN, FINDING) == 1
    output = capsys.readouterr().out
    assert "command incomplete" in output and "replayed_fixed" not in output
    assert "Private fixture" not in output
    assert load(settings, RUN)[0].suggested_changes[0].status.value == "replayed_fixed"
