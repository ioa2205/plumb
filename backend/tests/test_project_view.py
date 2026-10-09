"""Frozen project navigation and policy provenance, without fresh model judgments."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.app import create_app
from backend.contracts.code import PolicyStatus
from backend.contracts.export import render as schemas
from backend.contracts.project_view import ProjectPage, ProjectRule
from backend.map_store import MapStore
from backend.policy_store import PolicyConflict, PolicyStore
from backend.project_reads import ProjectReads
from backend.reports import ReportBundle
from backend.review import Review
from backend.run_store import RunStore
from backend.settings import Settings
from backend.tests.support import ORIGIN, PORT, signed_in, visitor
from backend.tests.test_case_reads import files
from backend.tests.test_peer_api import saved_peers as saved_peers
from backend.tests.test_peer_records import recorded as recorded
from backend.tests.test_review import review as review


@pytest.fixture
def project(
    saved_peers: tuple[Settings, ReportBundle, Path], review: Review
) -> tuple[Settings, ReportBundle, Path]:
    settings, bundle, directory = saved_peers
    MapStore(settings.cache_dir / "application_maps.sqlite").save(review.map)
    RunStore(settings.cache_dir / "runs.sqlite").create(bundle.run, [])
    return settings, bundle, directory


def test_frozen_counts_paging_citations_and_read_only_navigation(
    project: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, bundle, _ = project
    before = files(settings.data_dir)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Project read started analysis, inference, execution or writes")

    for target in (
        "backend.review.Review.__init__",
        "backend.llama_server.LlamaServer.start",
        "analysis.snapshot.take_snapshot",
        "backend.policy_store.PolicyStore.confirm",
    ):
        monkeypatch.setattr(target, forbidden)
    client = signed_in(create_app(settings, port=PORT))
    base = f"/api/runs/{bundle.run.id}/project"
    rows = []
    offset = 0
    while True:
        response = client.get(base, params={"offset": offset})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        page = ProjectPage.model_validate(response.json())
        Draft202012Validator(json.loads(schemas()["ProjectPage.schema.json"])).validate(
            response.json()
        )
        assert page.included_files == len(bundle.snapshot.files)
        assert page.excluded_files == len(bundle.snapshot.excluded)
        assert page.flows_total == sum(page.frameworks.values())
        assert page.unresolved_links > 0
        assert all("candidate" in n.label for f in page.flows for n in f.guards)
        rows.extend(page.flows)
        if page.next_offset is None:
            break
        offset = page.next_offset
    assert len(rows) == page.flows_total and len({f.entry.id for f in rows}) == len(rows)
    node = rows[0].entry
    source = client.get(f"{base}/citations/{node.citation.id}")
    assert source.status_code == 200
    assert source.json()["citation"] == node.citation.model_dump(mode="json")
    assert source.json()["start_line"] == node.citation.span.start_line
    after = files(settings.data_dir)
    # SQLite may create empty WAL/shared-memory sidecars for a mode=ro WAL read.
    # Database facts, blobs and reports must stay byte-identical; no policy was written.
    sidecars = {"cache/application_maps.sqlite-wal", "cache/application_maps.sqlite-shm"}
    assert {k: v for k, v in after.items() if k not in sidecars} == before


def test_inferred_policy_confirmation_is_source_bound_persistent_and_idempotent(
    project: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, directory = project
    reads = ProjectReads(settings)
    before = files(directory)
    run_before = reads.runs.run(bundle.run.id)
    page = reads.page(bundle.run.id)
    assert page.rules and all(r.assertion.status is PolicyStatus.INFERRED for r in page.rules)
    rule = next(r for r in page.rules if r.assertion.kind == "owner")
    assert rule.sites_applying <= rule.sites_total and rule.sites_applying >= 3
    assert all(s.snapshot_id == page.snapshot_id for s in rule.assertion.evidence)
    with pytest.raises(PolicyConflict):
        reads.confirm(bundle.run.id, rule.assertion.id, "0" * 64)
    assert not reads.policies.path.exists()
    saved = reads.confirm(bundle.run.id, rule.assertion.id, rule.proposal_sha256)
    assert saved.assertion.status is PolicyStatus.CONFIRMED
    assert saved.assertion.confirmed_by == "Local reviewer" and saved.assertion.confirmed_at
    assert reads.confirm(bundle.run.id, rule.assertion.id, rule.proposal_sha256) == saved
    assert (
        next(
            r
            for r in ProjectReads(settings).page(bundle.run.id).rules
            if r.assertion.id == rule.assertion.id
        )
        == saved
    )
    assert files(directory) == before and reads.runs.run(bundle.run.id) == run_before


def test_concurrent_confirmation_keeps_one_author_and_time(
    project: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = project
    rule = ProjectReads(settings).page(bundle.run.id).rules[0]
    path = settings.cache_dir / "policies.sqlite"

    def confirm(_: int) -> ProjectRule:
        return PolicyStore(path).confirm(rule, rule.proposal_sha256)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(confirm, range(2)))
    assert first == second


def test_protected_api_refuses_stale_foreign_malformed_and_source_overreach(
    project: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = project
    app = create_app(settings, port=PORT)
    client = signed_in(app)
    base = f"/api/runs/{bundle.run.id}/project"
    page = client.get(base).json()
    rule = page["rules"][0]
    path = f"{base}/rules/{rule['assertion']['id']}/confirm"
    body = {"proposal_sha256": rule["proposal_sha256"]}
    assert visitor(app).get(base).status_code == 401
    assert client.post(path, json=body).status_code == 403
    assert (
        client.post(path, json=body, headers={"Origin": "https://foreign.invalid"}).status_code
        == 403
    )
    assert (
        client.post(path, json={**body, "author": "forged"}, headers={"Origin": ORIGIN}).status_code
        == 422
    )
    assert (
        client.post(
            path, json={"proposal_sha256": "0" * 64}, headers={"Origin": ORIGIN}
        ).status_code
        == 409
    )
    assert (
        client.post(
            path.replace(rule["assertion"]["id"], "policy:foreign"),
            json=body,
            headers={"Origin": ORIGIN},
        ).status_code
        == 404
    )
    assert client.post(path, json=body, headers={"Origin": ORIGIN}).status_code == 200
    assert client.get(base, params={"offset": -1}).status_code == 422
    assert client.get(f"{base}/citations/cite:foreign").status_code == 404
    assert (
        client.get(
            f"{base}/citations/{page['flows'][0]['entry']['citation']['id']}",
            params={"offset": 1_000_000},
        ).status_code
        == 404
    )


def test_missing_peer_records_do_not_infer_from_static_candidates_or_names(
    project: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, bundle, _ = project
    reads = ProjectReads(settings)
    monkeypatch.setattr(
        reads.cases, "_bundle", lambda _: bundle.model_copy(update={"peer_comparisons": []})
    )
    page = reads.page(bundle.run.id)
    assert page.flows and not page.rules and page.rules_total == 0


@pytest.mark.parametrize("fault", ["map_hash", "snapshot_blob", "policy_payload"])
def test_corrupt_frozen_records_fail_closed_without_private_error_details(
    project: tuple[Settings, ReportBundle, Path],
    fault: str,
) -> None:
    settings, bundle, _ = project
    reads = ProjectReads(settings)
    page = reads.page(bundle.run.id)
    if fault == "map_hash":
        graph = reads.maps.load(page.snapshot_id)
        assert graph is not None
        raw = graph.model_dump(mode="json")
        raw["entries"][0]["span"]["content_sha256"] = "0" * 64
        with sqlite3.connect(reads.maps.path) as db:
            db.execute("UPDATE maps SET payload=?", (json.dumps(raw),))
    elif fault == "snapshot_blob":
        file = next(
            f for f in bundle.snapshot.files if f.path == page.flows[0].entry.citation.span.path
        )
        path = reads._context(bundle.run.id)[2].blobs._path(file.sha256)
        path.write_text("private corrupted source", encoding="utf-8")
    else:
        rule = page.rules[0]
        reads.confirm(bundle.run.id, rule.assertion.id, rule.proposal_sha256)
        with sqlite3.connect(reads.policies.path) as db:
            db.execute("UPDATE policies SET payload=?", ('{"private": "path"}',))
    response = signed_in(create_app(settings, port=PORT)).get(f"/api/runs/{bundle.run.id}/project")
    assert response.status_code == 503
    assert "private" not in response.text and str(settings.data_dir) not in response.text
