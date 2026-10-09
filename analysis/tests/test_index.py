import ast
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from analysis.index import Index, index_path
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import FileFacts, extract, span_sha256, words
from backend.contracts.code import ProjectSnapshot, SymbolKind
from backend.contracts.common import Language

REPOSITORY = Path(__file__).resolve().parents[2]
TANDIR = REPOSITORY / "labs" / "tandir"
# Building the web lab writes next-env.d.ts, which Git ignores: a fresh clone has 59 modules.
MODULES = 59 + (TANDIR / "web/next-env.d.ts").is_file()
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("key", ["extractor_sha256", "parsers"])
def test_stale_extractor_or_parser_identity_rebuilds_owned_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    from analysis import index as module

    project = tmp_path / "source"
    project.mkdir()
    (project / "app.py").write_bytes(b"x = 1\n")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(project, store)
    path = tmp_path / "index.sqlite"
    first = Index.build(snapshot, store, path)
    first.close()
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE meta SET value = 'old' WHERE key = ?", (key,))
    calls: list[str] = []
    original = module.extract

    def extracting(
        path: str, language: Language, source: bytes, package_dirs: set[str]
    ) -> FileFacts:
        calls.append("extract")
        return original(path, language, source, package_dirs)

    monkeypatch.setattr(module, "extract", extracting)
    rebuilt = Index.build(snapshot, store, path)
    assert calls == ["extract"] and rebuilt.meta(key) != "old"
    rebuilt.close()
    calls.clear()
    reopened = Index.build(snapshot, store, path)
    assert not calls
    reopened.close()


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> SnapshotStore:
    return SnapshotStore(tmp_path_factory.mktemp("store"))


@pytest.fixture(scope="module")
def snapshot(store: SnapshotStore) -> ProjectSnapshot:
    return take_snapshot(TANDIR, store, now=NOW)


@pytest.fixture(scope="module")
def index(
    snapshot: ProjectSnapshot, store: SnapshotStore, tmp_path_factory: pytest.TempPathFactory
) -> Index:
    return Index.build(snapshot, store, index_path(tmp_path_factory.mktemp("cache"), snapshot.id))


# An independent oracle for Python: the standard library's own parser.

_COMPOUND = (ast.If, ast.Try, ast.With, ast.AsyncWith)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _ast_definitions(body: list[ast.stmt]) -> list[ast.stmt]:
    found: list[ast.stmt] = []
    for stmt in body:
        if isinstance(stmt, _DEFS):
            found.append(stmt)
        elif isinstance(stmt, _COMPOUND):
            for block in ("body", "orelse", "finalbody"):
                found += _ast_definitions(getattr(stmt, block, []))
            for handler in getattr(stmt, "handlers", []):
                found += _ast_definitions(handler.body)
    return found


def _ast_symbols(
    body: list[ast.stmt], parent: str | None = None, in_class: bool = False
) -> set[tuple[str, str, int, int]]:
    out: set[tuple[str, str, int, int]] = set()
    for node in _ast_definitions(body):
        assert isinstance(node, _DEFS)
        name = f"{parent}.{node.name}" if parent else node.name
        start = min([d.lineno for d in node.decorator_list] + [node.lineno])
        end = node.end_lineno or node.lineno
        if isinstance(node, ast.ClassDef):
            out.add((name, "class", start, end))
            out |= _ast_symbols(node.body, name, in_class=True)
        else:
            out.add((name, "method" if in_class else "function", start, end))
            out |= _ast_symbols(node.body, name)
    return out


def _ast_variables(tree: ast.Module) -> set[tuple[str, str, int, int]]:
    return {
        (s.targets[0].id, "variable", s.lineno, s.end_lineno or s.lineno)
        for s in tree.body
        if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name)
    }


def test_python_symbols_match_the_standard_library_parser(
    index: Index, snapshot: ProjectSnapshot, store: SnapshotStore
) -> None:
    python_files = [f for f in snapshot.files if f.language is Language.PYTHON]
    assert len(python_files) >= 25
    for file in python_files:
        tree = ast.parse(store.read(snapshot, file.path))
        expected = _ast_symbols(tree.body) | _ast_variables(tree)
        indexed = {
            (s.local_name, s.kind.value, s.start_line, s.end_line)
            for s in index.symbols(path=file.path)
            if s.kind is not SymbolKind.MODULE
        }
        assert indexed == expected, file.path


def test_tandir_symbol_counts(index: Index) -> None:
    counts = index.counts()
    assert counts["module"] == MODULES
    # TypeScript components and types, checked by hand against the web lab's sources.
    assert counts["component"] == 11
    assert counts["type"] == 13


def test_data_access_layer_functions(index: Index) -> None:
    exported = {
        s.name for s in index.symbols(path="web/lib/dal.ts", kind=SymbolKind.FUNCTION) if s.exported
    }
    assert exported == {
        "getViewer",
        "verifySession",
        "getStorefront",
        "getMyOrders",
        "getOrderDTO",
        "cancelOrderFor",
        "getMyDeliveries",
        "getDelivery",
        "getStaffOrders",
    }
    viewer = index.symbol("web/lib/dal:getViewer")
    assert viewer is not None and viewer.is_async  # cache(async () => ...)


