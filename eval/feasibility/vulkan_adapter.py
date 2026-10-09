"""Exercise the measured Vulkan factory through the real budgeted model adapter."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from agent.evidence import Cut, EvidencePacket
from agent.llm import ModelAdapter, Spend
from agent.questions import guard_summary
from agent.validator import check_answer
from backend.contracts.common import Language
from backend.contracts.investigation import Budget
from backend.preflight import PreflightResult
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from backend.vulkan_profile import MODEL_ID, create
from eval.bench.machine import machine_state
from eval.feasibility.common import RESULTS_DIR
from eval.feasibility.constrained_answers import SNIPPET_DIR


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    server = create(Settings(), f"m0-7a-adapter-{stamp}")
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "model": load_model_pins().get(MODEL_ID).model_dump(mode="json"),
        "llama_cpp": load_llama_cpp_pin().model_dump(mode="json"),
        "server_argv": server.config.argv(0, "<per-launch key>"),
        "machine_start": machine_state(),
        "passed": False,
    }

    def preflight() -> PreflightResult:
        result = server.preflight()
        report["preflight"] = asdict(result)
        return result

    name = "receipt_authn_only.py"
    source = (SNIPPET_DIR / name).read_bytes()
    packet = EvidencePacket.build(Cut.whole("function", name, Language.PYTHON, source))
    prompt = guard_summary(packet)
    spend = Spend(Budget(max_prompt_tokens=3000, max_seconds=120, max_retries=0))
    try:
        with ModelAdapter(server, preflight=preflight) as adapter:
            answer = adapter.ask(prompt.request(), spend)
            parsed = prompt.parse(answer.data)
            report["answer"] = asdict(answer)
            report["validator_violations"] = [asdict(v) for v in check_answer(prompt, parsed)]
            report["passed"] = spend.requests == 1 and answer.prompt_tokens > 0
    except Exception as error:
        report["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
    finally:
        server.stop()
        report["memory_abort"] = server.memory_abort
        report["passed"] = report["passed"] and not server.memory_abort
        report["spend"] = {
            "budget": spend.budget.model_dump(),
            "requests": spend.requests,
            "prompt_tokens": spend.prompt_tokens,
            "completion_tokens": spend.completion_tokens,
            "seconds": spend.seconds,
            "retries": spend.retries,
        }
        report["peak_working_set_bytes"] = (
            server.sampler.peak_working_set if server.sampler else None
        )
        report["log"] = (
            server.log_path.read_text(encoding="utf-8") if server.log_path.exists() else None
        )
        report["finished"] = datetime.now(UTC).isoformat()
        report["machine_end"] = machine_state()
        output = RESULTS_DIR / f"{stamp}-m0.7a-vulkan-adapter.json"
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Budgeted adapter passed={report['passed']}; {output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
