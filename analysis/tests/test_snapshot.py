import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from analysis.snapshot import (
    ChangedWhileReadingError,
    Limits,
    SnapshotStore,
    SnapshotTooLargeError,
    git_commit,
    read_contained,
    take_snapshot,
)
from analysis.tests.test_paths import make_junction, make_symlink
from backend.contracts.code import ExclusionReason, ProjectSnapshot, snapshot_id

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
REPOSITORY = Path(__file__).resolve().parents[2]
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="\n")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    write(root / "api" / "main.py", "from fastapi import FastAPI\n\napp = FastAPI()\n")
    write(root / "web" / "app" / "page.tsx", "export default function Page() {}\n")
    write(root / "web" / "proxy.ts", "export function proxy() {}\n")
    write(root / "pyproject.toml", "[project]\nname = 'x'\n")
    write(root / "README.md", "# x\n")
    write(root / ".env", "API_KEY=do-not-read\n")
    write(root / ".env.example", "API_KEY=\n")
    write(root / "deploy" / "server.pem", "-----BEGIN PRIVATE KEY-----\n")
    write(root / "logo.png", b"\x89PNG\r\n")
    write(root / "data.json", b'{"a": 1}\x00\x00')
    write(root / "big.py", "x = 1\n" * 400)  # 2400 bytes
    write(root / "node_modules" / "lib" / "index.js", "module.exports = 1\n")
    write(root / "api" / "__pycache__" / "main.cpython-312.pyc", b"\x00\x01")
    write(root / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(root / ".git" / "refs" / "heads" / "main", f"{COMMIT}\n")
    outside = tmp_path / "outside"
    write(outside / "secret.py", "TOKEN = 'outside the root'\n")
    return root


@pytest.fixture
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "store")


def snap(root: Path, store: SnapshotStore, sealed: list[Path] | None = None) -> ProjectSnapshot:
    limits = Limits(max_file_bytes=1000)
    return take_snapshot(root, store, limits=limits, sealed=sealed or [], now=NOW)


def reasons(snapshot: ProjectSnapshot) -> dict[str, str]:
    return {e.path: e.reason.value for e in snapshot.excluded}


def test_snapshot_includes_source_and_config(project: Path, store: SnapshotStore) -> None:
    snapshot = snap(project, store)
    files = {f.path: f.language for f in snapshot.files}
    assert files == {
        ".env.example": None,
        "README.md": None,
        "api/main.py": "python",
        "pyproject.toml": None,
        "web/app/page.tsx": "tsx",
        "web/proxy.ts": "typescript",
    }
    assert snapshot.id == snapshot_id(snapshot.files)
    assert snapshot.git_commit == COMMIT
    assert snapshot.dirty is None
    assert snapshot.root_name == "project"


