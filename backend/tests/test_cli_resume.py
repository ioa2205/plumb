"""Resume keeps run provenance and refuses replay/live mixing before model setup."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend import cli
from backend.contracts.runs import ReviewRun, RunLifecycle, RunStage, RunType
from backend.profiles import Profile
from backend.review import implementation_identity, write_json
from backend.run_store import RunStore
from backend.settings import Settings


@pytest.mark.parametrize(
    "module",
    [
        "agent/guards.py",
        "agent/boundaries.py",
        "analysis/resolution.py",
        "analysis/platform_calls.py",
        "analysis/typescript/platform_calls.mts",
        "analysis/typescript/platform-pin.json",
        "agent/guard_syntax.py",
        "agent/ts_role_guards.py",
        "agent/ts_guard_forms.py",
        "analysis/access_python.py",
        "agent/ts_paths.py",
        "backend/scheduling.py",
        "analysis/opengrep.py",
        "agent/priority.py",
        "agent/severity.py",
        "analysis/provenance.py",
        "analysis/typescript/serialization_facts.mts",
        "analysis/typescript/nextjs_facts.mts",
        "analysis/typescript/array_provenance.mts",
        "analysis/typescript/array-pin.json",
        "analysis/typescript/access_facts.mts",
        "analysis/access_facts.py",
        "analysis/nextjs.py",
        "analysis/serialization.py",
        "analysis/advisories.py",
        "analysis/security_signals.py",
        "backend/redaction.py",
        "analysis/advisory_pack/pin.json",
        "agent/proposals.py",
        "analysis/patches.py",
        "verification/proposals.py",
        "backend/contracts/verification.py",
        "backend/capabilities.json",
        "backend/profiles.py",
        "analysis/index.py",
        "analysis/syntax.py",
    ],
)
def test_source_proof_changes_invalidate_resume_identity(
    monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    before = implementation_identity()
    original = Path.read_bytes

    def changed(path: Path) -> bytes:
        data = original(path)
        return (
            data + b"\n# changed implementation\n"
            if path.as_posix().endswith("/" + module)
            else data
        )

    monkeypatch.setattr(Path, "read_bytes", changed)
    after = implementation_identity()
    assert before[module] != after[module]
    assert {p for p in before if before[p] != after[p]} == {module}


@pytest.mark.parametrize("kind", list(RunType))
def test_non_live_resume_refuses_before_profile_and_model_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: RunType,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setenv("PLUMB_DATA_DIR", str(settings.data_dir))
    monkeypatch.setattr(cli, "machine_state", lambda: {})
    run_id = "review-" + "a" * 32
    now = datetime.now(UTC)
    run = ReviewRun(
        id=run_id,
        snapshot_id="b" * 64,
        run_type=kind,
        lifecycle=RunLifecycle.PAUSED,
        stage=RunStage.INVESTIGATING,
        created_at=now,
        started_at=now,
    )
    RunStore(settings.cache_dir / "runs.sqlite").create(run, [])
    directory = settings.data_dir / "reviews" / run_id
    directory.mkdir(parents=True)
    write_json(
        directory / "context.json",
        {
            "snapshot_id": run.snapshot_id,
            "implementation": implementation_identity(),
            "profile": Profile().identity(),
        },
    )
    calls: list[str] = []

    def select(*args: object) -> None:
        calls.append("select")
        raise ValueError("Live profile selection reached")

    def forbidden(*args: object) -> None:
        pytest.fail("Resume constructed a model or analysis context unexpectedly")

    monkeypatch.setattr(cli, "select", select)
    monkeypatch.setattr(cli, "create", forbidden)
    monkeypatch.setattr(cli, "Review", forbidden)
    assert cli.main(["resume", run_id]) == 1
    output = capsys.readouterr().out
    if kind is RunType.LIVE:
        assert calls == ["select"] and "Live profile selection reached" in output
    else:
        assert not calls and "Saved/replayed runs cannot resume live inference" in output
    stored = RunStore(settings.cache_dir / "runs.sqlite").run(run_id)
    assert stored is not None and stored.run_type is kind
