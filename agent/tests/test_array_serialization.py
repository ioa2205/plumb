"""Bounded array source pairs; fixture judgments, never inference or target execution."""

from pathlib import Path

import pytest

from agent.boundaries import finding
from agent.llm import Spend
from analysis.serialization import crossings, exposed, minimized
from backend.contracts.investigation import Budget, Conclusion

from .test_boundary_policies import CLIENT, Judge, context, declare, investigator
from .test_guards import DB

ARRAY_DB = (
    DB.decode()
    + """
export function all<T>(sql: string, ...params: unknown[]): T[] {
  return db().prepare(sql).all(...params) as T[];
}
"""
)
DTO = """import {all} from './db';
const STATES = ['placed', 'baking'];
type Row = {id: number, status: string, phone: string};
function project(row: Row) {
  return {id: row.id, status: row.status, cancellable: STATES.includes(row.status)};
}
export function get(id: number) {
  const rows = all<Row>('SELECT id, status, phone FROM orders WHERE id = ?', id);
  return rows.map(project);
}
"""
PAGE = """import {get} from '../dto';
import {Client} from './Client';
export default function Page({params}: {params: {id: number}}) {
  const rows = get(params.id);
  return <Client orders={rows} />;
}
"""


@pytest.mark.parametrize("mode", ["protected", "unsafe", "inline", "nested_helper"])
def test_exact_row_map_and_literal_membership_keep_field_proofs(tmp_path: Path, mode: str) -> None:
    dto = DTO
    if mode == "unsafe":
        dto = dto.replace("id: row.id,", "id: row.id, phone: row.phone,")
    if mode == "inline":
        dto = dto.replace(
            "rows.map(project)", "rows.map(row => ({id: row.id, status: row.status}))"
        )
    if mode == "nested_helper":
        dto = dto.replace("return {id: row.id,", "return {nested: nested(row), id: row.id,")
        dto += "function nested(row: Row) { return {state: row.status}; }\n"
    with context(
        tmp_path, {"db.ts": ARRAY_DB, "dto.ts": dto, "app/page.tsx": PAGE, "app/Client.tsx": CLIENT}
    ) as review:
        entry_id = declare(review, fields=["phone"])
        entry = next(e.entry for e in review.nextjs.entries if e.entry.id == entry_id)
        path = next(p for p in review.access.accesses if p.site.entry_point_id == entry_id)
        facts = crossings(review.nextjs, entry.handler_symbol_id)
        assert facts and not any(c.unknowns for c in facts)
        fields = [f for c in facts for f in c.fields]
        assert any(f.field == "id" and f.output == "orders[].id" for f in fields)
        assert all(f.source_resource == f.query_resource == "orders" for f in fields)
        assert all(
            not review.sinks.validator.evidence(s) for f in fields for s in [f.source, *f.evidence]
        )
        witnesses = exposed(
            review.nextjs, entry.handler_symbol_id, path.owner_symbol_id, path.site.span, ["phone"]
        )
        assert bool(witnesses) == (mode == "unsafe")
        assert minimized(
            review.nextjs, entry.handler_symbol_id, path.owner_symbol_id, path.site.span, ["phone"]
        ) == (mode != "unsafe")
        judge = Judge(["phone"] if mode == "unsafe" else [])
        check = investigator(review, judge)
        result = check.investigate(entry_id, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is (
            Conclusion.SUPPORTED if mode == "unsafe" else Conclusion.REJECTED
        ), result.issues
        assert len(result.samples) == 3
        assert not check.classifier.validator.finding(
            finding(result, check, run_id="run:fixture", display_id="F-01"), guards=result.guards
        )
        packet = next(r.user for r in judge.requests if r.name == "client_exposure")
        assert "new DatabaseSync" in packet and "prepare(sql).all" in packet


@pytest.mark.parametrize(
    "mode",
    [
        "literal_mutated",
        "literal_alias_mutated",
        "literal_escaped",
        "prototype",
        "row_alias_mutated",
        "row_escaped",
        "optional_map",
        "computed_map",
        "this_arg",
        "callback_effect",
        "callback_mutation",
        "callback_default",
        "callback_extra_parameter",
        "callback_unknown",
        "callback_capture",
        "unknown_sibling",
        "fake_driver",
        "factory_unknown_return",
        "driver_escaped",
        "wrapper_effect",
        "row_arrays",
        "merged_array",
        "custom_map",
        "depth",
        "callback_rebound",
        "async_callback",
        "generator_callback",
        "wrapper_rebound",
        "factory_async",
        "nested_helper_rebound",
    ],
)
def test_unknown_or_mutated_array_transforms_never_establish_omission(
    tmp_path: Path, mode: str
) -> None:
    dto, db = DTO, ARRAY_DB
    additions = {
        "literal_mutated": "STATES.push('other');",
        "literal_alias_mutated": "const alias = STATES; alias.push('other');",
        "literal_escaped": "unknown(STATES);",
        "prototype": "Array.prototype.map = unknown;",
        "row_arrays": "declare const statement: any; statement.setReturnArrays(true);",
        "merged_array": "declare global { interface Array<T> { map: any; } }",
    }
    if mode in additions:
        dto += additions[mode]
    changes = {
        "row_alias_mutated": (
            "return rows.map(project);",
            "const alias = rows; alias.map = unknown; return rows.map(project);",
        ),
        "row_escaped": ("return rows.map(project);", "unknown(rows); return rows.map(project);"),
        "optional_map": ("rows.map(project)", "rows?.map(project)"),
        "computed_map": ("rows.map(project)", "rows['map'](project)"),
        "this_arg": ("rows.map(project)", "rows.map(project, external)"),
        "callback_effect": ("return {id: row.id,", "unknown(); return {id: row.id,"),
        "callback_mutation": ("return {id: row.id,", "row.phone = 'changed'; return {id: row.id,"),
        "callback_default": ("project(row: Row)", "project(row: Row = unknown())"),
        "callback_extra_parameter": ("project(row: Row)", "project(row: Row, array: Row[])"),
        "callback_unknown": ("rows.map(project)", "rows.map(unknown)"),
        "callback_capture": ("return {id: row.id,", "return {captured: outside.phone, id: row.id,"),
        "unknown_sibling": (
            "return {id: row.id,",
            "return {extra: unknown(row.phone), id: row.id,",
        ),
        "custom_map": (
            "return rows.map(project);",
            "const fake = {map: project}; return fake.map(rows);",
        ),
        "depth": ("return {id: row.id,", "return {deep: a(row), id: row.id,"),
    }
    if mode in changes:
        dto = dto.replace(*changes[mode])
    if mode == "depth":
        dto += (
            "function a(r: Row) { return b(r); }\n"
            "function b(r: Row) { return c(r); }\n"
            "function c(r: Row) { return {phone: r.phone}; }\n"
        )
    if mode == "callback_rebound":
        dto += "project = unknown;\n"
    if mode == "async_callback":
        dto = dto.replace("function project", "async function project")
    if mode == "generator_callback":
        dto = dto.replace("function project", "function* project")
    if mode == "wrapper_rebound":
        db += "all = unknown;\n"
    if mode == "factory_async":
        db = db.replace("function db", "async function db")
    if mode == "nested_helper_rebound":
        dto = dto.replace("return {id: row.id,", "return {nested: nested(row), id: row.id,")
        dto += "function nested(row: Row) { return {state: row.status}; }\nnested = unknown;\n"
    if mode == "fake_driver":
        db = db.replace('new DatabaseSync(":memory:")', "new Counterfeit()")
        db += "declare class Counterfeit { prepare(sql: string): any; }\n"
    if mode == "factory_unknown_return":
        db = db.replace("return connection.db;", "return external;")
    if mode == "driver_escaped":
        db += "unknown(connection);\n"
    if mode == "wrapper_effect":
        db = db.replace("return db().prepare(sql).all", "unknown(); return db().prepare(sql).all")
    with context(
        tmp_path, {"db.ts": db, "dto.ts": dto, "app/page.tsx": PAGE, "app/Client.tsx": CLIENT}
    ) as review:
        entry = next(e.entry for e in review.nextjs.entries if e.entry.route == "/")
        facts = crossings(review.nextjs, entry.handler_symbol_id)
        assert facts and any(c.unknowns for c in facts), mode
        for path in review.access.accesses:
            assert not minimized(
                review.nextjs,
                entry.handler_symbol_id,
                path.owner_symbol_id,
                path.site.span,
                ["phone"],
            ), mode
