"""Static owned-fixture guard proofs with the actual compiler; no target execution."""

import re
from collections.abc import Iterator

import pytest

from agent.guard_syntax import Check, checks
from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.peers import PeerCheck
from analysis.access import AccessMap, AccessPath
from analysis.index import Index, index_path
from analysis.resolution import CallGraph, LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import _parser, _text, _walk, span_sha256
from analysis.typescript_resolution import resolve_typescript
from backend.contracts.code import (
    AccessSite,
    DataLayer,
    GuardKind,
    Operation,
    SourceSpan,
    SymbolKind,
)
from backend.contracts.common import InputOrigin, Language
from backend.settings import Settings

from .test_guards import DB

CLIENT = (
    b'import { PrismaClient } from "@prisma/client";\nexport const client = new PrismaClient();\n'
)
KEYED = b"""import { client } from "./client";
export async function scoped(id: number, viewer: {id: number}) {
  const row = await client.order.findUnique({where: {id, customerId: viewer.id}});
  return row;
}
"""


def keyed_facts(source: bytes = KEYED, client: bytes = CLIENT) -> list[Check]:
    return checks(
        Language.TYPESCRIPT,
        source,
        1,
        len(source.splitlines()),
        path="dal.ts",
        read=lambda p: client if p == "client.ts" else None,
    )


def test_keyed_filter_needs_executable_client_and_literal_predicate() -> None:
    facts = checks(
        Language.TYPESCRIPT,
        KEYED,
        1,
        len(KEYED.splitlines()),
        path="dal.ts",
        read=lambda p: CLIENT if p == "client.ts" else None,
    )
    assert len(facts) == 1
    assert facts[0].pairs == (("customerId", "viewer.id"),) and facts[0].resource == "order"
    assert [c.label for c in facts[0].context] == ["orm import", "orm instance"]


@pytest.mark.parametrize(
    "old,new",
    [
        (b"{id, customerId: viewer.id}", b"{id, OR: [{customerId: viewer.id}, {}]}"),
        (b"{id, customerId: viewer.id}", b"{id, customerId: {not: viewer.id}}"),
        (b"{id, customerId: viewer.id}", b"{id, ...claimed, customerId: viewer.id}"),
        (b"{id, customerId: viewer.id}", b"{id, customerId: viewer.id, customerId: other.id}"),
        (b"{id, customerId: viewer.id}", b"{id, [field]: viewer.id}"),
        (b"const row =", b"client.order = fake;\n  const row ="),
        (b"const row =", b"mutate(client);\n  const row ="),
        (b"const row =", b"if (enabled) return null;\n  const row ="),
        (b"const row =", b"if (enabled) { const row ="),
        (b"viewer: {id: number}", b"viewer: {id: number}, client: any"),
    ],
)
def test_keyed_unsupported_or_modified_query_never_confirms(old: bytes, new: bytes) -> None:
    assert not keyed_facts(KEYED.replace(old, new))


@pytest.mark.parametrize(
    "client",
    [
        CLIENT.replace(b"@prisma/client", b"./fake"),
        CLIENT.replace(b"new PrismaClient()", b"fakeClient()"),
        CLIENT.replace(b"export const", b"const"),
        CLIENT.replace(b"const client", b"let client"),
        CLIENT + b"client.order = replacement;\n",
        CLIENT + b"mutate(client);\n",
        CLIENT.replace(b"export const", b"// export const client\nconst"),
    ],
)
def test_client_names_and_comments_do_not_prove_orm_behavior(client: bytes) -> None:
    assert not keyed_facts(client=client)


DENIAL = b"""export function check(row, viewer) {
  if (row.branch_id !== viewer.branch_id) return Response.json({detail: "Denied"}, {status: 403});
  return row;
}
"""


