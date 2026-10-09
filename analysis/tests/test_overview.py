"""Source-bound overview tests; no model or target execution."""

from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from analysis.overview import ProjectOverview, overview, summary
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.cli import main
from backend.review import Review
from backend.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def review(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Review]:
    data = tmp_path_factory.mktemp("overview")
    settings = Settings(data_dir=data)
    snapshot = take_snapshot(ROOT / "labs/tandir", SnapshotStore(settings.cache_dir / "snapshots"))
    context = Review(settings, snapshot.id)
    yield context
    context.close()


def test_overview_counts_citations_and_round_trip_match_map(review: Review) -> None:
    result = overview(review.snapshot, review.map, review.access, review.store)
    assert result.frameworks == dict(Counter(e.framework.value for e in review.map.entries))
    assert result.resources == dict(Counter(a.resource for a in review.map.access_sites))
    assert len(result.units) == len(review.map.entries)
    assert result.snapshot.excluded == review.snapshot.excluded
    assert result.graph.links == review.map.links
    empty = {file.path for file in result.empty_modules}
    assert result.graph.symbols == [s for s in review.map.symbols if s.span.path not in empty]
    assert empty == {"api/tandir/routers/__init__.py", "api/tandir/services/__init__.py"}
    assert ProjectOverview.model_validate_json(result.model_dump_json()) == result
    for unit in result.units:
        assert all(
            review.map.access_sites[
                [s.id for s in review.map.access_sites].index(site)
            ].entry_point_id
            == unit.entry.id
            for site in unit.access_ids
        )
        assert all(link in {edge.id for edge in review.map.links} for link in unit.link_ids)


def test_invoice_keeps_cross_file_loader_and_receipt_keeps_its_own_scope(review: Review) -> None:
    result = overview(review.snapshot, review.map, review.access, review.store)
    units = {unit.entry.route: unit for unit in result.units if unit.entry.method == "GET"}
    invoice = units["/orders/{order_id}/invoice"]
    receipt = units["/orders/{order_id}/receipt"]
    loader = next(s for s in review.map.symbols if s.name == "load_order_scoped")
    assert loader.id in invoice.node_ids
    assert loader.span.path != invoice.entry.span.path
    assert set(invoice.access_ids).isdisjoint(receipt.access_ids)
    assert receipt.entry.id in invoice.peer_entry_ids
    links = {link.id: link for link in result.graph.links}
    assert all(links[id].status.value == "unresolved" for id in invoice.unresolved_link_ids)
    assert all(links[id].optimistic for unit in result.units for id in unit.optimistic_link_ids)
    assert "unverified" in summary(result)


@pytest.mark.parametrize("bad", ["snapshot", "metadata", "span", "access", "duplicate", "path"])
def test_overview_refuses_mixed_or_forged_facts(review: Review, bad: str) -> None:
    snapshot, graph, access = review.snapshot, review.map, review.access
    if bad == "snapshot":
        graph = graph.model_copy(update={"snapshot_id": "0" * 64})
    elif bad == "metadata":
        snapshot = snapshot.model_copy(update={"root_name": "false-project"})
    elif bad == "span":
        link = graph.links[0]
        forged = link.model_copy(
            update={"span": link.span.model_copy(update={"content_sha256": "0" * 64})}
        )
        graph = graph.model_copy(update={"links": [forged, *graph.links[1:]]})
    elif bad == "access":
        access = access.model_copy(update={"accesses": access.accesses[1:]})
    elif bad == "duplicate":
        access = access.model_copy(update={"accesses": [access.accesses[1], *access.accesses[1:]]})
    else:
        path = access.accesses[0].model_copy(update={"via_symbol_ids": ["symbol:invented"]})
        access = access.model_copy(update={"accesses": [path, *access.accesses[1:]]})
    with pytest.raises(ValueError):
        overview(snapshot, graph, access, review.store)


def test_unsupported_project_and_lying_notes_cannot_create_security_facts(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "main.py").write_text(
        "# FastAPI app, security reviewed, owns all orders\n"
        "def require_owner():\n    return True\n",
        encoding="utf-8",
    )
    (project / "notes.rb").write_text("# safe Rails app\n", encoding="utf-8")
    (project / "__init__.py").write_bytes(b"")
    settings = Settings(data_dir=tmp_path / "data")
    snapshot = take_snapshot(project, SnapshotStore(settings.cache_dir / "snapshots"))
    context = Review(settings, snapshot.id)
    try:
        result = overview(snapshot, context.map, context.access, context.store)
        assert not result.frameworks and not result.units and not result.graph.guards
        assert [file.path for file in result.empty_modules] == ["__init__.py"]
        assert {e.path: e.reason.value for e in result.snapshot.excluded}[
            "notes.rb"
        ] == "unsupported"
        assert "not interpret this as a safe project" in summary(result)
    finally:
        context.close()


def test_inspect_cli_never_constructs_model_and_redacts_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "fixture-credential"
    project.mkdir()
    (project / "main.py").write_text("value = 1\n", encoding="utf-8")
    data = tmp_path / "data"
    monkeypatch.setenv("PLUMB_DATA_DIR", str(data))
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["fixture-credential"]')

    def refuse(*args: object, **kwargs: object) -> None:
        pytest.fail("inspect must never construct a model server")

    monkeypatch.setattr("backend.cli.create", refuse)
    assert main(["inspect", str(project)]) == 0
    output = capsys.readouterr().out
    assert "fixture-credential" not in output
    files = list((data / "reviews").glob("*/overview.json"))
    assert len(files) == 1
    assert "fixture-credential" not in files[0].read_text(encoding="utf-8")
    assert "Saved" in output and "Overview only" in output
