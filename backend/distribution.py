"""Build a local Windows prototype from locked inputs; never from target projects.

Build-time tools are uv/git. The assembled application needs neither. Models and
the optional lab execution environment are deliberately separate from this package.
"""

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from backend.portable_launch import digest, member, verify
from backend.review import implementation_identity
from backend.settings import Settings
from backend.setup.download import fetch
from backend.workbench import MANIFEST_NAME, ExportManifest

ROOT = Path(__file__).resolve().parents[1]
PINS = Path(__file__).parent / "setup/pins/portable.json"


def array_contracts(app: Path) -> dict[str, str]:
    """Ship only the pinned trusted SQLite API source/version and its license."""
    pin = json.loads((ROOT / "analysis/typescript/array-pin.json").read_bytes())
    source = ROOT / "analysis/typescript/node_modules/@types/node"
    if (
        pin["version"] != "sqlite-rows-1"
        or json.loads((source / "package.json").read_bytes())["version"]
        != pin["node_types_version"]
        or digest(source / "sqlite.d.ts") != pin["sqlite_sha256"]
    ):
        raise ValueError("SQLite array API pin mismatch; restore locked helper dependencies")
    target = app / "analysis/typescript/node_modules/@types/node"
    for name in ("package.json", "sqlite.d.ts", "LICENSE"):
        copy_file(source / name, target / name)
    return pin


def command(arguments: list[str], *, output: Path | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed build tools; no target scripts
        arguments, cwd=ROOT, check=True, capture_output=True, timeout=300
    )
    if output is not None:
        output.write_bytes(result.stdout)
    return result.stdout.decode("utf-8").strip()


def unpack_zip(
    archive: Path, target: Path, *, prefix: str = "", only: set[str] | None = None
) -> None:
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            if entry.is_dir():
                continue
            if prefix and not entry.filename.startswith(prefix):
                raise ValueError("Unexpected runtime archive layout")
            name = entry.filename.removeprefix(prefix)
            path = member(target, name)
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Linked runtime archive member")
            if only is not None and name not in only:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as data, path.open("xb") as dest:
                shutil.copyfileobj(data, dest)


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as data, target.open("xb") as dest:
        shutil.copyfileobj(data, dest)