@pytest.mark.parametrize(
    "old,new",
    [
        (b"!==", b"==="),
        (b"row.branch_id !== viewer.branch_id", b"row.branch_id !== viewer.branch_id && enabled"),
        (b"if (row", b"if (enabled) { if (row"),
        (b"  if (row", b"  try {\n  if (row"),
        (b"return Response.json", b"Response.json"),
        (b"status: 403", b"status: 200"),
        (b"row, viewer", b"row, viewer, Response"),
        (b"  if (row", b"  viewer.branch_id = row.branch_id;\n  if (row"),
        (b"  if (row", b"  return row;\n  if (row"),
    ],
)
def test_nonmandatory_field_denial_is_not_a_guard(old: bytes, new: bytes) -> None:
    source = DENIAL.replace(old, new)
    assert not checks(
        Language.TYPESCRIPT,
        source,
        1,
        len(source.splitlines()),
        path="guard.ts",
        read=lambda _: None,
    )


def test_or_denial_requires_every_bound_equality_on_continuation() -> None:
    source = DENIAL.replace(
        b"row.branch_id !== viewer.branch_id",
        b"row.branch_id !== viewer.branch_id || row.customer_id !== viewer.id",
    )
    found = checks(
        Language.TYPESCRIPT,
        source,
        1,
        len(source.splitlines()),
        path="guard.ts",
        read=lambda _: None,
    )
    assert len(found) == 1
    assert found[0].pairs == (
        ("row.branch_id", "viewer.branch_id"),
        ("row.customer_id", "viewer.id"),
    )


SOURCE = b"""import { redirect } from "next/navigation";
import { one } from "./db";
import { client } from "./client";
declare function lookup(): Promise<{id: number, branch_id: number, role: string} | null>;
export async function session() {
  const viewer = await lookup();
  if (!viewer) redirect("/login");
  return viewer;
}
export async function aliasSession() {
  const viewer = await lookup();
  if (!viewer) redirect("/login");
  const authenticated = viewer;
  return authenticated;
}
export async function wrongSession() {
  const viewer = await lookup();
  if (!viewer) redirect("/login");
  const authenticated = other;
  return authenticated;
}
export async function keyed(id: number) {
  const viewer = await session();
  const row = await client.order.findUnique({where: {id, customerId: viewer.id}});
  return row;
}
export async function aliased(id: number) {
  const viewer = await aliasSession();
  const identity = viewer;
  const row = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, identity.id);
  return row;
}
export async function conditional(id: number) {
  const viewer = await session();
  const row = one("SELECT * FROM orders WHERE id = ?", id);
  if (row.customer_id !== viewer.id) return Response.json({detail: "Denied"}, {status: 403});
  return row;
}
export async function tenant(id: number) {
  const viewer = await session();
  const row = one("SELECT * FROM orders WHERE id = ?", id);
  if (row.branch_id !== viewer.branch_id) return Response.json({detail: "Denied"}, {status: 403});
  return row;
}
export async function role(id: number) {
  const viewer = await session();
  if (viewer.role !== "admin") return Response.json({detail: "Denied"}, {status: 403});
  const row = one("SELECT * FROM orders WHERE id = ?", id);
  return row;
}
export async function supplied(id: number, viewer: {id: number}) {
  const row = await client.order.findUnique({where: {id, customerId: viewer.id}});
  return row;
}
export async function wrongIdentity(id: number) {
  const viewer = await wrongSession();
  const row = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  return row;
}
export async function exposed(id: number) {
  const viewer = await session();
  const row = one("SELECT * FROM orders WHERE id = ?", id);
  disclose(row);
  if (row.customer_id !== viewer.id) return Response.json({detail: "Denied"}, {status: 403});
  return row;
}
export async function unrelated(id: number) {
  const viewer = await session();
  const row = one("SELECT * FROM orders WHERE id = ?", id);
  if (other.customer_id !== viewer.id) return Response.json({detail: "Denied"}, {status: 403});
  return row;
}
export async function optional(id: number, enabled: boolean) {
  if (enabled) return aliased(id);
  return null;
}
export async function direct(id: number) {
  return aliased(id);
}
"""


