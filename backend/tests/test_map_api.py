import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from analysis.access import AccessMap
from analysis.application_map import assemble_map, build_map
from analysis.fastapi import FastAPIMap
from analysis.index import Index, index_path
from analysis.nextjs import ClientProps, NextJSMap
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.app import create_app
from backend.contracts.application_map import ApplicationMap
from backend.contracts.code import SourceSpan, SymbolKind
from backend.contracts.common import LinkStatus
from backend.map_store import MapStore, MapUnavailable
from backend.settings import Settings

from .support import ORIGIN, signed_in

TANDIR = Path(__file__).resolve().parents[2] / "labs" / "tandir"


@pytest.fixture(scope="module")
def tandir(tmp_path_factory: pytest.TempPathFactory) -> tuple[ApplicationMap, Settings]:
    settings = Settings(data_dir=tmp_path_factory.mktemp("map-api"))
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(TANDIR, store)
    index = Index.build(snapshot, store, index_path(settings.cache_dir, snapshot.id))
    try:
        result = build_map(snapshot, store, index, settings.cache_dir, use_ty=False)
    finally:
        index.close()
    MapStore(settings.cache_dir / "application_maps.sqlite").save(result)
    return result, settings


def test_api_returns_complete_tandir_map_with_unknown_links(
    tandir: tuple[ApplicationMap, Settings],
) -> None:
    expected, settings = tandir
    with signed_in(create_app(settings)) as client:
        response = client.get(f"/api/snapshots/{expected.snapshot_id}/map")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    actual = ApplicationMap.model_validate(response.json())
    assert actual == expected
    assert len(actual.entries) == 39
    # M3.10d added field-flow sites; transport must preserve the complete extracted map.
    assert len(actual.access_sites) == len(expected.access_sites) == 87
    unknown = {u.id for u in actual.unknown_targets}
    assert unknown
    assert all(
        link.status is LinkStatus.UNRESOLVED for link in actual.links if link.target in unknown
    )
    assert {link.status for link in actual.links} == set(LinkStatus)
    assert actual.limitations and actual.issues


def test_entry_guard_and_data_paths_retain_uncertainty(
    tandir: tuple[ApplicationMap, Settings],
) -> None:
    result, _ = tandir
    entry = next(e for e in result.entries if e.route == "/orders/{order_id}/invoice")
    sites = [
        s for s in result.access_sites if s.entry_point_id == entry.id and s.resource == "Order"
    ]
    assert len(sites) == 1
    links = [link for link in result.links if link.target == sites[0].id]
    assert any(link.source == entry.id and link.kind == "access" for link in links)
    assert any(link.kind == "may_check" and link.status is LinkStatus.UNRESOLVED for link in links)
    assert all(not g.confirmed for g in result.guards)
    assert all(not site.guard_ids for site in result.access_sites)
    assert any(link.kind == "client_props" for link in result.links)
    proxies = {g.id for g in result.guards if g.optimistic}
    assert proxies
    assert all(
        link.optimistic for link in result.links if link.source in proxies or link.target in proxies
    )


@pytest.mark.parametrize("change", ["snapshot", "endpoint", "duplicate", "unknown", "proxy"])
def test_invalid_graphs_are_rejected(tandir: tuple[ApplicationMap, Settings], change: str) -> None:
    result, _ = tandir
    data = result.model_dump(mode="json")
    if change == "snapshot":
        data["links"][0]["span"]["snapshot_id"] = "0" * 64
    elif change == "endpoint":
        data["links"][0]["target"] = "missing:1"
    elif change == "duplicate":
        data["symbols"].append(data["symbols"][0])
    elif change == "unknown":
        unknown = {u["id"] for u in data["unknown_targets"]}
        next(link for link in data["links"] if link["target"] in unknown)["status"] = "resolved"
    elif change == "proxy":
        next(link for link in data["links"] if link["kind"] == "proxy")["optimistic"] = False
    with pytest.raises(ValidationError):
        ApplicationMap.model_validate(data)


