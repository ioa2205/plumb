"""Surrounding code remains frozen display context, never extra evidence authority."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import SecretStr

from agent.tests.test_validator import FILES, ORDERS_PY, T0, Lab
from analysis.snapshot import SnapshotStore
from backend import case_reads
from backend.app import create_app
from backend.contracts.cases import SnapshotCodePage
from backend.contracts.export import render as schemas
from backend.contracts.investigation import ExhibitRole
from backend.contracts.runs import ReviewRun
from backend.reports import ReportBundle
from backend.settings import Settings
from backend.tests.support import PORT, signed_in, visitor
from backend.tests.test_case_reads import files
from backend.tests.test_peer_api import saved_peers as saved_peers
from backend.tests.test_peer_records import recorded as recorded
from backend.tests.test_review import review as review
from backend.tests.test_saved_reports import RUN_ID
from backend.tests.test_saved_reports import saved as saved


def path(bundle: ReportBundle) -> str:
    return f"/api/runs/{bundle.run.id}/findings/{bundle.findings[0].id}/exhibits/E01/code"


def test_context_and_full_file_pages_preserve_citation_and_original_numbering(
    saved: tuple[Settings, ReportBundle, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved
    before = files(settings.data_dir)
    span = bundle.findings[0].exhibits[0].span
    source = SnapshotStore(settings.cache_dir / "snapshots").read(bundle.snapshot, span.path)
    original = source.decode().split("\n")[:-1]
    # A live file change cannot contaminate a saved context/full-file read.
    (tmp_path / "fixture/project" / span.path).write_text("raise RuntimeError('never run')\n")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Code context attempted inference, analysis, execution or snapshot writes")

    for target in (
        "backend.llama_server.LlamaServer.start",
        "backend.review.Review.__init__",
        "analysis.snapshot.SnapshotStore.save",
        "analysis.snapshot.BlobStore.put",
    ):
        monkeypatch.setattr(target, forbidden)
    client = signed_in(create_app(settings, port=PORT))
    page = SnapshotCodePage.model_validate(client.get(path(bundle)).json())
    assert page.citation == span and page.context_is_not_evidence and page.comments_are_not_evidence
    assert page.file_sha256 == hashlib.sha256(source).hexdigest()
    assert page.lines == original[span.start_line - 4 : span.end_line + 3]
    assert (page.range_start, page.range_end) == (span.start_line - 3, span.end_line + 3)
    schema = json.loads(schemas()["SnapshotCodePage.schema.json"])
    assert not list(Draft202012Validator(schema).iter_errors(page.model_dump(mode="json")))
    offset = 0
    collected: list[str] = []
    while True:
        page = SnapshotCodePage.model_validate(
            client.get(path(bundle), params={"mode": "file", "offset": offset, "lines": 2}).json()
        )
        assert page.citation == span and page.before == page.after == 0
        assert page.start_line == offset + 1 and page.file_line_count == len(original)
        collected.extend(page.lines)
        if page.next_offset is None:
            break
        offset = page.next_offset
    assert collected == original and files(settings.data_dir) == before


def test_peer_context_is_bound_to_its_saved_case_and_citation(
    saved_peers: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = saved_peers
    peer = bundle.peer_comparisons[0]
    row = peer.rows[0]
    client = signed_in(create_app(settings, port=PORT))
    base = f"/api/runs/{bundle.run.id}/findings/{peer.finding_id}/peers/{row.site.id}/citations"
    page = SnapshotCodePage.model_validate(client.get(f"{base}/0/code").json())
    assert page.citation == row.site.span
    source = SnapshotStore(settings.cache_dir / "snapshots").read(
        bundle.snapshot, row.site.span.path
    )
    assert page.lines == source.decode().split("\n")[page.start_line - 1 : page.end_line]
    assert client.get(f"{base}/201/code").status_code == 404
    assert client.get(base.replace(row.site.id, "absent") + "/0/code").status_code == 404


@pytest.mark.parametrize(
    "params,status",
    [
        ({"before": -1}, 422),
        ({"after": 81}, 422),
        ({"lines": 81}, 422),
        ({"offset": -1}, 422),
        ({"offset": 1_000_001}, 422),
        ({"mode": "live"}, 422),
        ({"offset": 999}, 503),
    ],
)
def test_context_ranges_and_auth_are_refused_safely(
    saved: tuple[Settings, ReportBundle, Path],
    params: dict[str, int | str],
    status: int,
) -> None:
    settings, bundle, _ = saved
    app = create_app(settings, port=PORT)
    assert visitor(app).get(path(bundle)).status_code == 401
    client = signed_in(app)
    assert (
        client.get(path(bundle), headers={"Origin": "https://foreign.invalid"}).status_code == 403
    )
    response = client.get(path(bundle), params=params)
    assert response.status_code == status and str(settings.data_dir) not in response.text


def test_missing_notes_changed_source_and_size_cannot_expose_context(
    saved: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, bundle, _ = saved
    client = signed_in(create_app(settings, port=PORT))
    assert client.get(path(bundle).replace("E01", "E99")).status_code == 404
    reader = case_reads.CaseReads(settings)
    with pytest.raises(case_reads.CaseUnavailable):
        reader.code_page(RUN_ID, bundle.findings[0].id, tag="E01", site_id="other", citation=0)
    monkeypatch.setattr(case_reads, "MAX_CASE_BYTES", 20)
    assert client.get(path(bundle)).status_code == 503
    monkeypatch.undo()
    bundle.findings[0].exhibits[0] = (
        bundle.findings[0].exhibits[0].model_copy(update={"role": ExhibitRole.DEVELOPER_NOTE})
    )
    monkeypatch.setattr(case_reads, "load", lambda *args: (bundle, Path("unused")))
    with pytest.raises(case_reads.CaseUnavailable, match="Developer notes"):
        reader.code_page(RUN_ID, bundle.findings[0].id, tag="E01", mode="file")
    monkeypatch.undo()
    file = next(
        f for f in bundle.snapshot.files if f.path == bundle.findings[0].exhibits[0].span.path
    )
    SnapshotStore(settings.cache_dir / "snapshots").blobs._path(file.sha256).write_bytes(
        b"private-corruption"
    )
    response = client.get(path(bundle), params={"mode": "file"})
    assert response.status_code == 503 and "private-corruption" not in response.text


def test_multiline_secret_starting_outside_a_page_is_redacted_before_slicing(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = saved
    span = bundle.findings[0].exhibits[0].span
    source = (
        SnapshotStore(settings.cache_dir / "snapshots").read(bundle.snapshot, span.path).decode()
    )
    secret = "\n".join(source.split("\n")[5:12])
    reader = case_reads.CaseReads(
        settings.model_copy(update={"redaction_secrets": (SecretStr(secret),)})
    )
    page = reader.code_page(RUN_ID, bundle.findings[0].id, tag="E01", before=0, after=0, lines=2)
    assert page.lines == ["[REDACTED]", "[REDACTED]"] and page.citation == span


def test_unicode_separators_and_carriage_returns_do_not_invent_source_line_numbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"# display separators: \r\v" + "\u2028".encode() + b"\n" + FILES[ORDERS_PY]
    monkeypatch.setitem(FILES, ORDERS_PY, source)
    lab = Lab(tmp_path)
    settings = Settings(data_dir=tmp_path / "data")
    shutil.copytree(lab.store.directory, settings.cache_dir / "snapshots")
    finding = lab.finding(
        run_id=RUN_ID,
        exhibits=[
            {
                "tag": "E01",
                "span": lab.span(ORDERS_PY, 11, 14),
                "role": "evidence",
                "gloss": "Fixture code",
            }
        ],
    )
    run = ReviewRun(
        id=RUN_ID,
        snapshot_id=lab.snapshot.id,
        run_type="saved",
        lifecycle="completed",
        created_at=T0,
        started_at=T0,
        finished_at=T0,
        finding_ids=[finding.id],
    )
    bundle = ReportBundle(run=run, snapshot=lab.snapshot, findings=[finding])
    # This focuses the source boundary; all ordinary report validation is covered above.
    monkeypatch.setattr(case_reads, "load", lambda *args: (bundle, Path("unused")))
    reader = case_reads.CaseReads(settings)
    page = reader.code_page(RUN_ID, finding.id, tag="E01", mode="file")
    assert page.file_line_count == source.count(b"\n")
    assert page.lines[0] == source.decode().split("\n")[0]
    exact = reader.excerpt(RUN_ID, finding.id, "E01", 0, 80)
    assert exact.lines == source.decode().split("\n")[10:14]


@pytest.mark.parametrize(
    "field,value",
    [
        ("file_line_count", 1),
        ("range_start", 1),
        ("end_line", 999),
        ("context_is_not_evidence", False),
        ("next_offset", 1),
    ],
)
def test_code_page_contract_rejects_false_ranges_or_context_authority(
    saved: tuple[Settings, ReportBundle, Path],
    field: str,
    value: int | bool,
) -> None:
    settings, bundle, _ = saved
    page = case_reads.CaseReads(settings).code_page(RUN_ID, bundle.findings[0].id, tag="E01")
    raw = page.model_dump()
    raw[field] = value
    with pytest.raises(ValueError):
        SnapshotCodePage.model_validate(raw)
