"""Preview or install Plumb's own locked CLI prerequisites; never loads a model.

Run from the repository: uv run plumb setup [--install] [--json]
Large missing downloads require --approve-large-downloads. No driver/admin action.
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from backend.profiles import (
    NOT_COMPARED,
    REGISTRY,
    chosen,
    cpu_profile_id,
    doctor,
    verify_runtime,
)
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup import llama_cpp, opengrep
from backend.setup.download import DownloadError, UnsafeArchiveError, fetch, is_verified
from backend.setup.models import model_path
from backend.setup.pins import load_llama_cpp_pin, load_model_pins, load_opengrep_pin
from backend.system_tools import on_search_path, unsupported_system
from backend.user_config import remember_location

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "analysis/typescript"


def _run(argv: list[str]) -> str:
    result = subprocess.run(  # noqa: S603 - trusted tools and this repository's locked helper only
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return result.stdout.strip()


def pnpm_command(node: Path) -> list[str] | None:
    found = on_search_path("pnpm")
    if found is None:
        return None
    command = found.resolve()
    if command.suffix.lower() == ".exe":
        return [str(command)]
    # Invoke the installed JS entry directly; do not build a cmd/PowerShell string.
    for entry in (
        command.parent / "node_modules/pnpm/bin/pnpm.cjs",
        command.parent / "node_modules/corepack/dist/pnpm.js",
    ):
        if entry.is_file():
            return [str(node), str(entry)]
    return None


def helper_status(settings: Settings) -> dict[str, Any]:
    node_version = None
    try:
        if settings.node_binary.is_file():
            node_version = _run([str(settings.node_binary), "--version"])
        major = int((node_version or "").removeprefix("v").split(".")[0])
        node_ok = major >= 24
    except (OSError, ValueError, subprocess.SubprocessError):
        node_ok = False
    installed = False
    try:
        package = HELPER / "node_modules/typescript/package.json"
        installed = json.loads(package.read_text(encoding="utf-8"))["version"] == "6.0.3"
        installed = installed and (HELPER / "node_modules/typescript/lib/typescript.js").is_file()
    except (OSError, ValueError, KeyError):
        pass
    manager = pnpm_command(settings.node_binary)
    return {
        "node_binary": str(settings.node_binary),
        "node_version": node_version,
        "node_compatible": node_ok,
        "typescript_version_matches_pin": installed,
        "pnpm_available": manager is not None,
        "pnpm_command": manager,
        "ready": node_ok and installed,
        "action": (
            "Install Node.js 24+ and pnpm if missing; PLUMB_NODE_BINARY accepts an absolute path"
        ),
    }


def installable_models() -> list[str]:
    """Pinned models a CPU profile can review with: the default first."""
    return [m.id for m in load_model_pins().models if cpu_profile_id(m) in REGISTRY]


def preview(
    settings: Settings, *, inspect_only: bool = False, model_id: str | None = None
) -> dict[str, Any]:
    if settings.data_dir.resolve().is_relative_to(ROOT):
        raise ValueError("PLUMB_DATA_DIR must be outside the repository")
    if model_id is not None and inspect_only:
        raise ValueError("--model installs a review model; it cannot be used with --inspect-only")
    if model_id is not None and model_id not in installable_models():
        raise ValueError(f"Unknown or unsupported model {model_id!r}; see plumb doctor --json")
    report = doctor(settings)
    pins = load_model_pins()
    # The profile this computer would review with; systems without one install nothing.
    judged = chosen(report)
    available = report["selected_profile"] is not None
    # A named model other than that profile's is reviewed through its own CPU profile.
    other = model_id is not None and model_id != judged["model_id"]
    if other:
        judged = chosen(report, cpu_profile_id(pins.get(model_id)))
        available = judged["compatible_measured_host"]
    profile = REGISTRY[judged["id"]]
    model = pins.get(profile.model_id)
    runtime = load_llama_cpp_pin()
    missing: list[dict[str, Any]] = []
    if not inspect_only and available:
        if not judged["model_verified"]:
            missing.append(
                {
                    "kind": "model",
                    "source": model.url,
                    "size_bytes": model.size,
                    "sha256": model.sha256,
                    "license": model.license,
                }
            )
        for asset in runtime.variants[profile.backend].assets:
            archive = llama_cpp.downloads_dir(settings) / asset.name
            if not is_verified(archive, sha256=asset.sha256, size=asset.size):
                missing.append(
                    {
                        "kind": "runtime",
                        "source": asset.url,
                        "size_bytes": asset.size,
                        "sha256": asset.sha256,
                        "license": "MIT (llama.cpp); bundled dependencies retain their licenses",
                    }
                )
        scanner = report["pattern_scanner"]
        if not scanner["verified_installed"]:
            # Reviews order their questions with it (PROJECT_PLAN §7); inspection does not use it.
            missing.append(
                {
                    "kind": "pattern scanner",
                    "source": scanner["source"],
                    "size_bytes": scanner["size_bytes"],
                    "sha256": scanner["sha256"],
                    "license": scanner["license"],
                }
            )
    helper = helper_status(settings)
    total = sum(item["size_bytes"] for item in missing)
    return {
        "mode": "inspect-only" if inspect_only else "review",
        "data_dir": str(settings.data_dir),
        "profile": profile.id if available and not inspect_only else None,
        "model": model_id,
        "model_note": f"{model.family} ({model.id}): {NOT_COMPARED}" if other else None,
        "doctor": report,
        "typescript_helper": helper,
        "missing_downloads": missing,
        "missing_download_bytes": total,
        "requires_large_download_approval": total > 500_000_000,
        "model_loaded": False,
        "ready": helper["ready"]
        and (inspect_only or (judged["ready"] if other else report["selection_ready"])),
        "next": "plumb setup --install"
        + (" --inspect-only" if inspect_only else "")
        + (f" --model {model_id}" if model_id else "")
        + (" --approve-large-downloads" if total > 500_000_000 else ""),
    }


def install(
    settings: Settings, plan: dict[str, Any], *, approve_large_downloads: bool = False
) -> dict[str, Any]:
    inspect_only = plan["mode"] == "inspect-only"
    # A preview can go stale. Recompute before any installation and check again at fetch.
    plan = preview(settings, inspect_only=inspect_only, model_id=plan.get("model"))
    if plan["requires_large_download_approval"] and not approve_large_downloads:
        raise ValueError(
            "Missing downloads exceed 500 MB; inspect the preview and explicitly approve first"
        )
    if not inspect_only and plan["profile"] is None:
        raise ValueError(
            "No review profile exists for this system (AI review needs 64-bit Windows); "
            "use --inspect-only"
        )
    helper = plan["typescript_helper"]
    if not helper["node_compatible"]:
        raise ValueError(helper["action"])
    if not helper["ready"] and not helper["pnpm_available"]:
        raise ValueError("Install pnpm for the trusted TypeScript helper, then rerun setup")
    free = plan["doctor"]["inventory"]["disk_free_bytes"]
    if free is None or free < plan["missing_download_bytes"]:
        raise ValueError(
            "Free disk space cannot cover even the missing downloads; no installation started"
        )
    if not helper["ready"]:
        _run(
            [
                *helper["pnpm_command"],
                "--dir",
                str(HELPER),
                "install",
                "--frozen-lockfile",
                "--ignore-scripts",
                "--prefer-offline",
            ]
        )
    if not inspect_only:
        profile = REGISTRY[plan["profile"]]
        runtime = load_llama_cpp_pin()
        model = load_model_pins().get(profile.model_id)
        if not verify_runtime(settings, runtime, profile.backend):
            if llama_cpp.is_installed(settings, runtime, profile.backend):
                raise ValueError(
                    "Runtime integrity failed; preserve existing files "
                    "and use a clean data directory"
                )
            with httpx.Client(timeout=httpx.Timeout(30, read=120)) as client:
                llama_cpp.install(settings, runtime, profile.backend, client)
        if not is_verified(model_path(settings, model), sha256=model.sha256, size=model.size):
            if model.size > 500_000_000 and not approve_large_downloads:
                raise ValueError(
                    "Model became missing/unverified; large download approval is required"
                )
            with httpx.Client(timeout=httpx.Timeout(30, read=120)) as client:
                fetch(
                    model.url,
                    model_path(settings, model),
                    sha256=model.sha256,
                    size=model.size,
                    client=client,
                )
        scanner = load_opengrep_pin()
        if not is_verified(
            opengrep.binary_path(settings, scanner),
            sha256=scanner.asset.sha256,
            size=scanner.asset.size,
        ):
            with httpx.Client(timeout=httpx.Timeout(30, read=120)) as client:
                opengrep.install(settings, scanner, client)
    result = preview(settings, inspect_only=inspect_only, model_id=plan.get("model"))
    result["installation_attempted"] = True
    result["note"] = "Assets installed; inference still checks live memory. No model was loaded."
    return result


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Shared public and legacy module flags; no installation while parsing."""
    parser.add_argument(
        "--install", action="store_true", help="Install only this repo's locked prerequisites"
    )
    parser.add_argument(
        "--approve-large-downloads",
        action="store_true",
        help="Explicitly approve the pinned downloads disclosed by the preview",
    )
    parser.add_argument(
        "--inspect-only", action="store_true", help="Set up source inspection without model assets"
    )
    parser.add_argument(
        "--model",
        choices=installable_models(),
        help="Install this pinned model instead of the default (see plumb doctor)",
    )
    parser.add_argument("--data-dir", type=Path, help="Absolute external data directory")
    parser.add_argument(
        "--json", action="store_true", help="Print full machine-readable diagnostics"
    )