def test_assembly_refuses_mixed_snapshots_and_keeps_unplaced_props_visible(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("def handler() -> None:\n    return None\n", encoding="utf-8")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, tmp_path / "index.sqlite")
    try:
        fastapi = FastAPIMap(snapshot_id=snapshot.id, routes=[], routers=[], issues=[])
        access = AccessMap(snapshot_id=snapshot.id, accesses=[])
        handler = index.symbols(kind=SymbolKind.FUNCTION)[0]
        # Cites a file the index has no symbol for, so no node can be the link's source.
        outside = ClientProps(
            component_symbol_id=handler.id,
            props={"order": "order"},
            span=SourceSpan(
                snapshot_id=snapshot.id,
                path="web/page.tsx",
                start_line=3,
                end_line=3,
                content_sha256="0" * 64,
            ),
        )

        def nextjs(snapshot_id: str) -> NextJSMap:
            return NextJSMap(
                snapshot_id=snapshot_id,
                entries=[],
                components=[],
                client_props=[outside],
                data_modules=[],
                proxies=[],
                issues=[],
            )

        result = assemble_map(snapshot, index, fastapi, nextjs(snapshot.id), access, [])
        assert not result.links
        assert result.issues == [
            "web/page.tsx:3: client props are rendered outside any indexed symbol"
        ]
        with pytest.raises(ValueError, match="same snapshot"):
            assemble_map(snapshot, index, fastapi, nextjs("0" * 64), access, [])
    finally:
        index.close()


def test_missing_and_malformed_snapshot_ids(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    with signed_in(create_app(settings)) as client:
        assert client.get(f"/api/snapshots/{'0' * 64}/map").status_code == 404
        # A traversal never reaches the handler: no route matches the rewritten path.
        for key in ("../outside", "%2e%2e%2foutside"):
            assert client.get(f"/api/snapshots/{key}/map").status_code == 404
        for key in ("C:private", "abc", "A" * 64, "0" * 65):
            assert client.get(f"/api/snapshots/{key}/map").status_code == 422
        write = client.post(f"/api/snapshots/{'0' * 64}/map", headers={"Origin": ORIGIN})
        assert write.status_code == 405
    assert not (settings.cache_dir / "application_maps.sqlite").exists()


def test_reads_do_not_start_analysis(tandir: tuple[ApplicationMap, Settings]) -> None:
    result, settings = tandir
    with (
        patch("analysis.application_map.build_map", side_effect=AssertionError("analysis ran")),
        signed_in(create_app(settings)) as client,
    ):
        assert client.get(f"/api/snapshots/{result.snapshot_id}/map").status_code == 200


def test_corrupt_cache_returns_clean_error(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    settings.cache_dir.mkdir()
    path = settings.cache_dir / "application_maps.sqlite"
    path.write_bytes(b"not a database")
    with signed_in(create_app(settings)) as client:
        response = client.get(f"/api/snapshots/{'0' * 64}/map")
    assert response.status_code == 503
    assert str(tmp_path) not in response.text


def test_store_rejects_wrong_key_and_oversized_payload(tmp_path: Path) -> None:
    path = tmp_path / "map.sqlite"
    valid = ApplicationMap(
        snapshot_id="0" * 64,
        entries=[],
        symbols=[],
        guards=[],
        access_sites=[],
        unknown_targets=[],
        links=[],
    )
    store = MapStore(path)
    store.save(valid)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE maps SET snapshot_id=?", ("1" * 64,))
    with pytest.raises(MapUnavailable, match="snapshot does not match"):
        store.load("1" * 64)
    with patch("backend.map_store.MAX_MAP_BYTES", 2):
        with pytest.raises(MapUnavailable, match="read budget"):
            store.load("1" * 64)
        with pytest.raises(ValueError, match="storage budget"):
            store.save(valid)
    with pytest.raises(ValueError, match="invalid snapshot"):
        store.load("../outside")


def test_store_revalidates_models(tmp_path: Path, tandir: tuple[ApplicationMap, Settings]) -> None:
    original, _ = tandir
    invalid = original.model_copy(update={"snapshot_id": "0" * 64})
    with pytest.raises(ValidationError):
        MapStore(tmp_path / "map.sqlite").save(invalid)


def test_openapi_uses_generated_map_contract(tmp_path: Path) -> None:
    with signed_in(create_app(Settings(data_dir=tmp_path))) as client:
        schema = client.get("/openapi.json").json()
    route = schema["paths"]["/api/snapshots/{snapshot_id}/map"]["get"]
    response = route["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("/ApplicationMap")
    assert schema["components"]["schemas"]["LinkStatus"]["enum"] == [
        "resolved",
        "inferred",
        "unresolved",
    ]