def typescript(cache: Path, target: Path, client: httpx.Client) -> dict[str, str]:
    lock = (ROOT / "analysis/typescript/pnpm-lock.yaml").read_text()
    marker = "  typescript@6.0.3:\n    resolution: {integrity: "
    integrity = lock.split(marker, 1)[1].split("}", 1)[0]
    if not integrity.startswith("sha512-"):
        raise ValueError("Unsupported TypeScript integrity")
    url = "https://registry.npmjs.org/typescript/-/typescript-6.0.3.tgz"
    archive = cache / "typescript-6.0.3.tgz"
    if not archive.exists():
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with archive.open("xb") as output:
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 25_000_000:
                        raise ValueError("TypeScript archive exceeded its download bound")
                    output.write(chunk)
    with archive.open("rb") as stream:
        actual = base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode()
    if "sha512-" + actual != integrity:
        raise ValueError("TypeScript archive does not match the locked integrity")
    with tarfile.open(archive) as source:
        for entry in source.getmembers():
            if entry.isdir():
                continue
            if not entry.isfile() or not entry.name.startswith("package/"):
                raise ValueError("Unexpected TypeScript archive member")
            path = member(target, entry.name.removeprefix("package/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            data = source.extractfile(entry)
            if data is None:
                raise ValueError("Missing TypeScript archive member")
            with data, path.open("xb") as output:
                shutil.copyfileobj(data, output)
    return {"url": url, "integrity": integrity, "sha256": digest(archive)}


def source_files() -> list[str]:
    tracked = command(["git", "ls-files", "-z"]).split("\0")
    packages = {"backend", "analysis", "agent", "verification", "knowledge"}
    result = []
    for name in tracked:
        parts = Path(name).parts
        if not parts or any(p in {"tests", "node_modules", "__pycache__"} for p in parts):
            continue
        if (parts[0] in packages or name.startswith("labs/tandir/")) and name.endswith(
            (
                ".py",
                ".json",
                ".toml",
                ".txt",
                ".md",
                ".mts",
                ".yaml",
                ".css",
                ".patch",
                ".lock",
                ".ts",
                ".tsx",
            )
        ):
            result.append(name)
    # From eval: machine-state recording, and the two first-use checks with their three
    # snippets (ADR-0024). No corpus or sealed split.
    result += [
        "eval/__init__.py",
        "eval/bench/__init__.py",
        "eval/bench/machine.py",
        "eval/feasibility/__init__.py",
        "eval/feasibility/common.py",
        "eval/feasibility/canary.py",
        "eval/feasibility/constrained_answers.py",
        *(n for n in tracked if n.startswith("eval/fixtures/snippets/") and n.endswith(".py")),
    ]
    return sorted(set(result))


def frontend_files(app: Path) -> None:
    source = ROOT / "frontend/out"
    manifest = ExportManifest.model_validate_json((source / MANIFEST_NAME).read_bytes())
    for name, item in manifest.files.items():
        path = member(source, name)
        if digest(path) != item.sha256:
            raise ValueError(f"Stale workbench export: {name}")
        copy_file(path, app / "frontend/out" / name)
    copy_file(source / MANIFEST_NAME, app / "frontend/out" / MANIFEST_NAME)


def frontend_licenses(target: Path) -> None:
    store = ROOT / "frontend/node_modules/.pnpm"
    packages = [
        *store.glob("*/node_modules/*/package.json"),
        *store.glob("*/node_modules/@*/*/package.json"),
    ]
    seen: set[str] = set()
    for package in packages:
        value = json.loads(package.read_bytes())
        name = f"{value['name'].replace('/', '__')}@{value['version']}"
        if name in seen:
            continue
        seen.add(name)
        copy_file(package, target / name / "package.json")
        for file in package.parent.iterdir():
            if file.is_file() and file.name.lower().startswith(
                ("license", "licence", "copying", "notice", "ofl")
            ):
                copy_file(file, target / name / file.name)
    if not seen:
        raise ValueError("Frontend dependency notices are missing")


def drop_build_launchers(deps: Path, keep: frozenset[str] = frozenset({"ty.exe"})) -> list[str]:
    """Remove console-script launchers that `pip install --target` writes into deps/bin.

    Each one starts the build machine's interpreter by absolute path, so it names a
    folder on that machine and cannot run anywhere else. The package starts Python
    through plumb.cmd instead. ty.exe is a real binary and stays.
    """
    folder = deps / "bin"
    removed = []
    for path in sorted(folder.glob("*.exe")) if folder.is_dir() else []:
        if path.name not in keep:
            path.unlink()
            removed.append(path.name)
    return removed


def build_machine_markers(*folders: Path) -> list[bytes]:
    """Lower-case byte forms of local folders that must never appear inside a package."""
    markers = set()
    for folder in folders:
        text = str(folder.absolute()).rstrip("\\/").lower()
        markers |= {
            text.encode(),
            text.replace("\\", "/").encode(),
            text.replace("\\", "\\\\").encode(),
        }
    return sorted(markers)


def assert_no_build_paths(output: Path, markers: list[bytes]) -> None:
    """Refuse a package in which any file names the checkout or the builder's home folder."""
    found = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            content = path.read_bytes().lower()
            if any(marker in content for marker in markers):
                found.append(path.relative_to(output).as_posix())
    if found:
        raise ValueError(f"Package files name a build-machine folder: {', '.join(found[:5])}")


def build(output: Path, cache: Path) -> Path:
    if sys.platform != "win32":
        raise ValueError("This prototype builder targets Windows x64 only")
    output, cache = output.absolute(), cache.absolute()
    if (
        output.exists()
        or output.is_relative_to(ROOT)
        or output.is_relative_to(cache)
        or cache.is_relative_to(output)
    ):
        raise ValueError("Use a new output folder outside the checkout and download cache")
    archive_path = output.parent / (output.name + ".zip")
    if archive_path.exists():
        raise ValueError("The output archive already exists; choose a new version folder")
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True)
    app, runtime = output / "app", output / "python"
    pins = json.loads(PINS.read_bytes())
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for kind, pin in pins.items():
            archive = fetch(
                pin["url"],
                cache / Path(urlsplit(pin["url"]).path).name,
                sha256=pin["sha256"],
                size=pin["size"],
                client=client,
            )
            unpack_zip(
                archive,
                output / ("python" if kind == "python" else "node"),
                prefix="node-v24.11.0-win-x64/" if kind == "node" else "",
                only={"node.exe", "LICENSE", "README.md", "CHANGELOG.md"}
                if kind == "node"
                else None,
            )
        ts = typescript(cache, app / "analysis/typescript/node_modules/typescript", client)
    array_pin = array_contracts(app)
    # Only Node and its notices are shipped; npm/corepack are build-time tools.
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("The build requires uv")
    requirements = cache / "requirements.txt"
    command(
        [uv, "export", "--locked", "--no-dev", "--no-emit-project", "--format", "requirements-txt"],
        output=requirements,
    )
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    ty = next(p for p in lock["package"] if p["name"] == "ty")
    with requirements.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\nty=={ty['version']} " + " ".join(f"--hash={w['hash']}" for w in ty["wheels"]) + "\n"
        )
    command(
        [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--target",
            str(output / "deps"),
            "--require-hashes",
            "--no-deps",
            "--only-binary",
            ":all:",
            "-r",
            str(requirements),
        ]
    )
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    metadata = output / "deps" / f"plumb-{project['version']}.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.3\nName: plumb\nVersion: {project['version']}\n"
        f"Summary: {project['description']}\n",
        encoding="utf-8",
    )
    # ty's wheel installs its executable in target/Scripts on Windows. Place the
    # same verified binary at embedded Python's sysconfig scripts location.
    binaries = list((output / "deps").rglob("ty.exe"))
    if len(binaries) != 1:
        raise ValueError("Expected one locked ty executable")
    copy_file(binaries[0], runtime / "Scripts/ty.exe")
    drop_build_launchers(output / "deps")
    for name in source_files():
        copy_file(member(ROOT, name), app / name)
    frontend_files(app)
    frontend_licenses(output / "licenses/frontend")
    for name in (
        "uv.lock",
        "pyproject.toml",
        "analysis/typescript/pnpm-lock.yaml",
        "frontend/pnpm-lock.yaml",
    ):
        copy_file(ROOT / name, output / "inputs" / name)
    copy_file(requirements, output / "inputs/requirements.txt")
    copy_file(PINS, output / "inputs/portable.json")
    copy_file(Path(__file__).with_name("portable_launch.py"), output / "launch.py")
    (runtime / "python312._pth").write_text("python312.zip\n.\n../app\n../deps\n", encoding="utf-8")
    (output / "plumb.cmd").write_text(
        '@echo off\r\n"%~dp0python\\python.exe" -I -B "%~dp0launch.py" %*\r\n'
        "exit /b %errorlevel%\r\n",
        encoding="utf-8",
        newline="",
    )
    (output / "Start Plumb.cmd").write_text(
        '@echo off\r\n"%~dp0python\\python.exe" -I -B "%~dp0launch.py" web\r\npause\r\n',
        encoding="utf-8",
        newline="",
    )
    (output / "README.txt").write_text(
        "Plumb portable prototype — Windows x64\n\n"
        "GET STARTED\n"
        "1. Extract the whole ZIP. Double-click Start Plumb.cmd. Keep its terminal open.\n"
        "2. On Project, enter your authorized local project folder and inspect its source.\n"
        "3. Check readiness before Run review. Missing assets need the setup step below.\n"
        "Ctrl+C in the command window shuts down at a checkpoint and stops the owned model.\n"
        "No Python, Node, uv, pnpm, administrator or Windows Sandbox setup is needed.\n"
        "Opening the workbench or inspecting source does not load a model.\n\n"
        "ONE-TIME MODEL SETUP\n"
        "Open a terminal in this extracted folder. Run: plumb.cmd setup\n"
        "Read the pinned download sizes/licenses, then use: plumb.cmd setup --install\n"
        "If the preview needs over 500 MB, installation requires the explicit extra flag\n"
        "--approve-large-downloads. Existing verified assets are reused.\n"
        "Inference stays local; only the measured hardware profile is qualified.\n\n"
        "TERMINAL ALTERNATIVES\n"
        'plumb.cmd inspect "D:\\path\\to\\project"\n'
        'plumb.cmd review "D:\\path\\to\\project" --limit 1\n'
        "plumb.cmd resume <run-id>\n"
        "plumb.cmd report <run-id> --open\n"
        "In source-checkout examples, replace 'uv run plumb' with 'plumb.cmd'.\n"
        "Saved reports open without a model; completed matching receipt replays are shown.\n"
        "The replay command needs an optional pinned Tandir execution environment that\n"
        "this portable package does not include. Source reviews do not require that runner.\n\n"
        "STORAGE AND PROTOTYPE LIMITS\n"
        "Data and reports stay outside this installation. Do not add files here.\n"
        "Packaged local inference/resume has been checked on the development laptop.\n"
        "Clean-profile and authenticated browser acceptance remain open; hardware support\n"
        "and known model-quality gaps are shown by setup. This is not a certified release.\n"
        "Python 3.12.5 and Node 24.11.0 preserve development versions; runtime upgrades\n"
        "and release signing are not certified by this prototype build.\n"
        "Python/dependency licenses remain in python/ and deps/*dist-info/. Node's\n"
        "LICENSE is in node/. TypeScript notices are beside its package. Frontend\n"
        "notices are in licenses/frontend/. release.json records inputs and file hashes;\n"
        "it detects damage, not a malicious replacement of both launcher and inventory.\n",
        encoding="utf-8",
    )
    record = {
        "format": 1,
        "status": "local-prototype",
        "created_at": datetime.now(UTC).isoformat(),
        "source_commit": command(["git", "rev-parse", "HEAD"]),
        "implementation": implementation_identity(),
        "source_dirty": bool(
            command(
                [
                    "git",
                    "diff",
                    "HEAD",
                    "--",
                    "backend",
                    "analysis",
                    "agent",
                    "verification",
                    "frontend",
                ]
            )
        ),
        "runtimes": pins,
        "typescript": ts,
        "array_contracts": array_pin,
        "files": {
            p.relative_to(output).as_posix(): digest(p)
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    (output / "release.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    assert_no_build_paths(output, build_machine_markers(ROOT, Path.home(), cache))
    verify(output)
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in [*record["files"], "release.json"]:
            archive.write(output / name, f"{output.name}/{name}")
    return output / "release.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    try:
        result = build(args.output, args.cache or Settings().data_dir / "downloads/portable")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Portable build incomplete: {error}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
