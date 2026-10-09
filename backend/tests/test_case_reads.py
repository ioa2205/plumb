"""Saved case API boundaries, including real snapshot reads and hostile substitutions."""

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import SecretStr, ValidationError

from analysis.snapshot import SnapshotStore
from backend import case_reads
from backend.app import create_app
from backend.contracts import READ_CONTRACTS
from backend.contracts.cases import CaseDetail, CitedExcerpt, FindingPage
from backend.contracts.export import render as schemas
from backend.contracts.investigation import ExhibitRole, RuntimeVerification
from backend.contracts.verification import ProbeOutcome, SnapshotRole
from backend.reports import ReportBundle, render
from backend.settings import Settings
from backend.tests.contract_examples import probe_run, steps, suggested_change
from backend.tests.support import PORT, signed_in, visitor
from backend.tests.test_saved_reports import RUN_ID
from backend.tests.test_saved_reports import saved as saved


def files(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_saved_case_and_excerpt_are_exact_read_only_projections(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved
    before = files(settings.data_dir)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Saved API started analysis, execution, model, browser or writes")

    for target in (
        "backend.review.Review.__init__",
        "backend.llama_server.LlamaServer.start",
        "backend.run_store.RunStore.create",
        "backend.saved_reports.launch",
        "analysis.snapshot.SnapshotStore.save",
        "analysis.snapshot.BlobStore.put",
    ):
        monkeypatch.setattr(target, forbidden)
    app = create_app(settings, port=PORT)
    path = f"/api/runs/{RUN_ID}/findings"
    assert visitor(app).get(path).status_code == 401
    client = signed_in(app)
    page = FindingPage.model_validate(client.get(path, params={"limit": 1}).json())
    assert page.run == bundle.run and page.findings == bundle.findings
    assert page.total == 1 and page.next_offset is None
    empty = client.get(path, params={"offset": 999}).json()
    assert empty["findings"] == [] and empty["total"] == 1 and empty["next_offset"] is None
    case_path = f"{path}/{bundle.findings[0].id}"
    detail = CaseDetail.model_validate(client.get(case_path).json())
    assert detail.finding == bundle.findings[0] and detail.peer_comparison == "not_recorded"
    assert client.get(f"{case_path}/peers/absent/citations/0").status_code == 404
    assert detail.probe_runs == [] and detail.suggested_change is None
    assert "Static support does not establish runtime reproduction." in detail.limitations
    excerpt = CitedExcerpt.model_validate(
        client.get(f"{case_path}/exhibits/E01", params={"lines": 2}).json()
    )
    span = bundle.findings[0].exhibits[0].span
    original = SnapshotStore(settings.cache_dir / "snapshots").read(bundle.snapshot, span.path)
    assert (
        excerpt.lines == original.decode().splitlines()[span.start_line - 1 : span.start_line + 1]
    )
    assert excerpt.exhibit.span == span and excerpt.next_offset == 2
    last = client.get(f"{case_path}/exhibits/E01", params={"offset": 2}).json()
    assert last["start_line"] == span.start_line + 2 and last["next_offset"] is None
    assert files(settings.data_dir) == before
    examples = {FindingPage: page, CaseDetail: detail, CitedExcerpt: excerpt}
    assert set(examples).issubset(READ_CONTRACTS)
    for kind, example in examples.items():
        schema = json.loads(schemas()[f"{kind.__name__}.schema.json"])
        Draft202012Validator.check_schema(schema)
        assert not list(Draft202012Validator(schema).iter_errors(example.model_dump(mode="json")))


@pytest.mark.parametrize("tail", ["", "/finding:1", "/finding:1/exhibits/E01"])
def test_case_routes_reject_foreign_origin_and_require_session(
    saved: tuple[Settings, ReportBundle, Path], tail: str
) -> None:
    app = create_app(saved[0], port=PORT)
    path = f"/api/runs/{RUN_ID}/findings{tail}"
    assert visitor(app).get(path).status_code == 401
    client = signed_in(app)
    response = client.get(path, headers={"Origin": "https://foreign.invalid"})
    assert response.status_code == 403 and "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    ("tail", "params", "status"),
    [
        ("", {"limit": 21}, 422),
        ("", {"offset": -1}, 422),
        ("", {"limit": 0}, 422),
        ("/finding:outside", {}, 404),
        ("/finding:1/exhibits/E99", {}, 404),
        ("/finding:1/exhibits/E01", {"lines": 81}, 422),
        ("/finding:1/exhibits/E01", {"offset": 1_000_001}, 422),
        ("/finding:1/exhibits/E01", {"offset": 999}, 503),
    ],
)
def test_invalid_pages_and_uncited_records_are_refused(
    saved: tuple[Settings, ReportBundle, Path], tail: str, params: dict[str, int], status: int
) -> None:
    client = signed_in(create_app(saved[0], port=PORT))
    response = client.get(f"/api/runs/{RUN_ID}/findings{tail}", params=params)
    assert response.status_code == status
    assert str(saved[0].data_dir) not in response.text


@pytest.mark.parametrize("failure", ["json", "html", "run", "span", "blob", "path", "size"])
def test_corruption_substitution_and_oversize_never_return_source_or_private_errors(
    saved: tuple[Settings, ReportBundle, Path], failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, directory = saved
    if failure in {"json", "html"}:
        (directory / f"report.{failure}").write_text("private-fixture corrupt", encoding="utf-8")
    elif failure == "blob":
        entry = next(
            f for f in bundle.snapshot.files if f.path == bundle.findings[0].exhibits[0].span.path
        )
        path = SnapshotStore(settings.cache_dir / "snapshots").blobs._path(entry.sha256)
        path.write_bytes(b"private-fixture corrupt")
    elif failure == "size":
        monkeypatch.setattr(case_reads, "MAX_CASE_BYTES", 20)
    else:
        data = json.loads((directory / "report.json").read_text())
        if failure == "run":
            data["run"]["id"] = "review-" + "b" * 32
            data["findings"][0]["run_id"] = data["run"]["id"]
        elif failure == "span":
            data["findings"][0]["exhibits"][0]["span"]["content_sha256"] = "b" * 64
        else:
            data["findings"][0]["exhibits"][0]["span"]["path"] = "../private-fixture"
        (directory / "report.json").write_text(json.dumps(data), encoding="utf-8")
    client = signed_in(create_app(settings, port=PORT))
    response = client.get(f"/api/runs/{RUN_ID}/findings/{bundle.findings[0].id}/exhibits/E01")
    assert response.status_code == 503
    assert "private-fixture" not in response.text and str(directory) not in response.text


def test_request_scoped_redaction_and_comments_preserve_span_and_lines(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    original_settings, bundle, directory = saved
    settings = original_settings.model_copy(update={"redaction_secrets": (SecretStr("order_id"),)})
    store = SnapshotStore(settings.cache_dir / "snapshots")
    for name, kind in (("report.json", "json"), ("report.html", "html")):
        (directory / name).write_text(
            render(bundle, store, kind, secrets=("order_id",)), encoding="utf-8", newline="\n"
        )
    reader = case_reads.CaseReads(settings)
    excerpt = reader.excerpt(RUN_ID, bundle.findings[0].id, "E01", 0, 80)
    assert "order_id" not in "\n".join(excerpt.lines) and "[REDACTED]" in "\n".join(excerpt.lines)
    assert excerpt.exhibit.span == bundle.findings[0].exhibits[0].span
    assert excerpt.text_is_redacted and excerpt.comments_are_not_evidence


def test_developer_note_cannot_be_read_as_evidence(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved
    bundle.findings[0].exhibits[0] = (
        bundle.findings[0].exhibits[0].model_copy(update={"role": ExhibitRole.DEVELOPER_NOTE})
    )
    monkeypatch.setattr(case_reads, "load", lambda *args: (bundle, Path("unused")))
    with pytest.raises(case_reads.CaseUnavailable, match="Developer notes"):
        case_reads.CaseReads(settings).excerpt(RUN_ID, bundle.findings[0].id, "E01", 0, 80)


def test_projection_invariants_reject_cross_run_and_forged_proof(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = saved
    reader = case_reads.CaseReads(settings)
    detail = reader.case(RUN_ID, bundle.findings[0].id)
    bad = detail.model_dump()
    bad["finding"]["run_id"] = "other"
    with pytest.raises(ValidationError, match="recorded run"):
        CaseDetail.model_validate(bad)
    bad = detail.model_dump()
    bad["finding"]["probe_run_ids"] = ["not-recorded"]
    with pytest.raises(ValidationError, match="proof records"):
        CaseDetail.model_validate(bad)
    page = reader.page(RUN_ID, 0, 1).model_dump()
    page["next_offset"] = 0
    with pytest.raises(ValidationError, match="continuation"):
        FindingPage.model_validate(page)
    excerpt = reader.excerpt(RUN_ID, bundle.findings[0].id, "E01", 0, 2).model_dump()
    excerpt["end_line"] += 1
    with pytest.raises(ValidationError, match="numbered page"):
        CitedExcerpt.model_validate(excerpt)


def test_case_includes_original_and_patched_proof_without_mixing_findings(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, directory = saved
    finding = bundle.findings[0].model_copy(
        update={
            "probe_run_ids": ["probe:1"],
            "suggested_change_id": "change:1",
            "runtime_verification": RuntimeVerification.REPRODUCED,
        }
    )
    before = probe_run().model_copy(update={"snapshot_id": bundle.snapshot.id})
    after = before.model_copy(
        update={
            "id": "probe:2",
            "snapshot_id": "b" * 64,
            "snapshot_role": SnapshotRole.PATCHED,
            "steps": steps(404, False),
            "outcome": ProbeOutcome.FIXED,
        }
    )
    change = suggested_change()
    bundle = ReportBundle.model_validate(
        {
            **bundle.model_dump(),
            "findings": [finding.model_dump()],
            "probe_runs": [before.model_dump(), after.model_dump()],
            "suggested_changes": [change.model_dump()],
        }
    )
    store = SnapshotStore(settings.cache_dir / "snapshots")
    for name, kind in (("report.json", "json"), ("report.html", "html")):
        (directory / name).write_text(render(bundle, store, kind), encoding="utf-8", newline="\n")
    detail = case_reads.CaseReads(settings).case(RUN_ID, finding.id)
    assert [p.outcome.value for p in detail.probe_runs] == ["reproduced", "fixed"]
    assert [p.snapshot_id for p in detail.probe_runs] == [bundle.snapshot.id, "b" * 64]
    assert detail.suggested_change == change
