from collections.abc import Iterator
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from analysis import typescript_resolution
from analysis.index import Index, index_path
from analysis.platform_calls import non_authorizing, platform_identity
from analysis.resolution import CallGraph, LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.typescript_resolution import NodeLimits, TypeScriptUnavailable, resolve_typescript
from backend.settings import Settings

TANDIR = Path(__file__).resolve().parents[2] / "labs" / "tandir"


@pytest.fixture(scope="module")
def tandir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[CallGraph, Index]]:
    cache = tmp_path_factory.mktemp("typescript-resolution")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(TANDIR, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        yield resolve_typescript(snapshot, store, index, cache), index
    finally:
        index.close()


@pytest.mark.parametrize(
    ("caller", "callee", "target", "kind"),
    [
        (
            "web/app/orders/actions:cancelOrder",
            "cancelOrderFor",
            "web/lib/dal:cancelOrderFor",
            "call",
        ),
        ("web/app/backoffice/actions:refundOrder", "run", "web/lib/db:run", "call"),
        ("web/lib/dal:cancelOrderFor", "verifySession", "web/lib/dal:verifySession", "call"),
        ("web/lib/dal:verifySession", "getViewer", "web/lib/dal:getViewer", "call"),
        ("web/lib/dal:getViewer", "viewerForToken", "web/lib/sessions:viewerForToken", "call"),
        ("web/app/orders/[id]/page:OrderPage", "getOrderDTO", "web/lib/dal:getOrderDTO", "call"),
        (
            "web/app/api/admin/reports/route:GET",
            "viewerForToken",
            "web/lib/sessions:viewerForToken",
            "call",
        ),
        (
            "web/app/orders/[id]/OrderSummary:OrderSummary",
            "cancelOrder",
            "web/app/orders/actions:cancelOrder",
            "reference",
        ),
    ],
)
def test_tandir_calls_and_server_action_references(
    tandir: tuple[CallGraph, Index],
    caller: str,
    callee: str,
    target: str,
    kind: str,
) -> None:
    graph, index = tandir
    assert not graph.issues
    caller_row, target_row = index.symbol(caller), index.symbol(target)
    assert caller_row is not None and target_row is not None
    edge = next(e for e in graph.calls(caller_row.id) if e.callee == callee)
    assert edge.target_id == target_row.id
    assert edge.status is LinkStatus.RESOLVED and edge.kind == kind
    if target.endswith(":cancelOrder"):
        assert index.file_directive(target_row.path) == "use server"


def test_tandir_external_calls_are_visible(tandir: tuple[CallGraph, Index]) -> None:
    graph, _ = tandir
    edge = next(e for e in graph.edges if e.callee == "revalidatePath")
    assert edge.status is LinkStatus.UNRESOLVED and edge.target_id is None
    assert 0 < graph.peak_rss_bytes < NodeLimits().rss_bytes


def resolve(
    tmp_path: Path,
    files: dict[str, str],
    limits: NodeLimits | None = None,
) -> tuple[CallGraph, dict[str, str]]:
    root = tmp_path / "project"
    for name, source in files.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source, encoding="utf-8")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(tmp_path, snapshot.id))
    try:
        graph = resolve_typescript(snapshot, store, index, tmp_path, limits=limits)
        return graph, {row.id: row.qualified_name for row in index.symbols()}
    finally:
        index.close()


def test_alias_reexports_namespace_imports_and_unicode(tmp_path: Path) -> None:
    graph, names = resolve(
        tmp_path,
        {
            "lib/loader.ts": "export function load() { return 1; }\n",
            "lib/index.ts": "export { load as publicLoad } from './loader';\n",
            "main.ts": (
                "import { publicLoad as alias } from './lib';\n"
                "import * as service from './lib/loader';\n"
                "export function route() {\n"
                "  const label = '🍞'; alias();\n"
                "  return service.load();\n}\n"
            ),
        },
    )
    assert len(graph.edges) == 2
    assert all(e.target_id and names[e.target_id] == "lib/loader:load" for e in graph.edges)
    assert graph.edges[0].column == 22


