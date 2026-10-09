"""Recorded real local-model development acceptance for all remaining Tandir pairs."""

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.boundaries import BoundaryInvestigator
from agent.boundaries import finding as boundary_finding
from agent.families import SinkInvestigator, finding
from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelAdapter, ModelRequest, Spend
from analysis.index import Index, index_path
from analysis.nextjs import extract_nextjs
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.typescript_resolution import resolve_typescript
from backend.contracts.common import Family
from backend.contracts.investigation import Budget
from backend.preflight import PreflightResult
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from backend.vulkan_profile import MODEL_ID, create
from eval.bench.machine import machine_state
from eval.feasibility.common import RESULTS_DIR
from eval.ground_truth import load

FOCUSED_CASES = ("TANDIR-B1", "TANDIR-B1-L", "TANDIR-B2-L", "TANDIR-C1-L")
ROLE_CASES = ("TANDIR-D3-L", "TANDIR-D3")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--focused-sql", action="store_true", help="M3.10b's predeclared 4 cases / 12 requests"
    )
    group.add_argument(
        "--focused-roles",
        action="store_true",
        help="M3.4a's 2 cases / 7 requests; no sweep or tuning",
    )
    args = parser.parse_args()
    sql, roles = args.focused_sql, args.focused_roles
    focused = sql or roles
    selected_ids = ROLE_CASES if roles else FOCUSED_CASES
    max_requests = 7 if roles else 12
    settings = Settings()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    server = create(settings, f"m3-10-{stamp}")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(RESULTS_DIR.parent.parent / "labs/tandir", store)
    index = Index.build(snapshot, store, index_path(settings.cache_dir, snapshot.id))
    model_pin = load_model_pins().get(MODEL_ID).model_dump(mode="json")
    launch = server.config.argv(0, "<per-launch key>")
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "model": model_pin,
        "llama_cpp": load_llama_cpp_pin().model_dump(mode="json"),
        "server_argv": launch,
        "snapshot": snapshot.model_dump(mode="json"),
        "machine_start": machine_state(),
        "requests": [],
        "cases": [],
        "completed": False,
        "acceptance": {
            "scope": "M3.4a focused TypeScript roles"
            if roles
            else "M3.10b focused SQL"
            if sql
            else "M3.10 remaining families",
            "case_ids": list(selected_ids) if focused else None,
            "max_requests": max_requests if focused else None,
            "max_request_seconds_per_case": 150 if focused else 480,
            "predeclaration": "docs/research-log/2026-10-07-typescript-roles.md"
            if roles
            else "docs/research-log/2026-10-06-failure-audit.md"
            if sql
            else None,
        },
        "implementation": {
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for p in (
                "analysis/sinks.py",
                "analysis/provenance.py",
                "analysis/nextjs.py",
                "analysis/serialization.py",
                "analysis/typescript/serialization_facts.mts",
                "analysis/typescript/nextjs_facts.mts",
                "analysis/typescript/access_facts.mts",
                "analysis/typescript/resolver.mts",
                "agent/families.py",
                "agent/boundaries.py",
                "agent/validator.py",
                "agent/questions.py",
                "agent/guards.py",
                "agent/guard_syntax.py",
                "agent/ts_role_guards.py",
                "eval/feasibility/families.py",
            )
        },
    }

    def preflight() -> PreflightResult:
        result = server.preflight()
        report["preflight"] = asdict(result)
        return result

    try:
        sink_check = SinkInvestigator(snapshot, store, index)
        graph = None if sql else resolve_typescript(snapshot, store, index, settings.cache_dir)
        nextjs = None if sql else extract_nextjs(snapshot, store, index, settings.cache_dir)
        with ModelAdapter(server, preflight=preflight) as adapter:

            class Recorder:
                def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
                    if focused and len(report["requests"]) >= max_requests:
                        raise RuntimeError("Predeclared request limit reached")
                    row: dict[str, Any] = {"request": request.body()}
                    report["requests"].append(row)
                    answer = adapter.ask(request, spend)
                    row["answer"] = asdict(answer)
                    print(f"{request.name}: answer {len(report['requests'])}", flush=True)
                    return answer

            model = Recorder()
            boundary = None
            if graph is not None and nextjs is not None:
                classifier = Classifier(
                    snapshot,
                    store,
                    model,
                    SummaryCache(
                        settings.cache_dir / f"guards/roles-{stamp}.sqlite"
                        if roles
                        else settings.cache_dir / "guards/families.sqlite"
                    ),
                    identity=json.dumps(model_pin, sort_keys=True) + json.dumps(launch),
                )
                boundary = BoundaryInvestigator(snapshot, store, index, graph, nextjs, classifier)
            # Expected labels are used only after investigation, never in model context.
            cases = {c.id: c for c in load().cases}
            selected = (
                [cases[name] for name in selected_ids]
                if focused
                else [c for c in cases.values() if c.family is not Family.AUTHORIZATION]
            )
            for case in selected:
                row: dict[str, Any] = {
                    "case": case.id,
                    "path": case.path,
                    "symbol": case.symbol,
                    "expected": case.expected.value,
                    "passed": False,
                }
                report["cases"].append(row)
                try:
                    spend = Spend(
                        Budget(
                            max_prompt_tokens=18000,
                            max_seconds=150 if focused else 480,
                            max_retries=0,
                        )
                    )
                    if case.family is Family.NEXTJS_EXPOSURE:
                        if boundary is None or nextjs is None:
                            raise RuntimeError("Next.js analysis is unavailable in this sink slice")
                        entry = next(
                            e.entry
                            for e in nextjs.entries
                            if e.entry.span.path == case.path
                            and boundary.symbols[e.entry.handler_symbol_id].name == case.symbol
                        )
                        result = boundary.investigate(entry.id, model, spend)
                        row["result"] = result.model_dump(mode="json")
                        output = boundary_finding(
                            result,
                            boundary,
                            run_id="run:remaining-development",
                            display_id=f"F-{len(report['cases']):02d}",
                        )
                        errors = sink_check.validator.finding(output, guards=result.guards)
                        row["finding"] = output.model_dump(mode="json")
                        row["violations"] = [asdict(e) for e in errors]
                    else:
                        signal = next(
                            i
                            for i, (path, fact) in sink_check.facts.items()
                            if path == case.path and fact.function == case.symbol
                        )
                        result = sink_check.investigate(signal, model, spend)
                        output = finding(
                            result,
                            run_id="run:remaining-development",
                            display_id=f"F-{len(report['cases']):02d}",
                        )
                        errors = sink_check.validator.finding(output, guards=result.guards)
                        row["result"], row["finding"] = (
                            result.model_dump(mode="json"),
                            output.model_dump(mode="json"),
                        )
                        row["violations"] = [asdict(e) for e in errors]
                    row["passed"] = result.conclusion is case.expected and not row.get("violations")
                    row["spend"] = {
                        **asdict(spend),
                        "budget": spend.budget.model_dump(mode="json"),
                    }
                    print(
                        f"{case.id}: {result.conclusion.value}; expected={case.expected.value}; "
                        f"passed={row['passed']}",
                        flush=True,
                    )
                except Exception as error:
                    row["spend"] = {
                        **asdict(spend),
                        "budget": spend.budget.model_dump(mode="json"),
                    }
                    row["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
                    print(f"{case.id}: recorded miss ({type(error).__name__})", flush=True)
                    if focused:
                        raise
            report["completed"] = True
    except Exception as error:
        report["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
    finally:
        server.stop()
        index.close()
        report["memory_abort"] = server.memory_abort
        report["finished"] = datetime.now(UTC).isoformat()
        report["machine_end"] = machine_state()
        task = "m3.4a-focused-roles" if roles else "m3.10b-focused-sql" if sql else "m3.10-families"
        output = RESULTS_DIR / f"{stamp}-{task}.json"
        output.write_text(
            json.dumps(server.redactor.strings(report), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Recorded {output}; completed={report['completed']}", flush=True)
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
