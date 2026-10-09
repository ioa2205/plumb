import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from analysis.access import AccessMap, extract_accesses
from analysis.access_facts import sql_access
from analysis.fastapi import FastAPIMap, extract_fastapi
from analysis.index import Index, index_path
from analysis.nextjs import NextJSMap, extract_nextjs
from analysis.resolution import LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from backend.contracts.code import DataLayer, Operation
from backend.contracts.common import InputOrigin

TANDIR = Path(__file__).resolve().parents[2] / "labs" / "tandir"


@pytest.fixture(scope="module")
def tandir(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[AccessMap, FastAPIMap, NextJSMap, Index]]:
    cache = tmp_path_factory.mktemp("access-map")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(TANDIR, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    fastapi, nextjs = (
        extract_fastapi(snapshot, store, index),
        extract_nextjs(snapshot, store, index, cache),
    )
    try:
        yield (
            extract_accesses(snapshot, store, index, cache, fastapi=fastapi, nextjs=nextjs),
            fastapi,
            nextjs,
            index,
        )
    finally:
        index.close()


def test_eight_customer_order_access_paths(
    tandir: tuple[AccessMap, FastAPIMap, NextJSMap, Index],
) -> None:
    result, fastapi, _, index = tandir
    entries = {r.entry.id: r.entry for r in fastapi.routes}
    names = {r.id: r.qualified_name for r in index.symbols()}
    sites = [
        a
        for a in result.accesses
        if a.site.resource == "Order"
        and a.site.key_origin is InputOrigin.PATH
        and (entries[a.site.entry_point_id].route or "").startswith("/orders/")
    ]
    assert len(sites) == 8
    assert {
        (entries[a.site.entry_point_id].method, entries[a.site.entry_point_id].route) for a in sites
    } == {
        ("GET", "/orders/{order_id}"),
        ("GET", "/orders/{order_id}/receipt"),
        ("GET", "/orders/{order_id}/invoice"),
        ("POST", "/orders/{order_id}/cancel"),
        ("GET", "/orders/{order_id}/items"),
        ("GET", "/orders/{order_id}/tracking"),
        ("GET", "/orders/{order_id}/photos"),
        ("POST", "/orders/{order_id}/photos"),
    }
    invoice = next(
        a for a in sites if entries[a.site.entry_point_id].route == "/orders/{order_id}/invoice"
    )
    assert names[invoice.owner_symbol_id] == "tandir.services.orders.load_order_scoped"
    assert [names[i] for i in invoice.via_symbol_ids] == [
        "tandir.routers.orders.get_invoice",
        "tandir.services.orders.load_order_scoped",
    ]
    items = next(
        a for a in sites if entries[a.site.entry_point_id].route == "/orders/{order_id}/items"
    )
    assert names[items.owner_symbol_id] == "tandir.services.orders.owned_order"
    assert all(a.status is LinkStatus.INFERRED and a.site.guard_ids == [] for a in sites)


def test_staff_courier_and_web_accesses_remain_visible(
    tandir: tuple[AccessMap, FastAPIMap, NextJSMap, Index],
) -> None:
    result, fastapi, nextjs, _ = tandir
    entries = {
        e.id: e for e in [*[r.entry for r in fastapi.routes], *[r.entry for r in nextjs.entries]]
    }
    assert {
        entries[a.site.entry_point_id].route
        for a in result.accesses
        if a.site.resource == "Order" and a.site.key_origin is InputOrigin.PATH
    } >= {
        "/admin/orders/{order_id}",
        "/courier/orders/{order_id}",
        "/kitchen/orders/{order_id}/receipt",
        "/branches/{branch_id}/orders",
    }
    web = [a for a in result.accesses if a.site.resource == "orders"]
    assert {(entries[a.site.entry_point_id].route, a.site.key_origin) for a in web} >= {
        ("/orders/[id]", InputOrigin.PATH),
        ("/courier/[id]", InputOrigin.PATH),
        (None, InputOrigin.BODY),
    }
    actions = [a for a in web if a.site.operation is Operation.UPDATE]
    assert {a.site.span.path for a in actions} == {
        "web/lib/dal.ts",
        "web/app/backoffice/actions.ts",
    }
    assert any(a.status is LinkStatus.UNRESOLVED for a in result.accesses)
    assert not result.issues
    assert AccessMap.model_validate_json(result.model_dump_json()) == result
    for access in result.accesses:
        span = access.site.span
        assert span.content_sha256 == span_sha256(
            (TANDIR / span.path).read_bytes(), span.start_line, span.end_line
        )


def fixture_map(tmp_path: Path, files: dict[str, str]) -> AccessMap:
    root, cache = tmp_path / "project", tmp_path / "cache"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        return extract_accesses(snapshot, store, index, cache)
    finally:
        index.close()


def python_app(body: str) -> str:
    return (
        """from fastapi import FastAPI
from sqlalchemy.orm import Session
from sqlalchemy import select as choose, text
class Record: pass
app = FastAPI()
"""
        + body
    )


def test_python_alias_keyword_helper_and_raw_sql(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        {
            "app.py": python_app("""
@app.get("/records/{record_id}")
def view(record_id: int, db: Session):
    copied = record_id
    load(db=db, key=copied)
    db.execute(text("SELECT * FROM records WHERE id = :key"), {"key": record_id})
def load(db: Session, key: int):
    return db.scalars(choose(Record).where(Record.id == key)).first()
""")
        },
    )
    assert len(result.accesses) == 2
    assert {a.site.data_layer for a in result.accesses} == {DataLayer.SQLALCHEMY, DataLayer.RAW_SQL}
    assert all(a.site.key_origin is InputOrigin.PATH for a in result.accesses)


def test_constant_keys_fake_receivers_and_nested_functions_do_not_become_request_accesses(
    tmp_path: Path,
) -> None:
    result = fixture_map(
        tmp_path,
        {
            "app.py": python_app("""
@app.get("/records/{record_id}")
def view(record_id: int, db: Session):
    db.get(Record, 12)
    def unused():
        return db.get(Record, record_id)
    return {"record_id": record_id}.get("record_id")
""")
        },
    )
    assert not result.accesses


def test_python_rebinding_retains_possible_input_and_unknown_is_not_constant(
    tmp_path: Path,
) -> None:
    result = fixture_map(
        tmp_path,
        {
            "app.py": python_app("""
@app.get("/records/{record_id}")
def view(record_id: int, db: Session):
    key = record_id
    if condition(): key = 12
    db.get(Record, key)
    return db.get(Record, dynamic())
""")
        },
    )
    assert {a.site.key_origin for a in result.accesses} == {InputOrigin.PATH, InputOrigin.UNKNOWN}
    assert any(a.status is LinkStatus.UNRESOLVED for a in result.accesses)


def test_local_sqlalchemy_shadow_does_not_establish_driver_provenance(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        {
            "app.py": python_app(
                '@app.get("/records/{record_id}")\n'
                "def view(record_id:int, db:Session): return db.get(Record,record_id)"
            ),
            "sqlalchemy/__init__.py": "",
            "sqlalchemy/orm.py": "class Session: pass",
        },
    )
    assert not result.accesses


def web_files(source: str, **extra: str) -> dict[str, str]:
    return {
        "package.json": json.dumps({"dependencies": {"next": "16.3.8"}}),
        "app/actions.ts": source,
        **extra,
    }


def test_prisma_request_and_constant_accesses_have_distinct_policy_bindings(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        web_files(""""use server";
import { PrismaClient as Client } from "@prisma/client";
const database = new Client();
export async function view(id: number) {
  const key = Number(id);
  await database.record.findUnique({where: {id:key}});
  return database.record.findUnique({where: {id:12}});
}"""),
    )
    assert len(result.accesses) == 2
    assert {p.site.key_origin for p in result.accesses} == {InputOrigin.CONSTANT, InputOrigin.BODY}
    site = next(p.site for p in result.accesses if p.site.key_origin is InputOrigin.BODY)
    assert (site.resource, site.data_layer, site.key_origin) == (
        "record",
        DataLayer.PRISMA,
        InputOrigin.BODY,
    )


def test_drizzle_parameter_alias_and_page_params(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        {
            "package.json": '{"dependencies":{"next":"16.3.8"}}',
            "app/[id]/page.tsx": """import { drizzle } from "drizzle-orm/node-sqlite";
import { eq as equal } from "drizzle-orm";
import { records } from "../../schema";
const database = drizzle({});
export default async function Page({params}: {params:Promise<{id:string}>}) {
  const {id} = await params;
  const row = database.select().from(records).where(equal(records.id, Number(id)));
  return <p>{row}</p>;
}""",
            "schema.ts": "export const records = {}",
        },
    )
    assert len(result.accesses) == 1
    assert result.accesses[0].site.data_layer is DataLayer.DRIZZLE
    assert result.accesses[0].site.key_origin is InputOrigin.PATH


def test_raw_sqlite_driver_and_wrapper_calls(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        web_files(
            """"use server";
import { one } from "../data";
const PREFIX = "SELECT * FROM records";
export async function view(id: number) { return one(`${PREFIX} WHERE id = ?`, id); }
""",
            **{
                "data.ts": """import { DatabaseSync } from "node:sqlite";
const database = new DatabaseSync(":memory:");
export function one(sql:string, value:number) { return database.prepare(sql).get(value); }"""
            },
        ),
    )
    assert len(result.accesses) == 1
    assert result.accesses[0].site.data_layer is DataLayer.RAW_SQL
    assert result.accesses[0].site.key_origin is InputOrigin.BODY


def test_plain_sql_text_and_names_do_not_prove_a_database_call(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        web_files(""""use server";
const database = { record: {findUnique: (value: unknown) => value} };
export async function view(id:number) {
  console.log("SELECT * FROM records WHERE id = ?", id);
  return database.record.findUnique({where:{id}});
}"""),
    )
    assert not result.accesses


def test_prisma_imported_singleton_and_shorthand_key(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        web_files(
            """"use server";
import { client } from "../database";
export async function view(id:number) { return client.record.findUnique({where:{id}}); }
""",
            **{
                "database.ts": """import { PrismaClient } from "@prisma/client";
export const client = new PrismaClient();"""
            },
        ),
    )
    assert len(result.accesses) == 1
    assert result.accesses[0].site.key_origin is InputOrigin.BODY


def test_fastapi_query_and_explicit_body_binding(tmp_path: Path) -> None:
    result = fixture_map(
        tmp_path,
        {
            "app.py": python_app("""
from fastapi import Body
@app.get("/records")
def query(key: int, db: Session): return db.get(Record, key)
@app.post("/records")
def posted(db: Session, key: int = Body()): return db.get(Record, key)
""")
        },
    )
    assert {a.site.key_origin for a in result.accesses} == {InputOrigin.QUERY, InputOrigin.BODY}


def test_access_traversal_limit_is_visible(tmp_path: Path) -> None:
    functions = "\n".join(
        f"def f{i}(db: Session, key: int): return f{i + 1}(db, key)" for i in range(18)
    )
    result = fixture_map(
        tmp_path,
        {
            "app.py": python_app(
                '@app.get("/records/{key}")\ndef entry(key:int,db:Session): return f0(db,key)\n'
                + functions
                + "\ndef f18(db:Session,key:int): return db.get(Record,key)\n"
            )
        },
    )
    assert any("traversal budget reached" in i for i in result.issues)


def test_static_access_extraction_never_imports_target(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    body = (
        f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n'
        '@app.get("/records/{key}")\ndef entry(key:int,db:Session): return db.get(Record,key)\n'
    )
    result = fixture_map(tmp_path, {"app.py": python_app(body)})
    assert len(result.accesses) == 1 and not marker.exists()


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT * FROM orders WHERE id = ? AND customer_id = ?", ("orders", Operation.READ, [0])),
        ("UPDATE orders SET status = ? WHERE id = ?", ("orders", Operation.UPDATE, [1])),
        ("DELETE FROM records WHERE id = :key", ("records", Operation.DELETE, ["key"])),
        ("SELECT * FROM records WHERE id = $2", ("records", Operation.READ, [1])),
        ("SELECT * FROM records WHERE branch_id = ?", ("records", Operation.READ, [0])),
        ("SELECT 'WHERE id = ?' FROM records", None),
        ("SELECT * FROM records /* WHERE id = ? */", None),
        ("SELECT * FROM records WHERE status = 'id = ?'", None),
        ("SELECT * FROM records WHERE id = 12", None),
    ],
)
def test_sql_lexical_keys(
    sql: str, expected: tuple[str, Operation, list[str | int]] | None
) -> None:
    assert sql_access(sql) == expected