class Model:
    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        fields = request.schema["properties"]["guards"]["items"]["properties"]
        kinds = fields["kind"]["enum"]
        subject = obj = None
        if "authenticated" in kinds:
            kind = "authenticated"
        elif "role" in kinds:
            kind = "role"
        else:
            subjects = fields["subject"]["enum"]
            objects = fields["object"]["enum"]
            subject = next(s for s in subjects if s and s.startswith(("viewer.", "identity.")))
            obj = next(s for s in objects if s and not s.startswith(("viewer.", "identity.")))
            kind = "tenant" if "branch_id" in obj else "owner"
        return JsonAnswer(
            {
                "guards": [
                    {
                        "kind": kind,
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
    root = tmp_path_factory.mktemp("guard-forms")
    project = root / "project"
    project.mkdir()
    for path, data in {"dal.ts": SOURCE, "db.ts": DB, "client.ts": CLIENT}.items():
        (project / path).write_bytes(data)
    store = SnapshotStore(root / "snapshots")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, index_path(root, snapshot.id))
    try:
        graph = resolve_typescript(snapshot, store, index, root)
        python = CallGraph(
            snapshot_id=snapshot.id, language="python", resolver_version="fixture", edges=[]
        )
        classifier = Classifier(
            snapshot, store, Model(), SummaryCache(root / "guards.sqlite"), identity="fixture"
        )
        peers = PeerCheck(classifier, index, python, Settings(), typescript_graph=graph)
        tree = _parser(Language.TYPESCRIPT).parse(SOURCE)
        paths = []
        for node in _walk(tree.root_node):
            callee = (
                _text(node.child_by_field_name("function"))
                if node.type == "call_expression"
                else ""
            )
            if callee not in ("one", "client.order.findUnique"):
                continue
            start, end = node.start_point.row + 1, node.end_point.row + 1
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
                resource="order" if callee.startswith("client") else "orders",
                operation=Operation.READ,
                key_origin=InputOrigin.PATH,
                data_layer=DataLayer.PRISMA if callee.startswith("client") else DataLayer.RAW_SQL,
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
                    reason="Frozen fixture with actual compiler graph",
                )
            )
        yield peers, AccessMap(snapshot_id=snapshot.id, accesses=paths)
    finally:
        index.close()


def test_exact_queries_receive_only_their_source_bound_guard(
    fixture: tuple[PeerCheck, AccessMap],
) -> None:
    peers, access = fixture
    result = peers.build(access)
    by_site = {p.site.id: peers.symbols[p.owner_symbol_id].name for p in access.accesses}
    actual = {by_site[c.site_id]: {g.kind for g in c.guards} for c in result.checks}
    assert actual == {
        "keyed": {GuardKind.OWNER},
        "aliased": {GuardKind.OWNER},
        "conditional": {GuardKind.OWNER},
        "tenant": {GuardKind.TENANT},
        "role": {GuardKind.ROLE},
        "supplied": set(),
        "wrongIdentity": set(),
        "exposed": set(),
        "unrelated": set(),
    }
    assert sum(len(g.site_ids) for g in result.groups) == len(access.accesses)
    assert all(not g.excluded for g in result.groups)
    for record in result.checks:
        for span in record.evidence:
            assert not peers.classifier.validator.evidence(span)
        for guard in record.guards:
            assert peers.classifier.validator.confirm(
                guard, subject=guard.subject, object=guard.object
            ).confirmed


def test_wrong_resource_and_optional_caller_cannot_inherit_alias_guard(
    fixture: tuple[PeerCheck, AccessMap],
) -> None:
    peers, access = fixture
    path = next(p for p in access.accesses if peers.symbols[p.owner_symbol_id].name == "aliased")
    for caller, guarded in [("direct", True), ("optional", False)]:
        symbol = next(s for s in peers.symbols.values() if s.name == caller)
        changed = path.model_copy(update={"via_symbol_ids": [symbol.id, path.owner_symbol_id]})
        result = peers.build(access.model_copy(update={"accesses": [changed]}))
        assert bool(result.checks[0].guards) is guarded
    for name in ("conditional", "role", "keyed"):
        path = next(p for p in access.accesses if peers.symbols[p.owner_symbol_id].name == name)
        wrong = path.model_copy(update={"site": path.site.model_copy(update={"resource": "other"})})
        result = peers.build(access.model_copy(update={"accesses": [wrong]}))
        assert not result.checks[0].guards
