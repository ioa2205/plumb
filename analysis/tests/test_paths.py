import os
import sys
from pathlib import Path

import pytest

from analysis.paths import (
    RootError,
    UnsafePathError,
    canonical_root,
    check_relative,
    resolve_inside,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")


def make_junction(link: Path, target: Path) -> None:
    import _winapi  # Windows only: creates a junction without admin rights

    _winapi.CreateJunction(str(target), str(link))


def make_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as e:  # Windows without Developer Mode or admin rights
        pytest.skip(f"cannot create symlinks here: {e}")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "api").mkdir(parents=True)
    (root / "api" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / "web" / "app" / "[id]").mkdir(parents=True)
    (root / "web" / "app" / "[id]" / "page.tsx").write_text("export {}\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("not yours\n", encoding="utf-8")
    return canonical_root(root)


@pytest.mark.parametrize("rel", ["api/app.py", "web/app/[id]/page.tsx", ".git/HEAD", "a b/c.py"])
def test_plain_relative_paths_are_accepted(rel: str) -> None:
    assert check_relative(rel).as_posix() == rel


@pytest.mark.parametrize(
    "rel",
    [
        "",
        "..",
        "../outside/secret.txt",
        "api/../../outside/secret.txt",
        "./api/app.py",
        "api/./app.py",
        "api//app.py",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "C:secret.txt",
        "//server/share/file",
        "api\\app.py",
        "app.py:hidden",
        "api/app.py::$DATA",
        "con",
        "NUL.txt",
        "api/com1.py",
        "LPT9",
        "api/app.py.",
        "api/app.py ",
        "api/ap\x00p.py",
        "api/ap\np.py",
    ],
)
def test_unsafe_relative_paths_are_refused(rel: str) -> None:
    with pytest.raises(UnsafePathError):
        check_relative(rel)


def test_resolve_inside_finds_a_file(tree: Path) -> None:
    assert resolve_inside(tree, "api/app.py") == tree / "api" / "app.py"


def test_resolve_inside_refuses_dot_dot(tree: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_inside(tree, "../outside/secret.txt")


def test_missing_file_is_not_found(tree: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_inside(tree, "api/missing.py")


@windows_only
def test_resolve_inside_refuses_a_junction(tree: Path) -> None:
    make_junction(tree / "linked", tree.parent / "outside")
    assert (tree / "linked" / "secret.txt").is_file()  # the junction works
    with pytest.raises(UnsafePathError, match="link"):
        resolve_inside(tree, "linked/secret.txt")
    with pytest.raises(UnsafePathError, match="link"):
        resolve_inside(tree, "linked")


def test_resolve_inside_refuses_a_symlink(tree: Path) -> None:
    make_symlink(tree / "api" / "leak.txt", tree.parent / "outside" / "secret.txt")
    with pytest.raises(UnsafePathError, match="link"):
        resolve_inside(tree, "api/leak.txt")


def test_resolve_inside_refuses_a_hard_link(tree: Path) -> None:
    os.link(tree.parent / "outside" / "secret.txt", tree / "api" / "hard.txt")
    with pytest.raises(UnsafePathError, match="hard links"):
        resolve_inside(tree, "api/hard.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive file system")
def test_case_variants_resolve_to_the_same_file(tree: Path) -> None:
    assert resolve_inside(tree, "API/APP.PY").samefile(tree / "api" / "app.py")


def test_root_must_be_an_existing_folder(tmp_path: Path) -> None:
    with pytest.raises(RootError):
        canonical_root(tmp_path / "missing")
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RootError):
        canonical_root(tmp_path / "file.txt")


ALL_USERS = Path("C:/Users/All Users")  # a symlink to C:\ProgramData on every Windows install


@pytest.mark.skipif(not ALL_USERS.is_symlink(), reason="needs the built-in Windows symlink")
def test_resolve_inside_refuses_a_real_windows_symlink() -> None:
    root = canonical_root(Path("C:/Users"))
    with pytest.raises(UnsafePathError, match="link"):
        resolve_inside(root, "All Users")


def _stat(mode: int, attributes: int = 0, links: int = 1) -> os.stat_result:
    return os.stat_result((mode, 0, 0, links, 0, 0, 0, 0, 0, 0), {"st_file_attributes": attributes})


def test_link_detection_by_mode_and_reparse_attribute() -> None:
    import stat

    from analysis.paths import has_extra_links, is_link

    assert is_link(_stat(stat.S_IFLNK | 0o777))
    assert is_link(_stat(stat.S_IFDIR | 0o755, attributes=0x400))  # junction, reparse point
    assert not is_link(_stat(stat.S_IFREG | 0o644))
    assert has_extra_links(_stat(stat.S_IFREG | 0o644, links=2))
    assert not has_extra_links(_stat(stat.S_IFDIR | 0o755, links=3))
