"""One offline shared-workflow fixture, saved/API/export isolation and non-leakage."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis.snapshot import SnapshotStore, take_snapshot
from backend.app import create_app
from backend.case_reads import CaseReads
from backend.contracts.runs import Coverage, ReviewRun
from backend.reports import ReportBundle, render
from backend.review import Review, export
from backend.run_store import RunStore
from backend.scheduling import Preparation, prepare
from backend.settings import Settings
from backend.tests.support import PORT, signed_in, visitor

RUN = "review-" + "c" * 32
NOW = datetime(2026, 10, 7, tzinfo=UTC)


def test_offline_review_persists_signals_in_api_and_all_exports_without_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    token = "ghp_" + "T" * 34
    (target / "app.py").write_text(
        f'from fastapi import FastAPI as App\napp=App(debug=True)\napi_key="{token}"\n',
        encoding="utf-8",
        newline="\n",
    )
    (target / "package-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/rsc-alias": {
                        "name": "react-server-dom-webpack",
                        "version": "19.1.1",
                        "resolved": "https://registry.npmjs.org/react-server-dom-webpack/-/react-server-dom-webpack-19.1.1.tgz",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (target / ".env").write_text('password="excluded-credential"', encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(target, store)
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    run = ReviewRun(
        id=RUN,
        snapshot_id=snapshot.id,
        run_type="saved",
        lifecycle="completed",
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW,
        coverage=Coverage(total=0),
    )
    runs.create(run, [])
    context = Review(settings, snapshot.id)
    try:
        context.preparation = prepare(context, RUN, tmp_path / "guards.sqlite", "fixture")
        assert context.preparation.supplementary is not None
        frozen = context.preparation.model_dump_json()
        directory = settings.data_dir / "reviews" / RUN
        bundle = export(context, runs, RUN, directory)
        assert bundle.supplementary is not None
        assert {s.category for s in bundle.supplementary.signals} == {
            "secret",
            "configuration",
            "dependency",
        }
        assert not bundle.findings and not bundle.run.finding_ids
        assert bundle.run.coverage == run.coverage
        for name in ("report.json", "report.html", "report.md", "report.sarif"):
            text = (directory / name).read_text(encoding="utf-8")
            assert token not in text and "excluded-credential" not in text
            searchable = text.replace("\\.", ".") if name == "report.md" else text
            assert "19.1.1" in searchable and "GHSA-fv66-9v8q-g76r" in searchable
            assert "exposure" in text.lower()
        sarif = json.loads((directory / "report.sarif").read_bytes())
        assert sarif["runs"][0]["results"] == []
        assert sarif["runs"][0]["properties"]["plumbReport"]["supplementary"]
        (directory / "scheduling.json").write_text(frozen, encoding="utf-8")
        selection = settings.data_dir / "advisories/active.json"
        selection.parent.mkdir(parents=True)
        selection.write_text("{}", encoding="utf-8")
        context.preparation = Preparation.model_validate_json(
            (directory / "scheduling.json").read_bytes()
        )
        assert context.preparation.model_dump_json() == frozen
        assert export(context, runs, RUN, directory).supplementary == bundle.supplementary
    finally:
        context.close()

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Saved API read attempted a fresh advisory observation")

    monkeypatch.setattr("analysis.security_signals.observe", forbidden)
    reads = CaseReads(settings)
    page = reads.finding_list(RUN)
    assert page.supplementary == bundle.supplementary and page.total == 0
    assert sum(page.counts.values()) == 0 and page.run.coverage.total == 0
    app = create_app(settings, port=PORT)
    url = f"/api/runs/{RUN}/finding-list"
    assert visitor(app).get(url).status_code == 401
    client = signed_in(app)
    response = client.get(url)
    assert response.status_code == 200 and token not in response.text
    assert response.json()["supplementary"]["pack_sha256"] == bundle.supplementary.pack_sha256
    assert client.get(url, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    wrong_run = bundle.supplementary.model_copy(update={"run_id": "another-run"})
    with pytest.raises(ValidationError):
        ReportBundle.model_validate(
            {**bundle.model_dump(), "supplementary": wrong_run.model_dump()}
        )
    bad_signal = bundle.supplementary.signals[0].model_copy(
        update={
            "source": bundle.supplementary.signals[0].source.model_copy(
                update={"content_sha256": "0" * 64}
            ),
        }
    )
    changed = bundle.supplementary.model_copy(update={"signals": [bad_signal]})
    with pytest.raises(ValueError):
        render(bundle.model_copy(update={"supplementary": changed}), store, "json")
