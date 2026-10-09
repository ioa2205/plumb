"""Exact scalar SQL source chains and fixtures; never execute analyzed code."""

import json
from pathlib import Path

import pytest

from agent.evidence import EvidencePacket
from agent.llm import Spend
from analysis.serialization import crossings, minimized
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.investigation import Budget, Conclusion
from backend.contracts.policies import FrozenPolicies
from backend.review import Review
from backend.settings import Settings

from .test_boundary_policies import CLIENT, PAGE, context, declare, investigator
from .test_client_boundary_packets import FieldJudge
from .test_field_packets import code
from .test_guards import DB


@pytest.mark.parametrize("form", ["rest", "positional", "alias"])
@pytest.mark.parametrize("omitted", [False, True])
def test_scalar_sql_packets_retain_execution_binding_and_protected_control(
    tmp_path: Path, form: str, omitted: bool
) -> None:
    page, db = PAGE, DB.decode()
    if form == "positional":
        db = db.replace("...params: unknown[]", "id: number").replace("get(...params)", "get(id)")
    elif form == "alias":
        page = page.replace("import { one }", "import { one as selectRecord }").replace(
            "one(", "selectRecord("
        )
    if omitted:
        page = page.replace("phone: row.phone, ", "")
    with context(tmp_path, {"db.ts": db, "app/page.tsx": page, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = FieldJudge([] if omitted else ["phone"])
        check = investigator(review, judge)
        path = next(p for p in check.paths.values() if p.site.entry_point_id == entry)
        packet = EvidencePacket.build(*check.field_cuts(entry, path, ["phone"]))
        text = code(packet)
        for fragment in [
            "import { DatabaseSync }",
            "new DatabaseSync",
            "export function one<T>",
            "prepare(sql).get(",
        ]:
            assert fragment in text
        assert ("import { one as selectRecord }" if form == "alias" else "import { one }") in text
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is (Conclusion.REJECTED if omitted else Conclusion.SUPPORTED)
        assert [s.seed for s in result.samples] == [42, 43, 44]
        assert all("export function one<T>" in r.user for r in judge.requests)


@pytest.mark.parametrize(
    "mode",
    [
        "wrong_sql",
        "wrong_param",
        "effect",
        "rebound",
        "fake_driver",
        "escaped",
        "modified_get",
        "type_only",
        "namespace",
        "default",
        "spread_destructure",
    ],
)
def test_unproven_scalar_execution_cannot_establish_omission(tmp_path: Path, mode: str) -> None:
    page = PAGE.replace("phone: row.phone, ", "")
    db = DB.decode()
    if mode == "wrong_sql":
        db = db.replace("prepare(sql)", "prepare('SELECT id FROM other')")
    elif mode == "wrong_param":
        db = db.replace("get(...params)", "get(42)")
    elif mode == "effect":
        db = db.replace("return db().prepare", "unknown(); return db().prepare")
    elif mode == "rebound":
        db += "one = other;\n"
    elif mode == "fake_driver":
        db = db.replace('new DatabaseSync(":memory:")', "new Counterfeit()")
        db += "declare class Counterfeit {prepare(sql: string): any;}\n"
    elif mode == "escaped":
        db += "unknown(connection);\n"
    elif mode == "modified_get":
        db += "unknown.get = replacement;\n"
    elif mode == "type_only":
        page = page.replace("import { one }", "import type { one }")
    elif mode == "namespace":
        page = page.replace("import { one }", "import * as queries").replace("one(", "queries.one(")
    elif mode == "default":
        db = db.replace("sql: string,", "sql: string = 'SELECT id FROM other',")
    elif mode == "spread_destructure":
        db += "unknown.get = replacement;\n"
        page = page.replace(
            "const dto = { deliveryAddress: row.delivery_address, id: row.id };\n"
            "  const alias = dto;",
            "const dto = {...row};\n  const { id: publicId } = dto;",
        ).replace("order={{...alias}}", "order={{id: publicId}}")
    with context(tmp_path, {"db.ts": db, "app/page.tsx": page, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        check = investigator(review, FieldJudge([]))
        handler = check.entries[entry].handler_symbol_id
        flows = crossings(review.nextjs, handler)
        assert flows and any(c.unknowns for c in flows)
        for path in check.paths.values():
            if path.site.entry_point_id == entry:
                assert not minimized(
                    review.nextjs, handler, path.owner_symbol_id, path.site.span, ["phone"]
                )
        result = check.investigate(entry, FieldJudge([]), Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is Conclusion.INCONCLUSIVE


@pytest.mark.parametrize("form", ["destructure", "object_spread", "jsx_spread", "includes"])
def test_helper_projection_keeps_runtime_import_evidence(tmp_path: Path, form: str) -> None:
    helper = """import { one } from './db';
export function load(id: number) {
  const row = one('SELECT id, phone FROM orders WHERE id = ?', id);
  return { id: row.id, phone: row.phone };
}
"""
    projection = {
        "destructure": (
            "const {phone: phoneValue, id} = dto; "
            "return <Client order={{phone: phoneValue, id: id}} />;"
        ),
        "object_spread": "const copy = {...dto}; return <Client order={copy} />;",
        "jsx_spread": "return <Client {...dto} />;",
        "includes": "return <Client order={{phone: ['+998'].includes(dto.phone), id: dto.id}} />;",
    }[form]
    page = f"""import {{ load }} from '../load';
import {{ Client }} from './Client';
export default function Page({{params}}: {{params: {{id: number}}}}) {{
  const dto = load(params.id);
  {projection}
}}
"""
    with context(
        tmp_path, {"load.ts": helper, "app/page.tsx": page, "app/Client.tsx": CLIENT}
    ) as review:
        entry = declare(review, fields=["phone"])
        judge = FieldJudge(["phone"])
        check = investigator(review, judge)
        path = next(p for p in check.paths.values() if p.site.entry_point_id == entry)
        packet = EvidencePacket.build(*check.field_cuts(entry, path, ["phone"]))
        text = code(packet)
        for fragment in ["import { load }", "import { one }", "export function one<T>"]:
            assert fragment in text
        assert not any(
            c.unknowns for c in crossings(review.nextjs, check.entries[entry].handler_symbol_id)
        )
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is Conclusion.SUPPORTED


def test_unrelated_same_named_wrapper_is_not_query_evidence(tmp_path: Path) -> None:
    extra = "export function one(sql: string) { return 'unrelated wrapper'; }\n"
    with context(
        tmp_path, {"app/page.tsx": PAGE, "app/Client.tsx": CLIENT, "unrelated.ts": extra}
    ) as review:
        entry = declare(review, fields=["phone"])
        check = investigator(review, FieldJudge(["phone"]))
        path = next(p for p in check.paths.values() if p.site.entry_point_id == entry)
        packet = EvidencePacket.build(*check.field_cuts(entry, path, ["phone"]))
        assert "unrelated wrapper" not in code(packet)
        assert all(part.path != "unrelated.ts" for part in packet.excerpts)


def test_actual_d2_retains_scalar_wrapper_driver_and_caller_imports(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    prepared = json.loads(
        (root / "docs/results/2026-10-08-m6.9v-phone-client-binding-preparation.json").read_bytes()
    )
    original = json.loads(
        (root / "docs/results/2026-10-08-m6.9v-phone-client-binding-execution.json").read_bytes()
    )
    settings = Settings(data_dir=tmp_path / "data")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(root / "labs/tandir", store)
    review = Review(settings, snapshot.id)
    try:
        review.policies = FrozenPolicies.model_validate(prepared["requirements"])
        check = investigator(review, FieldJudge(["phone"]))
        entry = next(e.entry for e in review.nextjs.entries if e.entry.route == "/courier/[id]")
        path = next(
            p
            for p in check.paths.values()
            if p.site.entry_point_id == entry.id and p.site.resource == "users"
        )
        packet = EvidencePacket.build(*check.field_cuts(entry.id, path, ["phone"]))
        text = code(packet)
        for fragment in [
            "export function one<T>",
            "prepare(sql).get(...params)",
            "import { getDelivery }",
            "import { all, one, run }",
            "import { DatabaseSync",
            "new DatabaseSync",
            '"use client";',
            "phone: user.phone",
            "customer={delivery.customer}",
        ]:
            assert fragment in text
        assert not any(c.unknowns for c in crossings(review.nextjs, entry.handler_symbol_id))
        saved = next(r for r in original["records"] if r["case_id"] == "TANDIR-D2")
        assert saved["questions"][0]["answer"]["result"]["conclusion"] == "inconclusive"
        assert [
            r["answer"]
            for r in saved["requests"]
            if r["body"].get("response_format", {}).get("json_schema", {}).get("name")
            == "client_exposure"
        ] == [{"fields": []}] * 3
        assert len(packet.line_ids) <= 80
    finally:
        review.close()