def human_summary(result: dict[str, Any], *, installing: bool) -> str:
    """Explain state and next action; keep exact download disclosures visible."""
    if "setup_refused" in result:
        lines = [f"Setup could not finish: {result['setup_refused']}"]
        for key in (
            "installation_error",
            "record_write_error",
            "preferences_write_error",
            "action",
        ):
            if result.get(key):
                lines.append(str(result[key]))
        return "\n".join([*lines, "No model was loaded. Full diagnostics: plumb setup --json"])
    inspection = result["mode"] == "inspect-only"
    lines = ["Plumb setup result" if installing else "Plumb setup preview (no installation)"]
    lines.append(f"Data folder: {result['data_dir']}")
    if result.get("preferences_file"):
        lines.append(f"Data folder remembered for later terminals: {result['preferences_file']}")
    lines.append("Mode: source inspection" if inspection else "Mode: AI source review")
    lines.append("Windows Sandbox, Docker and administrator rights are not required for this mode.")
    helper = result["typescript_helper"]
    lines.append("Source tools: ready" if helper["ready"] else f"Source tools: {helper['action']}")
    report = result["doctor"]
    if not inspection:
        selected = result.get("profile") or report["selected_profile"]
        lines.append(f"Review profile: {selected or 'none for this system'}")
        if result.get("model_note"):
            lines.append(f"Model: {result['model_note']}")
            lines.append(f"Review with it by adding: --profile {selected}")
        judged = chosen(report, selected)
        lines.extend(report["messages"] if not result.get("model_note") else judged["messages"])
        lines.append(f"Evaluated scope: {judged['evaluated_capability']}")
    missing = result["missing_downloads"]
    if missing:
        lines.append(f"Missing pinned downloads: {result['missing_download_bytes']:,} bytes")
        for item in missing:
            lines.extend(
                [
                    f"  {item['kind']}: {item['size_bytes']:,} bytes; {item['license']}",
                    f"  Source: {item['source']}",
                    f"  SHA256: {item['sha256']}",
                ]
            )
        if result["requires_large_download_approval"]:
            lines.append(
                "Installation requires explicit large-download approval after this preview."
            )
    else:
        lines.append("No model/runtime downloads are missing for this mode.")
    if result["ready"]:
        lines.append(
            "Ready for source inspection." if inspection else "Ready for the scoped AI review."
        )
        lines.append(
            "Next: plumb inspect <folder>"
            if inspection
            else "Next: plumb review <folder> --open-report"
        )
        if any(item["kind"] == "pattern scanner" for item in missing):
            lines.append(
                "The pattern scanner is not installed yet. A review still runs, but its "
                "questions are not ordered by pattern leads. Install it with: plumb setup --install"
            )
    elif not inspection and report["selected_profile"] is None:
        lines.append(
            "AI review is not available on this system; source inspection works without a model."
        )
        lines.append("Next: plumb setup --install --inspect-only")
    elif installing:
        lines.append(
            "Setup remains incomplete; address the diagnostic above, then rerun plumb setup."
        )
    else:
        lines.append(f"Next: {result['next']}")
    lines.append("No model was loaded. Full diagnostics: plumb setup --json")
    return "\n".join(lines)