def test_directives_and_components(index: Index) -> None:
    assert index.file_directive("web/app/login/actions.ts") == "use server"
    assert index.file_directive("web/app/backoffice/actions.ts") == "use server"
    assert index.file_directive("web/app/courier/[id]/DeliveryCard.tsx") == "use client"
    assert index.file_directive("web/lib/dal.ts") is None
    card = index.symbol("web/app/courier/[id]/DeliveryCard:DeliveryCard")
    assert card is not None and card.kind is SymbolKind.COMPONENT and card.exported
    page = index.symbol("web/app/courier/[id]/page:DeliveryPage")
    assert page is not None and page.is_default and page.is_async


def test_route_decorators_are_kept(index: Index) -> None:
    receipt = index.symbol("tandir.routers.orders.get_receipt")
    assert receipt is not None
    assert receipt.decorators == ('router.get("/{order_id}/receipt")',)
    assert (receipt.start_line, receipt.end_line) == (82, 91)


def test_imports(index: Index) -> None:
    orders = {(i.module, i.name) for i in index.imports("api/tandir/routers/orders.py")}
    assert ("tandir.services.orders", "load_order_scoped") in orders
    card_imports = index.imports("web/app/courier/[id]/DeliveryCard.tsx")
    card = {(i.module, i.name, i.kind) for i in card_imports}
    assert ("@/lib/dal", "CustomerRecord", "type") in card
    assert ("react", "useState", "named") in card


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("load_order_scoped", "tandir.services.orders.load_order_scoped"),
        ("loadOrderScoped", "tandir.services.orders.load_order_scoped"),
        ("verify session", "web/lib/dal:verifySession"),
        ("refundOrder", "web/app/backoffice/actions:refundOrder"),
        ("proxy", "web/proxy:proxy"),
    ],
)
def test_search_finds_known_functions_first(index: Index, text: str, expected: str) -> None:
    hits = index.search(text, limit=3)
    assert hits and hits[0].qualified_name == expected


def test_search_finds_every_receipt_route(index: Index) -> None:
    names = {h.qualified_name for h in index.search("receipt", limit=20)}
    assert {"tandir.routers.orders.get_receipt", "tandir.routers.kitchen.print_receipt"} <= names


def test_search_by_kind_and_falls_back_to_any_word(index: Index) -> None:
    hits = index.search("order dto", kinds=(SymbolKind.FUNCTION,))
    assert {h.name for h in hits} >= {"getOrderDTO", "toOrderDTO"}
    assert all(h.kind is SymbolKind.FUNCTION for h in hits)
    assert index.search("cancelOrderFor zzzunknownword")  # OR fallback


@pytest.mark.parametrize("text", ['"); DROP TABLE symbols; --', "a OR b NEAR(c)", "*", "", "^"])
def test_search_treats_text_as_words_never_as_query_syntax(index: Index, text: str) -> None:
    index.search(text)  # no exception
    assert index.counts()["module"] == MODULES


def test_symbols_become_contracts_with_span_hashes(
    index: Index, snapshot: ProjectSnapshot, store: SnapshotStore
) -> None:
    row = index.symbol("tandir.routers.orders.get_invoice")
    assert row is not None
    symbol = index.to_contract(row, snapshot.id)
    source = store.read(snapshot, "api/tandir/routers/orders.py")
    assert symbol.span.content_sha256 == span_sha256(source, 94, 101)
    assert symbol.span.path == "api/tandir/routers/orders.py"


def test_index_is_reused_for_the_same_snapshot(
    index: Index, snapshot: ProjectSnapshot, store: SnapshotStore, tmp_path: Path
) -> None:
    path = tmp_path / "x.sqlite"
    first = Index.build(snapshot, store, path)
    first.close()
    stamp = path.stat().st_mtime_ns
    again = Index.build(snapshot, store, path)
    assert again.meta("snapshot_id") == snapshot.id
    assert path.stat().st_mtime_ns == stamp
    again.close()


def test_files_with_syntax_errors_are_still_indexed() -> None:
    facts = extract("bad.py", Language.PYTHON, b"def ok():\n    pass\n\ndef broken(:\n", set())
    assert facts.has_errors
    assert "ok" in {s.local_name for s in facts.symbols}


def test_python_module_names_follow_packages() -> None:
    from analysis.syntax import python_module

    packages = {"api/tandir", "api/tandir/routers"}
    assert python_module("api/tandir/routers/orders.py", packages) == "tandir.routers.orders"
    assert python_module("api/tandir/__init__.py", packages) == "tandir"
    assert python_module("scripts/tool.py", packages) == "tool"


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("load_order_scoped", "load order scoped"),
        ("getOrderDTO", "get order dto"),
        ("HTTPException", "http exception"),
        ("DeliveryCard", "delivery card"),
        ("v2Api", "v2 api"),
    ],
)
def test_identifier_words(identifier: str, expected: str) -> None:
    assert words(identifier) == expected
