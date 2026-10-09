"""Shared fixtures for the agent tests."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from analysis.snapshot import SnapshotStore, capture_snapshot
from backend.system_tools import on_search_path

ROOT = Path(__file__).resolve().parents[2]
# The practice app's README as the saved 8 October 2026 records saw it. M7.9b reworded one
# sentence of it afterwards, which changed the lab's snapshot ID and no source file.
RECORDED_README_BLOB = "91a098d8f879344fac25e75a44119769bb238dad"
RECORDED_README_SHA256 = "d02842d439541eacf6a5a812bf9b74ea7ba9eba946e1c8296e0cf5085ed1f433"


@pytest.fixture(scope="session")
def recorded_lab(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The practice app as the saved records saw it, rebuilt in a temporary folder (M7.9e).

    Today's files, with the README taken from this repository's Git history and checked
    against its hash. Each replay still compares the rebuilt lab's snapshot ID with the one
    in its record, so a lab whose source has changed since is refused there, not here.
    """
    if not (ROOT / "docs/results").is_dir():
        pytest.skip("needs the saved evaluation records; this copy does not hold them")
    git = on_search_path("git")
    done = (
        subprocess.run(  # noqa: S603 - Git on this repository's own history
            [str(git), "cat-file", "blob", RECORDED_README_BLOB],
            cwd=ROOT,
            capture_output=True,
            timeout=60,
        )
        if git
        else None
    )
    if done is None or done.returncode != 0:
        pytest.skip("needs the practice app's earlier README from this repository's Git history")
    assert hashlib.sha256(done.stdout).hexdigest() == RECORDED_README_SHA256
    lab = ROOT / "labs/tandir"
    folder = tmp_path_factory.mktemp("recorded-lab") / "tandir"
    store = SnapshotStore(tmp_path_factory.mktemp("recorded-lab-store"))
    for file in capture_snapshot(lab, store).files:
        target = folder / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(lab / file.path, target)
    (folder / "README.md").write_bytes(done.stdout)
    # The records were taken on a working copy whose web/tsconfig.json ended in CR LF: the
    # framework's build wrote that last line ending on Windows. Git checks the file out with
    # LF, so a clone differs from the recorded lab by that one byte. Put it back.
    config = folder / "web/tsconfig.json"
    plain = config.read_bytes().replace(b"\r", b"")
    config.write_bytes(plain.removesuffix(b"\n") + b"\r\n")
    return folder
