"""Install the pinned llama.cpp builds and run their acceptance checks.

uv run python -m backend.setup.llama_cpp install [--variant cpu] [--variant cuda-12.4]
uv run python -m backend.setup.llama_cpp check
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from backend.settings import Settings
from backend.setup.download import extract_zip, fetch
from backend.setup.pins import LlamaCppPin, Variant, load_llama_cpp_pin

MARKER = ".plumb-install.json"


def install_dir(settings: Settings, pin: LlamaCppPin, variant: str) -> Path:
    return settings.llama_cpp_dir / pin.build / variant


def downloads_dir(settings: Settings) -> Path:
    return settings.cache_dir / "downloads"


def _marker(pin: LlamaCppPin, variant: Variant) -> dict[str, object]:
    return {"build": pin.build, "assets": {a.name: a.sha256 for a in variant.assets}}


def is_installed(settings: Settings, pin: LlamaCppPin, variant: str) -> bool:
    marker = install_dir(settings, pin, variant) / MARKER
    if not marker.is_file():
        return False
    return json.loads(marker.read_text(encoding="utf-8")) == _marker(pin, pin.variants[variant])


def install(settings: Settings, pin: LlamaCppPin, variant: str, client: httpx.Client) -> Path:
    """Download, verify, and extract one variant. Re-running is a no-op once installed."""
    spec = pin.variants[variant]
    target = install_dir(settings, pin, variant)
    if is_installed(settings, pin, variant):
        return target
    for asset in spec.assets:
        print(f"  {asset.name} ({asset.size / 1e6:.1f} MB)", flush=True)
        archive = fetch(
            asset.url,
            downloads_dir(settings) / asset.name,
            sha256=asset.sha256,
            size=asset.size,
            client=client,
        )
        extract_zip(archive, target)
    (target / MARKER).write_text(json.dumps(_marker(pin, spec), indent=2), encoding="utf-8")
    return target


def binary(settings: Settings, pin: LlamaCppPin, variant: str, name: str = "llama-server") -> Path:
    path = install_dir(settings, pin, variant) / f"{name}.exe"
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing; run the llama_cpp install command")
    return path


def run_tool(exe: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    """Run one of the pinned, hash-verified llama.cpp binaries (never analyzed code)."""
    return subprocess.run(  # noqa: S603 - fixed argv to a pinned, hash-verified binary
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _check(settings: Settings, pin: LlamaCppPin) -> int:
    failures = 0
    for variant in pin.variants:
        print(f"## {pin.release} ({pin.build}) {variant}")
        if not is_installed(settings, pin, variant):
            print("not installed\n")
            failures += 1
            continue
        exe = binary(settings, pin, variant)
        # --verbose makes the log name the backend DLLs it loads (for example ggml-cpu-icelake).
        for args in (("--version",), ("--verbose", "--list-devices")):
            result = run_tool(exe, *args)
            print(f"$ llama-server {' '.join(args)}  (exit {result.returncode})")
            print((result.stdout + result.stderr).strip(), "\n", sep="")
            failures += result.returncode != 0
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    inst = sub.add_parser("install", help="download, verify, and extract pinned builds")
    inst.add_argument("--variant", action="append", help="variant name (default: all)")
    sub.add_parser("check", help="print version and device list for each installed build")
    args = parser.parse_args(argv)

    settings, pin = Settings(), load_llama_cpp_pin()
    if args.command == "check":
        return 1 if _check(settings, pin) else 0
    variants = args.variant or list(pin.variants)
    unknown = sorted(set(variants) - set(pin.variants))
    if unknown:
        parser.error(f"unknown variant(s) {unknown}; pinned: {sorted(pin.variants)}")
    with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
        for variant in variants:
            print(f"{pin.build} {variant} -> {install_dir(settings, pin, variant)}", flush=True)
            install(settings, pin, variant, client)
    print("installed and verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
