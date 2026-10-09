"""First-use check of a CPU profile on this computer (ADR-0024).

A memory estimate alone does not qualify a profile (PROJECT_PLAN §9.1). Before its
first review, each computer answers the two build-acceptance checks with the exact
profile: structured answers (M0.6) and the cross-request leak check (M0.8). The saved
record is tied to the profile, the pins and the host. It is not a security boundary.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins

if TYPE_CHECKING:
    from backend.profiles import Host, Profile
    from backend.vulkan_profile import VulkanServer

FORMAT = 1
PAIRS = 10
NOT_NEEDED, PENDING, PASSED, FAILED, REFUSED = (
    "not needed",
    "pending",
    "passed",
    "failed",
    "refused",
)


def folder(settings: Settings) -> Path:
    return settings.data_dir / "profile-checks"


def host_facts(host: "Host") -> dict[str, Any]:
    """What ties a check to one computer. No serial number, account or process list."""
    return {
        "os": host.os,
        "architecture": host.architecture,
        "cpu": host.cpu,
        "physical_cores": host.physical_cores,
        "logical_cores": host.logical_cores,
        "total_memory_bytes": host.memory.total_bytes,
    }


def key(profile: "Profile", host: "Host") -> str:
    model = load_model_pins().get(profile.model_id)
    runtime = load_llama_cpp_pin()
    payload = {
        "format": FORMAT,
        "profile": profile.identity(),
        "model_sha256": model.sha256,
        "runtime": [runtime.release, runtime.build, runtime.commit],
        "host": host_facts(host),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def state(settings: Settings, profile: "Profile", host: "Host") -> str:
    """The newest pass or fail saved for this exact profile, pins and computer."""
    if profile.device_name:
        return NOT_NEEDED  # measured on its own hardware (ADR-0006)
    wanted, newest = key(profile, host), PENDING
    try:
        records = sorted(folder(settings).glob(f"{profile.id}-*.json"))
    except OSError:
        return PENDING
    for path in records:  # file names begin with the time of the check
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(record, dict)
            and record.get("key") == wanted
            and record.get("outcome") in {PASSED, FAILED}
        ):
            newest = record["outcome"]
    return newest


def passed(record: dict[str, Any]) -> bool:
    answers, pairs = record.get("answers", []), record.get("canary", [])
    return (
        len(answers) == 3
        and all(row.get("parsed") and not row.get("invalid_citations") for row in answers)
        and len(pairs) == PAIRS
        and all(row["a_contains_token"] and not row["leaked"] for row in pairs)
    )


def explain(record: dict[str, Any]) -> str:
    saved = f" Record: {record['path']}" if record.get("path") else ""
    if record["outcome"] == REFUSED:
        return (
            "The first-use check of the model runner could not run: "
            f"{record.get('reason', 'not enough free memory')} "
            "Nothing was decided about this computer; close apps and try again." + saved
        )
    return (
        "The model runner failed its first-use check on this computer, so AI review is off. "
        "Run plumb calibrate to try again; plumb inspect still works." + saved
    )


def run(
    settings: Settings,
    profile: "Profile",
    host: "Host",
    server: "VulkanServer",
    say: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Load the model once on ``server``, answer both checks, then save and return the record."""
    from eval.bench.machine import machine_state
    from eval.feasibility.canary import run_pairs
    from eval.feasibility.constrained_answers import SNIPPETS, run_one

    model, runtime = load_model_pins().get(profile.model_id), load_llama_cpp_pin()
    stamp = datetime.now(UTC)
    record: dict[str, Any] = {
        "format": FORMAT,
        "key": key(profile, host),
        "profile": profile.identity(),
        "host": host_facts(host),
        "model": model.model_dump(mode="json"),
        "llama_cpp": {
            "release": runtime.release,
            "build": runtime.build,
            "commit": runtime.commit,
            "backend": profile.backend,
        },
        "server_argv": server.config.argv(0, "<per-launch key>"),
        "started": stamp.isoformat(),
        "answers": [],
        "canary": [],
        "model_loaded": False,
        "outcome": FAILED,
    }
    try:
        record["machine_start"] = machine_state()
        admission = server.preflight()
        record["preflight"] = asdict(admission)
        if not admission.ok:
            record.update(outcome=REFUSED, reason=admission.message)
            return record
        server.start()
        record.update(model_loaded=True, load_seconds=server.load_seconds)
        for index, snippet in enumerate(SNIPPETS, 1):
            record["answers"].append(run_one(server, *snippet))
            say(f"  First-use check: structured answer {index} of {len(SNIPPETS)}")
        for index in range(1, PAIRS + 1):
            record["canary"].extend(run_pairs(server, 1, False))
            say(f"  First-use check: leak-check pair {index} of {PAIRS}")
        record["outcome"] = PASSED if passed(record) else FAILED
    except Exception as error:
        record["error"] = server.redactor.text(f"{type(error).__name__}: {error}")
    finally:
        if server.sampler is not None:
            server.sampler.sample()
            record["peak_working_set_bytes"] = server.sampler.peak_working_set
            record["peak_private_bytes"] = server.sampler.peak_private
        try:
            server.stop()
        except Exception as error:
            record["cleanup_error"] = type(error).__name__
            record["outcome"] = FAILED
        if server.memory_abort and record["outcome"] != PASSED:
            # The computer ran short of memory; that says nothing about the runner.
            record.update(outcome=REFUSED, reason=server.memory_abort)
        record["memory_abort"] = server.memory_abort
        record["finished"] = datetime.now(UTC).isoformat()
        record["machine_end"] = machine_state()
        path = folder(settings) / f"{profile.id}-{stamp.strftime('%Y%m%d-%H%M%S-%f')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record["path"] = str(path)
        path.write_text(
            json.dumps(Redactor.configured().strings(record), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return record