def execute(args: argparse.Namespace) -> int:
    """Run the shared installer and announce success only after saving its record."""
    record: dict[str, Any] = {"started": datetime.now(UTC).isoformat(), "model_loaded": False}
    settings = None
    redactor = Redactor()
    redaction_ready = False
    result: dict[str, Any] = {}
    result_code = 1
    try:
        # Redaction settings must be available even when remembered storage is invalid.
        # This explicit path is used only to read environment secrets; it is never written.
        redactor = Redactor.configured(Settings(data_dir=ROOT.parent))
        redaction_ready = True
        settings = Settings(data_dir=args.data_dir) if args.data_dir else Settings()
        plan = preview(settings, inspect_only=args.inspect_only, model_id=args.model)
        record["preview"] = plan
        if args.install:
            result = install(settings, plan, approve_large_downloads=args.approve_large_downloads)
            record["result"] = result
            result_code = 0 if result["ready"] else 2
        else:
            result = plan
            result_code = 0
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        httpx.HTTPError,
        DownloadError,
        UnsafeArchiveError,
    ) as error:
        record["error"] = (
            redactor.text(f"{type(error).__name__}: {error}")
            if redaction_ready
            else "Invalid Plumb environment settings; check PLUMB_* values and rerun setup"
        )
        result = {"setup_refused": record["error"], "model_loaded": False}
    finally:
        if args.install and settings is not None and "preview" in record:
            record["finished"] = datetime.now(UTC).isoformat()
            record["exit_code"] = result_code
            folder = settings.cache_dir / "setup"
            try:
                folder.mkdir(parents=True, exist_ok=True)
                record_path = folder / f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}.json"
                record_path.write_text(
                    json.dumps(redactor.strings(record), indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                if result_code == 0:
                    try:
                        result["preferences_file"] = str(remember_location(settings.data_dir))
                    except (OSError, ValueError) as error:
                        result_code = 1
                        result = {
                            "setup_refused": "Could not remember the data folder",
                            "preferences_write_error": f"{type(error).__name__}: {error}",
                            "action": (
                                "Use PLUMB_DATA_DIR for this terminal. Assets and existing "
                                "preferences were preserved; full automatic setup is incomplete."
                            ),
                            "model_loaded": False,
                        }
                        record.update(result=result, exit_code=result_code)
                        record_path.write_text(
                            json.dumps(redactor.strings(record), indent=2) + "\n",
                            encoding="utf-8",
                            newline="\n",
                        )
            except OSError as error:
                result_code = 1
                result = {
                    "setup_refused": "Could not save the setup outcome record",
                    "record_write_error": f"{type(error).__name__}: {error}",
                    "action": (
                        "Choose a writable external PLUMB_DATA_DIR and rerun the setup preview. "
                        "Assets may already be installed; preserve existing files."
                    ),
                    "model_loaded": False,
                }
                if "error" in record:
                    result["installation_error"] = record["error"]
    # Announce success only after the required outcome record has been saved.
    safe_result = redactor.strings(result)
    print(
        json.dumps(safe_result, indent=2)
        if args.json
        else human_summary(safe_result, installing=args.install)
    )
    return result_code


def main(argv: list[str] | None = None) -> int:
    if refusal := unsupported_system():
        print(refusal)
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return execute(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
