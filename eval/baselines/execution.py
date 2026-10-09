"""Explicit bounded local execution of frozen development baseline packets.

Never executes packet code, installs assets or opens held-out data. Production
investigation settings are unchanged. Actual acceptance remains a separate gate.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import httpx
from pydantic import AwareDatetime, Field, JsonValue

from agent.llm import ModelAdapter, ModelRequest, ModelTimeout, ModelUnavailable, Spend
from analysis.paths import check_relative
from backend import profiles
from backend.contracts.common import Contract, Sha256
from backend.contracts.investigation import Budget
from backend.preflight import PreflightResult
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.opengrep import binary
from backend.setup.pins import load_opengrep_pin
from eval.baselines import development as base
from eval.candidate import write_new
from eval.mutation import development as corpus

ExecutionKind = Literal["local_execution", "software_fixture"]
MAX_RAW = 1_000_000


class ScannerFailure(ValueError):
    def __init__(self, raw: str, reason: str = "Scanner output refused") -> None:
        super().__init__(reason)
        self.raw = raw


class Execution(Contract):
    scope: Literal["development_baseline_execution"] = "development_baseline_execution"
    final_candidate: Literal[False] = False
    evidence_kind: ExecutionKind
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    preparation_sha256: Sha256
    method: base.Method
    state: Literal["completed", "failed", "unrun"] = "unrun"
    execution_pins: dict[str, Sha256]
    machine_start: dict[str, JsonValue] = Field(default_factory=dict)
    machine_end: dict[str, JsonValue] = Field(default_factory=dict)
    observations: dict[str, JsonValue] = Field(default_factory=dict)
    records: list[base.SavedRecord]
    raw_transport: dict[str, str] = Field(default_factory=dict)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    error: str | None = None


def identity() -> dict[str, str]:
    return {
        name: corpus.sha((corpus.ROOT / name).read_bytes())
        for name in (
            "eval/baselines/execution.py",
            "eval/baselines/development.py",
            "agent/llm.py",
            "backend/profiles.py",
            "backend/vulkan_profile.py",
            "backend/llama_server.py",
            "backend/setup/opengrep.py",
            "backend/redaction.py",
            "eval/bench/machine.py",
        )
    }


def machine_state() -> dict[str, Any]:
    # Windows diagnostics are collected only on explicit execution, never at import/preparation.
    from eval.bench.machine import machine_state as read

    return read()


def checkpoint(path: Path, execution: Contract) -> None:
    data = execution.model_dump_json(indent=2).encode()
    if len(data) > base.MAX_BYTES:
        raise ValueError("execution record exceeds persistence budget")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".baseline-", delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            file.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_scanner(raw: str, root: Path, packet: base.Packet) -> str:
    if len(raw.encode()) > MAX_RAW:
        raise ValueError("scanner output exceeded budget")
    data = json.loads(raw, object_pairs_hook=base._unique_pairs)
    if not isinstance(data, dict) or data.get("errors"):
        raise ValueError("scanner returned errors")
    paths = data.get("paths", {})
    if not isinstance(paths, dict) or paths.get("skipped"):
        raise ValueError("scanner skipped frozen inputs")
    rows = data.get("results")
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("scanner result list is missing or unbounded")
    normalized = []
    for row in rows:
        reported = Path(row["path"])
        relative = reported.relative_to(root) if reported.is_absolute() else reported
        path = relative.as_posix()
        check_relative(path)
        normalized.append(
            {
                "check_id": row["check_id"],
                "path": path,
                "start": row["start"],
                "end": row["end"],
                "extra": row["extra"],
            }
        )
    value = json.dumps({"results": normalized, "errors": [], "version": data.get("version")})
    base.raw_predictions(value, "opengrep", packet)
    return value


def scan(exe: Path, packet: base.Packet, settings: Settings, seconds: float) -> tuple[str, str]:
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="baseline-", dir=settings.cache_dir) as folder:
        work = Path(folder)
        root = work / "source"
        root.mkdir()
        for name, source in packet.sources.items():
            path = root.joinpath(*check_relative(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.encode())
        argv = [
            str(exe),
            "scan",
            "--config",
            str(base.RULES),
            "--json",
            "--taint-intrafile",
            "--disable-version-check",
            "--no-git-ignore",
            "--no-rewrite-rule-ids",
            "--quiet",
            "--jobs",
            "1",
            "--timeout",
            "5",
            "--max-memory",
            "256",
            str(root),
        ]
        environment = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith(("OPENGREP_", "SEMGREP_"))
        }
        output = work / "output.json"
        try:
            with output.open("wb") as file:
                done = subprocess.run(  # noqa: S603 - verified binary and trusted pinned rules only
                    argv,
                    cwd=work,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=file,
                    stderr=subprocess.DEVNULL,
                    timeout=seconds,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
        except subprocess.TimeoutExpired as error:
            if output.stat().st_size <= MAX_RAW:
                raise ScannerFailure(
                    output.read_text(encoding="utf-8", errors="replace"), "Scanner timed out"
                ) from error
            raise ValueError("Scanner timeout output exceeded budget") from error
        if output.stat().st_size > MAX_RAW:
            raise ValueError("scanner output exceeded budget")
        raw = output.read_text(encoding="utf-8")
        if done.returncode not in (0, 1):
            raise ScannerFailure(raw, f"Scanner exited {done.returncode}")
        try:
            return raw, normalize_scanner(raw, root, packet)
        except (ValueError, KeyError, TypeError, IndexError, RecursionError) as error:
            raise ScannerFailure(raw) from error


class ObservedAdapter(ModelAdapter):
    """Retain bounded completion content even when the existing decoder refuses it."""

    raw: str | None = None

    def _attempt(
        self, path: str, body: dict[str, Any], limit: float
    ) -> httpx.Response | ModelTimeout | ModelUnavailable:
        result = super()._attempt(path, body, limit)
        if path == "/v1/chat/completions" and isinstance(result, httpx.Response):
            try:
                raw = result.json()["choices"][0]["message"]["content"]
                if isinstance(raw, str) and len(raw.encode()) <= MAX_RAW:
                    self.raw = self.redactor.text(raw)
            except (ValueError, KeyError, IndexError, TypeError):
                pass
        return result


def accounting(prepared: base.Preparation, execution: Execution) -> dict[str, JsonValue]:
    # Fresh outputs are explicitly replayed into the saved-output scorer. Preserve
    # the actual execution kind in the outer manifest; never call replay fresh acceptance.
    if execution.execution_pins != identity():
        raise ValueError("Execution implementation drift")
    run = base.SavedRun(
        preparation_sha256=execution.preparation_sha256,
        method=execution.method,
        evidence_kind="software_fixture"
        if execution.evidence_kind == "software_fixture"
        else "saved_answer_replay",
        state=execution.state,
        records=execution.records,
    )
    return base.account(prepared, run)


def execute(
    prepared: base.Preparation,
    method: base.Method,
    output: Path,
    settings: Settings,
    *,
    evidence_kind: ExecutionKind = "local_execution",
    clock: Callable[[], float] = time.perf_counter,
) -> Execution:
    packets = base.check(prepared)
    if method not in {"one_shot", "opengrep"}:
        raise ValueError("Unknown baseline method")
    started = clock()
    execution = Execution(
        evidence_kind=evidence_kind,
        started_at=datetime.now(UTC),
        preparation_sha256=corpus.sha(corpus.canonical(prepared.model_dump(mode="json"))),
        method=method,
        execution_pins=identity(),
        records=[
            base.SavedRecord(
                case_id=case.id,
                packet_sha256=packet.sha256,
                state="unrun",
                error="Not attempted",
                seconds=0,
                prompt_tokens=0,
                completion_tokens=0,
            )
            for case, packet in zip(prepared.cases, packets, strict=True)
        ],
    )
    write_new(output, execution)  # Exclusive before diagnostics/assets/processes.
    server = None
    adapter = None
    redactor = Redactor.configured()
    try:
        execution = execution.model_copy(update={"machine_start": machine_state()})
        remaining = prepared.max_seconds - (clock() - started)
        if remaining <= 0:
            raise TimeoutError("Batch budget elapsed before initialization")
        exe = None
        if method == "opengrep":
            exe = binary(settings, load_opengrep_pin())
        else:
            log_name = f"baseline-{uuid4().hex}"
            execution.observations["log_id"] = log_name
            server = profiles.create(settings, log_name, profiles.Profile())
            server.startup_timeout = min(server.startup_timeout, remaining)

            def preflight() -> PreflightResult:
                from dataclasses import asdict

                result = server.preflight()
                execution.observations["preflight"] = asdict(result)
                return result

            adapter = ObservedAdapter(server, preflight=preflight)
            adapter.start()
            execution.observations["load_seconds"] = server.load_seconds
        for i, packet in enumerate(packets):
            remaining = prepared.max_seconds - (clock() - started)
            if i >= prepared.max_attempts or remaining <= 0:
                execution = execution.model_copy(
                    update={"error": "Declared batch attempt/time limit reached"}
                )
                break
            began = clock()
            raw = None
            prompt_tokens = completion_tokens = 0
            spend = Spend(
                Budget(
                    max_prompt_tokens=profiles.Profile().context - 600,
                    max_seconds=remaining,
                    max_retries=0,
                )
            )
            try:
                if exe is not None:
                    native, raw = scan(exe, packet, settings, remaining)
                    execution.raw_transport[prepared.cases[i].id] = redactor.text(native)
                else:
                    if adapter is None:
                        raise ValueError("Model adapter unavailable")
                    adapter.raw = None
                    body = base.request(packet)
                    request = ModelRequest(
                        name="matched_baseline",
                        system=str(body["system"]),
                        user=str(body["user"]),
                        schema=cast(dict[str, Any], body["schema"]),
                        max_tokens=600,
                    )
                    if adapter.redactor.text(request.user) != request.user or (
                        adapter.redactor.text(request.system) != request.system
                    ):
                        raise ValueError("Redaction would change matched baseline input")
                    answer = adapter.ask(request, spend)
                    raw = answer.raw
                    prompt_tokens, completion_tokens = (
                        answer.prompt_tokens,
                        answer.completion_tokens,
                    )
                base.raw_predictions(raw, method, packet)
                record = base.SavedRecord(
                    case_id=prepared.cases[i].id,
                    packet_sha256=packet.sha256,
                    state="completed",
                    raw=redactor.text(raw),
                    seconds=clock() - began,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            except Exception as error:
                if isinstance(error, ScannerFailure):
                    execution.raw_transport[prepared.cases[i].id] = redactor.text(error.raw)
                record = base.SavedRecord(
                    case_id=prepared.cases[i].id,
                    packet_sha256=packet.sha256,
                    state="failed",
                    error=str(error)
                    if isinstance(error, ScannerFailure)
                    else f"Attempt refused ({type(error).__name__})",
                    seconds=clock() - began,
                    prompt_tokens=spend.prompt_tokens,
                    completion_tokens=spend.completion_tokens,
                )
            if adapter is not None and adapter.raw is not None:
                execution.raw_transport[prepared.cases[i].id] = adapter.raw
            execution.records[i] = record
            if len(execution.model_dump_json().encode()) > base.MAX_BYTES - 200_000:
                execution.raw_transport.pop(prepared.cases[i].id, None)
                execution.records[i] = record.model_copy(
                    update={
                        "state": "failed",
                        "raw": None,
                        "error": "Aggregate output budget exceeded",
                    }
                )
                execution = execution.model_copy(
                    update={"error": "Aggregate output budget exceeded; current raw omitted"}
                )
                break
            checkpoint(output, execution)
    except BaseException as error:
        execution = execution.model_copy(
            update={"error": f"Batch refused ({type(error).__name__})"}
        )
    finally:
        if server is not None:
            try:
                server.stop()  # Also closes clients after preflight/start failures.
                if server.sampler is not None:
                    execution.observations["peak_working_set_bytes"] = (
                        server.sampler.peak_working_set
                    )
                    execution.observations["peak_private_bytes"] = server.sampler.peak_private
            except Exception as error:
                execution = execution.model_copy(
                    update={"error": f"Model teardown failed ({type(error).__name__})"}
                )
        try:
            execution = execution.model_copy(update={"machine_end": machine_state()})
        except Exception:
            execution.observations["machine_end"] = "unavailable"
        execution = execution.model_copy(
            update={"elapsed_seconds": clock() - started, "finished_at": datetime.now(UTC)}
        )
        state = (
            "failed"
            if execution.error
            or any(r.state != "completed" for r in execution.records)
            or execution.elapsed_seconds > prepared.max_seconds
            else "completed"
        )
        execution = execution.model_copy(update={"state": state})
        checkpoint(output, execution)
    return execution


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("preparation", type=Path)
    run.add_argument("--method", choices=["one_shot", "opengrep"], required=True)
    run.add_argument("--output", type=Path, required=True)
    account_command = commands.add_parser("account")
    account_command.add_argument("preparation", type=Path)
    account_command.add_argument("execution", type=Path)
    account_command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepared = base.Preparation.model_validate(base.read(args.preparation, base.Preparation))
        if args.command == "account":
            if args.execution.stat().st_size > base.MAX_BYTES:
                raise ValueError("Execution exceeds record budget")
            raw = args.execution.read_bytes()
            if len(raw) > base.MAX_BYTES:
                raise ValueError("Execution exceeds record budget")
            value = Execution.model_validate_json(raw)
            write_new(args.output, accounting(prepared, value))
            print("Accounted saved execution; release acceptance remains unassessed.")
            return 0
        execution = execute(prepared, args.method, args.output, Settings())
        print(f"Execution {execution.state}; saved all case records, final gates unassessed.")
        return 0 if execution.state == "completed" else 1
    except (OSError, ValueError):
        print("Baseline execution refused; inspect saved identity/bounds.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
