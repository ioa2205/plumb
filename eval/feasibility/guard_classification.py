"""Recorded guard-summary development runs on Tandir source; never imports the lab."""

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from agent.evidence import Cut, EvidencePacket
from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelAdapter, ModelRequest, Spend
from agent.questions import guard_summary
from agent.validator import check_answer
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import extract, span_sha256
from backend.contracts.code import SourceSpan, Symbol, SymbolKind
from backend.contracts.common import Language
from backend.contracts.investigation import Budget
from backend.preflight import PreflightResult
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from backend.vulkan_profile import MODEL_ID, create
from eval.bench.machine import machine_state
from eval.feasibility.common import RESULTS_DIR
from eval.ground_truth import symbol_span

ROOT = RESULTS_DIR.parent.parent / "labs" / "tandir"
SECURITY = "api/tandir/security.py"
SERVICES = "api/tandir/services/orders.py"
DAL = "web/lib/dal.ts"
# Predeclared development expectations, never placed in a model request.
CASES = (
    ("sign-in", ((SECURITY, "current_user"),), {"authenticated"}),
    ("owner-comparison", ((SERVICES, "ensure_owner"),), {"owner"}),
    ("scoped-query", ((SERVICES, "load_order_scoped"),), {"owner"}),
    ("tenant", (("api/tandir/routers/kitchen.py", "_branch_order"),), {"tenant"}),
    ("role", ((SECURITY, "require_role"), (SECURITY, "current_user")), {"role", "authenticated"}),
    (
        "receipt",
        (("api/tandir/routers/orders.py", "get_receipt"), (SECURITY, "current_user")),
        {"authenticated"},
    ),
    ("dal-owner", ((DAL, "getOrderDTO"), (DAL, "verifySession")), {"owner", "authenticated"}),
    ("public", ((DAL, "getStorefront"),), {"none"}),
)
CANONICAL = {
    "sign-in": {"AUTHN"},
    "owner-comparison": {"OWNER(Order.customer_id = principal.id)"},
    "scoped-query": {"OWNER(Order.customer_id = principal.id)"},
    "tenant": {"TENANT(Order.branch_id = principal.branch_id)"},
    "role": {"ROLE(roles)", "AUTHN"},
    "receipt": {"AUTHN"},
    "dal-owner": {"OWNER(Order.customer_id = principal.id)", "AUTHN"},
    "public": set(),
}


