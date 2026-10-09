"""Portable inventory and extraction boundaries; no downloads or model."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from backend import distribution
from backend.distribution import source_files, unpack_zip
from backend.portable_launch import digest, member, verify


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/absolute",
        "a/../../b",
        "a\\b",
        "C:/root",
        "a:stream",
        "a//b",
        "a/./b",
        "nul.txt",
        "CON/file",
        "a./file",
        "a /file",
        "a\nfile",
    ],
)
def test_inventory_paths_refuse_escape_and_windows_aliases(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        member(tmp_path, name)


def inventory(root: Path) -> None:
    (root / "application.py").write_text("# trusted application\n")
    (root / "release.json").write_text(
        json.dumps({"format": 1, "files": {"application.py": digest(root / "application.py")}})
    )


def test_inventory_checks_exact_content_and_extra_files(tmp_path: Path) -> None:
    inventory(tmp_path)
    assert verify(tmp_path)["format"] == 1
    (tmp_path / "application.py").write_text("# modified\n")
    with pytest.raises(ValueError, match="changed"):
        verify(tmp_path)
    inventory(tmp_path)
    (tmp_path / "user-script.py").write_text("# not in package\n")
    with pytest.raises(ValueError, match="Unexpected files"):
        verify(tmp_path)


@pytest.mark.parametrize(
    "files",
    [
        {"../escape": "0" * 64},
        {"application.py": "bad"},
        {"application.py": "0" * 64, "Application.py": "0" * 64},
    ],
)
def test_invalid_inventory_refuses(tmp_path: Path, files: dict[str, str]) -> None:
    (tmp_path / "release.json").write_text(json.dumps({"format": 1, "files": files}))
    with pytest.raises(ValueError):
        verify(tmp_path)


def test_archive_refuses_parent_and_link_and_preserves_selected_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("runtime/node.exe", b"pinned bytes")
        z.writestr("runtime/unneeded.txt", b"omitted")
    unpack_zip(archive, tmp_path / "out", prefix="runtime/", only={"node.exe"})
    assert (tmp_path / "out/node.exe").read_bytes() == b"pinned bytes"
    assert not (tmp_path / "out/unneeded.txt").exists()
    for name, mode in [("../escape", 0), ("linked", 0o120777 << 16)]:
        with zipfile.ZipFile(archive, "w") as z:
            item = zipfile.ZipInfo(name)
            item.external_attr = mode
            z.writestr(item, "untrusted")
        with pytest.raises(ValueError):
            unpack_zip(archive, tmp_path / "refused")


def test_distribution_allowlist_excludes_private_and_evaluation_data() -> None:
    names = source_files()
    assert "backend/cli.py" in names
    assert "analysis/typescript/resolver.mts" in names
    assert "agent/validator.py" in names
    assert "eval/bench/machine.py" in names
    assert all("tests" not in Path(n).parts for n in names)
    assert all(not n.startswith(("docs/", "tmp/", "eval/corpus", "eval/splits")) for n in names)
    assert not {"notes.md", "ML_Engineer_CaseStudy.pdf", "AGENTS.md", ".env"}.intersection(names)


@pytest.mark.parametrize("changed", [None, "version", "api", "pin"])
def test_array_contract_packaging_preserves_exact_pins_and_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str | None
) -> None:
    root = tmp_path / "checkout"
    helper = root / "analysis/typescript"
    types = helper / "node_modules/@types/node"
    types.mkdir(parents=True)
    api = b"fixture SQLite array API\n"
    pin = {
        "version": "sqlite-rows-1",
        "node_types_version": "24.19.1",
        "sqlite_sha256": hashlib.sha256(api).hexdigest(),
    }
    (helper / "array-pin.json").write_text(
        json.dumps({**pin, **({"version": "wrong"} if changed == "pin" else {})})
    )
    (types / "sqlite.d.ts").write_bytes(api + (b"changed" if changed == "api" else b""))
    (types / "package.json").write_text(
        json.dumps({"version": "wrong" if changed == "version" else "24.19.1"})
    )
    (types / "LICENSE").write_text("fixture MIT license\n")
    monkeypatch.setattr(distribution, "ROOT", root)
    app = tmp_path / "app"
    if changed:
        with pytest.raises(ValueError, match="SQLite array API pin mismatch"):
            distribution.array_contracts(app)
        assert not app.exists()
    else:
        assert distribution.array_contracts(app) == pin
        target = app / "analysis/typescript/node_modules/@types/node"
        assert (target / "sqlite.d.ts").read_bytes() == api
        assert (target / "LICENSE").read_text() == "fixture MIT license\n"
        assert {p.name for p in target.iterdir()} == {"sqlite.d.ts", "package.json", "LICENSE"}


def test_build_launchers_are_dropped_and_the_real_binary_stays(tmp_path: Path) -> None:
    bin_dir = tmp_path / "deps/bin"
    bin_dir.mkdir(parents=True)
    for name in ("fastapi.exe", "uvicorn.exe", "ty.exe"):
        (bin_dir / name).write_bytes(b"MZ launcher")
    (bin_dir / "pywin32_postinstall.py").write_text("# script\n")
    assert distribution.drop_build_launchers(tmp_path / "deps") == ["fastapi.exe", "uvicorn.exe"]
    assert sorted(p.name for p in bin_dir.iterdir()) == ["pywin32_postinstall.py", "ty.exe"]
    assert distribution.drop_build_launchers(tmp_path / "missing") == []


@pytest.mark.parametrize(
    "content",
    [
        rb"#!C:\Work\Checkout\.venv\Scripts\python.exe",
        b"path = 'c:/work/checkout/frontend'",
        rb'{"source": "C:\\Work\\Checkout\\app"}',
    ],
)
def test_a_package_naming_the_build_checkout_is_refused(tmp_path: Path, content: bytes) -> None:
    package = tmp_path / "package"
    (package / "deps/bin").mkdir(parents=True)
    (package / "deps/bin/tool.exe").write_bytes(b"MZ\x00" + content + b"\x00PK")
    markers = distribution.build_machine_markers(Path("C:/Work/Checkout"))
    with pytest.raises(ValueError, match=r"deps/bin/tool\.exe"):
        distribution.assert_no_build_paths(package, markers)


def test_a_clean_package_passes_the_build_path_check(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "README.txt").write_text('plumb.cmd inspect "D:\\path\\to\\project"\n')
    markers = distribution.build_machine_markers(Path("C:/Work/Checkout"))
    distribution.assert_no_build_paths(package, markers)
