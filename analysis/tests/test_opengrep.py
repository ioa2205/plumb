"""Pattern leads stay bound to executable frozen source and never run target code."""

import json
import subprocess
from pathlib import Path
from typing import BinaryIO

import pytest

from analysis import opengrep
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.investigation import ObservationStatus
from backend.settings import Settings

RULE = "plumb.injection.shell-command-not-literal"


def result(path: str, *, line: int = 2, rule: str = RULE) -> dict:
    return {"check_id": rule, "path": path, "start": {"line": line}, "end": {"line": line}}


@pytest.fixture
def source(tmp_path: Path) -> tuple:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text(
        "# subprocess.run(user, shell=True)\nsubprocess.run(user, shell=True)\n",
        encoding="utf-8",
    )
    (project / ".semgrepignore").write_text("main.py", encoding="utf-8")
    (project / "config.yaml").write_text("not trusted configuration", encoding="utf-8")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(project, store)
    return project, snapshot, store


@pytest.mark.parametrize(
    "bad",
    [
        result("../outside.py"),
        result("absent.py"),
        result("main.py", line=1),
        result("main.py", line=999),
        result("main.py", rule="untrusted-rule"),
        result("main.py", line=True),
    ],
)
def test_invalid_matches_cannot_supply_queue_evidence(source: tuple, bad: dict) -> None:
    root, snapshot, store = source
    signals, limits = opengrep.parse_signals({"results": [bad]}, root, snapshot, store)
    assert not signals and limits


def test_matches_deduplicate_without_erasing_scanner_errors(source: tuple) -> None:
    root, snapshot, store = source
    signals, limits = opengrep.parse_signals(
        {"results": [result("main.py"), result("main.py")], "errors": [{"type": "timeout"}]},
        root,
        snapshot,
        store,
    )
    assert len(signals) == 1 and signals[0].span.snapshot_id == snapshot.id
    assert limits and "partial" in limits[0]


def test_scanner_receives_only_frozen_source_and_pinned_configuration(
    source: tuple,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, snapshot, store = source
    (project / "main.py").write_text("raise RuntimeError('live source changed')", encoding="utf-8")
    monkeypatch.setattr(opengrep, "binary", lambda *_: Path("trusted-scanner.exe"))
    monkeypatch.setenv("SEMGREP_APP_TOKEN", "do-not-forward")
    roots = []

    def execute(
        argv: list[str], *, stdout: BinaryIO, **kwargs: object
    ) -> subprocess.CompletedProcess:
        root = Path(argv[-1])
        roots.append(root)
        assert {p.name for p in root.iterdir()} == {"main.py"}
        assert (root / "main.py").read_bytes() == store.read(snapshot, "main.py")
        assert argv[argv.index("--config") + 1] == str(opengrep.RULES)
        assert "--no-git-ignore" in argv and "--disable-version-check" in argv
        environment = kwargs["env"]
        assert isinstance(environment, dict) and "SEMGREP_APP_TOKEN" not in environment
        stdout.write(json.dumps({"results": [result(str(root / "main.py"))]}).encode())
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(opengrep.subprocess, "run", execute)
    scan = opengrep.scan(snapshot, store, Settings(data_dir=tmp_path / "data"), "review:test")
    assert scan.observation.status is ObservationStatus.OK and len(scan.signals) == 1
    assert scan.observation.output_sha256
    assert scan.observation.inputs["snapshot_id"] == snapshot.id
    assert all(not root.exists() for root in roots)


@pytest.mark.parametrize(
    "failure,status",
    [
        (FileNotFoundError(), ObservationStatus.REFUSED),
        (subprocess.TimeoutExpired("scanner", 120), ObservationStatus.TIMEOUT),
        (ValueError("malformed output"), ObservationStatus.ERROR),
    ],
)
def test_scanner_failures_remain_visible_without_manufacturing_findings(
    source: tuple,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status: ObservationStatus,
) -> None:
    _, snapshot, store = source

    def fail(*args: object) -> Path:
        raise failure

    monkeypatch.setattr(opengrep, "binary", fail)
    scan = opengrep.scan(snapshot, store, Settings(data_dir=tmp_path / "data"), "review:test")
    assert scan.observation.status is status and scan.limitations and not scan.signals