def packet_for(parts: tuple[tuple[str, str], ...]) -> EvidencePacket:
    cuts = []
    for index, (path, symbol) in enumerate(parts):
        source = (ROOT / path).read_bytes()
        start, end = symbol_span(source.decode(), path, symbol)
        language = Language.PYTHON if path.endswith(".py") else Language.TYPESCRIPT
        cuts.append(Cut(f"part {index}", path, language, source, start, end))
    return EvidencePacket.build(*cuts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--focused", action="store_true", help="Use executable-check summaries/cache"
    )
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    settings = Settings()
    server = create(settings, f"m3-4-guards-{stamp}")
    store = SnapshotStore(settings.cache_dir / "guard-development")
    snapshot = take_snapshot(ROOT, store) if args.focused else None
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "model": load_model_pins().get(MODEL_ID).model_dump(mode="json"),
        "llama_cpp": load_llama_cpp_pin().model_dump(mode="json"),
        "server_argv": server.config.argv(0, "<per-launch key>"),
        "machine_start": machine_state(),
        "cases": [],
        "passed": False,
        "focused": args.focused,
        "snapshot": snapshot.model_dump(mode="json") if snapshot else None,
        "requests": [],
        "implementation_hashes": {
            path: hashlib.sha256((RESULTS_DIR.parent.parent / path).read_bytes()).hexdigest()
            for path in (
                "agent/guards.py",
                "agent/guard_syntax.py",
                "agent/questions.py",
                "agent/validator.py",
            )
        },
    }

    def preflight() -> PreflightResult:
        result = server.preflight()
        report["preflight"] = asdict(result)
        return result

    try:
        with ModelAdapter(server, preflight=preflight) as adapter:

            class Recorder:
                def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
                    entry: dict[str, Any] = {"request": request.body()}
                    report["requests"].append(entry)
                    answer = adapter.ask(request, spend)
                    entry["answer"] = asdict(answer)
                    return answer

            cache = SummaryCache(settings.cache_dir / "guards" / f"development-{stamp}.sqlite")
            classifier = (
                Classifier(
                    snapshot,
                    store,
                    Recorder(),
                    cache,
                    identity=json.dumps(report["model"], sort_keys=True)
                    + json.dumps(report["server_argv"]),
                )
                if snapshot
                else None
            )
            for name, parts, expected in CASES:
                packet = packet_for(parts)
                prompt = guard_summary(packet)
                spend = Spend(Budget(max_prompt_tokens=3000, max_seconds=120, max_retries=0))
                row: dict[str, Any] = {
                    "name": name,
                    "expected": sorted(expected),
                    "source_hashes": {
                        p: hashlib.sha256(
                            store.read(snapshot, p) if snapshot else (ROOT / p).read_bytes()
                        ).hexdigest()
                        for p, _ in parts
                    },
                    "preview_request" if args.focused else "request": prompt.request().body(),
                    "passed": False,
                }
                report["cases"].append(row)
                try:
                    if classifier and snapshot:
                        summaries = []
                        for path, symbol_name in parts:
                            source = store.read(snapshot, path)
                            start, end = symbol_span(source.decode(), path, symbol_name)
                            symbol = Symbol(
                                id="symbol:"
                                + hashlib.sha256(f"{path}:{symbol_name}".encode()).hexdigest()[:24],
                                snapshot_id=snapshot.id,
                                name=symbol_name,
                                qualified_name=symbol_name,
                                kind=SymbolKind.FUNCTION,
                                language=Language.PYTHON
                                if path.endswith(".py")
                                else Language.TYPESCRIPT,
                                span=SourceSpan(
                                    snapshot_id=snapshot.id,
                                    path=path,
                                    start_line=start,
                                    end_line=end,
                                    content_sha256=span_sha256(source, start, end),
                                ),
                            )
                            own_spend = Spend(
                                Budget(max_prompt_tokens=12000, max_seconds=240, max_retries=0)
                            )
                            context = []
                            if symbol_name == "verifySession":
                                for context_path, context_name in (
                                    (DAL, "getViewer"),
                                    ("web/lib/sessions.ts", "viewerForToken"),
                                ):
                                    data = store.read(snapshot, context_path)
                                    facts = extract(context_path, Language.TYPESCRIPT, data, set())
                                    fact = next(f for f in facts.symbols if f.name == context_name)
                                    context.append(
                                        Symbol(
                                            id="symbol:"
                                            + hashlib.sha256(
                                                f"{context_path}:{context_name}".encode()
                                            ).hexdigest()[:24],
                                            snapshot_id=snapshot.id,
                                            name=context_name,
                                            qualified_name=context_name,
                                            kind=fact.kind,
                                            language=Language.TYPESCRIPT,
                                            span=SourceSpan(
                                                snapshot_id=snapshot.id,
                                                path=context_path,
                                                start_line=fact.start_line,
                                                end_line=fact.end_line,
                                                content_sha256=span_sha256(
                                                    data, fact.start_line, fact.end_line
                                                ),
                                            ),
                                        )
                                    )
                            summary = classifier.classify(
                                symbol, own_spend, resource="Order", context=tuple(context)
                            )
                            summaries.append(summary)
                            if not summary.issues:
                                previous = classifier.cache_hits
                                cached = classifier.classify(
                                    symbol, own_spend, resource="Order", context=tuple(context)
                                )
                                if cached != summary or classifier.cache_hits != previous + 1:
                                    raise ValueError(
                                        "helper cache did not reuse its validated summary"
                                    )
                        kinds = {g.kind.value for s in summaries for g in s.guards} or {"none"}
                        row["summaries"] = [s.model_dump(mode="json") for s in summaries]
                        row["expected_canonical"] = sorted(CANONICAL[name])
                        row["passed"] = (
                            kinds == expected
                            and all(not s.issues for s in summaries)
                            and {g.canonical for s in summaries for g in s.guards}
                            == CANONICAL[name]
                        )
                    else:
                        answer = adapter.ask(prompt.request(), spend)
                        parsed = prompt.parse(answer.data)
                        row["answer"] = asdict(answer)
                        row["violations"] = [asdict(v) for v in check_answer(prompt, parsed)]
                        kinds = {g["kind"] for g in answer.data["guards"]}
                        row["passed"] = kinds == expected and not row["violations"]
                except Exception as error:
                    row["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
                print(f"{name}: {row['passed']}", flush=True)
        report["passed"] = all(row["passed"] for row in report["cases"])
    except Exception as error:
        report["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
    finally:
        server.stop()
        report["memory_abort"] = server.memory_abort
        report["passed"] = report["passed"] and not server.memory_abort
        report["peak_working_set_bytes"] = (
            server.sampler.peak_working_set if server.sampler else None
        )
        report["finished"] = datetime.now(UTC).isoformat()
        report["machine_end"] = machine_state()
        output = RESULTS_DIR / f"{stamp}-m3.4-guard-classification.json"
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Guard development passed={report['passed']}; {output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
