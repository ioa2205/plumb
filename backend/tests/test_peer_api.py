"""Saved peer API boundaries; fixture judgments are replay, never model-quality evidence."""

import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from analysis.snapshot import SnapshotStore
from backend import case_reads
from backend.app import create_app
from backend.contracts.cases import CaseDetail, PeerExcerpt
from backend.contracts.export import render as schemas
from backend.contracts.peers import PeerComparison
from backend.reports import ReportBundle, render
from backend.review import Review
from backend.settings import Settings
from backend.tests.support import PORT, signed_in, visitor
from backend.tests.test_case_reads import files
from backend.tests.test_peer_records import recorded as recorded
from backend.tests.test_review import review as review
from backend.tests.test_saved_reports import RUN_ID


@pytest.fixture
def saved_peers(
    recorded: ReportBundle, review: Review, tmp_path: Path
) -> tuple[Settings, ReportBundle, Path]:
    settings = Settings(data_dir=tmp_path / "data")
    shutil.copytree(review.store.directory, settings.cache_dir / "snapshots")
    raw = recorded.model_dump(mode="json")
    raw["run"]["id"] = RUN_ID
    for finding in raw["findings"]:
        finding["run_id"] = RUN_ID
    bundle = ReportBundle.model_validate(raw)
    directory = settings.data_dir / "reviews" / RUN_ID
    directory.mkdir(parents=True)
    for name, kind in (("report.json", "json"), ("report.html", "html")):
        (directory / name).write_text(
            render(bundle, review.store, kind), encoding="utf-8", newline="\n"
        )
    return settings, bundle, directory


def test_exact_peer_api_and_all_citations_are_read_only(
    saved_peers: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved_peers
    before = files(settings.data_dir)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Saved peer read started analysis, model, execution or writes")

    for target in (
        "backend.review.Review.__init__",
        "agent.peers.PeerCheck.build",
        "backend.llama_server.LlamaServer.start",
        "backend.run_store.RunStore.create",
        "analysis.snapshot.SnapshotStore.save",
        "analysis.snapshot.BlobStore.put",
    ):
        monkeypatch.setattr(target, forbidden)
    client = signed_in(create_app(settings, port=PORT))
    store = SnapshotStore(settings.cache_dir / "snapshots")
    schema = json.loads(schemas()["PeerExcerpt.schema.json"])
    seen: set[tuple[str, int]] = set()
    for peer in bundle.peer_comparisons:
        base = f"/api/runs/{RUN_ID}/findings/{peer.finding_id}"
        detail = CaseDetail.model_validate(client.get(base).json())
        assert detail.peer_comparison == peer
        for row in peer.rows:
            citations = [
                row.site.span,
                row.entry.span,
                *[g.span for g in row.guards],
                *row.evidence,
            ]
            for index, span in enumerate(citations):
                if (row.site.id, index) in seen:
                    continue
                seen.add((row.site.id, index))
                path = f"{base}/peers/{row.site.id}/citations/{index}"
                excerpt = PeerExcerpt.model_validate(client.get(path, params={"lines": 2}).json())
                assert excerpt.span == span and excerpt.site_id == row.site.id
                assert excerpt.citation == index and excerpt.finding_id == peer.finding_id
                assert (
                    excerpt.lines
                    == store.read(bundle.snapshot, span.path)
                    .decode()
                    .splitlines()[span.start_line - 1 : min(span.end_line, span.start_line + 1)]
                )
                if excerpt.next_offset is not None:
                    next_page = PeerExcerpt.model_validate(
                        client.get(path, params={"offset": excerpt.next_offset}).json()
                    )
                    assert next_page.start_line == excerpt.end_line + 1
                assert not list(
                    Draft202012Validator(schema).iter_errors(excerpt.model_dump(mode="json"))
                )
    assert files(settings.data_dir) == before


@pytest.mark.parametrize("mutation", ["finding", "question", "group", "snapshot"])
def test_projection_refuses_comparison_from_another_case(
    saved_peers: tuple[Settings, ReportBundle, Path], mutation: str
) -> None:
    settings, bundle, _ = saved_peers
    detail = case_reads.CaseReads(settings).case(RUN_ID, bundle.findings[0].id)
    raw = detail.model_dump(mode="json")
    peer = raw["peer_comparison"]
    if mutation == "finding":
        peer["finding_id"] = "other"
    elif mutation == "question":
        peer["question_id"] = "other"
    elif mutation == "group":
        peer["group"]["id"] = "other"
    else:
        raw["finding"]["snapshot_id"] = "0" * 64
    with pytest.raises(ValueError):
        CaseDetail.model_validate(raw)


@pytest.mark.parametrize(
    ("site", "citation", "params", "status"),
    [
        ("absent", 0, {}, 404),
        ("valid", 201, {}, 404),
        ("valid", 202, {}, 422),
        ("valid", -1, {}, 422),
        ("valid", 0, {"offset": 999}, 503),
        ("valid", 0, {"lines": 81}, 422),
        ("valid", 0, {"offset": -1}, 422),
    ],
)
def test_missing_and_out_of_bounds_peer_citations_are_refused(
    saved_peers: tuple[Settings, ReportBundle, Path],
    site: str,
    citation: int,
    params: dict[str, int],
    status: int,
) -> None:
    settings, bundle, _ = saved_peers
    peer = bundle.peer_comparisons[0]
    site_id = peer.rows[0].site.id if site == "valid" else "absent"
    client = signed_in(create_app(settings, port=PORT))
    response = client.get(
        f"/api/runs/{RUN_ID}/findings/{peer.finding_id}/peers/{site_id}/citations/{citation}",
        params=params,
    )
    assert response.status_code == status and str(settings.data_dir) not in response.text


def test_peer_auth_corruption_and_size_boundaries(
    saved_peers: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, directory = saved_peers
    peer = bundle.peer_comparisons[0]
    row = peer.rows[0]
    path = f"/api/runs/{RUN_ID}/findings/{peer.finding_id}/peers/{row.site.id}/citations/0"
    app = create_app(settings, port=PORT)
    assert visitor(app).get(path).status_code == 401
    client = signed_in(app)
    assert client.get(path, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    monkeypatch.setattr(case_reads, "MAX_CASE_BYTES", 20)
    assert client.get(path).status_code == 503
    monkeypatch.undo()
    raw = json.loads((directory / "report.json").read_bytes())
    raw["peer_comparisons"][0]["rows"][0]["site"]["span"]["content_sha256"] = "0" * 64
    (directory / "report.json").write_text(json.dumps(raw), encoding="utf-8")
    response = client.get(path)
    assert response.status_code == 503 and "content_sha256" not in response.text


def test_unknown_peer_guards_do_not_create_a_deviation(recorded: ReportBundle) -> None:
    raw = recorded.peer_comparisons[0].model_dump(mode="json")
    for row in raw["rows"]:
        row["guards"] = []
        row["issues"] = ["Guard classification unresolved in recorded search"]
    raw["group"].update(columns=[], deviations=[])
    assert not PeerComparison.model_validate(raw).group.deviations
