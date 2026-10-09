"""Read-only inventory and selection of pinned local profiles (ADR-0007, ADR-0024)."""

import hashlib
import json
import platform
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import psutil

from backend import acceptance, cpu_profile, vulkan_profile
from backend.capabilities import table
from backend.contracts.runs import ReviewRun
from backend.memory import MemoryStatus, read_memory
from backend.preflight import GB
from backend.settings import Settings
from backend.setup import llama_cpp, opengrep
from backend.setup.download import is_verified, sha256_file
from backend.setup.models import model_path
from backend.setup.pins import (
    LlamaCppPin,
    ModelPin,
    load_llama_cpp_pin,
    load_model_pins,
    load_opengrep_pin,
)
from backend.system_tools import NVIDIA_SMI, POWERSHELL, system_tool

PROFILE_ID = "mx350-vulkan-8k"
CPU_PROFILE_ID = "cpu-8k"
CPU_NAME = "i5-1135G7"


@dataclass(frozen=True)
class Profile:
    id: str = PROFILE_ID
    model_id: str = vulkan_profile.MODEL_ID
    model_sha256: str = vulkan_profile.MODEL_SHA256
    runtime_commit: str = vulkan_profile.BUILD_COMMIT
    backend: str = "vulkan"
    context: int = 8192
    threads: int = 4
    batch: int = 256
    microbatch: int = 64
    offload_layers: int = 99
    host_required_bytes: int = vulkan_profile.REQUIREMENT.host_bytes
    device_required_bytes: int = vulkan_profile.REQUIREMENT.device_bytes
    device: str = vulkan_profile.DEVICE
    device_name: str = vulkan_profile.DEVICE_NAME
    extra_args: tuple[str, ...] = vulkan_profile.EXTRA_ARGS
    stateless: bool = True
    reasoning: str = "off"

    def identity(self) -> dict[str, Any]:
        # JSON normalizes tuples; saved contexts and newly selected profiles compare exactly.
        return json.loads(json.dumps(asdict(self)))


# E1, the comparison of models on the same cases, has not been run.
NOT_COMPARED = "quality not yet compared with the default"


def _cpu(profile_id: str, model: ModelPin, required: int) -> Profile:
    return Profile(
        id=profile_id,
        model_id=model.id,
        model_sha256=model.sha256,
        backend=cpu_profile.BACKEND,
        threads=cpu_profile.THREADS,
        batch=cpu_profile.BATCH,
        microbatch=cpu_profile.MICROBATCH,
        offload_layers=0,
        host_required_bytes=required,
        device_required_bytes=0,
        device="",
        device_name="",
        extra_args=(),
    )


def cpu_profile_id(model: ModelPin) -> str | None:
    """The CPU profile that reviews with ``model``; None when it cannot be judged."""
    if model.id == vulkan_profile.MODEL_ID:
        return CPU_PROFILE_ID
    return None if model.kv_bytes_per_token is None else f"{CPU_PROFILE_ID}-{model.id}"


def _registry() -> dict[str, Profile]:
    pins = load_model_pins()
    default = pins.get(vulkan_profile.MODEL_ID)
    profiles = {
        PROFILE_ID: Profile(),
        CPU_PROFILE_ID: _cpu(CPU_PROFILE_ID, default, cpu_profile.REQUIRED_BYTES),
    }
    # Another pinned model is only ever an explicit choice, so it comes after the defaults.
    for model in pins.models:
        required = cpu_profile.required_bytes(model)
        if model.id != default.id and required is not None:
            profiles[f"{CPU_PROFILE_ID}-{model.id}"] = _cpu(
                f"{CPU_PROFILE_ID}-{model.id}", model, required
            )
    return profiles


# In order of preference: the measured graphics-card profile on its own hardware, then
# the CPU profile that any 64-bit Windows computer may use, then the same CPU settings
# with each other pinned model (ADR-0024). "auto" takes the first that fits the host.
REGISTRY = _registry()


@dataclass(frozen=True)
class Host:
    os: str
    architecture: str
    cpu: str | None
    physical_cores: int | None
    logical_cores: int | None
    memory: MemoryStatus
    gpu_names: tuple[str, ...]
    dedicated_free_bytes: int | None
    disk_free_bytes: int | None
    issues: tuple[str, ...] = ()