def test_exclusions_are_listed_with_their_reason(project: Path, store: SnapshotStore) -> None:
    assert reasons(snap(project, store)) == {
        ".env": "secret",
        ".git": "default_ignored",
        "api/__pycache__": "default_ignored",
        "big.py": "too_large",
        "data.json": "binary",
        "deploy/server.pem": "secret",
        "logo.png": "unsupported",
        "node_modules": "default_ignored",
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
def test_a_junction_is_refused_not_followed(project: Path, store: SnapshotStore) -> None:
    make_junction(project / "shared", project.parent / "outside")
    snapshot = snap(project, store)
    assert reasons(snapshot)["shared"] == "link"
    assert not any(f.path.startswith("shared/") for f in snapshot.files)


def test_a_symlink_is_refused_not_followed(project: Path, store: SnapshotStore) -> None:
    make_symlink(project / "api" / "settings.py", project.parent / "outside" / "secret.py")
    snapshot = snap(project, store)
    assert reasons(snapshot)["api/settings.py"] == "link"
    assert "api/settings.py" not in {f.path for f in snapshot.files}


def test_a_hard_link_is_refused(project: Path, store: SnapshotStore) -> None:
    os.link(project.parent / "outside" / "secret.py", project / "api" / "config.py")
    assert reasons(snap(project, store))["api/config.py"] == "link"


def test_reads_come_from_the_snapshot_not_the_live_tree(
    project: Path, store: SnapshotStore
) -> None:
    before = snap(project, store)
    original = (project / "api" / "main.py").read_bytes()
    write(project / "api" / "main.py", "app = None  # edited, not committed\n")
    after = snap(project, store)
    assert store.read(before, "api/main.py") == original
    assert store.read(after, "api/main.py") == b"app = None  # edited, not committed\n"
    assert before.id != after.id
    assert store.load(before.id) == before


def test_same_content_gives_the_same_id(project: Path, store: SnapshotStore) -> None:
    assert snap(project, store).id == snap(project, store).id


def test_recapture_returns_original_manifest_without_rewriting(
    project: Path, store: SnapshotStore
) -> None:
    first = snap(project, store)
    manifest = store.directory / "snapshots" / f"{first.id}.json"
    original = manifest.read_bytes()
    modified = manifest.stat().st_mtime_ns
    later = take_snapshot(
        project, store, limits=Limits(max_file_bytes=1000), now=NOW + timedelta(days=1)
    )
    assert later == first == store.load(first.id)
    assert manifest.read_bytes() == original
    assert manifest.stat().st_mtime_ns == modified


@pytest.mark.parametrize(
    "field", ["root_name", "git_commit", "dirty", "excluded", "size", "language"]
)
def test_conflicting_metadata_is_refused_and_original_preserved(
    project: Path, store: SnapshotStore, field: str
) -> None:
    original = snap(project, store)
    changed = original.model_dump()
    changed["created_at"] = NOW + timedelta(days=1)
    if field in ("size", "language"):
        changed["files"][0][field] = 999 if field == "size" else "python"
    else:
        changed[field] = {
            "root_name": "another-project",
            "git_commit": "a" * 40,
            "dirty": True,
            "excluded": [],
        }[field]
    candidate = ProjectSnapshot.model_validate(changed)
    assert candidate.id == original.id
    manifest = store.directory / "snapshots" / f"{original.id}.json"
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="conflicting metadata"):
        store.save(candidate)
    assert manifest.read_bytes() == before
    assert store.load(original.id) == original


def test_corrupt_manifest_is_not_repaired_by_recapture(project: Path, store: SnapshotStore) -> None:
    first = snap(project, store)
    manifest = store.directory / "snapshots" / f"{first.id}.json"
    manifest.write_bytes(b"{incomplete")
    with pytest.raises(ValueError):
        snap(project, store)
    assert manifest.read_bytes() == b"{incomplete"


def test_wrong_manifest_key_is_refused_on_load_and_save(
    project: Path, store: SnapshotStore
) -> None:
    first = snap(project, store)
    write(project / "api" / "main.py", "different = True\n")
    second = snap(project, store)
    path = store.directory / "snapshots" / f"{first.id}.json"
    wrong = second.model_dump_json().encode()
    path.write_bytes(wrong)
    with pytest.raises(ValueError, match="manifest id"):
        store.load(first.id)
    with pytest.raises(ValueError, match="manifest id"):
        store.save(first)
    assert path.read_bytes() == wrong


@pytest.mark.parametrize("conflicting", [False, True])
def test_simultaneous_saves_publish_one_complete_original(
    project: Path,
    store: SnapshotStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conflicting: bool,
) -> None:
    first = snap(project, store)
    second = first.model_copy(update={"created_at": NOW + timedelta(days=1)})
    if conflicting:
        second = second.model_copy(update={"root_name": "another-project"})
    destination = SnapshotStore(tmp_path / "simultaneous")
    rendezvous = Barrier(2, timeout=10)
    original_link = os.link

    def publish(source: Path, target: Path) -> None:
        # Force both writers past their initial lookup before either publishes.
        rendezvous.wait()
        original_link(source, target)

    monkeypatch.setattr("analysis.snapshot.os.link", publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(destination.save, candidate) for candidate in (first, second)]
        results: list[ProjectSnapshot] = []
        failures: list[ValueError] = []
        for future in futures:
            try:
                results.append(future.result(timeout=15))
            except ValueError as error:
                failures.append(error)
    persisted = destination.load(first.id)
    assert persisted in (first, second)
    assert results == [persisted] * (1 if conflicting else 2)
    assert len(failures) == int(conflicting)
    assert all("conflicting metadata" in str(error) for error in failures)
    assert list((destination.directory / "snapshots").iterdir()) == [
        destination.directory / "snapshots" / f"{first.id}.json"
    ]


