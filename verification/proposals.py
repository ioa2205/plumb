"""Admit a regression template only with an exact trusted fixture mapping.

This module creates data, never runs the adapter or returns a model-written request.
General runners and fixture mapping remain explicit M4 integration work.
"""

import hashlib
import json

from agent.questions import Allowed, Denied, ProbeParameters
from analysis.snapshot import SnapshotStore
from backend.contracts.code import ProjectSnapshot
from backend.contracts.common import Family
from backend.contracts.investigation import Finding
from backend.contracts.verification import ProbeSpec
from verification import lab


def regression(
    finding: Finding, intent: ProbeParameters, snapshot: ProjectSnapshot, store: SnapshotStore
) -> tuple[ProbeSpec | None, str | None, str]:
    missing = (
        "No supported probe adapter with explicit principal, credential and setup mapping "
        "exists for this frozen finding."
    )
    if finding.family is not Family.AUTHORIZATION or (
        intent.parameter != "order_id"
        or intent.denied is not Denied.OTHER_USER
        or intent.allowed is not Allowed.OWNER
    ):
        return None, None, missing
    raw = lab.PIN.read_bytes()
    pin = json.loads(raw)
    files = {f.path for f in snapshot.files}
    prefix = "api/"
    if not all(prefix + name in files for name in pin["files"]):
        return None, None, missing
    if any(
        hashlib.sha256(store.read(snapshot, prefix + name)).hexdigest() != digest
        for name, digest in pin["files"].items()
    ):
        return None, None, "Bundled fixture hashes differ; regression probe is unavailable."
    path = prefix + lab.RECEIPT_PATH
    source = store.read(snapshot, path)
    start = (
        source.index(lab.RECEIPT_BEFORE.encode())
        if source.count(lab.RECEIPT_BEFORE.encode()) == 1
        else -1
    )
    if start < 0:
        return None, None, missing
    first = source[:start].count(b"\n") + 1
    last = first + len(lab.RECEIPT_BEFORE.splitlines()) - 1
    if not any(
        e.span.path == path and e.span.start_line <= first and e.span.end_line >= last
        for e in finding.exhibits
    ):
        return None, None, "Finding does not cite the pinned receipt fixture; probe unavailable."
    marker = "PlumbRegression_" + hashlib.sha256(finding.id.encode()).hexdigest()[:16]
    spec = lab.receipt_spec(marker, finding_id=finding.id)
    lab.admit(spec)
    return (
        spec,
        hashlib.sha256(raw).hexdigest(),
        (
            "Pinned Tandir API receipt template: alice creates the marked order; bob is the "
            "other-customer attack and alice the owner control. Seeded disposable credentials "
            "are supplied only by the trusted runner. No probe was executed."
        ),
    )
