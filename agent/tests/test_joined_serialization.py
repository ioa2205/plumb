"""Joined source provenance and packets; fixture judgments, never target execution."""

from pathlib import Path

import pytest

from agent.boundaries import finding
from agent.llm import Spend
from analysis.serialization import crossings, exposed, minimized
from backend.contracts.investigation import Budget, Conclusion

from .test_boundary_policies import CLIENT, Judge, context, declare, investigator

SQL = """const HEAD = `SELECT orders.id, orders.delivery_address,
branches.name AS branch, branches.phone AS branchPhone FROM orders`;
export const ORDER_SELECT = HEAD + ' JOIN branches ON branches.id = orders.branch_id';
"""
PAGE = """import { one } from '../db';
import { ORDER_SELECT as query } from '../sql';
import { Client } from './Client';
export default function Page({params}: {params: {id: number}}) {
  const row = one(`${query} WHERE orders.id = ?`, params.id);
  const dto = {...row};
  return <Client order={dto} />;
}
"""


@pytest.mark.parametrize("mode", ["spread", "member", "primary_phone", "unknown_sibling"])
def test_joined_columns_keep_resource_identity_and_constant_sql_exhibits(
    tmp_path: Path, mode: str
) -> None:
    sql, page = SQL, PAGE
    if mode == "member":
        page = page.replace(
            "{...row}",
            "{id: row.id, branch: row.branch, branchPhone: row.branchPhone}",
        )
    if mode == "primary_phone":
        sql = sql.replace("orders.id,", "orders.id, orders.phone,")
        page = page.replace("{...row}", "{...row, phone: row.phone}")
    if mode == "unknown_sibling":
        page = page.replace("{...row}", "{...row, transformed: unknown(row.id)}")
    with context(
        tmp_path, {"sql.ts": sql, "app/page.tsx": page, "app/Client.tsx": CLIENT}
    ) as review:
        entry_id = declare(review, fields=["phone"])
        entry = next(e.entry for e in review.nextjs.entries if e.entry.id == entry_id)
        path = next(p for p in review.access.accesses if p.site.entry_point_id == entry_id)
        facts = crossings(review.nextjs, entry.handler_symbol_id)
        fields = [f for c in facts for f in c.fields]
        foreign = next(f for f in fields if f.output == "order.branchPhone")
        assert foreign.field == "phone" and foreign.source_resource == "branches"
        assert foreign.query_resource == "orders" and foreign.source == path.site.span
        assert {(s.path, s.start_line, s.end_line) for s in foreign.evidence} >= {
            ("sql.ts", 1, 2),
            ("sql.ts", 3, 3),
        }
        witnesses = exposed(
            review.nextjs, entry.handler_symbol_id, path.owner_symbol_id, path.site.span, ["phone"]
        )
        assert bool(witnesses) == (mode == "primary_phone")
        assert all(f.source_resource == "orders" for _, f, _ in witnesses)
        assert minimized(
            review.nextjs, entry.handler_symbol_id, path.owner_symbol_id, path.site.span, ["phone"]
        ) == (mode in {"spread", "member"})
        judge = Judge(["phone"] if mode == "primary_phone" else [])
        check = investigator(review, judge)
        result = check.investigate(entry_id, judge, Spend(Budget(max_prompt_tokens=24000)))
        expected = (
            Conclusion.SUPPORTED
            if mode == "primary_phone"
            else Conclusion.INCONCLUSIVE
            if mode == "unknown_sibling"
            else Conclusion.REJECTED
        )
        assert result.conclusion is expected and len(result.samples) == 3, result.issues
        packet = next(r.user for r in judge.requests if r.name == "client_exposure")
        assert "const HEAD =" in packet and "export const ORDER_SELECT =" in packet
        case = finding(result, check, run_id="run:fixture", display_id="F-01")
        assert any("branches.phone" in e.gloss for e in case.exhibits)
        assert not check.classifier.validator.finding(case, guards=result.guards)
        if mode == "unknown_sibling":
            assert result.flow_unknowns == ["Indirect transformation unresolved"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT orders.id, branches.phone FROM orders "
        "JOIN branches ON branches.id = orders.branch_id",
        "SELECT id, branches.phone AS branchPhone FROM orders "
        "JOIN branches ON branches.id = orders.branch_id",
        "SELECT orders.id, unrelated.phone AS branchPhone FROM orders "
        "JOIN branches ON branches.id = orders.branch_id",
        "SELECT orders.id, branches.* FROM orders JOIN branches ON branches.id = orders.branch_id",
        "SELECT orders.id, branches.phone AS id FROM orders "
        "JOIN branches ON branches.id = orders.branch_id",
        "SELECT orders.id, branches.phone AS ID FROM orders "
        "JOIN branches ON branches.id = orders.branch_id",
        "SELECT o.id, b.phone AS branchPhone FROM orders AS o "
        "JOIN branches AS b ON b.id = o.branch_id",
        "SELECT orders.id FROM orders JOIN orders ON orders.id = orders.id",
        "SELECT orders.id, upper(branches.phone) AS branchPhone FROM orders "
        "JOIN branches ON branches.id = orders.branch_id",
        "SELECT orders.id FROM orders UNION SELECT phone FROM branches",
        "SELECT orders.id FROM orders /* JOIN branches */",
        "SELECT orders.id FROM orders; SELECT phone FROM branches",
        "SELECT orders.id FROM (SELECT id FROM orders)",
    ],
)
def test_unsupported_or_ambiguous_joined_projection_cannot_prove_omission(
    tmp_path: Path, sql: str
) -> None:
    # An absent output key also stays unknown; a valid sibling column cannot erase it.
    page = PAGE.replace("{...row}", "{id: row.id, branchPhone: row.branchPhone}")
    with context(
        tmp_path,
        {
            "sql.ts": f"export const ORDER_SELECT = `{sql}`;",
            "app/page.tsx": page,
            "app/Client.tsx": CLIENT,
        },
    ) as review:
        entry = next(e.entry for e in review.nextjs.entries if e.entry.route == "/")
        facts = crossings(review.nextjs, entry.handler_symbol_id)
        assert facts and any(c.unknowns for c in facts)
        for path in review.access.accesses:
            assert not minimized(
                review.nextjs,
                entry.handler_symbol_id,
                path.owner_symbol_id,
                path.site.span,
                ["phone"],
            )


@pytest.mark.parametrize(
    "declaration",
    [
        "declare const unknown: string; export const ORDER_SELECT = unknown;",
        "declare const unknown: string; "
        "export const ORDER_SELECT = `SELECT ${unknown} FROM orders`;",
        "const A = B; const B = A; export const ORDER_SELECT = A;",
        "let mutable = 'SELECT orders.id FROM orders'; export const ORDER_SELECT = mutable;",
    ],
)
def test_unbound_dynamic_cyclic_and_mutable_sql_are_not_constant_projection_evidence(
    tmp_path: Path, declaration: str
) -> None:
    with context(
        tmp_path, {"sql.ts": declaration, "app/page.tsx": PAGE, "app/Client.tsx": CLIENT}
    ) as review:
        entry = next(e.entry for e in review.nextjs.entries if e.entry.route == "/")
        facts = crossings(review.nextjs, entry.handler_symbol_id)
        assert facts and all(not c.fields and c.unknowns for c in facts)
