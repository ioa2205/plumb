"""Actual TypeScript resolution with fixture judgments, never accuracy evidence."""

import re
from collections.abc import Iterator

import pytest

from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.peers import PeerCheck
from analysis.access import AccessMap, AccessPath
from analysis.index import Index, index_path
from analysis.resolution import CallGraph, LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import _parser, _text, _walk, span_sha256
from analysis.typescript_resolution import resolve_typescript
from backend.contracts.code import AccessSite, DataLayer, Operation, SourceSpan, SymbolKind
from backend.contracts.common import InputOrigin, Language
from backend.settings import Settings

from .test_guards import DB

SOURCE = b"""import { redirect } from "next/navigation";
import { one } from "./db";
declare function lookup(): Promise<{id: number} | null>;
export async function session() {
  const viewer = await lookup();
  if (!viewer) redirect("/login");
  return viewer;
}
export async function wrongSession() {
  const viewer = await lookup();
  if (!viewer) redirect("/login");
  return other;
}
export async function scoped(id: number) {
  const viewer = await session();
  const row = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  return row;
}
export async function raw(id: number) {
  const row = one("SELECT * FROM orders WHERE id = ?", id);
  return row;
}
export async function supplied(id: number, viewer: {id: number}) {
  const row = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  return row;
}
export async function changed(id: number) {
  const viewer = await session();
  viewer.id = 42;
  const row = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  return row;
}
export async function wrongReturn(id: number) {
  const viewer = await wrongSession();
  const row = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  return row;
}
export async function twoQueries(id: number) {
  const viewer = await session();
  const protectedRow = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  const unprotectedRow = one("SELECT * FROM orders WHERE id = ?", id);
  return unprotectedRow;
}
export async function direct(id: number) {
  return scoped(id);
}
export async function optional(id: number, enabled: boolean) {
  if (enabled) return scoped(id);
  return raw(id);
}
export async function escaped(id: number) {
  const viewer = await session();
  changeIdentity(viewer);
  const row = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  return row;
}
"""


class Model:
    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        fields = request.schema["properties"]["guards"]["items"]["properties"]
        auth = "authenticated" in fields["kind"]["enum"]
        subject = None if auth else fields["subject"]["enum"][1]
        obj = None if auth else fields["object"]["enum"][1]
        return JsonAnswer(
            {
                "guards": [
                    {
                        "kind": "authenticated" if auth else "owner",
                        "subject": subject,
                        "object": obj,
                        "line_ids": list(dict.fromkeys(re.findall(r"\bL\d+\b", request.user))),
                    }
                ]
            },
            "",
            1,
            1,
            0,
        )


@pytest.fixture(scope="module")
def fixture(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[PeerCheck, AccessMap]]:
    root = tmp_path_factory.mktemp("ts-paths")
    project = root / "project"
    project.mkdir()
    (project / "dal.ts").write_bytes(SOURCE)
    (project / "db.ts").write_bytes(DB)
    store = SnapshotStore(root / "snapshots")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, index_path(root, snapshot.id))
    try:
        graph = resolve_typescript(snapshot, store, index, root)
        python = CallGraph(
            snapshot_id=snapshot.id, language="python", resolver_version="fixture", edges=[]
        )
        classifier = Classifier(
            snapshot, store, Model(), SummaryCache(root / "guard.sqlite"), identity="fixture"
        )
        peers = PeerCheck(classifier, index, python, Settings(), typescript_graph=graph)
        tree = _parser(Language.TYPESCRIPT).parse(SOURCE)
        paths = []
        for n in _walk(tree.root_node):
            if n.type != "call_expression" or _text(n.child_by_field_name("function")) != "one":
                continue
            start, end = n.start_point.row + 1, n.end_point.row + 1
            owner = next(
                s
                for s in peers.symbols.values()
                if s.span.path == "dal.ts"
                and s.kind is SymbolKind.FUNCTION
                and s.span.start_line <= start <= s.span.end_line
            )
            span = SourceSpan(
                snapshot_id=snapshot.id,
                path="dal.ts",
                start_line=start,
                end_line=end,
                content_sha256=span_sha256(SOURCE, start, end),
            )
            site = AccessSite(
                id=f"site:{owner.name}:{start}",
                snapshot_id=snapshot.id,
                entry_point_id=f"entry:{owner.name}",
                resource="orders",
                operation=Operation.READ,
                key_origin=InputOrigin.PATH,
                data_layer=DataLayer.RAW_SQL,
                span=span,
            )
            paths.append(
                AccessPath(
                    site=site,
                    owner_symbol_id=owner.id,
                    key_expression="id",
                    possible_origins=[InputOrigin.PATH],
                    via_symbol_ids=[owner.id],
                    status=LinkStatus.RESOLVED,
                    reason="fixture access; actual compiler call edges",
                )
            )
        yield peers, AccessMap(snapshot_id=snapshot.id, accesses=paths)
    finally:
        index.close()


def test_only_exact_scoped_queries_vote_and_all_sites_remain_visible(
    fixture: tuple[PeerCheck, AccessMap],
) -> None:
    peers, access = fixture
    result = peers.build(access)
    guarded = {c.site_id for c in result.checks if c.guards}
    expected = {
        p.site.id
        for p in access.accesses
        if peers.symbols[p.owner_symbol_id].name == "scoped"
        or (peers.symbols[p.owner_symbol_id].name == "twoQueries" and p.site.span.start_line == 40)
    }
    assert guarded == expected
    assert len(guarded) == 2
    assert len(result.checks) == len(access.accesses) == len(result.groups[0].site_ids)
    assert result.groups[0].excluded == []
    for check in result.checks:
        if check.guards:
            assert len(check.evidence) >= 3
            assert all(not peers.classifier.validator.evidence(s) for s in check.evidence)


@pytest.mark.parametrize("caller,applies", [("direct", True), ("optional", False)])
def test_caller_path_must_be_unconditional(
    fixture: tuple[PeerCheck, AccessMap], caller: str, applies: bool
) -> None:
    peers, access = fixture
    path = next(p for p in access.accesses if peers.symbols[p.owner_symbol_id].name == "scoped")
    symbol = next(s for s in peers.symbols.values() if s.name == caller)
    path = path.model_copy(update={"via_symbol_ids": [symbol.id, path.owner_symbol_id]})
    result = peers.build(access.model_copy(update={"accesses": [path]}))
    assert bool(result.checks[0].guards) is applies
    assert result.groups[0].site_ids == [path.site.id]


def test_other_resource_or_unresolved_path_does_not_inherit_guard(
    fixture: tuple[PeerCheck, AccessMap],
) -> None:
    peers, access = fixture
    path = next(p for p in access.accesses if peers.symbols[p.owner_symbol_id].name == "scoped")
    for changed in (
        path.model_copy(update={"site": path.site.model_copy(update={"resource": "invoices"})}),
        path.model_copy(update={"status": LinkStatus.UNRESOLVED}),
    ):
        result = peers.build(access.model_copy(update={"accesses": [changed]}))
        assert not result.checks[0].guards
        assert result.groups[0].site_ids == [changed.site.id]
