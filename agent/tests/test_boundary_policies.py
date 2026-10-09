"""Compiler/source and fixture judgments only; reviewed source is never executed."""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent.boundaries import BoundaryInvestigator, finding
from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.validator import Unconfirmed
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.code import GuardKind, PolicyAssertion, PolicyStatus
from backend.contracts.common import Family
from backend.contracts.investigation import Budget, Conclusion
from backend.contracts.policies import BoundPolicy, FrozenPolicies
from backend.contracts.runs import ReviewRun, RunLifecycle, RunType
from backend.review import Review, Workflow, export
from backend.run_store import RunStore
from backend.settings import Settings

from .test_guards import DB

CLIENT = '"use client";\nexport function Client(props: unknown) { return null; }\n'
PAGE = """import { one } from '../db';
import { Client } from './Client';
export default async function Page({params}: {params: {id: number}}) {
  const row = one('SELECT id, delivery_address, phone FROM orders WHERE id = ?', params.id);
  const dto = { deliveryAddress: row.delivery_address, phone: row.phone, id: row.id };
  const alias = dto;
  return <Client order={{...alias}} />;
}
"""
SESSION = """import { redirect } from "next/navigation";
declare function lookup(): Promise<{id: number, role: string} | null>;
export async function session() {
  const viewer = await lookup();
  if (!viewer) redirect("/login");
  return viewer;
}
"""
ACTION = """'use server';
import { one } from './db';
import { session } from './session';
export async function action(id: number) {
  const viewer = await session();
  return one('SELECT id FROM orders WHERE id = ?', id);
}
"""


class Judge:
    def __init__(self, fields: list[str] | None = None, *, disagree: bool = False) -> None:
        self.fields, self.disagree = fields or [], disagree
        self.requests: list[ModelRequest] = []

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.requests.append(request)
        if request.name == "gather":
            return JsonAnswer({"look": "enough"}, "", 1, 1, 0)
        if request.name == "client_exposure":
            lines = re.findall(
                r"(L\d+)\s+.*?(?:delivery_address|row\.phone|<Client|Response\.json)", request.user
            )
            names = [] if self.disagree and request.seed == 43 else self.fields
            return JsonAnswer(
                {
                    "fields": [
                        {"name": f, "line_ids": list(dict.fromkeys(lines))[:6]} for f in names
                    ]
                },
                "",
                1,
                1,
                0,
            )
        if request.name == "intentional_exception":
            return JsonAnswer({"reason": "none_found", "line_ids": []}, "", 1, 1, 0)
        props = request.schema["properties"]["guards"]["items"]["properties"]
        kinds = props["kind"]["enum"]
        kind = next(k for k in ["authenticated", "role", "owner"] if k in kinds)
        focus = re.search(r"Classify ONLY the check or query on (L\d+)", request.user)
        assert focus
        return JsonAnswer(
            {
                "guards": [
                    {
                        "kind": kind,
                        "subject": next(
                            (v for v in props["subject"].get("enum", []) if v is not None), None
                        ),
                        "object": next(
                            (v for v in props["object"].get("enum", []) if v is not None), None
                        ),
                        "line_ids": [focus[1]],
                    }
                ]
            },
            "",
            1,
            1,
            0,
        )


@contextmanager
def context(tmp_path: Path, sources: dict[str, str]) -> Iterator[Review]:
    settings = Settings(data_dir=tmp_path / "data")
    root = tmp_path / "source"
    root.mkdir()
    files = {
        "package.json": '{"dependencies":{"next":"16.0.0"}}',
        "db.ts": DB.decode(),
        "session.ts": SESSION,
        **sources,
    }
    for path, text in files.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8", newline="\n")
    snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
    review = Review(settings, snapshot.id)
    try:
        yield review
    finally:
        review.close()