def test_instance_calls_ambiguous_dispatch_and_shadowing(tmp_path: Path) -> None:
    graph, names = resolve(
        tmp_path,
        {
            "main.ts": (
                "class A { load() { return 1; } }\n"
                "class B { load() { return 2; } }\n"
                "function load() { return 3; }\n"
                "function known(item: A) { return item.load(); }\n"
                "function unknown(item: A | B) { return item.load(); }\n"
                "function shadow(load: () => number) { return load(); }\n"
            )
        },
    )
    by_caller = {names[e.caller_id]: e for e in graph.edges}
    assert by_caller["main:known"].status is LinkStatus.RESOLVED
    assert by_caller["main:known"].target_id
    assert names[by_caller["main:known"].target_id] == "main:A.load"
    assert by_caller["main:unknown"].status is LinkStatus.UNRESOLVED
    assert by_caller["main:shadow"].status is LinkStatus.UNRESOLVED


def test_nested_functions_on_the_same_line_have_distinct_callers(tmp_path: Path) -> None:
    graph, names = resolve(
        tmp_path,
        {
            "main.ts": (
                "function helper() {}\n"
                "function outer() { function inner() { helper(); } inner(); }\n"
            )
        },
    )
    links = {(names[e.caller_id], e.callee) for e in graph.edges}
    assert ("main:outer.inner", "helper") in links
    assert ("main:outer", "inner") in links


def test_config_aliases_are_scoped_and_jsonc_is_accepted(tmp_path: Path) -> None:
    graph, names = resolve(
        tmp_path,
        {
            "one/tsconfig.json": '{// comment\n"compilerOptions":{"paths":{"@/*":["./*"]},},}',
            "one/lib.ts": "export function load() {}\n",
            "one/main.ts": "import {load} from '@/lib';\nexport function route() { load(); }\n",
            "two/tsconfig.json": '{"compilerOptions":{"paths":{"@/*":["src/*"]}}}',
            "two/src/lib.ts": "export function load() {}\n",
            "two/main.ts": "import {load} from '@/lib';\nexport function route() { load(); }\n",
        },
    )
    assert not graph.issues
    assert {names[e.target_id] for e in graph.edges if e.target_id} == {
        "one/lib:load",
        "two/src/lib:load",
    }


@pytest.mark.parametrize(
    "config",
    [
        '{"compilerOptions":{"baseUrl":"../../outside","paths":{"@/*":["*"]}}}',
        '{"compilerOptions":{"paths":{"@/*":["../../outside/*"]}}}',
        '{"extends":"../../outside/tsconfig.json"}',
        "this is not JSON",
    ],
)
def test_target_configuration_cannot_load_files_outside_snapshot(
    tmp_path: Path, config: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "lib.ts").write_text("export function load() {}", encoding="utf-8")
    graph, _ = resolve(
        tmp_path,
        {
            "tsconfig.json": config,
            "main.ts": "import {load} from '@/lib';\nexport function route() { load(); }\n",
        },
    )
    assert all(e.status is LinkStatus.UNRESOLVED for e in graph.edges)


def test_source_code_plugins_and_node_options_never_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "executed"
    preload = tmp_path / "preload.cjs"
    preload.write_text(f"require('fs').writeFileSync({str(marker)!r}, 'BAD');", encoding="utf-8")
    monkeypatch.setenv("NODE_OPTIONS", f"--require={preload}")
    graph, names = resolve(
        tmp_path,
        {
            "main.ts": (
                "import {writeFileSync} from 'node:fs';\n"
                f"writeFileSync({str(marker)!r}, 'BAD');\n"
                "export function safe() {}\nsafe();\n"
            ),
            "plugin.js": "throw new Error('target plugin must not execute');\n",
            "tsconfig.json": '{"compilerOptions":{"plugins":[{"name":"./plugin.js"}]}}',
        },
    )
    assert not marker.exists()
    assert any(e.target_id and names[e.target_id] == "main:safe" for e in graph.edges)


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (NodeLimits(input_bytes=1), "input budget"),
        (NodeLimits(output_bytes=1), "output budget"),
        (NodeLimits(timeout_seconds=0.000001), "time budget"),
        (NodeLimits(rss_bytes=1), "RSS budget"),
    ],
)
def test_resource_limits_fail_visibly(tmp_path: Path, limits: NodeLimits, message: str) -> None:
    with pytest.raises(TypeScriptUnavailable, match=message):
        resolve(tmp_path, {"main.ts": "export function load() {}\nload();\n"}, limits)


