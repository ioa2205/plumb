"""Focused source packets and fixture judgments; no model or target execution."""

import json
from pathlib import Path

import pytest

from agent.boundaries import finding
from agent.evidence import EvidencePacket
from agent.llm import Spend
from analysis.serialization import crossings
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.code import GuardKind
from backend.contracts.investigation import Budget, Conclusion
from backend.contracts.policies import FrozenPolicies
from backend.review import Review
from backend.settings import Settings

from .test_boundary_policies import CLIENT, PAGE, Judge, context, declare, investigator


def code(packet: EvidencePacket) -> str:
    return "\n".join(line.text for part in packet.excerpts for line in part.lines)


def test_focused_chain_keeps_helper_parameters_and_removes_unrelated_body(tmp_path: Path) -> None:
    page = """import { load } from '../load';
import { audit } from '../audit';
import { Client } from './Client';
export default function Page({params}: {params: {id: number}}) {
  const unrelated = audit();
  const dto = load(params.id);
  return <Client order={dto} />;
}
"""
    helpers = {
        "load.ts": """import { fetch } from './fetch';
import { project } from './project';
export function load(id: number) {
  const row = fetch(id);
  return project(row);
}
""",
        "fetch.ts": """import { one } from './db';
export function fetch(id: number) {
  return one('SELECT id, phone FROM orders WHERE id = ?', id);
}
""",
        "project.ts": """export function project(value: any) {
  const dto = {id: value.id, phone: value.phone};
  return dto;
}
""",
        "audit.ts": "export function audit() {\n  return 'unrelated-body';\n}\n",
    }
    with context(tmp_path, {"app/page.tsx": page, "app/Client.tsx": CLIENT, **helpers}) as review:
        entry = declare(review, fields=["phone"])
        check = investigator(review, Judge())
        path = next(p for p in check.paths.values() if p.site.entry_point_id == entry)
        full = EvidencePacket.build(*check.cuts(entry))
        focused = EvidencePacket.build(*check.field_cuts(entry, path, ["phone"]))
        text = code(focused)
        for fragment in (
            "load(params.id)",
            "function load(id",
            "fetch(id)",
            "function fetch(id",
            "SELECT id, phone FROM orders",
            "project(row)",
            "function project(value",
            "phone: value.phone",
            "<Client order={dto}",
            "const unrelated = audit()",
        ):
            assert fragment in text
        assert "unrelated-body" in code(full) and "unrelated-body" not in text
        assert len(focused.line_ids) < len(full.line_ids)
        for flow in crossings(review.nextjs, check.entries[entry].handler_symbol_id):
            for field in flow.fields:
                if field.field == "phone":
                    for span in [flow.span, field.source, *field.evidence]:
                        assert not check.classifier.validator.evidence(span)
                        assert any(
                            focused.location(line) == (span.path, span.start_line)
                            for line in focused.line_ids
                        )
        assert all(part.label.startswith("part ") for part in focused.excerpts)


@pytest.mark.parametrize("mode", ["spread", "conditional", "mutation", "graph", "conflict"])
def test_unknown_mutated_missing_and_conflicting_context_is_not_trimmed(
    tmp_path: Path, mode: str
) -> None:
    page, helpers = PAGE, {}
    if mode == "spread":
        page = page.replace("const alias = dto;", "const alias = {...dto, ...transform(row)};")
    elif mode == "conditional":
        page = page.replace(
            "const alias = dto;", "if (flag) return <Client order={row}/>;\n  const alias = dto;"
        )
    elif mode == "mutation":
        page = page.replace(
            "import { Client }", "import { project } from '../project';\nimport { Client }"
        ).replace(
            "{ deliveryAddress: row.delivery_address, phone: row.phone, id: row.id }",
            "project(row)",
        )
        helpers["project.ts"] = (
            "export let project = (value: any) => ({phone: value.phone, id: value.id});\n"
            "project = transform;\n"
        )
    elif mode == "graph":
        page = PAGE.replace(
            "import { one } from '../db';", "import { fetch } from '../fetch';"
        ).replace(
            "one('SELECT id, delivery_address, phone FROM orders WHERE id = ?', params.id)",
            "fetch(params.id)",
        )
        helpers["fetch.ts"] = (
            "import { one } from './db';\nexport function fetch(id: number) {\n"
            "  return one('SELECT id, delivery_address, phone FROM orders WHERE id = ?', id);\n}\n"
        )
    with context(tmp_path, {"app/page.tsx": page, "app/Client.tsx": CLIENT, **helpers}) as review:
        entry = declare(review, fields=["phone"])
        if mode == "conflict":
            policy = review.policies.policies[0]
            policies = [
                policy.model_copy(
                    update={
                        "assertion": policy.assertion.model_copy(
                            update={
                                "id": f"policy:conflict-{i}",
                                "kind": GuardKind.ROLE,
                                "canonical": f"role({i})",
                            }
                        )
                    }
                )
                for i in range(2)
            ]
            review.policies = FrozenPolicies(snapshot_id=review.snapshot.id, policies=policies)
        check = investigator(review, Judge())
        path = next(p for p in check.paths.values() if p.site.entry_point_id == entry)
        if mode == "graph":
            check.graph = check.graph.model_copy(update={"edges": []})
        assert check.field_cuts(entry, path, ["phone"]) == check.cuts(entry)