def declare(
    review: Review,
    *,
    fields: list[str] | None = None,
    required: GuardKind = GuardKind.UNKNOWN,
    role: str | None = None,
) -> str:
    path = next(p for p in review.access.accesses if p.site.resource == "orders")
    assertion = PolicyAssertion(
        id="policy:fixture",
        statement="Required by the fixture reviewer",
        resource=path.site.resource,
        kind=required,
        canonical=f"{required.value}(orders)",
        status=PolicyStatus.DECLARED,
        author="Fixture reviewer",
        created_at=datetime.now(UTC),
    )
    policy = BoundPolicy(
        assertion=assertion,
        snapshot_id=review.snapshot.id,
        source_run_id="run:fixture",
        sites=[path.site],
        provenance="Explicit fixture requirement",
        forbidden_fields=fields or [],
        required_role=role,
    )
    review.policies = FrozenPolicies(snapshot_id=review.snapshot.id, policies=[policy])
    return path.site.entry_point_id


def investigator(review: Review, judge: Judge) -> BoundaryInvestigator:
    classifier = Classifier(
        review.snapshot,
        review.store,
        judge,
        SummaryCache(review.settings.cache_dir / "guards.sqlite"),
        identity="fixture",
    )
    return BoundaryInvestigator(
        review.snapshot,
        review.store,
        review.index,
        review.typescript,
        review.nextjs,
        classifier,
        policies=review.policies,
        access=review.access,
    )


