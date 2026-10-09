"""Shared setup for runs against the real model: preflight, server, manifest, output."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.llama_server import LlamaServer, ServerConfig
from backend.preflight import check
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.models import model_path
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from eval.bench.machine import machine_state

RESULTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "results"


class PreflightRefused(RuntimeError):
    """Not enough free memory to load the model without paging."""


def start(
    *,
    model_id: str,
    variant: str,
    margin_bytes: int,
    log_name: str,
    ctx_size: int = 8192,
    threads: int = 4,
    stateless: bool = True,
) -> tuple[LlamaServer, dict[str, Any]]:
    """Preflight, then start the server. Returns the running server and the run manifest."""
    settings, pins, llama = Settings(), load_model_pins(), load_llama_cpp_pin()
    model = pins.get(model_id)
    result = check(model, ctx_size, margin_bytes, alternatives=pins.models)
    print(result.message, flush=True)
    if not result.ok:
        raise PreflightRefused(result.message)
    config = ServerConfig(
        binary=llama_cpp.binary(settings, llama, variant),
        model=model_path(settings, model),
        ctx_size=ctx_size,
        threads=threads,
        stateless=stateless,
    )
    manifest: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "llama_cpp": {"release": llama.release, "build": llama.build, "variant": variant},
        "model": {
            "id": model.id,
            "family": model.family,
            "file": model.file,
            "sha256_pinned": model.sha256,
            "quantization": model.quantization,
        },
        "settings": {
            "ctx_size": ctx_size,
            "threads": threads,
            "stateless": stateless,
            "server_argv": config.argv(0, "<per-launch key>"),
        },
        "preflight": {"margin_bytes": margin_bytes, "message": result.message},
        "machine_start": machine_state(),
    }
    server = LlamaServer(config, settings.cache_dir / "run-logs" / f"{log_name}.log")
    server.start()
    manifest["load_seconds"] = server.load_seconds
    return server, manifest


def finish(server: LlamaServer, manifest: dict[str, Any]) -> None:
    sampler = server.sampler
    if sampler is not None:
        sampler.sample()
        manifest["peak_working_set_bytes"] = sampler.peak_working_set
        manifest["peak_private_bytes"] = sampler.peak_private
    server.stop()
    manifest["finished"] = datetime.now(UTC).isoformat()
    manifest["machine_end"] = machine_state()


def write(name: str, report: dict[str, Any], summary_md: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    json_path = RESULTS_DIR / f"{stamp}-{name}.json"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    md = summary_md.replace("{json_name}", json_path.name)
    (RESULTS_DIR / f"{stamp}-{name}.md").write_text(md, encoding="utf-8", newline="\n")
    return json_path
