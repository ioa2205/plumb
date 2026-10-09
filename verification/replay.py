"""Replay only the release-pinned receipt change, never arbitrary target diffs."""

from dataclasses import dataclass

import httpx

from backend.contracts.verification import (
    ChangeStatus,
    ProbeOutcome,
    ProbeRun,
    ProbeSpec,
    SnapshotRole,
    SuggestedChange,
)
from backend.settings import Settings
from verification import lab


@dataclass(frozen=True)
class ReplayResult:
    change: SuggestedChange
    before: ProbeRun
    after: ProbeRun | None
    error: str | None = None


def receipt_change(finding_id: str = "finding:lab-receipt") -> SuggestedChange:
    return SuggestedChange(
        id="change:lab-receipt",
        finding_id=finding_id,
        intent="Scope the receipt loader to the signed-in order owner.",
        diff=lab.PATCH.read_text(encoding="utf-8"),
        files=["api/" + lab.RECEIPT_PATH],
    )


def admit_change(spec: ProbeSpec, change: SuggestedChange) -> None:
    lab.admit(spec)
    # Verification includes the patch hash and output bytes before any child is started.
    lab.verified_files(variant="receipt_fixed")
    if (
        spec != lab.receipt_spec(spec.marker, finding_id=spec.finding_id)
        or change.finding_id != spec.finding_id
        or change.diff != receipt_change(spec.finding_id).diff
        or change.files != ["api/" + lab.RECEIPT_PATH]
        or change.status is not ChangeStatus.PROPOSED
        or change.replay_probe_run_ids
    ):
        raise lab.LabUnavailable("Replay admits only the reviewed proposed receipt change")


def conclude(change: SuggestedChange, before: ProbeRun, after: ProbeRun | None) -> ReplayResult:
    if (
        before.finding_id != change.finding_id
        or before.snapshot_role is not SnapshotRole.VULNERABLE
    ):
        raise lab.LabUnavailable("Replay baseline identity is inconsistent")
    # The contract's replay IDs refer only to patched runs; baseline is kept separately.
    status = ChangeStatus.PROPOSED if after is None else ChangeStatus.REPLAY_FAILED
    ids = []
    if after is not None:
        if (
            after.finding_id != change.finding_id
            or after.snapshot_role is not SnapshotRole.PATCHED
            or after.id == before.id
            or after.snapshot_id == before.snapshot_id
            or after.runner is not before.runner
            or after.runner_manifest_sha256 != before.runner_manifest_sha256
        ):
            raise lab.LabUnavailable("Replay patched identity is inconsistent")
        ids.append(after.id)
        if before.outcome is ProbeOutcome.REPRODUCED:
            if after.outcome is ProbeOutcome.FIXED:
                status = ChangeStatus.REPLAYED_FIXED
            elif after.outcome is ProbeOutcome.NOT_FIXED:
                status = ChangeStatus.REPLAYED_NOT_FIXED
    updated = SuggestedChange.model_validate(
        {
            **change.model_dump(mode="json"),
            "status": status,
            "replay_probe_run_ids": ids,
        }
    )
    return ReplayResult(updated, before, after)


def run(spec: ProbeSpec, change: SuggestedChange, settings: Settings | None = None) -> ReplayResult:
    settings = settings or Settings()
    admit_change(spec, change)
    before = lab.run_release(spec, settings, variant="vulnerable")
    if before.outcome is not ProbeOutcome.REPRODUCED:
        result = conclude(change, before, None)
        return ReplayResult(
            result.change, before, None, "Baseline did not reproduce; replay not attempted"
        )
    try:
        after = lab.run_release(spec, settings, variant="receipt_fixed")
    except (OSError, ValueError, httpx.HTTPError):
        result = conclude(change, before, None)
        return ReplayResult(result.change, before, None, "Patched release verification unavailable")
    return conclude(change, before, after)