@pytest.mark.parametrize(
    "mode", ["alias", "helper", "omitted", "literal", "dynamic", "conditional"]
)
def test_exact_field_projection_and_omission_pairs(tmp_path: Path, mode: str) -> None:
    source, helpers = PAGE, {}
    if mode == "helper":
        source = PAGE.replace(
            "import { Client }", "import { project } from '../dto';\nimport { Client }"
        ).replace(
            "{ deliveryAddress: row.delivery_address, phone: row.phone, id: row.id }",
            "project(row)",
        )
        helpers["dto.ts"] = (
            "export function project(value: any) {\n"
            "  return {deliveryAddress: value.delivery_address, phone: value.phone, "
            "id: value.id};\n}\n"
        )
    elif mode in {"omitted", "literal"}:
        source = PAGE.replace("phone: row.phone, ", "" if mode == "omitted" else "phone: 'fixed', ")
    elif mode == "dynamic":
        source = PAGE.replace("const alias = dto;", "const alias = {...dto, ...transform(row)};")
    elif mode == "conditional":
        source = PAGE.replace(
            "const alias = dto;", "if (flag) return <Client order={row} />;\n  const alias = dto;"
        )
    with context(tmp_path, {"app/page.tsx": source, "app/Client.tsx": CLIENT, **helpers}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge(["phone"] if mode in {"alias", "helper"} else [])
        check = investigator(review, judge)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        expected = (
            Conclusion.SUPPORTED
            if mode in {"alias", "helper"}
            else Conclusion.REJECTED
            if mode in {"omitted", "literal"}
            else Conclusion.INCONCLUSIVE
        )
        assert result.conclusion is expected
        assert len(result.samples) == 3
        case = finding(result, check, run_id="run:fixture", display_id="F-01")
        assert not check.classifier.validator.finding(case, guards=result.guards)
        if mode in {"alias", "helper"}:
            assert any(
                f.field == "delivery_address" and f.output == "order.deliveryAddress"
                for f in result.field_flows
            )
            assert any("phone" in e.gloss and "order.phone" in e.gloss for e in case.exhibits)
        if mode in {"omitted", "literal"}:
            guard = next(g for g in result.guards if g.kind is GuardKind.MINIMIZED)
            with pytest.raises(Unconfirmed):
                check.classifier.validator.confirm(
                    guard.model_copy(update={"role": json.dumps(["delivery_address"])})
                )
        if mode in {"dynamic", "conditional"}:
            assert result.issues or result.flow_unknowns


@pytest.mark.parametrize("actual_role", ["admin", "manager"])
def test_explicit_role_requirement_does_not_accept_another_role(
    tmp_path: Path, actual_role: str
) -> None:
    source = ACTION.replace(
        "  return one",
        f'  if (viewer.role !== "{actual_role}") '
        'return Response.json({error: "Denied"}, {status: 403});\n  return one',
    )
    with context(tmp_path, {"app/actions.ts": source.replace("'./", "'../")}) as review:
        entry = declare(review, required=GuardKind.ROLE, role="admin")
        judge = Judge()
        check = investigator(review, judge)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is (
            Conclusion.REJECTED if actual_role == "admin" else Conclusion.SUPPORTED
        )
        assert all(g.role == "admin" for g in result.guards)
        assert result.policies[0].required_role == "admin"
        assert len(result.samples) == 3
        case = finding(result, check, run_id="run:fixture", display_id="F-01")
        assert not check.classifier.validator.finding(case, guards=result.guards)


@pytest.mark.parametrize("protected", [False, True])
def test_actions_bind_the_declared_owner_policy_to_the_exact_dal(
    tmp_path: Path, protected: bool
) -> None:
    source = (
        ACTION.replace(
            "FROM orders WHERE id = ?", "FROM orders WHERE id = ? AND customer_id = ?"
        ).replace("?', id)", "?', id, viewer.id)")
        if protected
        else ACTION
    )
    with context(tmp_path, {"app/actions.ts": source.replace("'./", "'../")}) as review:
        entry = declare(review, required=GuardKind.OWNER)
        judge = Judge()
        check = investigator(review, judge)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is (Conclusion.REJECTED if protected else Conclusion.SUPPORTED)
        assert len(result.samples) == 3
        assert not check.classifier.validator.finding(
            finding(result, check, run_id="run:fixture", display_id="F-01"), guards=result.guards
        )


@pytest.mark.parametrize("mode", ["missing", "role", "conditional", "unresolved"])
def test_role_requirement_has_an_actual_unconditional_handler_boundary(
    tmp_path: Path, mode: str
) -> None:
    source = ACTION
    if mode in {"role", "conditional"}:
        clause = 'viewer.role !== "admin"' if mode == "role" else 'flag && viewer.role !== "admin"'
        source = source.replace(
            "  return one",
            f'  if ({clause}) return Response.json({{error: "Denied"}}, '
            "{status: 403});\n  return one",
        )
    elif mode == "unresolved":
        source = source.replace("  return one", "  authorize();\n  return one")
    with context(tmp_path, {"app/actions.ts": source.replace("'./", "'../")}) as review:
        entry = declare(review, required=GuardKind.ROLE)
        judge = Judge()
        check = investigator(review, judge)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        expected = (
            Conclusion.REJECTED
            if mode == "role"
            else Conclusion.INCONCLUSIVE
            if mode in {"unresolved", "conditional"}
            else Conclusion.SUPPORTED
        )
        assert result.conclusion is expected


def test_field_disagreement_and_stale_exact_access_stay_open(tmp_path: Path) -> None:
    with context(tmp_path, {"app/page.tsx": PAGE, "app/Client.tsx": CLIENT}) as review:
        entry = declare(review, fields=["phone"])
        judge = Judge(["phone"], disagree=True)
        result = investigator(review, judge).investigate(
            entry, judge, Spend(Budget(max_prompt_tokens=24000))
        )
        assert result.conclusion is Conclusion.INCONCLUSIVE
        policy = review.policies.policies[0]
        site = policy.sites[0].model_copy(update={"resource": "users"})
        review.policies = review.policies.model_copy(
            update={"policies": [policy.model_copy(update={"sites": [site]})]}
        )
        with pytest.raises(ValueError, match="exact access"):
            investigator(review, Judge())


def test_minimized_proof_and_source_output_aliases_survive_the_saved_workflow(
    tmp_path: Path,
) -> None:
    source = PAGE.replace("phone: row.phone, ", "")
    with context(tmp_path, {"app/page.tsx": source, "app/Client.tsx": CLIENT}) as review:
        declare(review, fields=["phone"])
        questions, coverage, _ = review.questions("run:boundary", [], [], (Family.NEXTJS_EXPOSURE,))
        runs = RunStore(tmp_path / "runs.sqlite")
        runs.create(
            ReviewRun(
                id="run:boundary",
                snapshot_id=review.snapshot.id,
                run_type=RunType.LIVE,
                lifecycle=RunLifecycle.QUEUED,
                created_at=datetime.now(UTC),
                coverage=coverage,
            ),
            questions,
        )
        result = Workflow(
            review, runs, "run:boundary", Judge(), tmp_path / "guards.sqlite", "fixture", 1
        ).run()
        assert result.coverage.completed == 1
        bundle = export(review, runs, "run:boundary", tmp_path / "reports")
        assert len(bundle.findings) == 1
        assert bundle.findings[0].conclusion is Conclusion.REJECTED
        assert bundle.findings[0].policy_basis == review.policies.policies
        assert any(
            "delivery_address" in e.gloss and "deliveryAddress" in e.gloss
            for e in bundle.findings[0].exhibits
        )
        answer = runs.questions("run:boundary")[0].answer
        assert answer is not None and isinstance(answer["result"], dict)
        assert answer["result"]["field_flows"]
        # Export already rendered all four formats and revalidated the source proof.
        saved = (tmp_path / "reports/report.json").read_text(encoding="utf-8")
        assert "minimized" in saved and "deliveryAddress" in saved


def test_literal_sql_list_is_an_exact_declarable_nextjs_access(tmp_path: Path) -> None:
    route = (
        "import {one} from '../../../db';\nexport function GET() {\n"
        "  const rows = one('SELECT id, phone FROM orders');\n"
        "  return Response.json(rows);\n}\n"
    )
    with context(tmp_path, {"app/api/reports/route.ts": route}) as review:
        entry = declare(review, required=GuardKind.ROLE)
        path = next(p for p in review.access.accesses if p.site.entry_point_id == entry)
        assert path.site.operation.value == "list" and path.site.key_origin.value == "constant"
        judge = Judge()
        result = investigator(review, judge).investigate(
            entry, judge, Spend(Budget(max_prompt_tokens=24000))
        )
        assert result.conclusion is Conclusion.SUPPORTED


@pytest.mark.parametrize("mode", ["wrong_query", "external_helper", "no_policy", "shadow_response"])
def test_names_and_wrong_or_indirect_sources_never_establish_a_policy_breach(
    tmp_path: Path, mode: str
) -> None:
    source = PAGE
    if mode == "wrong_query":
        source = source.replace(
            "  const dto =",
            "  const other = one('SELECT id, phone FROM users WHERE id = ?', params.id);\n"
            "  const dto =",
        )
        source = source.replace("phone: row.phone", "phone: other.phone")
    elif mode == "external_helper":
        source = source.replace("const alias = dto;", "const alias = external(dto);")
    sources = {"app/page.tsx": source, "app/Client.tsx": CLIENT}
    if mode == "shadow_response":
        sources = {
            "app/api/orders/route.ts": "import {one} from '../../../db';\n"
            "export function GET(request: any) {\n"
            "  const row = one('SELECT id, phone FROM orders WHERE id = ?', request.id);\n"
            "  const Response = {json: external};\n  return Response.json(row);\n}\n"
        }
    with context(tmp_path, sources) as review:
        entry = declare(review, fields=["phone"])
        if mode == "no_policy":
            review.policies = FrozenPolicies(snapshot_id=review.snapshot.id)
        judge = Judge(["phone"] if mode == "no_policy" else [])
        result = investigator(review, judge).investigate(
            entry, judge, Spend(Budget(max_prompt_tokens=24000))
        )
        assert result.conclusion is not Conclusion.SUPPORTED
        if mode == "wrong_query":
            assert result.conclusion is Conclusion.REJECTED
            assert any(
                f.field == "phone" and f.source != review.policies.policies[0].sites[0].span
                for f in result.field_flows
            )
        else:
            assert result.conclusion is Conclusion.INCONCLUSIVE


def test_actual_tandir_dto_aliases_have_exact_query_and_crossing_citations(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2] / "labs/tandir"
    settings = Settings(data_dir=tmp_path / "data")
    snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
    review = Review(settings, snapshot.id)
    try:
        page = next(e.entry for e in review.nextjs.entries if e.entry.route == "/orders/[id]")
        from analysis.serialization import crossings

        facts = crossings(review.nextjs, page.handler_symbol_id)
        fields = [f for c in facts for f in c.fields]
        assert any(
            f.field == "delivery_address" and f.output == "order.deliveryAddress" for f in fields
        )
        assert any(f.field == "total_cents" and f.output == "order.totalCents" for f in fields)
        branch = next(f for f in fields if f.output == "order.branch")
        assert branch.field == "name" and branch.source_resource == "branches"
        assert branch.query_resource == "orders"
        assert any(
            s.path == "web/lib/dal.ts" and s.start_line == 107 and s.end_line == 109
            for s in branch.evidence
        )
        for field in fields:
            assert any(
                p.owner_symbol_id == field.source_owner_symbol_id
                and p.site.span == field.source
                and p.site.entry_point_id == page.id
                for p in review.access.accesses
            )
            assert all(
                not review.sinks.validator.evidence(s) for s in [field.source, *field.evidence]
            )
        assert not any(c.unknowns for c in facts)
        assert not any(
            "absent from the known query projection" in u for c in facts for u in c.unknowns
        )
        judge = Judge()
        cuts = investigator(review, judge).cuts(page.id)
        packet = "\n".join(
            "\n".join(c.source.decode().splitlines()[c.start - 1 : c.end]) for c in cuts
        )
        assert "const ORDER_SELECT =" in packet and "branches.name AS branch" in packet
        from analysis.serialization import minimized

        path = next(
            p
            for p in review.access.accesses
            if p.site.entry_point_id == page.id and p.site.resource == "orders"
        )
        assert minimized(
            review.nextjs, page.handler_symbol_id, path.owner_symbol_id, path.site.span, ["phone"]
        )
        assert not minimized(
            review.nextjs,
            page.handler_symbol_id,
            path.owner_symbol_id,
            path.site.span,
            ["delivery_address"],
        )
        assert any(
            f.field == "inscription" and f.output == "order.items[].inscription" for f in fields
        )
    finally:
        review.close()


@pytest.mark.parametrize("mode", ["protected", "missing", "not_awaited", "wrong_return"])
def test_declared_authentication_uses_the_actual_awaited_verifier(
    tmp_path: Path, mode: str
) -> None:
    source, session = ACTION, SESSION
    if mode == "missing":
        source = source.replace("  const viewer = await session();\n", "")
    elif mode == "not_awaited":
        source = source.replace("await session()", "session()")
    elif mode == "wrong_return":
        session = session.replace("return viewer;", "return other;")
    with context(
        tmp_path, {"app/actions.ts": source.replace("'./", "'../"), "session.ts": session}
    ) as review:
        entry = declare(review, required=GuardKind.AUTHENTICATED)
        judge = Judge()
        check = investigator(review, judge)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        expected = (
            Conclusion.REJECTED
            if mode == "protected"
            else Conclusion.SUPPORTED
            if mode == "missing"
            else Conclusion.INCONCLUSIVE
        )
        assert result.conclusion is expected
        assert len(result.samples) == 3


class CitationFailureJudge(Judge):
    def __init__(self, kind: GuardKind) -> None:
        super().__init__()
        self.invalid_kind = kind

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        answer = super().ask(request, spend)
        if request.name == "guard_summary":
            kinds = request.schema["properties"]["guards"]["items"]["properties"]["kind"]["enum"]
            if "none" in kinds and self.invalid_kind.value in kinds:
                answer.data["guards"][0]["line_ids"] = ["L999"]
        return answer


@pytest.mark.parametrize("required", [GuardKind.AUTHENTICATED, GuardKind.OWNER])
def test_unrelated_query_citation_failure_does_not_poison_a_sign_in_requirement(
    tmp_path: Path, required: GuardKind
) -> None:
    source = ACTION.replace(
        "FROM orders WHERE id = ?", "FROM orders WHERE id = ? AND customer_id = ?"
    ).replace("?', id)", "?', id, viewer.id)")
    with context(tmp_path, {"app/actions.ts": source.replace("'./", "'../")}) as review:
        entry = declare(review, required=required)
        judge = CitationFailureJudge(GuardKind.OWNER)
        check = investigator(review, judge)
        result = check.investigate(entry, judge, Spend(Budget(max_prompt_tokens=24000)))
        assert len(result.samples) == 3
        if required is GuardKind.AUTHENTICATED:
            assert result.conclusion is Conclusion.REJECTED and not result.issues
            assert all(g.kind is GuardKind.AUTHENTICATED for g in result.guards)
            assert all(
                "customer_id = ?" not in r.user
                for r in judge.requests
                if "none"
                in r.schema["properties"]
                .get("guards", {})
                .get("items", {})
                .get("properties", {})
                .get("kind", {})
                .get("enum", [])
            )
            assert not check.classifier.validator.finding(
                finding(result, check, run_id="run:fixture", display_id="F-01"),
                guards=result.guards,
            )
        else:
            assert result.conclusion is Conclusion.INCONCLUSIVE and result.issues


@pytest.mark.parametrize("mode", ["invalid_session", "unresolved_helper"])
def test_scoped_session_analysis_retains_required_failures_and_unknown_paths(
    tmp_path: Path, mode: str
) -> None:
    source = ACTION
    if mode == "unresolved_helper":
        source = source.replace("  const viewer", "  authorize();\n  const viewer")
    with context(tmp_path, {"app/actions.ts": source.replace("'./", "'../")}) as review:
        entry = declare(review, required=GuardKind.AUTHENTICATED)
        judge = (
            CitationFailureJudge(GuardKind.AUTHENTICATED) if mode == "invalid_session" else Judge()
        )
        result = investigator(review, judge).investigate(
            entry, judge, Spend(Budget(max_prompt_tokens=24000))
        )
        assert result.conclusion is Conclusion.INCONCLUSIVE
        assert result.issues and len(result.samples) == 3


def test_two_required_kinds_keep_separate_summaries_and_path_checks(tmp_path: Path) -> None:
    source = ACTION.replace(
        "  return one",
        '  if (viewer.role !== "admin") return Response.json({error: "Denied"}, '
        "{status: 403});\n  return one",
    )
    with context(tmp_path, {"app/actions.ts": source.replace("'./", "'../")}) as review:
        entry = declare(review, required=GuardKind.ROLE, role="admin")
        role_policy = review.policies.policies[0]
        authenticated = role_policy.model_copy(
            update={
                "assertion": role_policy.assertion.model_copy(
                    update={
                        "id": "policy:session",
                        "kind": GuardKind.AUTHENTICATED,
                        "canonical": "AUTHN",
                    }
                ),
                "required_role": None,
            }
        )
        review.policies = FrozenPolicies(
            snapshot_id=review.snapshot.id, policies=[role_policy, authenticated]
        )
        judge = Judge()
        result = investigator(review, judge).investigate(
            entry, judge, Spend(Budget(max_prompt_tokens=24000))
        )
        assert result.conclusion is Conclusion.REJECTED and not result.issues
        assert {g.kind for g in result.guards} == {GuardKind.ROLE, GuardKind.AUTHENTICATED}
        assert len(result.samples) == 6


@pytest.mark.parametrize(
    "case_id,handler,expected,indices",
    [
        ("TANDIR-D1-L", "cancelOrder", Conclusion.REJECTED, [2, 3, 4, 5]),
        ("TANDIR-D1", "refundOrder", Conclusion.SUPPORTED, [1, 2, 3]),
    ],
)
def test_saved_m6_9k_action_packets_replay_the_exact_session_requirement(
    tmp_path: Path, case_id: str, handler: str, expected: Conclusion, indices: list[int]
) -> None:
    """Saved-answer replay; the original fresh abstention/quality gate stays unchanged."""
    root = Path(__file__).resolve().parents[2]
    execution_path = root / "docs/results/2026-10-08-m6.9k-nextjs-execution.json"
    saved: Any = json.loads(execution_path.read_text(encoding="utf-8"))
    record = next(r for r in saved["records"] if r["case_id"] == case_id)
    assert record["questions"][0]["answer"]["result"]["conclusion"] == "inconclusive"
    prepared: Any = json.loads(
        (root / "docs/results/2026-10-08-m6.9k-nextjs-preparation.json").read_text(encoding="utf-8")
    )

    def normalize(body: dict[str, Any]) -> str:
        # Only per-request spotlight boundary entropy differs. IDs, source, schema,
        # seeds, prompt text and all request settings must match saved packets exactly.
        return re.sub(
            r"evidence-[0-9a-f]{8}", "evidence-00000000", json.dumps(body, sort_keys=True)
        )

    class Replay:
        def __init__(self) -> None:
            self.used: list[int] = []

        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            matching = [
                i
                for i, r in enumerate(record["requests"])
                if normalize(r["body"]) == normalize(request.body())
            ]
            assert len(matching) == 1, "No exact saved packet for this request; no fixture fallback"
            index = matching[0]
            self.used.append(index)
            response = record["requests"][index]
            assert response["error"] is None
            return JsonAnswer(json.loads(response["raw_answer"]), response["raw_answer"], 0, 0, 0)

    settings = Settings(data_dir=tmp_path / "data")
    snapshot = take_snapshot(root / "labs/tandir", SnapshotStore(settings.cache_dir / "snapshots"))
    assert snapshot.id == record["snapshot"]["id"] == prepared["snapshot"]["id"]
    review = Review(settings, snapshot.id)
    try:
        review.policies = FrozenPolicies.model_validate(prepared["requirements"])
        replay = Replay()
        classifier = Classifier(
            snapshot,
            review.store,
            replay,
            SummaryCache(tmp_path / "replay.sqlite"),
            identity="saved-m6.9k-replay",
        )
        check = BoundaryInvestigator(
            snapshot,
            review.store,
            review.index,
            review.typescript,
            review.nextjs,
            classifier,
            policies=review.policies,
            access=review.access,
        )
        entry = next(
            e.entry
            for e in review.nextjs.entries
            if check.symbols[e.entry.handler_symbol_id].name == handler
        )
        result = check.investigate(entry.id, replay, Spend(Budget(max_prompt_tokens=24000)))
        assert result.conclusion is expected and not result.issues
        assert len(result.samples) == 3 and [s.seed for s in result.samples] == [42, 43, 44]
        assert replay.used == indices
        assert not classifier.validator.finding(
            finding(result, check, run_id="run:replay", display_id="F-01"), guards=result.guards
        )
        if case_id == "TANDIR-D1-L":
            owner = next(s for s in check.symbols.values() if s.name == "cancelOrderFor")
            original = classifier.classify(owner, Spend(Budget()), resource="orders")
            assert original.issues and not original.guards
            assert replay.used[-1] == 1  # Original invalid owner answer remains refused.
    finally:
        review.close()
