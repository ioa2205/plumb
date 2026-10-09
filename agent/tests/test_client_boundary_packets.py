"""Frozen client module bindings; fixture questions never execute target code."""

import json
import re
from pathlib import Path

import pytest

from agent.evidence import EvidencePacket
from agent.llm import JsonAnswer, ModelRequest, Spend
from analysis.serialization import crossings
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.investigation import Budget, Conclusion
from backend.contracts.policies import FrozenPolicies
from backend.review import Review
from backend.settings import Settings

from .test_boundary_policies import CLIENT, PAGE, Judge, context, declare, investigator
from .test_field_packets import code


class FieldJudge(Judge):
    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        if request.name != "client_exposure":
            return super().ask(request, spend)
        self.requests.append(request)
        lines = re.findall(r"(L\d+)\s+.*?(?:row\.phone|return <)", request.user)
        data = {"fields": [{"name": name, "line_ids": lines} for name in self.fields]}
        return JsonAnswer(data, json.dumps(data), 1, 1, 0)


@pytest.mark.parametrize(
    "binding", ["direct", "alias", "reexport", "default", "multiline", "const"]
)
def test_frozen_directive_import_export_chain_is_in_every_field_packet(
    tmp_path: Path, binding: str
) -> None:
    page, client, extra = PAGE, CLIENT, {}
    expected = ["import { Client }", "export function Client"]
    if binding == "alias":
        page = page.replace("import { Client }", "import { Client as Panel }").replace(
            "<Client ", "<Panel "
        )
        expected[0] = "import { Client as Panel }"
    elif binding == "reexport":
        page = page.replace(
            "import { Client } from './Client'", "import { Panel } from '../barrel'"
        )
        page = page.replace("<Client ", "<Panel ")
        extra["barrel.ts"] = "export { Client as Panel } from './app/Client';\n"
        expected = ["import { Panel }", "export { Client as Panel }", "export function Client"]
    elif binding == "default":
        client = client.replace("export function Client", "export default function Client")
        page = page.replace("import { Client }", "import Client")
        expected = ["import Client", "export default function Client"]
    elif binding == "multiline":
        page = page.replace("import { Client }", "import {\n  Client,\n}")
        expected = ["import {", "Client,", "} from './Client'", "export function Client"]
    elif binding == "const":
        client = '"use client";\nexport const\n  Client = (props: unknown) => null;\n'
        expected = ["import { Client }", "export const", "Client ="]
    with context(tmp_path, {"app/page.tsx": page, "app/Client.tsx": client, **extra}) as review:
        entry = declare(review, fields=["phone"])
        judge = FieldJudge(["phone"])
        check = investigator(review, judge)
        path = next(p for p in check.paths.values() if p.site.entry_point_id == entry)
        packet = EvidencePacket.build(*check.field_cuts(entry, path, ["phone"]))
        text = code(packet)
        for fragment in ['"use client";', *expected, "phone: row.phone", "SELECT id"]:
            assert fragment in text
        flows = crossings(review.nextjs, check.entries[entry].handler_symbol_id)
        assert flows and all(c.boundary_evidence and not c.unknowns for c in flows)
        for span in [s for c in flows for s in c.boundary_evidence]:
            assert not check.classifier.validator.evidence(span)
            assert any(
                packet.location(line) == (span.path, span.start_line) for line in packet.line_ids
            )
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is Conclusion.SUPPORTED
        assert len(judge.requests) == 3
        assert all('"use client";' in r.user for r in judge.requests)
        assert all(p.label.startswith("part ") for p in packet.excerpts)