def _run(executable: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed system diagnostic or verified pinned runtime
        [str(executable), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return result.stdout + result.stderr


def inventory(settings: Settings) -> Host:
    """Collect no serials, accounts or process list; start no model and write no files."""
    issues: list[str] = []
    cpu = None
    names: tuple[str, ...] = ()
    vram = None
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                cpu = str(winreg.QueryValueEx(key, "ProcessorNameString")[0])
        except OSError:
            issues.append("CPU model unavailable; no compatible measured host can be assumed")
        try:
            output = _run(
                system_tool(POWERSHELL),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "@(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) "
                "| ConvertTo-Json -Compress",
            )
            parsed = json.loads(output)
            names = (parsed,) if isinstance(parsed, str) else tuple(parsed)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            issues.append("Graphics inventory unavailable; shared GPU memory is not spare RAM")
        try:
            output = _run(
                system_tool(NVIDIA_SMI),
                "--query-gpu=name,memory.free",
                "--format=csv,noheader,nounits",
            )
            matches = []
            for line in output.splitlines():
                name, _, free = line.rpartition(",")
                if name.strip() == vulkan_profile.DEVICE_NAME:
                    matches.append(int(free.strip()) * 1024**2)
            if len(matches) != 1 or matches[0] < 0:
                raise ValueError("Dedicated MX350 memory unavailable or ambiguous")
            vram = matches[0]
            names = tuple(dict.fromkeys((*names, vulkan_profile.DEVICE_NAME)))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass  # only the MX350 profile needs this reading, and it reports the gap itself
    else:
        cpu = platform.processor() or None
        issues.append("Plumb's model runner is pinned for 64-bit Windows only")
    parent = settings.data_dir
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    try:
        disk = psutil.disk_usage(str(parent)).free
    except (OSError, ValueError):
        disk = None
        issues.append("Data-volume free disk space unavailable")
    return Host(
        platform.system(),
        platform.machine(),
        cpu,
        psutil.cpu_count(logical=False),
        psutil.cpu_count(),
        read_memory(),
        names,
        vram,
        disk,
        tuple(issues),
    )


def verify_runtime(settings: Settings, pin: LlamaCppPin, variant: str) -> bool:
    """Verify installed bytes against the retained hash-pinned archives before execution.

    An install marker is inventory metadata, not a binary-integrity guarantee.
    Missing archives require re-verification through setup, never automatic downloads.
    """
    try:
        if not llama_cpp.is_installed(settings, pin, variant):
            return False
        root = llama_cpp.install_dir(settings, pin, variant).resolve()
        for asset in pin.variants[variant].assets:
            archive = llama_cpp.downloads_dir(settings) / asset.name
            if not is_verified(archive, sha256=asset.sha256, size=asset.size):
                return False
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    if member.is_dir():
                        continue
                    relative = PurePosixPath(member.filename)
                    target = (root / member.filename).resolve()
                    if relative.is_absolute() or ".." in relative.parts:
                        return False
                    if not target.is_relative_to(root) or not target.is_file():
                        return False
                    if target.stat().st_size != member.file_size:
                        return False
                    digest = hashlib.sha256()
                    with bundle.open(member) as stream:
                        for chunk in iter(lambda: stream.read(1024**2), b""):
                            digest.update(chunk)
                    if sha256_file(target) != digest.hexdigest():
                        return False
        # Extra loadable files could change DLL/plugin resolution despite valid pinned files.
        allowed = {
            member.filename.replace("\\", "/")
            for asset in pin.variants[variant].assets
            for member in _members(llama_cpp.downloads_dir(settings) / asset.name)
            if not member.is_dir()
        }
        return all(
            f.relative_to(root).as_posix() in allowed
            for f in root.rglob("*")
            if f.is_file() and f.suffix.lower() in {".exe", ".dll"}
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return False


def _members(path: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(path) as bundle:
        return bundle.infolist()


# Information for the user, never a reason to refuse a profile.
FIRST_USE_PENDING = (
    "The first review on this computer begins with a check of the model runner "
    "that takes a few minutes; plumb calibrate runs it now"
)


def host_fits(host: Host, profile: Profile) -> bool:
    """The MX350 profile needs the hardware it was measured on; a CPU profile any x64 Windows."""
    windows = host.os == "Windows" and host.architecture.lower() in {"amd64", "x86_64"}
    if not profile.device_name:
        return windows
    return windows and CPU_NAME in (host.cpu or "") and profile.device_name in host.gpu_names


def _judge(
    settings: Settings,
    host: Host,
    profile: Profile,
    model: ModelPin,
    runtime: LlamaCppPin,
    model_verified: bool,
    runtime_verified: bool,
    capabilities: dict[str, Any],
    versions: dict[str, str],
) -> dict[str, Any]:
    """One profile on this host: fit, verified assets, runner check and first-use state."""
    offload = bool(profile.device_name)
    pins_match = model.sha256 == profile.model_sha256 and runtime.commit == profile.runtime_commit
    compatible_host = host_fits(host, profile)
    runtime_compatible: bool | None = None
    device_free = host.dedicated_free_bytes if offload else None
    messages: list[str] = []
    if pins_match and compatible_host and runtime_verified:
        try:
            binary = llama_cpp.binary(settings, runtime, profile.backend)
            if profile.backend not in versions:
                versions[profile.backend] = ""  # a runner that fails is asked once
                versions[profile.backend] = _run(binary, "--version")
            if f"build {runtime.build.removeprefix('b')}" not in versions[profile.backend]:
                raise ValueError("Installed runtime does not report the pinned build")
            if offload:
                listed = vulkan_profile.device_budget(_run(binary, "--list-devices"))
                device_free = min(listed, device_free) if device_free is not None else None
            runtime_compatible = True
        except (OSError, ValueError, subprocess.SubprocessError):
            runtime_compatible = False
            messages.append(
                "The pinned model runner failed its version or device check; "
                "run plumb setup --install again"
            )
    memory_fit = host.memory.available_bytes >= profile.host_required_bytes and (
        not offload or (device_free is not None and device_free >= profile.device_required_bytes)
    )
    # A lower bound for missing download bytes, not a claim about complete install/cache usage.
    minimum_download = (0 if model_verified else model.size) + (
        0 if runtime_verified else sum(a.size for a in runtime.variants[profile.backend].assets)
    )
    disk_fit = host.disk_free_bytes is not None and host.disk_free_bytes >= minimum_download
    first_use = acceptance.state(settings, profile, host)
    prerequisites = all(
        (
            pins_match,
            compatible_host,
            model_verified,
            runtime_verified,
            runtime_compatible,
            memory_fit,
            disk_fit,
        )
    )
    if not compatible_host:
        messages.append(
            "This profile was measured only on an i5-1135G7 with an MX350"
            if offload
            else "AI review needs 64-bit Windows on an x64 processor"
        )
    if offload and compatible_host and host.dedicated_free_bytes is None:
        messages.append("Dedicated MX350 free VRAM unavailable; it cannot be replaced by RAM")
    if not memory_fit:
        messages.append(
            "Insufficient or unknown RAM/dedicated VRAM; close apps and rerun doctor"
            if offload
            else f"Needs {profile.host_required_bytes / GB:.2f} GB of free memory and "
            f"{host.memory.available_bytes / GB:.2f} GB is free; close apps and rerun doctor"
        )
    if not model_verified or not runtime_verified:
        messages.append("Pinned assets need setup/re-verification; doctor installs nothing")
    if not disk_fit:
        messages.append("Data volume cannot establish even the minimum missing-download space")
    if not pins_match:
        messages.append("Pins changed; this profile must be measured again before use")
    if compatible_host and first_use == acceptance.PENDING:
        messages.append(FIRST_USE_PENDING)
    if first_use == acceptance.FAILED:
        messages.append(
            "The model runner failed its first-use check on this computer, so AI review is "
            "off; run plumb calibrate to try again"
        )
    return {
        **profile.identity(),
        "quantization": model.quantization,
        "compatible_measured_host": compatible_host,
        "pins_match": pins_match,
        "model_verified": model_verified,
        "runtime_verified": runtime_verified,
        "runtime_compatible": runtime_compatible,
        "estimated_memory_fit": memory_fit,
        "dedicated_free_bytes": device_free,
        "minimum_missing_download_bytes": minimum_download,
        "minimum_download_disk_fit": disk_fit,
        "first_use_check": first_use,
        "prerequisites_ready": prerequisites,
        "ready": prerequisites and first_use != acceptance.FAILED,
        "runtime_validation": (
            "ADR-0006; schema/canary acceptance on i5-1135G7/MX350"
            if offload
            else f"ADR-0024; first-use check on this computer: {first_use}"
        ),
        "evaluated_capability": (
            "Historical scoped invoice/receipt development evidence only. "
            "Current engine family evaluation is unrun; broader quality gates remain open."
            if offload
            else "Same model, investigator and validator as the measured profile. Review "
            "quality with this profile is not measured; broader quality gates remain open."
            if profile.model_id == vulkan_profile.MODEL_ID
            else f"{model.family}: {NOT_COMPARED}. No review has been recorded with this "
            "model; its memory requirement is an estimate."
        ),
        "capabilities": capabilities,
        "all_security_quality_gates_met": False,
        "launch_rechecks_memory": True,
        "live_stop_bytes": vulkan_profile.LOW_MEMORY_BYTES,
        "messages": messages,
    }


def doctor(settings: Settings, host: Host | None = None) -> dict[str, Any]:
    host = host or inventory(settings)
    pins, runtime = load_model_pins(), load_llama_cpp_pin()
    if settings.profile != "auto" and settings.profile not in REGISTRY:
        raise ValueError(
            f"PLUMB_PROFILE names an unknown profile {settings.profile!r}; known: {list(REGISTRY)}"
        )
    capabilities = table().model_dump(mode="json")
    models: dict[str, bool] = {}
    runtimes: dict[str, bool] = {}
    versions: dict[str, str] = {}
    judged = []
    for profile in REGISTRY.values():
        model = pins.get(profile.model_id)
        # Hashing a model takes seconds; profiles that share one share the result.
        if model.id not in models:
            models[model.id] = is_verified(
                model_path(settings, model), sha256=model.sha256, size=model.size
            )
        if profile.backend not in runtimes:
            runtimes[profile.backend] = verify_runtime(settings, runtime, profile.backend)
        judged.append(
            _judge(
                settings,
                host,
                profile,
                model,
                runtime,
                models[model.id],
                runtimes[profile.backend],
                capabilities,
                versions,
            )
        )
    recommended = next(
        (p["id"] for p in judged if p["compatible_measured_host"] and p["pins_match"]), None
    )
    # PLUMB_PROFILE is the user's lasting choice; it goes through the same checks.
    selected = settings.profile if settings.profile != "auto" else recommended
    report: dict[str, Any] = {
        "inventory": asdict(host),
        "profiles": judged,
        "recommended_profile": recommended,
        "selected_profile": selected,
    }
    shown = chosen(report)
    candidates = [
        {
            "id": candidate.id,
            "family": candidate.family,
            "size_bytes": candidate.size,
            "quantization": candidate.quantization,
            "license": candidate.license,
            "source": candidate.url,
            "sha256": candidate.sha256,
            "requires_download_approval": candidate.size > 500_000_000,
            "validated_profile": PROFILE_ID if candidate.id == vulkan_profile.MODEL_ID else None,
            "verified_installed": models[candidate.id]
            if candidate.id in models
            else is_verified(
                model_path(settings, candidate), sha256=candidate.sha256, size=candidate.size
            ),
            **_fit(candidate, host),
        }
        for candidate in pins.models
    ]
    report.update(
        {
            "model_recommendation": _recommend(
                candidates,
                host,
                selected is not None
                and shown["model_id"] == vulkan_profile.MODEL_ID
                and shown["estimated_memory_fit"],
            ),
            "selection_ready": selected is not None and shown["ready"],
            "messages": [*host.issues, *shown["messages"]],
            "model_candidates": candidates,
            "pattern_scanner": _scanner(settings),
            "model_loaded": False,
            "downloads_started": False,
            "memory_note": (
                "Dedicated VRAM and host RAM are separate; shared GPU memory is not added to either"
            ),
            "disk_note": (
                "Download space is a lower bound; extracted files, snapshots and caches "
                "need additional space"
            ),
        }
    )
    return report


def _scanner(settings: Settings) -> dict[str, Any]:
    """The pinned pattern scanner. A review runs without it, but in no useful order."""
    pin = load_opengrep_pin()
    return {
        "name": "Opengrep",
        "release": pin.release,
        "size_bytes": pin.asset.size,
        "source": pin.asset.url,
        "sha256": pin.asset.sha256,
        "license": "LGPL-2.1 (Opengrep)",
        "verified_installed": is_verified(
            opengrep.binary_path(settings, pin), sha256=pin.asset.sha256, size=pin.asset.size
        ),
        "note": (
            "Orders review questions by pattern leads; a match never becomes a finding. "
            "Without it a review still runs and says so in its limitations."
        ),
    }


def _fit(candidate: ModelPin, host: Host) -> dict[str, Any]:
    """Whether a pinned model fits in the RAM that is free now, on the CPU profile."""
    default = candidate.id == vulkan_profile.MODEL_ID
    required = cpu_profile.required_bytes(candidate)
    return {
        "default": default,
        "cpu_profile": cpu_profile_id(candidate),
        "required_ram_bytes": required,
        # Only the default model's margin was measured; a larger model's is scaled from it.
        "requirement_measured": default,
        "fits_available_ram": None if required is None else host.memory.available_bytes >= required,
        "quality": "default; every recorded review used this model" if default else NOT_COMPARED,
    }


def _recommend(
    candidates: list[dict[str, Any]], host: Host, default_fits_selected: bool
) -> dict[str, Any]:
    """Name the default and the largest pinned model that fits. Fit is not quality."""
    usable = host_fits(host, REGISTRY[CPU_PROFILE_ID])
    # On its measured laptop the default model also fits through the MX350 profile.
    fitting = [
        c
        for c in candidates
        if usable and (c["fits_available_ram"] or (c["default"] and default_fits_selected))
    ]
    largest = max(fitting, key=lambda c: c["size_bytes"], default=None)
    return {
        "default_model": vulkan_profile.MODEL_ID,
        "default_fits": any(c["default"] for c in fitting),
        "largest_fitting_model": largest["id"] if largest else None,
        "label": None if largest is None or largest["default"] else NOT_COMPARED,
        "basis": (
            "Free memory now against model file + cache at 8K + margin. Only the default "
            "model's margin was measured; a larger model's margin is an estimate scaled from "
            "it. The default also counts as fitting when the selected profile's own memory "
            "check passes. Fitting says nothing about review quality: the model comparison "
            "(experiment E1) has not been run."
        ),
    }


def chosen(report: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
    """One judged profile; by default the selected one, or the CPU profile when none is."""
    wanted = profile_id or report["selected_profile"] or CPU_PROFILE_ID
    return next(p for p in report["profiles"] if p["id"] == wanted)


def select(settings: Settings, requested: str = "auto", *, rechecking: bool = False) -> Profile:
    """The profile a review may start with now.

    ``rechecking`` lets a failed first-use check run again; every other requirement applies.
    """
    if requested not in {"auto", *REGISTRY}:
        raise ValueError(f"Unknown profile {requested!r}; run plumb doctor")
    report = doctor(settings)
    judged = chosen(report, None if requested == "auto" else requested)
    available = requested != "auto" or report["selected_profile"] is not None
    if not available or not judged["prerequisites_ready" if rechecking else "ready"]:
        raise ValueError(
            "Profile unavailable: "
            + "; ".join(
                m
                for m in (*report["inventory"]["issues"], *judged["messages"])
                if m != FIRST_USE_PENDING
            )
            + ". Run plumb doctor."
        )
    return REGISTRY[judged["id"]]


def validate_resume(profile: Profile, saved: object, run: ReviewRun) -> None:
    if json.dumps(saved, sort_keys=True) != json.dumps(profile.identity(), sort_keys=True):
        raise ValueError("Profile changed or missing; start a new review")
    model = load_model_pins().get(profile.model_id)
    runtime = load_llama_cpp_pin()
    if (
        run.model is None
        or run.model.id != profile.model_id
        or run.model.file_sha256 != profile.model_sha256
        or run.model.quantization != model.quantization
        or run.toolchain is None
        or run.toolchain.backend != profile.backend
        or run.toolchain.llama_cpp_release != runtime.release
        or run.toolchain.llama_cpp_build != runtime.build
    ):
        raise ValueError("Stored run does not match its pinned profile")


def create(
    settings: Settings, log_name: str, profile: Profile, *, rechecking: bool = False
) -> vulkan_profile.VulkanServer:
    if profile != REGISTRY.get(profile.id):
        raise ValueError(
            "Profile settings are unmeasured; overrides cannot change launch parameters"
        )
    select(settings, profile.id, rechecking=rechecking)
    # Each profile is started by its own runner; a CPU profile never takes the MX350 launch.
    if profile.backend == cpu_profile.BACKEND:
        server = cpu_profile.create(settings, log_name, profile.model_id)
    else:
        server = vulkan_profile.create(settings, log_name)
    config = server.config
    actual = (
        config.ctx_size,
        config.threads,
        config.batch_size,
        config.ubatch_size,
        config.gpu_layers,
        config.extra_args,
        config.stateless,
        config.reasoning,
    )
    expected = (
        profile.context,
        profile.threads,
        profile.batch,
        profile.microbatch,
        profile.offload_layers,
        profile.extra_args,
        profile.stateless,
        profile.reasoning,
    )
    if actual != expected:
        server.stop()
        raise ValueError("Runtime settings drifted from the pinned profile")
    return server


def first_use_pending(settings: Settings, profile: Profile) -> bool:
    if profile.device_name:
        return False  # measured on its own hardware; no inventory is needed to know that
    return acceptance.state(settings, profile, inventory(settings)) == acceptance.PENDING


def first_use_check(settings: Settings, profile: Profile, log_name: str) -> dict[str, Any]:
    """Load the model once and save this computer's check of a profile. Never a review."""
    host = inventory(settings)
    server = create(settings, log_name, profile, rechecking=True)
    return acceptance.run(settings, profile, host, server)