def test_a_corrupted_blob_is_detected(project: Path, store: SnapshotStore) -> None:
    snapshot = snap(project, store)
    entry = next(f for f in snapshot.files if f.path == "api/main.py")
    (store.blobs.directory / entry.sha256[:2] / entry.sha256).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="corrupted"):
        store.read(snapshot, "api/main.py")


@pytest.mark.parametrize("rel", ["../outside/secret.py", "api/../.env", "C:/x.py"])
def test_store_reads_refuse_unsafe_paths(project: Path, store: SnapshotStore, rel: str) -> None:
    snapshot = snap(project, store)
    with pytest.raises(ValueError):
        store.read(snapshot, rel)


def test_store_reads_only_snapshot_files(project: Path, store: SnapshotStore) -> None:
    with pytest.raises(FileNotFoundError):
        store.read(snap(project, store), ".env")


def test_project_limits_stop_the_snapshot(project: Path, store: SnapshotStore) -> None:
    with pytest.raises(SnapshotTooLargeError, match="files"):
        take_snapshot(project, store, limits=Limits(max_file_bytes=1000, max_files=3))
    with pytest.raises(SnapshotTooLargeError, match="MiB"):
        take_snapshot(project, store, limits=Limits(max_file_bytes=1000, max_total_bytes=50))


def test_sealed_files_are_excluded(project: Path, store: SnapshotStore) -> None:
    sealed = project / "api" / "main.py"
    assert reasons(snap(project, store, sealed=[sealed]))["api/main.py"] == "sealed"


def test_a_file_swapped_after_its_check_is_not_read(tmp_path: Path) -> None:
    write(tmp_path / "a.py", "a = 1\n")
    write(tmp_path / "b.py", "b = 2\n")
    checked = os.lstat(tmp_path / "b.py")
    with pytest.raises(ChangedWhileReadingError):
        read_contained(tmp_path / "a.py", checked, 1000)
    assert read_contained(tmp_path / "a.py", os.lstat(tmp_path / "a.py"), 3) is None


def test_git_commit_from_packed_refs_and_detached_head(tmp_path: Path) -> None:
    write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(tmp_path / ".git" / "packed-refs", f"# pack-refs\n{COMMIT} refs/heads/main\n")
    assert git_commit(tmp_path) == COMMIT
    write(tmp_path / ".git" / "HEAD", f"{COMMIT}\n")
    assert git_commit(tmp_path) == COMMIT


@pytest.mark.parametrize(
    "head",
    ["ref: refs/heads/../../../outside\n", "ref: refs/heads/main\n", "garbage\n"],
)
def test_git_commit_is_none_when_unknown_or_odd(tmp_path: Path, head: str) -> None:
    write(tmp_path / ".git" / "HEAD", head)
    assert git_commit(tmp_path) is None


def test_a_worktree_git_file_is_not_followed(tmp_path: Path) -> None:
    write(tmp_path / ".git", "gitdir: C:/elsewhere/.git/worktrees/x\n")
    assert git_commit(tmp_path) is None


def test_the_tandir_lab_snapshot(store: SnapshotStore) -> None:
    snapshot = take_snapshot(REPOSITORY / "labs" / "tandir", store, now=NOW)
    paths = {f.path for f in snapshot.files}
    assert {"api/tandir/routers/orders.py", "web/app/page.tsx", "web/proxy.ts"} <= paths
    excluded = reasons(snapshot)
    for folder in ("api/.venv", "web/node_modules"):
        if (REPOSITORY / "labs" / "tandir" / folder).exists():
            assert excluded[folder] == ExclusionReason.DEFAULT_IGNORED


def test_sealed_evaluation_cases_never_enter_a_snapshot(store: SnapshotStore) -> None:
    from eval.splits import sealed_paths

    sealed = sealed_paths()
    snapshot = take_snapshot(REPOSITORY / "eval" / "fixtures", store, sealed=sealed, now=NOW)
    sealed_rel = {f"templates/{p.name}" for p in sealed}
    assert sealed_rel
    assert not sealed_rel & {f.path for f in snapshot.files}
    assert sealed_rel <= {p for p, r in reasons(snapshot).items() if r == "sealed"}
