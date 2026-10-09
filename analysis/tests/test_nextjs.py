import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from analysis.index import Index, index_path
from analysis.nextjs import NextJSMap, extract_nextjs, matcher_covers
from analysis.resolution import LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from analysis.typescript_resolution import NodeLimits
from backend.contracts.code import EntryPointKind

TANDIR = Path(__file__).resolve().parents[2] / "labs" / "tandir"


@pytest.fixture(scope="module")
def tandir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[NextJSMap, Index]]:
    cache = tmp_path_factory.mktemp("next-map")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(TANDIR, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        yield extract_nextjs(snapshot, store, index, cache), index
    finally:
        index.close()


def test_every_tandir_web_entry(tandir: tuple[NextJSMap, Index]) -> None:
    result, index = tandir
    names = {r.id: r.qualified_name for r in index.symbols()}
    assert len(result.entries) == 13
    assert result.issues == [
        "web/tests/support/next-mocks.ts: Dynamic import: component execution boundary unresolved"
    ]
    pages = {e.entry.route for e in result.entries if e.entry.kind is EntryPointKind.PAGE}
    assert pages == {
        "/",
        "/login",
        "/orders",
        "/orders/[id]",
        "/courier",
        "/courier/[id]",
        "/backoffice",
    }
    routes = {
        (e.entry.method, e.entry.route)
        for e in result.entries
        if e.entry.kind is EntryPointKind.ROUTE_HANDLER
    }
    assert routes == {("GET", "/api/admin/export"), ("GET", "/api/admin/reports")}
    actions = [e.entry for e in result.entries if e.entry.kind is EntryPointKind.SERVER_ACTION]
    assert {names[a.handler_symbol_id] for a in actions} == {
        "web/app/backoffice/actions:refundOrder",
        "web/app/orders/actions:cancelOrder",
        "web/app/login/actions:signIn",
        "web/app/login/actions:signOut",
    }
    assert all(a.method == "POST" and a.route is None for a in actions)


def test_proxy_is_optimistic_and_never_authorizes_an_action(
    tandir: tuple[NextJSMap, Index],
) -> None:
    result, _ = tandir
    assert len(result.proxies) == 1
    proxy = result.proxies[0]
    assert proxy.matcher == ["/api/admin/export"]
    assert proxy.optimistic and proxy.guard.optimistic and not proxy.guard.confirmed
    export = next(e for e in result.entries if e.entry.route == "/api/admin/export")
    assert len(export.proxies) == 1
    assert export.proxies[0].optimistic and export.proxies[0].status is LinkStatus.INFERRED
    reports = next(e for e in result.entries if e.entry.route == "/api/admin/reports")
    assert not reports.proxies
    for action in [e for e in result.entries if e.entry.kind is EntryPointKind.SERVER_ACTION]:
        assert all(p.status is LinkStatus.UNRESOLVED for p in action.proxies)
    assert NextJSMap.model_validate_json(result.model_dump_json()) == result
    assert '"optimistic":true' in result.model_dump_json()


def test_tandir_component_boundaries_and_props(tandir: tuple[NextJSMap, Index]) -> None:
    result, index = tandir
    names = {r.id: r.name for r in index.symbols()}
    assert len(result.components) == 11
    assert {names[c.symbol_id] for c in result.components if c.boundary == "client"} == {
        "OrderSummary",
        "DeliveryCard",
        "LoginForm",
    }
    props = {names[p.component_symbol_id]: p for p in result.client_props}
    assert props["DeliveryCard"].props == {
        "order": "{delivery.order}",
        "customer": "{delivery.customer}",
    }
    assert props["OrderSummary"].props == {"order": "{order}"}
    assert "LoginForm" in props
    for entry in result.entries:
        span = entry.entry.span
        assert span.content_sha256 == span_sha256(
            (TANDIR / span.path).read_bytes(), span.start_line, span.end_line
        )


def test_data_layer_is_source_marked_and_not_a_guard(tandir: tuple[NextJSMap, Index]) -> None:
    result, index = tandir
    assert {m.path for m in result.data_modules} == {
        "web/lib/dal.ts",
        "web/lib/db.ts",
        "web/lib/sessions.ts",
    }
    dal = next(m for m in result.data_modules if m.path == "web/lib/dal.ts")
    row = index.symbol("web/lib/dal:cancelOrderFor")
    assert row and row.id in dal.export_symbol_ids
    assert dal.status is LinkStatus.INFERRED
    assert dal.span.start_line == 1 and "not confirmed guards" in dal.reason


def fixture_map(tmp_path: Path, files: dict[str, str]) -> tuple[NextJSMap, dict[str, str]]:
    root, cache = tmp_path / "project", tmp_path / "cache"
    files = {"package.json": json.dumps({"dependencies": {"next": "16.3.8"}}), **files}
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        return extract_nextjs(snapshot, store, index, cache), {
            r.id: r.qualified_name for r in index.symbols()
        }
    finally:
        index.close()


def test_alias_exports_src_groups_and_private_routes(tmp_path: Path) -> None:
    result, names = fixture_map(
        tmp_path,
        {
            "src/app/(shop)/@slot/orders/[id]/page.tsx": (
                'export { View as default } from "../../../../../view";'
            ),
            "src/view.tsx": "export function View() { return <p />; }",
            "src/app/api/route.ts": (
                'import { handler } from "../../handler"; '
                "export { handler as GET, handler as POST };"
            ),
            "src/handler.ts": "export async function handler() { return new Response(); }",
            "src/app/_private/page.tsx": "export default function Private() { return <p />; }",
            "src/app/(.)photos/page.tsx": "export default function Photo() { return <p />; }",
        },
    )
    assert {(e.entry.method, e.entry.route) for e in result.entries} == {
        ("GET", "/orders/[id]"),
        ("GET", "/api"),
        ("POST", "/api"),
    }
    page = next(e for e in result.entries if e.entry.kind is EntryPointKind.PAGE)
    assert names[page.entry.handler_symbol_id] == "src/view:View"
    assert page.entry.span.path.endswith("page.tsx")
    assert any("intercepting route" in i for i in result.issues)


def test_actions_inline_alias_and_anonymous_default(tmp_path: Path) -> None:
    result, names = fixture_map(
        tmp_path,
        {
            "app/page.tsx": """export default async function Page() {
  async function save() { "use server"; return 1; }
  return <form action={save} />;
}""",
            "app/actions.ts": """"use server";
async function named() { return 1; }
function localOnly() { return 2; }
export { named as save };
export default async () => 3;
export type State = { ok: boolean };""",
        },
    )
    actions = {
        names[e.entry.handler_symbol_id]
        for e in result.entries
        if e.entry.kind is EntryPointKind.SERVER_ACTION
    }
    assert actions == {"app/page:Page.save", "app/actions:named", "app/actions:default"}
    assert not result.issues


def test_client_import_closure_respects_types_and_server_actions(tmp_path: Path) -> None:
    result, names = fixture_map(
        tmp_path,
        {
            "tsconfig.json": '{"compilerOptions":{"paths":{"@/*":["./*"]}}}',
            "app/page.tsx": (
                'import { Client } from "./Client"; import { Shared } from "../shared"; '
                "export default function Page() { return <><Client value={1} /><Shared /></> }"
            ),
            "app/Client.tsx": """"use client";
import { Child } from "../child";
import { Shared } from "../shared";
import type { State } from "../types";
import { save } from "@/actions";
export function Client() { return <><Child /><Shared /><form action={save} /></> }""",
            "child.tsx": "export function Child() { return <p /> }",
            "shared.tsx": "export function Shared() { return <p /> }",
            "types.tsx": "export type State = {}; export function Server() { return <p /> }",
            "actions.ts": (
                '"use server"; import "server-only"; export async function save() { return 1; }'
            ),
        },
    )
    contexts = {names[c.symbol_id]: c.boundary for c in result.components}
    assert contexts["child:Child"] == "client"
    assert contexts["shared:Shared"] == "shared"
    assert contexts["types:Server"] == "server"
    assert [names[p.component_symbol_id] for p in result.client_props] == ["app/Client:Client"]
    assert not result.issues


def test_source_data_markers_and_invalid_client_import_are_visible(tmp_path: Path) -> None:
    result, _ = fixture_map(
        tmp_path,
        {
            "app/page.tsx": (
                '"use client"; import "../server"; export default function Page(){ return <p /> }'
            ),
            "server.ts": 'import "server-only"; export function data() { return 1 }',
            "dal.ts": "// server-only\nexport function data() { return 1 }",
        },
    )
    assert [m.path for m in result.data_modules] == ["server.ts"]
    assert any("server-only module is reachable" in i for i in result.issues)


@pytest.mark.parametrize(
    "config",
    [
        "export const config = { matcher: readMatcher() };",
        'export const config = { matcher: [{source:"/api", has:[]}]}',
        'export const config = { matcher: "/api", ...settings };',
    ],
)
def test_dynamic_proxy_matchers_are_unknown(tmp_path: Path, config: str) -> None:
    result, _ = fixture_map(
        tmp_path,
        {
            "app/api/route.ts": "export function GET() { return new Response() }",
            "middleware.ts": f"export function middleware() {{ return 1 }}\n{config}",
        },
    )
    assert result.proxies[0].matcher is None
    assert result.proxies[0].convention == "middleware"
    assert result.entries[0].proxies[0].status is LinkStatus.UNRESOLVED
    assert result.issues


def test_proxy_without_matcher_is_optimistic_for_all_routes(tmp_path: Path) -> None:
    result, _ = fixture_map(
        tmp_path,
        {
            "app/page.tsx": "export default () => <p />;",
            "src/proxy.ts": "export default function gate(){ return 1 }",
        },
    )
    assert len(result.entries) == 1
    assert result.entries[0].proxies[0].status is LinkStatus.INFERRED
    assert not result.proxies[0].guard.confirmed


@pytest.mark.parametrize(
    ("pattern", "route", "expected"),
    [
        ("/api", "/api", True),
        ("/api", "/apix", False),
        ("/api/:path*", "/api", True),
        ("/api/:path*", "/api/a/b", True),
        ("/api/:path+", "/api", False),
        ("/api/:id", "/api/a", True),
        ("/api/:id", "/api/a/b", False),
        ("/:path*", "/[id]", True),
        ("/api/:id", "/api/[id]", None),
        ("/((?!api).*)", "/orders", None),
        ("/api", None, None),
        ("/(a+)+$", "/aaaaaaaaa", None),
    ],
)
def test_conservative_matcher(pattern: str, route: str | None, expected: bool | None) -> None:
    assert matcher_covers(pattern, route) is expected


def test_app_source_and_config_are_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    script = f'import fs from "node:fs"; fs.writeFileSync({json.dumps(str(marker))}, "ran");'
    result, _ = fixture_map(
        tmp_path,
        {
            "next.config.ts": script,
            "app/page.tsx": script + "\nexport default function Page() { return <p /> }",
        },
    )
    assert len(result.entries) == 1 and not marker.exists()


def test_non_next_projects_do_not_spawn_helper(tmp_path: Path) -> None:
    with patch("analysis.nextjs.run_helper", side_effect=AssertionError("unexpected helper")):
        result, _ = fixture_map(
            tmp_path, {"package.json": "{}", "app/page.tsx": "export default () => <p />"}
        )
    assert not result.entries


def test_missing_export_and_dynamic_import_report_limitations(tmp_path: Path) -> None:
    result, _ = fixture_map(
        tmp_path,
        {
            "app/page.tsx": 'const page = makePage(); export default page; import("./unknown");',
            "proxy.ts": "export const config = { matcher: ['/'] };",
        },
    )
    assert not result.entries
    assert any("no unique indexed handler" in i for i in result.issues)
    assert any("Dynamic import" in i for i in result.issues)
    assert any("proxy handler unresolved" in i for i in result.issues)


@pytest.mark.parametrize("path,start,end", [("missing.ts", 1, 1), ("sql.ts", 1, 999)])
def test_constant_sql_citations_must_be_inside_the_exact_snapshot(
    tmp_path: Path, path: str, start: int, end: int
) -> None:
    from analysis import nextjs

    helper = nextjs.run_helper

    def corrupt(
        payload: dict[str, Any], cache: Path, node: Path, limits: NodeLimits
    ) -> dict[str, Any]:
        output = helper(payload, cache, node, limits)
        crossing = next(c for m in output["modules"] for c in m["serializations"] if c["fields"])
        crossing["fields"][0]["evidence"].append(
            {"path": path, "start_line": start, "end_line": end}
        )
        return output

    with (
        patch("analysis.nextjs.run_helper", side_effect=corrupt),
        pytest.raises(ValueError, match="invalid framework source span"),
    ):
        fixture_map(
            tmp_path,
            {
                "sql.ts": "export const SQL = 'SELECT id FROM orders WHERE id = ?';",
                "db.ts": "import {DatabaseSync} from 'node:sqlite';\n"
                "const db = new DatabaseSync(':memory:');\n"
                "export function one(sql: string, id: number) { "
                "return db.prepare(sql).get(id); }",
                "app/api/orders/route.ts": "import {one} from '../../../db';\n"
                "import {SQL} from '../../../sql';\nexport function GET(request: any) {\n"
                "  const row = one(SQL, request.id);\n  return Response.json(row);\n}",
            },
        )


@pytest.mark.parametrize("mode", ["missing_path", "range", "omitted"])
def test_client_binding_helper_locations_remain_frozen_and_bounded(
    tmp_path: Path, mode: str
) -> None:
    from analysis import nextjs

    helper = nextjs.run_helper

    def corrupt(
        payload: dict[str, Any], cache: Path, node: Path, limits: NodeLimits
    ) -> dict[str, Any]:
        output = helper(payload, cache, node, limits)
        crossing = next(
            c for m in output["modules"] for c in m["serializations"] if c["kind"] == "props"
        )
        if mode == "omitted":
            crossing["boundary_evidence"] = []
        else:
            crossing["boundary_evidence"][0].update(
                {"path": "absent.tsx"} if mode == "missing_path" else {"end_line": 999}
            )
        return output

    files = {
        "app/page.tsx": "import {Client} from './Client';\n"
        "export default function Page() { return <Client value={1}/>; }",
        "app/Client.tsx": '"use client";\nexport function Client(props: any) {return null;}',
    }
    with patch("analysis.nextjs.run_helper", side_effect=corrupt):
        if mode == "omitted":
            result, _ = fixture_map(tmp_path, files)
            flow = next(c for c in result.serializations if c.kind == "props")
            assert "Client boundary source binding is unavailable" in flow.unknowns
        else:
            with pytest.raises(ValueError, match="invalid framework source span"):
                fixture_map(tmp_path, files)