def test_missing_node_is_a_visible_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_NODE_BINARY", str(tmp_path / "missing-node.exe"))
    with pytest.raises(TypeScriptUnavailable, match="PLUMB_NODE_BINARY"):
        resolve(tmp_path, {"main.ts": "export function load() {}\n"})


def test_node_path_must_be_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_NODE_BINARY", "node.exe")
    with pytest.raises(ValidationError, match="absolute path"):
        Settings()


def test_bad_syntax_is_visible(tmp_path: Path) -> None:
    graph, _ = resolve(tmp_path, {"main.ts": "export function load( { return ; }"})
    assert graph.issues and any("main.ts" in issue for issue in graph.issues)


def test_no_typescript_does_not_launch_node(tmp_path: Path) -> None:
    with patch(
        "analysis.typescript_resolution.run_helper", side_effect=AssertionError("unexpected")
    ):
        graph, _ = resolve(tmp_path, {"main.py": "x = 1\n"})
    assert not graph.edges


def test_base_url_and_javascript_extension_substitution(tmp_path: Path) -> None:
    graph, names = resolve(
        tmp_path,
        {
            "tsconfig.json": '{"compilerOptions":{"baseUrl":"src"}}',
            "src/lib.ts": "export function load() {}\n",
            "src/main.ts": "import {load} from 'lib.js';\nload();\n",
        },
    )
    assert graph.edges[0].target_id
    assert names[graph.edges[0].target_id] == "src/lib:load"


def test_helper_cannot_return_out_of_snapshot_evidence(tmp_path: Path) -> None:
    forged = {
        "version": "6.0.3",
        "platform_sha256": platform_identity(),
        "edges": [{"path": "../outside.ts"}],
        "issues": [],
        "peak_rss_bytes": 0,
    }
    with (
        patch("analysis.typescript_resolution.run_helper", return_value=forged),
        pytest.raises(TypeScriptUnavailable, match="outside the indexed snapshot"),
    ):
        resolve(tmp_path, {"main.ts": "export function load() {}\nload();\n"})


def test_platform_reads_are_separate_from_unknown_helpers_and_source_targets(
    tmp_path: Path,
) -> None:
    graph, _ = resolve(
        tmp_path,
        {
            "main.ts": (
                "export function route(data: FormData) {\n"
                '  const id = Number(data.get("id"));\n'
                "  authorize();\n}\n"
            )
        },
    )
    assert graph.platform_sha256 == platform_identity()
    assert {e.callee: e.platform_operation for e in graph.edges} == {
        "Number": "number_conversion",
        "data.get": "form_data_read",
        "authorize": None,
    }
    assert all(e.status is LinkStatus.UNRESOLVED and e.target_id is None for e in graph.edges)
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = store.load(graph.snapshot_id)
    for edge in graph.edges:
        assert non_authorizing(edge, graph, snapshot, store) is (
            edge.platform_operation is not None
        )
    edge = next(e for e in graph.edges if e.callee == "Number")
    assert not non_authorizing(
        edge, graph.model_copy(update={"platform_sha256": "0" * 64}), snapshot, store
    )
    assert not non_authorizing(
        edge,
        graph.model_copy(update={"resolver_version": "typescript-1; TS 6.0.3"}),
        snapshot,
        store,
    )
    corrupt = edge.model_copy(
        update={"span": edge.span.model_copy(update={"content_sha256": "0" * 64})}
    )
    changed = graph.model_copy(update={"edges": [corrupt]})
    assert not non_authorizing(corrupt, changed, snapshot, store)
    moved = edge.model_copy(update={"column": 0})
    assert not non_authorizing(moved, graph.model_copy(update={"edges": [moved]}), snapshot, store)


