"""Saved software reviews: comparison semantics and hostile boundary checks, no model."""

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from agent.tests.test_validator import DAL_TS, ORDERS_PY, T0, Lab
from backend.app import create_app
from backend.case_reads import CaseReads
from backend.contracts.application_map import ApplicationMap
from backend.contracts.cases import CaseDetail
from backend.contracts.investigation import DispositionUpdate, Question, QuestionStatus
from backend.contracts.peers import PeerComparison
from backend.contracts.run_history import GROUPS, RunComparison
from backend.contracts.runs import Coverage, ReviewRun
from backend.reports import ReportBundle, render
from backend.run_reads import RunReads, compare_rows, policy_drift, question_keys
from backend.run_store import RunStore
from backend.settings import Settings
from backend.tests.support import PORT, signed_in, visitor

BEFORE = "review-" + "b" * 32
AFTER = "review-" + "c" * 32


def recorded_pair(root: Path) -> tuple[Settings, ReportBundle, ReportBundle]:
    lab = Lab(root / "source")
    settings = Settings(data_dir=root / "data")
    shutil.copytree(lab.store.directory, settings.cache_dir / "snapshots")
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    rejected = lab.rejected()
    old = [
        lab.finding(
            id="finding:old-resolved",
            display_id="F-01",
            run_id=BEFORE,
            conclusion="candidate",
            exhibits=rejected.exhibits,
            question_ids=["q:old-resolved"],
        ),
        lab.finding(
            id="finding:old-present",
            display_id="F-02",
            run_id=BEFORE,
            question_ids=["q:old-present"],
        ),
        lab.finding(
            id="finding:old-unknown",
            display_id="F-03",
            run_id=BEFORE,
            conclusion="candidate",
            question_ids=["q:old-unknown"],
        ),
    ]
    new = [
        rejected.model_copy(
            update={
                "id": "finding:new-resolved",
                "display_id": "F-01",
                "run_id": AFTER,
                "question_ids": ["q:new-resolved"],
            }
        ),
        lab.finding(
            id="finding:new-present",
            display_id="F-02",
            run_id=AFTER,
            question_ids=["q:new-present"],
        ),
        lab.finding(
            id="finding:new-new",
            display_id="F-03",
            run_id=AFTER,
            conclusion="candidate",
            family="injection",
            cwe=[89],
            question_ids=["q:new-new"],
        ),
    ]
    packets = {
        "resolved": lab.span(ORDERS_PY, 16, 21),
        "present": lab.span(ORDERS_PY, 10, 13),
        "unknown": lab.span(ORDERS_PY, 1, 2),
        "new": lab.span(DAL_TS, 1, 5),
    }
    bundles = []
    for run_id, findings, names, hour in (
        (BEFORE, old, ["resolved", "present", "unknown"], 0),
        (AFTER, new, ["resolved", "present", "unknown", "new"], 1),
    ):
        run = ReviewRun(
            id=run_id,
            snapshot_id=lab.snapshot.id,
            run_type="replay",
            lifecycle="completed",
            created_at=T0 + timedelta(hours=hour),
            started_at=T0 + timedelta(hours=hour),
            finished_at=T0 + timedelta(hours=hour, seconds=30),
            finding_ids=[f.id for f in findings],
            coverage=Coverage(total=len(names), completed=3, excluded=hour),
        )
        questions = [
            Question(
                id=f"q:{'old' if hour == 0 else 'new'}-{name}",
                run_id=run_id,
                type="sink_safety" if name == "new" else "intentional_exception",
                family="injection" if name == "new" else "authorization",
                stage="record",
                status="excluded" if hour and name == "unknown" else "answered",
                subject_ids=[f"unit:{name}"],
                evidence=[packets[name]],
                answer=None if hour and name == "unknown" else {"software_fixture": True},
            )
            for name in names
        ]
        runs.create(run, questions)
        bundle = ReportBundle(
            run=run,
            snapshot=lab.snapshot,
            findings=findings,
            guards=[
                lab.owner_guard().model_copy(
                    update={"subject": "user.id", "object": "order.customer_id"}
                )
            ],
            limitations=["Explicit software replay; no real judgment or runtime fix."],
        )
        folder = settings.data_dir / "reviews" / run_id
        folder.mkdir(parents=True)
        for extension, kind in (("json", "json"), ("html", "html")):
            (folder / f"report.{extension}").write_text(
                render(bundle, lab.store, kind), encoding="utf-8", newline="\n"
            )
        bundles.append(bundle)
    return settings, bundles[0], bundles[1]


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Settings, ReportBundle, ReportBundle]:
    return recorded_pair(tmp_path)


