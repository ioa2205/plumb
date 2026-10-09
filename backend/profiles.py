"""Read-only inventory and selection of measured, pinned local profiles (ADR-0007)."""

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

from backend import vulkan_profile
from backend.capabilities import table
from backend.contracts.runs import ReviewRun
from backend.memory import MemoryStatus, read_memory
from backend.settings import Settings
from backend.setup import llama_cpp
from backend.setup.download import is_verified, sha256_file
from backend.setup.models import model_path
from backend.setup.pins import LlamaCppPin, load_llama_cpp_pin, load_model_pins

PROFILE_ID = "mx350-vulkan-8k"
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


REGISTRY = {PROFILE_ID: Profile()}


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


def _system_tool(name: str) -> Path:
    """Windows system directory, never a same-named program in an analyzed folder."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError("Cannot locate Windows system tools")
    return Path(buffer.value) / name


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
                _system_tool("WindowsPowerShell/v1.0/powershell.exe"),
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
                _system_tool("nvidia-smi.exe"),
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
            issues.append("Dedicated MX350 free VRAM unavailable; it cannot be replaced by RAM")
    else:
        cpu = platform.processor() or None
        issues.append("This runtime profile has only been validated on Windows x64")
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


def doctor(settings: Settings, host: Host | None = None) -> dict[str, Any]:
    host = host or inventory(settings)
    profile = REGISTRY[PROFILE_ID]
    model = load_model_pins().get(profile.model_id)
    runtime = load_llama_cpp_pin()
    pins_match = model.sha256 == profile.model_sha256 and runtime.commit == profile.runtime_commit
    model_verified = is_verified(model_path(settings, model), sha256=model.sha256, size=model.size)
    runtime_verified = verify_runtime(settings, runtime, profile.backend)
    compatible_host = (
        host.os == "Windows"
        and host.architecture.lower() in {"amd64", "x86_64"}
        and CPU_NAME in (host.cpu or "")
        and profile.device_name in host.gpu_names
    )
    runtime_compatible: bool | None = None
    device_free = host.dedicated_free_bytes
    messages = list(host.issues)
    if pins_match and compatible_host and runtime_verified:
        try:
            binary = llama_cpp.binary(settings, runtime, profile.backend)
            version = _run(binary, "--version")
            if f"build {runtime.build.removeprefix('b')}" not in version:
                raise ValueError("Installed runtime does not report the pinned build")
            listed = vulkan_profile.device_budget(_run(binary, "--list-devices"))
            runtime_compatible = True
            device_free = min(listed, device_free) if device_free is not None else None
        except (OSError, ValueError, subprocess.SubprocessError):
            runtime_compatible = False
            messages.append("Pinned runtime/device listing failed; calibration is required")
    memory_fit = (
        host.memory.available_bytes >= profile.host_required_bytes
        and device_free is not None
        and device_free >= profile.device_required_bytes
    )
    # A lower bound for missing download bytes, not a claim about complete install/cache usage.
    minimum_download = (0 if model_verified else model.size) + (
        0 if runtime_verified else sum(a.size for a in runtime.variants[profile.backend].assets)
    )
    disk_fit = host.disk_free_bytes is not None and host.disk_free_bytes >= minimum_download
    ready = all(
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
        messages.append("Hardware is unmeasured for this profile; use inspect or calibrate locally")
    if not memory_fit:
        messages.append("Insufficient or unknown RAM/dedicated VRAM; close apps and rerun doctor")
    if not model_verified or not runtime_verified:
        messages.append("Pinned assets need setup/re-verification; doctor installs nothing")
    if not disk_fit:
        messages.append("Data volume cannot establish even the minimum missing-download space")
    if not pins_match:
        messages.append("Pins changed; this profile needs calibration before use")
    return {
        "inventory": asdict(host),
        "profiles": [
            {
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
                "ready": ready,
                "runtime_validation": "ADR-0006; schema/canary acceptance on i5-1135G7/MX350",
                "evaluated_capability": (
                    "Historical scoped invoice/receipt development evidence only. "
                    "Current engine family evaluation is unrun; broader quality gates remain open."
                ),
                "capabilities": table().model_dump(mode="json"),
                "all_security_quality_gates_met": False,
                "launch_rechecks_memory": True,
                "live_stop_bytes": vulkan_profile.LOW_MEMORY_BYTES,
            }
        ],
        "recommended_profile": profile.id if compatible_host and pins_match else None,
        "selection_ready": ready,
        "messages": messages,
        "model_candidates": [
            {
                "id": candidate.id,
                "size_bytes": candidate.size,
                "quantization": candidate.quantization,
                "license": candidate.license,
                "source": candidate.url,
                "sha256": candidate.sha256,
                "requires_download_approval": candidate.size > 500_000_000,
                "validated_profile": profile.id if candidate.id == profile.model_id else None,
                "verified_installed": model_verified
                if candidate.id == profile.model_id
                else is_verified(
                    model_path(settings, candidate), sha256=candidate.sha256, size=candidate.size
                ),
            }
            for candidate in load_model_pins().models
        ],
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


def select(settings: Settings, requested: str = "auto") -> Profile:
    if requested not in {"auto", *REGISTRY}:
        raise ValueError(f"Unknown profile {requested!r}; run plumb doctor")
    report = doctor(settings)
    selected = report["recommended_profile"] if requested == "auto" else requested
    if selected is None or not report["selection_ready"]:
        raise ValueError(
            "Profile unavailable: " + "; ".join(report["messages"]) + ". Run plumb doctor."
        )
    return REGISTRY[selected]


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


def create(settings: Settings, log_name: str, profile: Profile) -> vulkan_profile.VulkanServer:
    if profile != REGISTRY.get(profile.id):
        raise ValueError(
            "Profile settings are unmeasured; overrides cannot change launch parameters"
        )
    select(settings, profile.id)
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