@pytest.mark.parametrize(
    "prefix,parameter,body",
    [
        ("function Number(value: unknown) { authorize(); return 1; }\n", "data: FormData", ""),
        ("interface FormData { get(key: string): string; }\n", "data: FormData", ""),
        ("type Input = FormData;\n", "data: Input", ""),
        ("", "data: any", ""),
        ("", "data: FormData | Other", ""),
        ("", "data: FormData = replacement", ""),
        ("", "data: FormData", 'const later = () => data.get("other");'),
        ("", "data: FormData", "data.get = authorize;"),
        ("", "data: FormData", "const alias = data; alias.get = authorize;"),
        ("", "data: FormData", "authorize(data);"),
        ("", "data: FormData", "data = replacement;"),
        ("", "data: FormData", "globalThis.Number = authorize;"),
        ("", "data: FormData", "FormData.prototype.get = authorize;"),
        ("", "data: FormData", "eval(dynamic);"),
    ],
)
def test_unproven_platform_bindings_and_mutations_stay_unknown(
    tmp_path: Path, prefix: str, parameter: str, body: str
) -> None:
    graph, _ = resolve(
        tmp_path,
        {
            "main.ts": prefix
            + (
                f"export function route({parameter}) {{\n  {body}\n"
                '  const id = Number(data.get("id"));\n}\n'
            )
        },
    )
    number = next(e for e in graph.edges if e.callee == "Number")
    assert number.platform_operation is None
    if not prefix.startswith("function Number"):
        getter = next(e for e in graph.edges if e.callee == "data.get")
        if "globalThis.Number" not in body:
            assert getter.platform_operation is None


@pytest.mark.parametrize(
    "expression",
    [
        'data?.get("id")',
        'data.get?.("id")',
        'data["get"]("id")',
        "data.get(key)",
        '(data as FormData).get("id")',
        "authorize()",
    ],
)
def test_only_direct_literal_key_platform_reads_can_feed_conversion(
    tmp_path: Path, expression: str
) -> None:
    graph, _ = resolve(
        tmp_path,
        {
            "main.ts": (
                f"export function route(data: FormData) {{ return Number({expression}); }}\n"
            )
        },
    )
    assert all(e.platform_operation is None for e in graph.edges)


def test_platform_attestation_is_required_from_the_trusted_helper(tmp_path: Path) -> None:
    forged = {"version": "6.0.3", "edges": [], "issues": [], "peak_rss_bytes": 0}
    with (
        patch("analysis.typescript_resolution.run_helper", return_value=forged),
        pytest.raises(TypeScriptUnavailable, match="unpinned platform"),
    ):
        resolve(tmp_path, {"main.ts": "export function route() {}\n"})


def test_imported_numeric_helper_is_not_a_platform_conversion(tmp_path: Path) -> None:
    graph, names = resolve(
        tmp_path,
        {
            "main.ts": 'import {Number} from "./helper";\n'
            'export function route(data: FormData) { return Number(data.get("id")); }\n',
            "helper.ts": "export function Number(value: unknown) { authorize(); return 1; }\n",
        },
    )
    number = next(e for e in graph.edges if e.callee == "Number")
    assert number.platform_operation is None and number.target_id
    assert names[number.target_id] == "helper:Number"


@pytest.mark.parametrize("damaged", ["platform", "sqlite"])
def test_actual_platform_hash_mismatch_refuses_without_changing_installed_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damaged: str
) -> None:
    # A disposable trusted-helper copy; never alter the installed package/user files.
    original = typescript_resolution.HELPER.parent
    helper = tmp_path / "helper"
    helper.mkdir()
    for name in (
        "resolver.mts",
        "access_facts.mts",
        "nextjs_facts.mts",
        "serialization_facts.mts",
        "array_provenance.mts",
        "array-pin.json",
        "platform_calls.mts",
        "platform-pin.json",
    ):
        copyfile(original / name, helper / name)
    library = helper / "node_modules/typescript/lib"
    library.mkdir(parents=True)
    for name in (
        "package.json",
        "lib/typescript.js",
        "lib/lib.es5.d.ts",
        "lib/lib.dom.d.ts",
        "lib/lib.es2016.array.include.d.ts",
    ):
        copyfile(
            original / "node_modules/typescript" / name, helper / "node_modules/typescript" / name
        )
    types = helper / "node_modules/@types/node"
    types.mkdir(parents=True)
    for name in ("package.json", "sqlite.d.ts"):
        copyfile(original / "node_modules/@types/node" / name, types / name)
    asset = library / "lib.es5.d.ts" if damaged == "platform" else types / "sqlite.d.ts"
    asset.write_bytes(asset.read_bytes() + b"\n")
    monkeypatch.setattr(typescript_resolution, "HELPER", helper / "resolver.mts")
    error = (
        "Platform declaration hash mismatch"
        if damaged == "platform"
        else "SQLite array API pin mismatch"
    )
    with pytest.raises(TypeScriptUnavailable, match=error):
        typescript_resolution.run_helper(
            {"files": [], "configs": [], "symbols": [], "framework": True},
            tmp_path / "cache",
            Settings().node_binary,
            NodeLimits(),
        )
