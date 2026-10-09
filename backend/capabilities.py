"""Finite capability accounting; never infer accuracy from assets or syntax support."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from analysis.snapshot import SnapshotStore
from analysis.syntax import extract, span_sha256
from backend.contracts.application_map import ApplicationMap
from backend.contracts.capabilities import (
    CapabilityEvidence,
    CapabilityRow,
    CapabilityTable,
    SourceLevel,
)
from backend.contracts.code import ProjectSnapshot
from backend.contracts.common import Family, Language

PIN = Path(__file__).with_name("capabilities.json")
RUNTIME_NOTE = (
    "General runtime-testable support is unavailable: no isolated backend has passed acceptance "
    "(ADR-0017). The separate hash-pinned bundled Tandir receipt/invoice exception has recorded "
    "runtime proof; it permits no arbitrary source or proposed diff execution."
)
QUALITY_NOTE = (
    "Investigated requires passing evaluation slices for this engine, model and framework. "
    "Current engine acceptance is unrun. Historical scoped successes and broader misses below "
    "are retained; software fixtures, installed assets and parsing do not prove model accuracy."
)


def _level(units: int | None, count: int | None) -> SourceLevel:
    return "unverified" if not units else "observed" if count == units else "partial"


def table(
    snapshot: ProjectSnapshot | None = None,
    graph: ApplicationMap | None = None,
    store: SnapshotStore | None = None,
) -> CapabilityTable:
    if PIN.stat().st_size > 32 * 1024:
        raise ValueError("Capability registry exceeds its size budget")
    raw = PIN.read_bytes()
    pin = json.loads(raw)
    if pin["version"] != 1 or pin["current_engine_acceptance"] != "unrun":
        raise ValueError("Capability registry requires actual current acceptance before promotion")
    evidence = [CapabilityEvidence.model_validate(e) for e in pin["evidence"]]
    rows = []
    parsed: dict[str, bool] = {}
    indexed: set[str] = set()
    if snapshot is not None:
        if graph is None or store is None or graph.snapshot_id != snapshot.id:
            raise ValueError("Capability observations require one frozen source/map")
        if store.load(snapshot.id) != snapshot:
            raise ValueError("Capability snapshot metadata changed")
        for file in snapshot.files:
            if file.language is not None:
                parsed[file.path] = not extract(
                    file.path, file.language, store.read(snapshot, file.path), set()
                ).has_errors
        for node in [*graph.symbols, *graph.entries]:
            span = node.span
            source = store.read(snapshot, span.path)
            if (
                node.snapshot_id != snapshot.id
                or span.snapshot_id != snapshot.id
                or span.end_line > max(1, len(source.splitlines()))
                or span.content_sha256 != span_sha256(source, span.start_line, span.end_line)
            ):
                raise ValueError("Capability map citation disagrees with frozen source")
        nonempty = {f.path for f in snapshot.files if f.size > 0}
        indexed = {s.span.path for s in graph.symbols if s.span.path in nonempty}
    categories: tuple[tuple[Literal["language", "framework"], list[str]], ...] = (
        ("language", [language.value for language in Language]),
        ("framework", ["fastapi", "nextjs"]),
    )
    for category, names in categories:
        for name in names:
            units = None
            parsed_units = indexed_units = None
            if snapshot is not None:
                paths = (
                    [f.path for f in snapshot.files if f.language and f.language.value == name]
                    if category == "language"
                    else [e.span.path for e in graph.entries if e.framework.value == name]
                    if graph
                    else []
                )
                units = len(paths)
                parsed_units = sum(parsed.get(p, False) for p in paths)
                indexed_units = sum(parsed.get(p, False) and p in indexed for p in paths)

            rows.append(
                CapabilityRow(
                    category=category,
                    name=name,
                    units=units,
                    parsed_units=parsed_units,
                    indexed_units=indexed_units,
                    parsed=_level(units, parsed_units),
                    indexed=_level(units, indexed_units),
                    workflow_implemented=category == "framework",
                    reason="Included source observations only. Extraction/resolution gaps remain; "
                    "no current model evaluation qualifies the framework or language "
                    "as Investigated.",
                )
            )
    rows.extend(
        CapabilityRow(
            category="family",
            name=family.value,
            parsed="not_applicable",
            indexed="not_applicable",
            workflow_implemented=True,
            reason="Bounded software workflow exists. "
            "Its current real-model development gate is open; "
            "historical receipt/invoice success does not qualify the full family.",
        )
        for family in Family
    )
    return CapabilityTable(
        registry_sha256=hashlib.sha256(raw).hexdigest(),
        snapshot_id=snapshot.id if snapshot else None,
        rows=rows,
        evidence=evidence,
        quality_note=QUALITY_NOTE,
        runtime_note=RUNTIME_NOTE,
    )
