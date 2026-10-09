"""Capability observations are source counts, never fixture/model accuracy."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis.index import Index
from analysis.snapshot import SnapshotStore, take_snapshot
from backend import capabilities
from backend.contracts.application_map import ApplicationMap
from backend.contracts.capabilities import CapabilityTable

ROOT = Path(__file__).resolve().parents[2]


def test_registry_retains_historical_evidence_without_promoting_assets_or_families() -> None:
    result = capabilities.table()
    assert len(result.rows) == 10
    assert all(
        not r.investigated and not r.runtime_testable and r.units is None for r in result.rows
    )
    assert all(r.parsed in {"unverified", "not_applicable"} for r in result.rows)
    for evidence in result.evidence:
        assert hashlib.sha256((ROOT / evidence.record).read_bytes()).hexdigest() == evidence.sha256
        assert not evidence.current_engine_acceptance
    assert "unrun" in result.quality_note and "bundled" in result.runtime_note


def test_observed_parsing_and_indexing_keep_failure_denominators_and_snapshot(
    tmp_path: Path,
) -> None:
    project = tmp_path / "source"
    project.mkdir()
    (project / "good.py").write_bytes(b"def f():\n    return 1\n")
    (project / "broken.py").write_bytes(b"def f(:\n")
    (project / "__init__.py").write_bytes(b"")
    (project / "unknown.rs").write_bytes(b"fn main() {}\n")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, tmp_path / "index.sqlite")
    try:
        symbols = [index.to_contract(s, snapshot.id) for s in index.symbols()]
    finally:
        index.close()
    graph = ApplicationMap(
        snapshot_id=snapshot.id,
        entries=[],
        symbols=symbols,
        guards=[],
        access_sites=[],
        unknown_targets=[],
        links=[],
    )
    result = capabilities.table(snapshot, graph, store)
    python = next(r for r in result.rows if r.name == "python")
    assert (python.units, python.parsed_units, python.indexed_units) == (3, 2, 1)
    assert python.parsed == python.indexed == "partial"
    assert next(r for r in result.rows if r.name == "fastapi").parsed == "unverified"
    assert result.snapshot_id == snapshot.id and snapshot.excluded[0].reason.value == "unsupported"
    with pytest.raises(ValueError, match="one frozen"):
        capabilities.table(snapshot, graph.model_copy(update={"snapshot_id": "a" * 64}), store)
    span = symbols[0].span.model_copy(update={"content_sha256": "b" * 64})
    corrupt = graph.model_copy(update={"symbols": [symbols[0].model_copy(update={"span": span})]})
    with pytest.raises(ValueError, match="citation"):
        capabilities.table(snapshot, corrupt, store)


@pytest.mark.parametrize("promotion", ["investigated", "runtime_testable"])
def test_contract_refuses_unmeasured_promotions_and_inconsistent_counts(promotion: str) -> None:
    value = capabilities.table().model_dump(mode="json")
    value["rows"][0][promotion] = True
    with pytest.raises(ValidationError):
        CapabilityTable.model_validate(value)
    value = capabilities.table().model_dump(mode="json")
    value["rows"][0].update(
        units=2, parsed_units=1, indexed_units=1, parsed="observed", indexed="observed"
    )
    with pytest.raises(ValidationError):
        CapabilityTable.model_validate(value)


def test_registry_rejects_unrecorded_acceptance_and_oversized_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "pin.json"
    pin = json.loads(capabilities.PIN.read_bytes())
    pin["current_engine_acceptance"] = "passed"
    path.write_text(json.dumps(pin), encoding="utf-8")
    monkeypatch.setattr(capabilities, "PIN", path)
    with pytest.raises(ValueError, match="acceptance"):
        capabilities.table()
    path.write_bytes(b" " * 32769)
    with pytest.raises(ValueError, match="size budget"):
        capabilities.table()
