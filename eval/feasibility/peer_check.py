"""Real local-model peer acceptance on Tandir source, without running the lab."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelAdapter, ModelRequest, Spend
from agent.peers import PeerCheck
from analysis.access import AccessMap, extract_accesses
from analysis.fastapi import extract_fastapi
from analysis.index import Index, index_path
from analysis.python_resolution import resolve_python
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.preflight import PreflightResult
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from backend.vulkan_profile import MODEL_ID, create
from eval.bench.machine import machine_state
from eval.feasibility.common import RESULTS_DIR


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    settings = Settings()
    server = create(settings, f"m3-5-peers-{stamp}")
    root = RESULTS_DIR.parent.parent / "labs" / "tandir"
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(settings.cache_dir, snapshot.id))
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "model": load_model_pins().get(MODEL_ID).model_dump(mode="json"),
        "llama_cpp": load_llama_cpp_pin().model_dump(mode="json"),
        "server_argv": server.config.argv(0, "<per-launch key>"),
        "snapshot": snapshot.model_dump(mode="json"),
        "machine_start": machine_state(),
        "requests": [],
        "passed": False,
        "scope": "All request-controlled/unresolved Order accesses; other resources separate",
        "implementation_hashes": {
            path: hashlib.sha256((RESULTS_DIR.parent.parent / path).read_bytes()).hexdigest()
            for path in (
                "agent/peers.py",
                "agent/guards.py",
                "agent/guard_syntax.py",
                "agent/questions.py",
                "agent/validator.py",
                "backend/settings.py",
            )
        },
    }

    def preflight() -> PreflightResult:
        result = server.preflight()
        report["preflight"] = asdict(result)
        return result

    try:
        # Static helper finishes before the model starts; reviewed source is never executed.
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
        report["access"] = access.model_dump(mode="json")
        print(f"Static extraction complete: {len(access.accesses)} Order access paths", flush=True)
        with ModelAdapter(server, preflight=preflight) as adapter:

            class Recorder:
                def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
                    row: dict[str, Any] = {"request": request.body()}
                    report["requests"].append(row)
                    answer = adapter.ask(request, spend)
                    row["answer"] = asdict(answer)
                    print(f"Guard judgment {len(report['requests'])} complete", flush=True)
                    return answer

            classifier = Classifier(
                snapshot,
                store,
                Recorder(),
                SummaryCache(settings.cache_dir / "guards" / f"peers-{stamp}.sqlite"),
                identity=json.dumps(report["model"], sort_keys=True)
                + json.dumps(report["server_argv"]),
            )
            engine = PeerCheck(classifier, index, graph, settings)
            result = engine.build(access)
            report["peer_result"] = result.model_dump(mode="json")
            report["summaries"] = [s.model_dump(mode="json") for s in engine.summaries.values()]
            entries = {r.entry.id: r.entry for r in fastapi.routes}
            sites = {
                a.site.id: entries[a.site.entry_point_id].route or "<unrouted>"
                for a in access.accesses
            }
            deviations = {sites[d.site_id] for g in result.groups for d in g.deviations}
            exclusions = {sites[e.site_id]: e.reason for g in result.groups for e in g.excluded}
            acceptance = {
                "receipt_flagged": "/orders/{order_id}/receipt" in deviations,
                "branch_not_flagged": not any(
                    route and (route.startswith("/branches/") or route.startswith("/kitchen/"))
                    for route in deviations
                ),
                "admin_excluded_with_reason": bool(exclusions.get("/admin/orders/{order_id}")),
            }
            report["deviation_routes"], report["exclusion_routes"] = sorted(deviations), exclusions
            report["acceptance"] = acceptance
            report["passed"] = all(acceptance.values())
    except Exception as error:
        report["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
    finally:
        server.stop()
        index.close()
        report["memory_abort"] = server.memory_abort
        report["passed"] = report["passed"] and not server.memory_abort
        report["finished"] = datetime.now(UTC).isoformat()
        report["machine_end"] = machine_state()
        report["peak_working_set_bytes"] = (
            server.sampler.peak_working_set if server.sampler else None
        )
        output = RESULTS_DIR / f"{stamp}-m3.5-peer-check.json"
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Peer development passed={report['passed']}; {output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
