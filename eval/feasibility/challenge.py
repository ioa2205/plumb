"""Recorded real-model challenge acceptance; cached guards retain their provenance."""

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.challenge import AuthorizationChallenge, finding
from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelAdapter, ModelRequest, Spend
from agent.peers import PeerCheck
from analysis.access import AccessMap, extract_accesses
from analysis.fastapi import extract_fastapi
from analysis.index import Index, index_path
from analysis.python_resolution import resolve_python
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.investigation import Budget, Conclusion
from backend.preflight import PreflightResult
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from backend.vulkan_profile import MODEL_ID, create
from eval.bench.machine import machine_state
from eval.feasibility.common import RESULTS_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard-cache", type=Path)
    args = parser.parse_args()
    settings = Settings()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    server = create(settings, f"m3-6-challenge-{stamp}")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(RESULTS_DIR.parent.parent / "labs" / "tandir", store)
    index = Index.build(snapshot, store, index_path(settings.cache_dir, snapshot.id))
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "model": load_model_pins().get(MODEL_ID).model_dump(mode="json"),
        "llama_cpp": load_llama_cpp_pin().model_dump(mode="json"),
        "server_argv": server.config.argv(0, "<per-launch key>"),
        "snapshot": snapshot.model_dump(mode="json"),
        "machine_start": machine_state(),
        "requests": [],
        "cases": [],
        "passed": False,
        "implementation_hashes": {
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for p in (
                "agent/challenge.py",
                "agent/peers.py",
                "agent/questions.py",
                "agent/validator.py",
            )
        },
        "guard_cache": str(args.guard_cache) if args.guard_cache else "shared summaries",
    }

    def preflight() -> PreflightResult:
        result = server.preflight()
        report["preflight"] = asdict(result)
        return result

    try:
        fastapi = extract_fastapi(snapshot, store, index)
        graph = resolve_python(snapshot, store, index, settings.cache_dir, use_ty=False)
        access = extract_accesses(
            snapshot, store, index, settings.cache_dir, fastapi=fastapi, python_graph=graph
        )
        access = AccessMap(
            snapshot_id=snapshot.id,
            accesses=[a for a in access.accesses if a.site.resource == "Order"],
            issues=access.issues,
        )
        entries = {r.entry.id: r.entry.route for r in fastapi.routes}
        with ModelAdapter(server, preflight=preflight) as adapter:

            class Recorder:
                def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
                    row: dict[str, Any] = {"request": request.body()}
                    report["requests"].append(row)
                    answer = adapter.ask(request, spend)
                    row["answer"] = asdict(answer)
                    print(
                        f"{request.name}: judgment {len(report['requests'])} complete", flush=True
                    )
                    return answer

            model = Recorder()
            classifier = Classifier(
                snapshot,
                store,
                model,
                SummaryCache(
                    args.guard_cache or settings.cache_dir / "guards" / "summaries.sqlite"
                ),
                identity=json.dumps(report["model"], sort_keys=True)
                + json.dumps(report["server_argv"]),
            )
            peers = PeerCheck(classifier, index, graph, settings)
            challenge = AuthorizationChallenge(peers, access, model)
            report["validated_guard_cache_hits"] = classifier.cache_hits
            for route, display, expected in (
                ("/orders/{order_id}/invoice", "F-08", Conclusion.REJECTED),
                ("/orders/{order_id}/receipt", "F-07", Conclusion.SUPPORTED),
            ):
                path = next(a for a in access.accesses if entries[a.site.entry_point_id] == route)
                result = challenge.investigate(
                    path.site.id,
                    Spend(Budget(max_prompt_tokens=12000, max_seconds=360, max_retries=0)),
                )
                case = finding(result, run_id="run:challenge-development", display_id=display)
                violations = classifier.validator.finding(case, guards=result.guards)
                passed = result.conclusion is expected and not violations
                report["cases"].append(
                    {
                        "route": route,
                        "expected": expected.value,
                        "passed": passed,
                        "result": result.model_dump(mode="json"),
                        "finding": case.model_dump(mode="json"),
                        "violations": [asdict(v) for v in violations],
                    }
                )
                print(f"{display}: {result.conclusion.value}; passed={passed}", flush=True)
            report["passed"] = all(c["passed"] for c in report["cases"])
    except Exception as error:
        report["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
    finally:
        server.stop()
        index.close()
        report["memory_abort"] = server.memory_abort
        report["passed"] = report["passed"] and not server.memory_abort
        report["finished"] = datetime.now(UTC).isoformat()
        report["machine_end"] = machine_state()
        output = RESULTS_DIR / f"{stamp}-m3.6-challenge.json"
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Challenge acceptance passed={report['passed']}; {output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