def test_matching_field_from_another_access_is_retained_and_cannot_answer_the_rule(
    tmp_path: Path,
) -> None:
    page = """import { one } from '../db';
import { Client } from './Client';
export default function Page({params}: {params: {id: number}}) {
  const primary = one('SELECT id FROM orders WHERE id = ?', params.id);
  const row = one('SELECT id, phone FROM users WHERE id = ?', params.id);
  const dto = {id: primary.id, phone: row.phone};
  return <Client order={dto}/>;
}
"""
    with context(tmp_path, {"app/page.tsx": page, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge(["phone"])
        check = investigator(review, judge)
        path = next(p for p in check.paths.values() if p.site.resource == "orders")
        text = code(EvidencePacket.build(*check.field_cuts(entry, path, ["phone"])))
        assert "FROM orders" in text and "FROM users" in text and "phone: row.phone" in text
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is Conclusion.INCONCLUSIVE
        assert len(result.samples) == 3 and all(s.violations for s in result.samples)
        assert all("orders access starting on L" in r.user for r in judge.requests)


@pytest.mark.parametrize("mode", ["empty", "disagree", "correct"])
def test_focused_fixture_answers_keep_three_judgments_and_empty_misses(
    tmp_path: Path, mode: str
) -> None:
    with context(tmp_path, {"app/page.tsx": PAGE, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge([] if mode == "empty" else ["phone"], disagree=mode == "disagree")
        check = investigator(review, judge)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is (
            Conclusion.SUPPORTED if mode == "correct" else Conclusion.INCONCLUSIVE
        )
        assert [s.seed for s in result.samples] == [42, 43, 44]
        assert len(judge.requests) == 3
        assert not check.classifier.validator.finding(
            finding(result, check, run_id="run:fixture", display_id="F-01"), guards=result.guards
        )


def test_stale_focus_and_corrupt_flow_source_refuse_before_judgment(tmp_path: Path) -> None:
    with context(tmp_path, {"app/page.tsx": PAGE, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge()
        check = investigator(review, judge)
        path = next(p for p in check.paths.values() if p.site.entry_point_id == entry)
        with pytest.raises(ValueError, match="exact access"):
            check.field_cuts(entry, path.model_copy(update={"key_expression": "forged"}), ["phone"])
        flow = crossings(check.nextjs, check.entries[entry].handler_symbol_id)[0]
        corrupt = flow.fields[0].model_copy(
            update={"source": flow.fields[0].source.model_copy(update={"content_sha256": "0" * 64})}
        )
        check.nextjs = check.nextjs.model_copy(
            update={"serializations": [flow.model_copy(update={"fields": [corrupt]})]}
        )
        with pytest.raises(ValueError, match="citation cannot be validated"):
            check.field_cuts(entry, path, ["phone"])
        assert not judge.requests


def test_source_limit_is_not_bypassed_by_field_focus(tmp_path: Path) -> None:
    page = PAGE.replace(
        "  const row =", "".join(f"  const unused{i} = {i};\n" for i in range(85)) + "  const row ="
    )
    with context(tmp_path, {"app/page.tsx": page, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge()
        with pytest.raises(ValueError, match="80"):
            investigator(review, judge).investigate(entry, judge, Spend(Budget()))
        assert not judge.requests


def test_actual_tandir_phone_chain_keeps_each_query_and_binding_without_inference(
    tmp_path: Path, recorded_lab: Path
) -> None:
    root = Path(__file__).resolve().parents[2]
    prepared = json.loads(
        (root / "docs/results/2026-10-08-m6.9k-nextjs-preparation.json").read_text(encoding="utf-8")
    )
    original = json.loads(
        (root / "docs/results/2026-10-08-m6.9k-nextjs-execution.json").read_text(encoding="utf-8")
    )
    record = next(r for r in original["records"] if r["case_id"] == "TANDIR-D2")
    settings = Settings(data_dir=tmp_path / "data")
    snapshot = take_snapshot(recorded_lab, SnapshotStore(settings.cache_dir / "snapshots"))
    review = Review(settings, snapshot.id)
    try:
        review.policies = FrozenPolicies.model_validate(prepared["requirements"])
        check = investigator(review, Judge())
        entry = next(e.entry for e in review.nextjs.entries if e.entry.route == "/courier/[id]")
        path = next(
            p
            for p in check.paths.values()
            if p.site.entry_point_id == entry.id and p.site.resource == "users"
        )
        full = EvidencePacket.build(*check.cuts(entry.id))
        focused = EvidencePacket.build(*check.field_cuts(entry.id, path, ["phone"]))
        text = code(focused)
        for fragment in (
            "function customerRecord(customerId",
            "FROM users WHERE id = ?",
            "customerId,",
            "phone: user.phone",
            "export async function getDelivery(",
            "orderId: number,",
            "customerRecord(order.customer_id)",
            "getDelivery(Number(id))",
            "customer={delivery.customer}",
        ):
            assert fragment in text
        assert len(focused.line_ids) < len(full.line_ids)
        assert snapshot.id == record["snapshot"]["id"]
        # Preserve the raw failed attempt; a changed packet cannot replay its answer.
        assert record["questions"][0]["answer"]["result"]["conclusion"] == "inconclusive"
        answers = [
            json.loads(r["raw_answer"])
            for r in record["requests"]
            if r["body"].get("response_format", {}).get("json_schema", {}).get("name")
            == "client_exposure"
        ]
        assert answers == [{"fields": []}] * 3
    finally:
        review.close()