def test_reviewer_resolution_changes_rows_without_changing_comparison_groups(
    pair: tuple[Settings, ReportBundle, ReportBundle],
) -> None:
    settings, _before, after = pair
    original = RunReads(settings).comparison(BEFORE, AFTER, "still_present")
    finding = after.findings[1]
    CaseReads(settings).update_disposition(
        AFTER,
        finding.id,
        DispositionUpdate(
            snapshot_id=finding.snapshot_id,
            expected_version=0,
            previous_disposition="open",
            disposition="resolved",
            reason="Linked source commit reviewed",
            actor="Reviewer",
            resolution_commit="a" * 40,
        ),
    )
    current = RunReads(settings).comparison(BEFORE, AFTER, "still_present")
    assert current.counts == original.counts
    assert current.after == original.after and current.before == original.before
    assert current.rows[0].after is not None
    assert current.rows[0].after.disposition.value == "resolved"
    assert current.rows[0].after.conclusion == finding.conclusion
    assert current.rows[0].after.runtime_verification == finding.runtime_verification


def test_actual_saved_boundaries_and_four_honest_groups(
    pair: tuple[Settings, ReportBundle, ReportBundle], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, before, after = pair
    assert RunReads(settings).comparison(BEFORE, AFTER).counts == dict.fromkeys(GROUPS, 1)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("History started analysis, inference or a write")

    monkeypatch.setattr("backend.llama_server.LlamaServer.start", forbidden)
    monkeypatch.setattr("backend.review.Review.__init__", forbidden)
    monkeypatch.setattr("backend.run_store.RunStore.create", forbidden)
    app = create_app(settings, port=PORT)
    assert visitor(app).get("/api/runs").status_code == 401
    client = signed_in(app)
    history = client.get("/api/runs")
    assert history.status_code == 200 and history.headers["cache-control"] == "no-store"
    assert [r["id"] for r in history.json()["runs"]] == [AFTER, BEFORE]
    for group in GROUPS:
        page = RunComparison.model_validate(
            client.get(
                f"/api/runs/{AFTER}/compare", params={"before": BEFORE, "group": group}
            ).json()
        )
        assert page.counts == dict.fromkeys(GROUPS, 1)
        assert len(page.rows) == 1 and page.rows[0].group == group
        assert page.policies == [] and page.before == before.run and page.after == after.run
    assert client.get("/api/runs", headers={"Origin": "http://foreign.invalid"}).status_code == 403
    assert client.get("/api/runs", params={"offset": -1}).status_code == 422
    assert (
        client.get(
            f"/api/runs/{AFTER}/compare", params={"before": BEFORE, "group": "fixed"}
        ).status_code
        == 422
    )


def test_missing_failed_and_ambiguous_judgments_never_establish_absence(
    pair: tuple[Settings, ReportBundle, ReportBundle],
) -> None:
    settings, before, after = pair
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    left, right = runs.questions(BEFORE), runs.questions(AFTER)
    for status in (
        QuestionStatus.PENDING,
        QuestionStatus.FAILED,
        QuestionStatus.REJECTED_BY_VALIDATOR,
    ):
        altered = [
            q.model_copy(update={"status": status, "answer": None})
            if q.id == "q:new-resolved"
            else q
            for q in right
        ]
        rows = compare_rows(before, after, left, altered, None, None)
        assert not any(row.group == "no_longer_observed" for row in rows)
    rows = compare_rows(before, after, [], right, None, None)
    assert sum(r.group == "not_reviewed" for r in rows) == 3
    duplicate = right[0].model_copy(update={"id": "q:duplicate"})
    assert not any(
        r.group == "no_longer_observed"
        for r in compare_rows(before, after, left, [*right, duplicate], None, None)
    )


def test_history_paging_and_empty_first_install_are_read_only(
    pair: tuple[Settings, ReportBundle, ReportBundle], tmp_path: Path
) -> None:
    settings, before, _ = pair
    missing = Settings(data_dir=tmp_path / "empty")
    assert RunReads(missing).history().total == 0 and not missing.data_dir.exists()
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    for i in range(21):
        runs.create(before.run.model_copy(update={"id": f"saved:{i}", "finding_ids": []}), [])
    history = RunReads(settings).history()
    assert len(history.runs) == 20 and history.total == 23 and history.next_offset == 20
    final = RunReads(settings).history(20)
    assert len(final.runs) == 3 and final.next_offset is None


def test_corrupt_identity_report_source_and_checkpoint_refuse_without_private_details(
    pair: tuple[Settings, ReportBundle, ReportBundle],
) -> None:
    settings, _, _ = pair
    client = signed_in(create_app(settings, port=PORT))
    for earlier, later in ((AFTER, AFTER), (AFTER, BEFORE), ("missing", AFTER)):
        response = client.get(f"/api/runs/{later}/compare", params={"before": earlier})
        assert response.status_code == 503 and str(settings.data_dir) not in response.text
    db_path = settings.cache_dir / "runs.sqlite"
    with sqlite3.connect(db_path) as db:
        row = json.loads(db.execute("SELECT payload FROM runs WHERE id=?", (AFTER,)).fetchone()[0])
        row["id"] = "private-secret"
        db.execute("UPDATE runs SET payload=? WHERE id=?", (json.dumps(row), AFTER))
    assert client.get("/api/runs").status_code == 503
    assert client.get(f"/api/runs/{AFTER}/compare", params={"before": BEFORE}).status_code == 503


def test_saved_peer_counts_retain_cohorts_and_never_merge_conflicting_records() -> None:
    case = CaseDetail.model_validate_json(
        (
            Path(__file__).resolve().parents[2]
            / "frontend/scripts/fixtures/archived-peer-case.json"
        ).read_bytes()
    )
    assert isinstance(case.peer_comparison, PeerComparison)
    peer = case.peer_comparison

    @dataclass
    class Observations:
        peer_comparisons: list[PeerComparison]

    saved = Observations([peer])
    drift = policy_drift(saved, saved)
    owner = next(d for d in drift if d.kind == "owner")
    assert owner.before and owner.after and owner.before.applying == 10 and owner.before.total == 11
    assert owner.before == owner.after and not owner.cohort_changed
    absent = policy_drift(saved, Observations([]))
    assert all(d.after is None and d.cohort_changed for d in absent)
    raw = peer.model_dump(mode="json")
    # A separately valid cohort containing only the guarded voters must not be
    # combined with the original group or appear to be the same denominator.
    guarded = [r for r in raw["rows"] if any(g["kind"] == "owner" for g in r["guards"])]
    raw["rows"] = guarded
    raw["subject_site_id"] = guarded[0]["site"]["id"]
    raw["group"]["site_ids"] = [r["site"]["id"] for r in guarded]
    raw["group"]["excluded"] = []
    raw["group"]["deviations"] = []
    for column in raw["group"]["columns"]:
        column["applied_site_ids"] = [
            i for i in column["applied_site_ids"] if i in raw["group"]["site_ids"]
        ]
    changed = PeerComparison.model_validate(raw)
    assert all(d.cohort_changed for d in policy_drift(saved, Observations([changed])))
    assert policy_drift(Observations([peer, changed]), Observations([])) == []


def test_unique_mapped_units_survive_changed_ids_but_repeated_operations_stay_unknown(
    tmp_path: Path,
) -> None:
    lab = Lab(tmp_path)
    span = lab.span(ORDERS_PY, 16, 21)

    def graph(tag: str, repeated: bool = False) -> ApplicationMap:
        site = {
            "id": f"site:{tag}",
            "snapshot_id": lab.snapshot.id,
            "entry_point_id": f"entry:{tag}",
            "resource": "Order",
            "operation": "read",
            "key_origin": "path",
            "data_layer": "sqlalchemy",
            "span": span,
        }
        return ApplicationMap.model_validate(
            {
                "snapshot_id": lab.snapshot.id,
                "entries": [
                    {
                        "id": f"entry:{tag}",
                        "snapshot_id": lab.snapshot.id,
                        "kind": "http_route",
                        "framework": "fastapi",
                        "method": "GET",
                        "route": "/orders/{id}/invoice",
                        "handler_symbol_id": f"symbol:{tag}",
                        "span": span,
                    }
                ],
                "symbols": [
                    {
                        "id": f"symbol:{tag}",
                        "snapshot_id": lab.snapshot.id,
                        "kind": "function",
                        "name": "invoice",
                        "qualified_name": "invoice",
                        "language": "python",
                        "span": span,
                    }
                ],
                "access_sites": [site, *([{**site, "id": "site:repeated"}] if repeated else [])],
                "guards": [],
                "links": [],
                "unknown_targets": [],
            }
        )

    def question(tag: str) -> Question:
        return Question(
            id=f"q:{tag}",
            run_id=BEFORE,
            type="intentional_exception",
            family="authorization",
            stage="frame",
            status="pending",
            subject_ids=[f"site:{tag}"],
            evidence=[span],
        )

    old = question_keys([question("old")], graph("old"))["q:old"]
    assert old == question_keys([question("new")], graph("new"))["q:new"]
    assert old != question_keys([question("new")], graph("new", True))["q:new"]