@pytest.mark.parametrize(
    "binding",
    [
        "type_clause",
        "type_name",
        "type_export",
        "wildcard",
        "namespace",
        "mutable",
        "modified",
        "shadow",
        "merged",
        "missing",
        "misplaced",
    ],
)
def test_unproven_runtime_bindings_never_supply_minimization(tmp_path: Path, binding: str) -> None:
    page = PAGE.replace(
        "{ deliveryAddress: row.delivery_address, phone: row.phone, id: row.id }",
        "{ id: row.id }",
    )
    client, extra = CLIENT, {}
    if binding == "type_clause":
        page = page.replace("import { Client }", "import type { Client }")
    elif binding == "type_name":
        page = page.replace("import { Client }", "import { type Client }")
    elif binding in {"type_export", "wildcard"}:
        page = page.replace("'./Client'", "'../barrel'")
        extra["barrel.ts"] = (
            "export type { Client } from './app/Client';\n"
            if binding == "type_export"
            else "export * from './app/Client';\n"
        )
    elif binding == "namespace":
        page = page.replace("import { Client }", "import * as UI").replace(
            "<Client ", "<UI.Client "
        )
    elif binding == "mutable":
        client = '"use client";\nexport let Client = (props: unknown) => null;\n'
    elif binding == "modified":
        client += "Client = replacement;\n"
    elif binding == "shadow":
        page = page.replace(
            "  const row =", "  const Client = (props: any) => null;\n  const row ="
        )
    elif binding == "merged":
        client = client.replace(
            "export function Client",
            "export function Client(props: any): any;\nexport function Client",
        )
    elif binding == "missing":
        client = client.replace('"use client";', '// "use client";')
    elif binding == "misplaced":
        client = "const marker = 1;\n" + client
    with context(tmp_path, {"app/page.tsx": page, "app/Client.tsx": client, **extra}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge([])
        check = investigator(review, judge)
        flows = crossings(review.nextjs, check.entries[entry].handler_symbol_id)
        assert not flows or any(c.unknowns for c in flows)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is Conclusion.INCONCLUSIVE
        assert not any(g.canonical.startswith("minimized(") for g in result.guards)


@pytest.mark.parametrize("corrupt", ["hash", "snapshot", "path"])
def test_corrupt_boundary_citation_refuses_before_any_model_request(
    tmp_path: Path, corrupt: str
) -> None:
    with context(tmp_path, {"app/page.tsx": PAGE, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge(["phone"])
        check = investigator(review, judge)
        flow = crossings(check.nextjs, check.entries[entry].handler_symbol_id)[0]
        span = flow.boundary_evidence[0]
        changed = {
            "hash": {"content_sha256": "0" * 64},
            "snapshot": {"snapshot_id": "0" * 64},
            "path": {"path": "missing.tsx"},
        }[corrupt]
        check.nextjs = check.nextjs.model_copy(
            update={
                "serializations": [
                    flow.model_copy(
                        update={
                            "boundary_evidence": [
                                span.model_copy(update=changed),
                                *flow.boundary_evidence[1:],
                            ]
                        }
                    )
                ]
            }
        )
        with pytest.raises(ValueError, match="citation cannot be validated"):
            check.investigate(entry, judge, Spend(Budget()))
        assert not judge.requests


def test_added_module_binding_source_obeys_the_unchanged_packet_budget(tmp_path: Path) -> None:
    imported = "import {\n" + "\n".join(f"  unused{i}," for i in range(81)) + "\n  Client,\n}"
    page = PAGE.replace("import { Client }", imported)
    with context(tmp_path, {"app/page.tsx": page, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge(["phone"])
        with pytest.raises(ValueError, match="80"):
            investigator(review, judge).investigate(entry, judge, Spend(Budget()))
        assert not judge.requests


def test_actual_tandir_courier_and_order_packets_include_the_exact_client_modules(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    prepared = json.loads(
        (root / "docs/results/2026-10-08-m6.9r-action-phone-preparation.json").read_bytes()
    )
    original = json.loads(
        (root / "docs/results/2026-10-08-m6.9r-action-phone-execution.json").read_bytes()
    )
    settings = Settings(data_dir=tmp_path / "data")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(root / "labs/tandir", store)
    review = Review(settings, snapshot.id)
    try:
        review.policies = FrozenPolicies.model_validate(prepared["requirements"])
        check = investigator(review, Judge())
        for route, name in [("/courier/[id]", "DeliveryCard"), ("/orders/[id]", "OrderSummary")]:
            entry = next(e.entry for e in review.nextjs.entries if e.entry.route == route)
            path = next(
                p
                for p in check.paths.values()
                if p.site.entry_point_id == entry.id
                and p.site.resource == ("users" if name == "DeliveryCard" else "orders")
            )
            packet = EvidencePacket.build(*check.field_cuts(entry.id, path, ["phone"]))
            text = code(packet)
            assert f"import {{ {name} }}" in text and f"export function {name}" in text
            assert '"use client";' in text
            target = f"web/app/{'courier' if name == 'DeliveryCard' else 'orders'}/[id]/{name}.tsx"
            assert any(packet.location(line) == (target, 1) for line in packet.line_ids)
        failed = next(r for r in original["records"] if r["case_id"] == "TANDIR-D2")
        assert failed["questions"][0]["answer"]["result"]["conclusion"] == "inconclusive"
        assert [
            json.loads(r["raw_answer"])
            for r in failed["requests"]
            if r["body"].get("response_format", {}).get("json_schema", {}).get("name")
            == "client_exposure"
        ] == [{"fields": []}] * 3
    finally:
        review.close()
