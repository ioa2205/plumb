"""Reviewer audit, concurrency, protected transport and immutable offline exports."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis.snapshot import SnapshotStore
from backend import disposition_store, saved_reports
from backend.app import create_app
from backend.case_reads import CaseReads, CaseUnavailable
from backend.contracts.cases import CaseDetail
from backend.contracts.investigation import (
    DispositionDecision,
    DispositionUpdate,
    Finding,
)
from backend.disposition_store import DispositionConflict, DispositionStore
from backend.reports import ReportBundle, render
from backend.run_reads import finding_row
from backend.settings import Settings
from backend.tests.support import ORIGIN, PORT, signed_in, visitor
from backend.tests.test_saved_reports import RUN_ID
from backend.tests.test_saved_reports import saved as saved


def intent(finding: Finding, **updates: object) -> DispositionUpdate:
    return DispositionUpdate.model_validate(
        {
            "snapshot_id": finding.snapshot_id,
            "expected_version": 0,
            "previous_disposition": "open",
            "disposition": "dismissed",
            "reason": "Reviewed bounded scope",
            "actor": "Reviewer",
            **updates,
        }
    )


def test_decision_journey_preserves_evidence_reports_and_legacy_reads(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, directory = saved
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    finding = bundle.findings[0]
    # A legacy saved report omits the new audit field. No rewrite is required.
    data = json.loads(original["report.json"])
    data.pop("disposition_history", None)
    (directory / "report.json").write_text(json.dumps(data), encoding="utf-8")
    original["report.json"] = (directory / "report.json").read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Reviewer action started inference or target execution")

    for target in (
        "backend.review.Review.__init__",
        "backend.llama_server.LlamaServer.start",
        "verification.lab._probe",
    ):
        monkeypatch.setattr(target, forbidden)
    client = signed_in(create_app(settings, port=PORT))
    base = f"/api/runs/{RUN_ID}/findings/{finding.id}"
    prior = "open"
    for version, state in enumerate(
        ("dismissed", "open", "accepted_risk", "open", "resolved", "open"), 1
    ):
        request = intent(
            finding,
            expected_version=version - 1,
            previous_disposition=prior,
            disposition=state,
            resolution_commit="a" * 40 if state == "resolved" else None,
        )
        response = client.post(
            base + "/disposition", json=request.model_dump(mode="json"), headers={"Origin": ORIGIN}
        )
        assert response.status_code == 200
        record = DispositionDecision.model_validate(response.json())
        assert record.version == version and record.previous_disposition == prior
        detail = CaseDetail.model_validate(client.get(base).json())
        assert detail.finding.disposition.value == state
        assert len(detail.disposition_history) == version
        assert detail.finding.model_dump(
            exclude={"disposition", "disposition_reason"}
        ) == finding.model_dump(exclude={"disposition", "disposition_reason"})
        assert detail.run == bundle.run and not detail.probe_runs
        assert detail.suggested_change is None
        page = client.get(f"/api/runs/{RUN_ID}/findings").json()
        assert page["findings"][0]["disposition"] == state
        assert CaseReads(settings).finding_list(RUN_ID, disposition=state).total == 1
        assert CaseReads(settings).finding_list(RUN_ID, disposition="absent").total == 0
        assert finding_row(detail.finding).disposition.value == state
        for format in ("json", "markdown", "html", "sarif"):
            exported = client.get(f"/api/runs/{RUN_ID}/current-report", params={"format": format})
            assert exported.status_code == 200 and exported.headers["cache-control"] == "no-store"
            assert "attachment" in exported.headers["content-disposition"]
            assert "Reviewed bounded scope" in exported.text and "Reviewer" in exported.text
            if format == "json":
                current = ReportBundle.model_validate(exported.json())
                assert current.findings[0] == detail.finding
                assert current.disposition_history == detail.disposition_history
                assert (
                    render(current, SnapshotStore(settings.cache_dir / "snapshots"), "json")
                    == exported.text
                )
            elif format == "sarif":
                assert (
                    exported.json()["runs"][0]["results"][0]["properties"]["finding"]["disposition"]
                    == state
                )
        assert {p.name: p.read_bytes() for p in directory.iterdir()} == original
        prior = state
    current, html = saved_reports.load(settings, RUN_ID)
    assert html == directory / "report.html"
    assert "Current reviewer decisions" in saved_reports.summary(current)
    assert (
        saved_reports.load(settings, RUN_ID, include_dispositions=False)[0].findings
        == bundle.findings
    )


def test_concurrent_apps_commit_once_and_stale_requests_refuse(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = saved
    finding = bundle.findings[0]
    stores = [DispositionStore(settings.cache_dir / "dispositions.sqlite") for _ in range(2)]

    def append(store: DispositionStore) -> str:
        try:
            store.append(finding, intent(finding))
            return "saved"
        except DispositionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, stores)) == ["conflict", "saved"]
    assert len(stores[0].history(finding)) == 1
    client = signed_in(create_app(settings, port=PORT))
    client.headers["Origin"] = ORIGIN
    path = f"/api/runs/{RUN_ID}/findings/{finding.id}/disposition"
    assert client.post(path, json=intent(finding).model_dump(mode="json")).status_code == 409
    wrong = intent(finding, snapshot_id="b" * 64)
    assert client.post(path, json=wrong.model_dump(mode="json")).status_code == 409
    assert len(stores[0].history(finding)) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"reason": " "},
        {"actor": " "},
        {"reason": "x" * 1001},
        {"actor": "x" * 101},
        {"reason": "two\nlines"},
        {"actor": "bad\x00name"},
        {"expected_version": True},
        {"expected_version": -1},
        {"disposition": "open"},
        {"disposition": "resolved"},
        {"resolution_commit": "b" * 40},
        {"disposition": "resolved", "resolution_commit": "../file"},
        {"disposition": "accepted_risk", "previous_disposition": "dismissed"},
        {"runtime_verification": "reproduced"},
        {"severity": "low"},
        {"conclusion": "rejected"},
    ],
)
def test_invalid_decision_inputs_refuse(
    updates: dict[str, object], saved: tuple[Settings, ReportBundle, Path]
) -> None:
    finding = saved[1].findings[0]
    with pytest.raises(ValidationError):
        intent(finding, **updates)
    payload = intent(finding).model_dump(mode="json") | updates
    client = signed_in(create_app(saved[0], port=PORT))
    client.headers["Origin"] = ORIGIN
    assert (
        client.post(
            f"/api/runs/{RUN_ID}/findings/{finding.id}/disposition", json=payload
        ).status_code
        == 422
    )
    assert not (saved[0].cache_dir / "dispositions.sqlite").exists()


def test_auth_origin_missing_run_finding_and_bad_report_are_refused(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, directory = saved
    finding = bundle.findings[0]
    path = f"/api/runs/{RUN_ID}/findings/{finding.id}/disposition"
    app = create_app(settings, port=PORT)
    payload = intent(finding).model_dump(mode="json")
    assert visitor(app).post(path, json=payload, headers={"Origin": ORIGIN}).status_code == 401
    assert visitor(app).get(f"/api/runs/{RUN_ID}/current-report").status_code == 401
    client = signed_in(app)
    client.headers["Origin"] = ORIGIN
    for method, url in (("post", path), ("get", f"/api/runs/{RUN_ID}/current-report")):
        response = getattr(client, method)(
            url,
            headers={"Origin": "https://foreign.invalid"},
            **({"json": payload} if method == "post" else {}),
        )
        assert response.status_code == 403
    assert client.post(path.replace(finding.id, "finding:outside"), json=payload).status_code == 404
    assert client.post(path.replace(RUN_ID, "review-" + "b" * 32), json=payload).status_code == 404
    (directory / "report.html").write_text("private-location tampered", encoding="utf-8")
    response = client.post(path, json=payload)
    assert response.status_code == 503 and "private-location" not in response.text
    assert not (settings.cache_dir / "dispositions.sqlite").exists()


@pytest.mark.parametrize(
    "failure", ["digest", "oversize", "snapshot", "run", "finding", "version", "state", "base"]
)
def test_corrupt_audit_never_becomes_current_evidence(
    saved: tuple[Settings, ReportBundle, Path], failure: str
) -> None:
    settings, bundle, _ = saved
    finding = bundle.findings[0]
    store = DispositionStore(settings.cache_dir / "dispositions.sqlite")
    record = store.append(finding, intent(finding))
    data = record.model_dump(mode="json")
    if failure == "snapshot":
        data["snapshot_id"] = "b" * 64
    if failure == "run":
        data["run_id"] = "review-" + "b" * 32
    if failure == "finding":
        data["finding_id"] = "outside"
    if failure == "version":
        data["version"] = 2
        data["expected_version"] = 1
    if failure == "state":
        data["previous_disposition"] = "accepted_risk"
        data["disposition"] = "open"
    if failure == "base":
        data["original_finding_sha256"] = "b" * 64
    payload = json.dumps(data) if failure != "oversize" else "private-input" * 1000
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("DROP TRIGGER refuse_update")
        db.execute(
            "UPDATE decisions SET payload=?,digest=?",
            (
                payload,
                "b" * 64 if failure == "digest" else hashlib.sha256(payload.encode()).hexdigest(),
            ),
        )
        db.commit()
    with pytest.raises((ValueError, sqlite3.Error)):
        store.history(finding)
    with pytest.raises(CaseUnavailable):
        CaseReads(settings).case(RUN_ID, finding.id)
    client = signed_in(create_app(settings, port=PORT))
    response = client.get(f"/api/runs/{RUN_ID}/current-report")
    assert response.status_code == 503 and "private-input" not in response.text


def test_budgets_append_only_and_failure_rollback(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved
    finding = bundle.findings[0]
    store = DispositionStore(settings.cache_dir / "dispositions.sqlite")
    first = store.append(finding, intent(finding))
    with closing(sqlite3.connect(store.path)) as db:
        for command in ("UPDATE decisions SET digest='bad'", "DELETE FROM decisions"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(command)
        db.execute(
            "CREATE TRIGGER insert_failure BEFORE INSERT ON decisions "
            "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
        db.commit()
    reopen = intent(
        finding, expected_version=1, previous_disposition="dismissed", disposition="open"
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.append(finding, reopen)
    assert store.history(finding) == [first]
    monkeypatch.setattr(disposition_store, "MAX_RUN_DECISIONS", 1)
    with pytest.raises(DispositionConflict):
        store.append(finding, reopen)
    assert store.history(finding) == [first]


def test_redaction_before_audit_persistence_and_escaped_exports(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = saved
    finding = bundle.findings[0]
    reader = CaseReads(settings)
    record = reader.update_disposition(
        RUN_ID,
        finding.id,
        intent(finding, reason="<img src=x onerror=alert(1)> token sk-" + "a" * 48),
    )
    assert "sk-" + "a" * 48 not in record.reason
    assert "sk-" + "a" * 48 not in reader.export(RUN_ID, "json")
    html = reader.export(RUN_ID, "html")
    assert "<img src=x" not in html and "&lt;img" in html


def test_missing_storage_reads_are_read_only_and_changed_baseline_refuses(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = saved
    store = DispositionStore(settings.cache_dir / "dispositions.sqlite")
    finding = bundle.findings[0]
    assert store.history(finding) == [] and not store.path.exists()
    store.append(finding, intent(finding))
    changed = finding.model_copy(update={"lede": "Different evidence assessment"})
    with pytest.raises(ValueError):
        store.history(changed)
    assert store.history(finding)


def test_projected_contract_rejects_mismatched_state_and_cross_finding(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, bundle, _ = saved
    f = bundle.findings[0]
    CaseReads(settings).update_disposition(RUN_ID, f.id, intent(f))
    detail = CaseReads(settings).case(RUN_ID, f.id)
    data = detail.model_dump(mode="json")
    data["finding"]["disposition"] = "open"
    with pytest.raises(ValidationError):
        CaseDetail.model_validate(data)
    data = detail.model_dump(mode="json")
    data["disposition_history"][0]["finding_id"] = "unrelated"
    with pytest.raises(ValidationError):
        CaseDetail.model_validate(data)
    projected = saved_reports.load(settings, RUN_ID)[0].model_dump(mode="json")
    projected["disposition_history"][0]["run_id"] = "unrelated"
    with pytest.raises(ValidationError):
        ReportBundle.model_validate(projected)


def test_linked_storage_refuses_before_writing(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved
    monkeypatch.setattr(disposition_store, "is_link", lambda status: True)
    with pytest.raises(ValueError, match="Linked"):
        DispositionStore(settings.cache_dir / "dispositions.sqlite").append(
            bundle.findings[0], intent(bundle.findings[0])
        )
    assert not (settings.cache_dir / "dispositions.sqlite").exists()


def test_storage_failure_returns_generic_refusal_without_changing_case(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved

    def refuse(*args: object, **kwargs: object) -> DispositionDecision:
        raise OSError("private-filesystem error")

    monkeypatch.setattr(DispositionStore, "append", refuse)
    client = signed_in(create_app(settings, port=PORT))
    client.headers["Origin"] = ORIGIN
    finding = bundle.findings[0]
    path = f"/api/runs/{RUN_ID}/findings/{finding.id}"
    response = client.post(path + "/disposition", json=intent(finding).model_dump(mode="json"))
    assert response.status_code == 503 and "private-filesystem" not in response.text
    assert client.get(path).json()["finding"]["disposition"] == "open"
