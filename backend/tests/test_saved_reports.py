"""Saved navigation stays offline and cannot open arbitrary or modified files."""

import json
import shutil
from pathlib import Path

import pytest

from agent.tests.test_validator import T0, Lab
from backend import saved_reports
from backend.cli import main
from backend.contracts.runs import Coverage, ReviewRun, RunLifecycle, RunStage
from backend.reports import ReportBundle, render
from backend.settings import Settings

RUN_ID = "review-" + "a" * 32


@pytest.fixture
def saved(tmp_path: Path) -> tuple[Settings, ReportBundle, Path]:
    lab = Lab(tmp_path / "fixture")
    settings = Settings(data_dir=tmp_path / "data")
    shutil.copytree(lab.store.directory, settings.cache_dir / "snapshots")
    finding = lab.finding(run_id=RUN_ID)
    run = ReviewRun(
        id=RUN_ID,
        snapshot_id=lab.snapshot.id,
        run_type="saved",
        lifecycle="completed",
        created_at=T0,
        started_at=T0,
        finished_at=T0,
        finding_ids=[finding.id],
        coverage=Coverage(total=4, completed=1, excluded=1, unsupported=2),
    )
    bundle = ReportBundle(
        run=run,
        snapshot=lab.snapshot,
        findings=[finding],
        limitations=["Synthetic fixture; this is not real model acceptance."],
    )
    directory = settings.data_dir / "reviews" / RUN_ID
    directory.mkdir(parents=True)
    for name, format in (("report.json", "json"), ("report.html", "html")):
        (directory / name).write_text(
            render(bundle, lab.store, format), encoding="utf-8", newline="\n"
        )
    return settings, bundle, directory


def test_headless_saved_report_keeps_ids_denominator_and_no_analysis(
    saved: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, bundle, directory = saved
    monkeypatch.setenv("PLUMB_DATA_DIR", str(settings.data_dir))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Saved viewing attempted analysis, model, browser or run creation")

    for name in ("RunStore", "Review", "create", "select"):
        monkeypatch.setattr(f"backend.cli.{name}", forbidden)
    monkeypatch.setattr(saved_reports, "launch", forbidden)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert main(["report", RUN_ID]) == 0
    output = capsys.readouterr().out
    assert "1/4 checks processed" in output
    assert "1 excluded, 2 unsupported" in output
    assert "1 supported, 0 rejected, 0 inconclusive" in output
    assert "Static support does not establish runtime reproduction" in output
    loaded, path = saved_reports.load(settings, RUN_ID)
    assert loaded.run.id == bundle.run.id and loaded.run.coverage == bundle.run.coverage
    assert [f.id for f in loaded.findings] == [f.id for f in bundle.findings]
    assert path == directory / "report.html"
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


@pytest.mark.parametrize("failure", [False, True])
def test_browser_failure_preserves_the_report_and_prints_path(
    saved: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: bool,
) -> None:
    settings, _, directory = saved
    original = (directory / "report.html").read_bytes()

    def unavailable(path: Path) -> bool:
        assert path == directory / "report.html"
        if failure:
            raise OSError("headless fixture")
        return False

    monkeypatch.setattr(saved_reports, "launch", unavailable)
    assert saved_reports.show(settings, RUN_ID, open_browser=True) == 2
    assert str(directory / "report.html") in capsys.readouterr().out
    assert (directory / "report.html").read_bytes() == original


def test_default_browser_dispatch_uses_only_the_validated_file_path(
    saved: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _, directory = saved
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(saved_reports.sys, "platform", "win32")
    monkeypatch.setattr(
        saved_reports.os, "startfile", lambda path, action: calls.append((path, action))
    )
    assert saved_reports.show(settings, RUN_ID, open_browser=True) == 0
    assert calls == [(str(directory / "report.html"), "open")]


@pytest.mark.parametrize("run_id", ["../report", "https://example.com", "review-" + "a" * 33])
def test_ids_cannot_navigate_outside_saved_reviews(
    saved: tuple[Settings, ReportBundle, Path],
    run_id: str,
) -> None:
    with pytest.raises(ValueError, match="Invalid"):
        saved_reports.load(saved[0], run_id)


def test_modified_html_is_refused_before_browser_dispatch(
    saved: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _, directory = saved
    (directory / "report.html").write_text("<script>untrusted()</script>", encoding="utf-8")
    monkeypatch.setattr(saved_reports, "launch", lambda path: pytest.fail("Modified HTML opened"))
    with pytest.raises(ValueError, match="differs"):
        saved_reports.show(settings, RUN_ID, open_browser=True)


def test_wrong_run_and_bad_evidence_are_refused(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, directory = saved
    data = json.loads((directory / "report.json").read_text())
    data["run"]["id"] = "review-" + "b" * 32
    data["findings"][0]["run_id"] = data["run"]["id"]
    (directory / "report.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="different review"):
        saved_reports.load(settings, RUN_ID)
    data["run"]["id"] = bundle.run.id
    data["findings"][0]["run_id"] = bundle.run.id
    data["findings"][0]["exhibits"][0]["span"]["content_sha256"] = "b" * 64
    (directory / "report.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        saved_reports.load(settings, RUN_ID)


def test_empty_partial_summary_never_claims_safety(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    _, bundle, _ = saved
    run = bundle.run.model_copy(
        update={
            "lifecycle": RunLifecycle.PAUSED,
            "stage": RunStage.INVESTIGATING,
            "finished_at": None,
            "finding_ids": [],
            "coverage": Coverage(total=4, pending=2, excluded=1, unsupported=1),
        }
    )
    empty = bundle.model_copy(update={"run": run, "findings": []})
    text = saved_reports.summary(empty)
    assert "paused" in text and "0/4 checks processed" in text
    assert "No checks have completed yet" in text and "new live review" in text
    assert "plumb resume" not in text
    assert "safe" not in text.lower()
