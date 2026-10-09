"""Pinned replay boundaries and oracle controls; fixtures are not runtime evidence."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.tests.test_validator import Lab, reproduced
from backend.contracts.verification import (
    Access,
    ChangeStatus,
    ProbeRun,
    ProbeStep,
    RunnerKind,
    SnapshotRole,
    StepRole,
    derive_outcome,
)
from backend.settings import Settings
from verification import lab, replay


def observation(*, patched: bool = False, attack: int = 200, control: int = 200) -> ProbeRun:
    role = SnapshotRole.PATCHED if patched else SnapshotRole.VULNERABLE
    steps = [
        ProbeStep(
            role=kind,
            principal=user,
            method="GET",
            path="/orders/1/receipt",
            expected_if_safe=expected,
            status=status,
            marker_present=status == 200,
        )
        for kind, user, expected, status in (
            (StepRole.ATTACK, "bob", Access.DENIED, attack),
            (StepRole.CONTROL, "alice", Access.ALLOWED, control),
        )
    ]
    return ProbeRun(
        id="probe-run:after" if patched else "probe-run:before",
        finding_id="finding:lab-receipt",
        runner=RunnerKind.BUNDLED_LAB,
        runner_manifest_sha256="3" * 64,
        snapshot_id=("2" if patched else "1") * 64,
        snapshot_role=role,
        steps=steps,
        outcome=derive_outcome(role, steps),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )


def test_receipt_patch_changes_only_its_reviewed_source_and_keeps_original_bytes() -> None:
    before, manifest = lab.verified_files()
    after, patched_manifest = lab.verified_files(variant="receipt_fixed")
    assert manifest == patched_manifest and before.keys() == after.keys()
    assert {name for name in before if before[name] != after[name]} == {lab.RECEIPT_PATH}
    assert lab.RECEIPT_BEFORE.encode() in before[lab.RECEIPT_PATH]
    assert lab.RECEIPT_AFTER.encode() in after[lab.RECEIPT_PATH]
    assert (lab.LAB / "api" / lab.RECEIPT_PATH).read_bytes() == before[lab.RECEIPT_PATH]


def test_replay_evidence_links_pass_the_existing_report_validator(tmp_path: Path) -> None:
    validator_lab = Lab(tmp_path)
    before = validator_lab.run()
    after = validator_lab.run(
        "probe:2",
        attack=(404, False),
        role="patched",
        outcome="fixed",
        snapshot_id="2" * 64,
    )
    proposed = validator_lab.change(status="proposed", replay_probe_run_ids=[])
    result = replay.conclude(proposed, before, after)
    finding = reproduced(validator_lab, suggested_change_id=result.change.id)
    assert (
        validator_lab.validator.finding(
            finding,
            probe_runs=[before, after],
            change=result.change,
        )
        == []
    )
    # Regression for the initial integration error: a baseline is not a patched replay.
    mixed = result.change.model_copy(update={"replay_probe_run_ids": [before.id, after.id]})
    assert validator_lab.validator.finding(finding, probe_runs=[before, after], change=mixed)


@pytest.mark.parametrize("mutation", ["diff", "path", "finding", "status", "prior_ids", "invoice"])
def test_unreviewed_change_or_probe_refuses_before_any_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    spec = lab.receipt_spec("PLUMB_TEST_123", invoice=mutation == "invoice")
    change = replay.receipt_change()
    updates = {
        "diff": {"diff": change.diff + "\n# unreviewed"},
        "path": {"files": ["../outside.py"]},
        "finding": {"finding_id": "finding:other"},
        "status": {"status": ChangeStatus.REPLAYED_FIXED},
        "prior_ids": {"replay_probe_run_ids": ["probe-run:old"]},
        "invoice": {},
    }
    change = change.model_copy(update=updates[mutation])
    monkeypatch.setattr(
        lab, "run_release", lambda *a, **kw: pytest.fail("Unreviewed code executed")
    )
    with pytest.raises(lab.LabUnavailable, match="reviewed proposed"):
        replay.run(spec, change, Settings(data_dir=tmp_path / "absent"))
    assert not (tmp_path / "absent").exists()


def test_patch_hash_mutation_refuses_before_source_is_written(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrong = tmp_path / "receipt.patch"
    wrong.write_bytes(lab.PATCH.read_bytes() + b"\n")
    monkeypatch.setattr(lab, "PATCH", wrong)
    with pytest.raises(lab.LabUnavailable, match="patch differs"):
        lab.verified_files(variant="receipt_fixed")


def test_patched_output_hash_mutation_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pin = json.loads(lab.PIN.read_text(encoding="utf-8"))
    pin["variants"]["receipt_fixed"]["files"][lab.RECEIPT_PATH] = "0" * 64
    wrong = tmp_path / "pin.json"
    wrong.write_text(json.dumps(pin), encoding="utf-8")
    monkeypatch.setattr(lab, "PIN", wrong)
    with pytest.raises(lab.LabUnavailable, match="Patched receipt differs"):
        lab.verified_files(variant="receipt_fixed")


@pytest.mark.parametrize(
    "variant,alter", [("receipt_fixed", True), ("vulnerable", False), ("unknown", False)]
)
def test_worker_rechecks_release_variant_before_imports(
    tmp_path: Path,
    variant: str,
    alter: bool,
) -> None:
    files, _ = lab.verified_files(variant="receipt_fixed")
    root = tmp_path / "api"
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    if alter:
        target = root / lab.RECEIPT_PATH
        target.write_bytes(target.read_bytes() + b"\nraise RuntimeError('unreviewed')\n")
    python = (
        lab.LAB / "api/.venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    result = subprocess.run(  # noqa: S603 - trusted worker refuses mismatched release before imports
        [str(python), "-I", str(lab.WORKER), str(root), str(tmp_path / "data"), variant],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert (
        "source copy hash mismatch" in result.stderr or "unknown bundled release" in result.stderr
    )
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "before_attack,before_control,after_attack,after_control,expected",
    [
        (200, 200, 404, 200, ChangeStatus.REPLAYED_FIXED),
        (200, 200, 200, 200, ChangeStatus.REPLAYED_NOT_FIXED),
        (200, 200, 500, 200, ChangeStatus.REPLAY_FAILED),
        (200, 200, 404, 500, ChangeStatus.REPLAY_FAILED),
        (200, 200, 404, 403, ChangeStatus.REPLAY_FAILED),
        (404, 200, 404, 200, ChangeStatus.REPLAY_FAILED),
        (200, 500, 404, 200, ChangeStatus.REPLAY_FAILED),
    ],
)
def test_change_status_requires_reproduction_then_denial_and_preserved_owner(
    before_attack: int,
    before_control: int,
    after_attack: int,
    after_control: int,
    expected: ChangeStatus,
) -> None:
    result = replay.conclude(
        replay.receipt_change(),
        observation(attack=before_attack, control=before_control),
        observation(patched=True, attack=after_attack, control=after_control),
    )
    assert result.change.status is expected
    assert result.change.replay_probe_run_ids == ["probe-run:after"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("finding_id", "finding:other"),
        ("id", "probe-run:before"),
        ("snapshot_id", "1" * 64),
        ("snapshot_role", SnapshotRole.VULNERABLE),
        ("runner_manifest_sha256", "4" * 64),
        ("runner", RunnerKind.DOCKER),
    ],
)
def test_mixed_replay_evidence_refuses(field: str, value: object) -> None:
    after = observation(patched=True, attack=404).model_copy(update={field: value})
    with pytest.raises(lab.LabUnavailable, match="identity"):
        replay.conclude(replay.receipt_change(), observation(), after)


@pytest.mark.parametrize("reproduced", [False, True])
def test_release_runs_are_sequential_and_unobserved_baseline_stops_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reproduced: bool,
) -> None:
    seen = []

    def run_release(spec: object, settings: object, *, variant: str) -> ProbeRun:
        seen.append(variant)
        return observation(
            patched=variant == "receipt_fixed",
            attack=200 if variant == "vulnerable" and reproduced else 404,
        )

    monkeypatch.setattr(lab, "run_release", run_release)
    result = replay.run(
        lab.receipt_spec("PLUMB_TEST_123"), replay.receipt_change(), Settings(data_dir=tmp_path)
    )
    assert seen == (["vulnerable", "receipt_fixed"] if reproduced else ["vulnerable"])
    assert result.change.status is (
        ChangeStatus.REPLAYED_FIXED if reproduced else ChangeStatus.PROPOSED
    )


def test_failed_patched_start_retains_actual_baseline_without_claiming_fix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = observation()

    def run_release(spec: object, settings: object, *, variant: str) -> ProbeRun:
        if variant == "receipt_fixed":
            raise lab.LabUnavailable("private-input failure")
        return before

    monkeypatch.setattr(lab, "run_release", run_release)
    result = replay.run(
        lab.receipt_spec("PLUMB_TEST_123"), replay.receipt_change(), Settings(data_dir=tmp_path)
    )
    assert result.before == before and result.after is None
    assert result.change.status is ChangeStatus.PROPOSED
    assert result.error and "private-input" not in result.error


def test_release_snapshots_keep_same_paths_and_exact_before_after_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from analysis.snapshot import SnapshotStore

    settings = Settings(data_dir=tmp_path)
    snapshots = []

    def probe(
        spec: object,
        settings: Settings,
        files: object,
        manifest: str,
        snapshot_id: str,
        variant: str,
    ) -> ProbeRun:
        store = SnapshotStore(settings.cache_dir / "replay-snapshots")
        snap = store.load(snapshot_id)
        snapshots.append((snap, store.read(snap, "api/" + lab.RECEIPT_PATH)))
        return observation(
            patched=variant == "receipt_fixed", attack=200 if variant == "vulnerable" else 404
        )

    monkeypatch.setattr(lab, "_probe", probe)
    for variant in ("vulnerable", "receipt_fixed", "vulnerable", "receipt_fixed"):
        lab.run_release(lab.receipt_spec("PLUMB_TEST_123"), settings, variant=variant)
    assert {f.path for f in snapshots[0][0].files} == {f.path for f in snapshots[1][0].files}
    assert snapshots[0][0].id != snapshots[1][0].id
    assert snapshots[0][0] == snapshots[2][0]
    assert snapshots[1][0] == snapshots[3][0]
    assert lab.RECEIPT_BEFORE.encode() in snapshots[0][1]
    assert lab.RECEIPT_AFTER.encode() in snapshots[1][1]
    assert not list(settings.cache_dir.glob("lab-release-*"))


@pytest.mark.parametrize("success", [False, True])
def test_replay_cli_saves_both_observations_and_returns_truthful_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    success: bool,
) -> None:
    from verification import __main__ as cli

    result = replay.conclude(
        replay.receipt_change(),
        observation(),
        observation(patched=True, attack=404 if success else 500),
    )
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "machine_state", lambda: {"fixture": True})
    monkeypatch.setattr(replay, "run", lambda *a, **kw: result)
    assert cli.main(["--replay"]) == (0 if success else 1)
    saved = list((tmp_path / "probes").glob("*/manifest.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["replay"]["before"] == result.before.model_dump(mode="json")
    assert result.after is not None
    assert record["replay"]["after"] == result.after.model_dump(mode="json")
    assert record["replay"]["change"]["status"] == result.change.status.value
    assert result.change.status.value in capsys.readouterr().out
