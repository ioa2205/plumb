"""Saved peer projection boundaries; fixture judgments are not fresh model evidence."""

import pytest
from pydantic import JsonValue

from backend.contracts.code import GuardKind
from backend.contracts.peers import PeerComparison
from backend.contracts.runs import RunLifecycle
from backend.peer_records import comparison
from backend.reports import ReportBundle, render
from backend.review import Review, Workflow, export
from backend.tests.test_review import Model, queued
from backend.tests.test_review import review as review


@pytest.fixture(scope="module")
def recorded(review: Review, tmp_path_factory: pytest.TempPathFactory) -> ReportBundle:
    folder = tmp_path_factory.mktemp("saved-peers")
    runs = queued(review, folder)
    assert (
        Workflow(review, runs, "run:test", Model(), folder / "guards.sqlite", "fixture", 2)
        .run()
        .lifecycle
        is RunLifecycle.COMPLETED
    )
    return export(review, runs, "run:test", folder / "reports")


def test_full_group_is_retained_with_distinct_subject_excluding_counts(
    recorded: ReportBundle,
) -> None:
    assert len(recorded.peer_comparisons) == 2
    for peer in recorded.peer_comparisons:
        voters = [r for r in peer.rows if r.exclusion is None]
        for deviation in peer.group.deviations:
            assert deviation.peers_total == len(voters) - 1
            column = next(c for c in peer.group.columns if c.key == deviation.missing)
            assert deviation.peers_applying == len(column.applied_site_ids)
            assert deviation.site_id not in column.applied_site_ids


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "extra",
        "snapshot",
        "resource",
        "entry",
        "unconfirmed",
        "optimistic",
        "column",
        "exclusion",
        "denominator",
        "deviation",
    ],
)
def test_malformed_membership_and_math_are_refused(recorded: ReportBundle, mutation: str) -> None:
    raw = recorded.peer_comparisons[0].model_dump(mode="json")
    guarded = next(row for row in raw["rows"] if row["guards"])
    if mutation == "duplicate":
        raw["rows"].append(raw["rows"][0])
    elif mutation == "missing":
        raw["rows"].pop()
    elif mutation == "extra":
        raw["group"]["site_ids"].append("site:invented")
    elif mutation == "snapshot":
        raw["rows"][0]["site"]["snapshot_id"] = "0" * 64
    elif mutation == "resource":
        raw["rows"][0]["site"]["resource"] = "different"
    elif mutation == "entry":
        raw["rows"][0]["entry"]["id"] = "entry:different"
    elif mutation == "unconfirmed":
        guarded["guards"][0]["confirmed"] = False
    elif mutation == "optimistic":
        guarded["guards"][0]["mechanism"] = "proxy_matcher"
    elif mutation == "column":
        raw["group"]["columns"][0]["applied_site_ids"].append(
            raw["group"]["columns"][0]["applied_site_ids"][0]
        )
    elif mutation == "exclusion":
        raw["rows"][0]["exclusion"] = "public because the name says so"
        raw["rows"][0]["evidence"] = []
    elif mutation == "denominator":
        raw["group"]["deviations"][0]["peers_total"] += 1
    else:
        raw["group"]["deviations"] = []
    with pytest.raises(ValueError):
        PeerComparison.model_validate(raw)


def test_universally_absent_guards_cannot_manufacture_a_flag(recorded: ReportBundle) -> None:
    raw = recorded.peer_comparisons[0].model_dump(mode="json")
    for row in raw["rows"]:
        row["guards"] = []
    raw["group"].update(columns=[], deviations=[])
    peer = PeerComparison.model_validate(raw)
    assert not peer.group.columns and not peer.group.deviations
    raw["group"]["columns"] = [
        {"key": "owner", "label": "owner", "applied_site_ids": raw["group"]["site_ids"]}
    ]
    with pytest.raises(ValueError):
        PeerComparison.model_validate(raw)


@pytest.mark.parametrize(
    "mutation", ["finding", "question", "group", "duplicate", "hash", "guard_kind"]
)
def test_report_boundary_revalidates_peer_links_and_real_source(
    recorded: ReportBundle, review: Review, mutation: str
) -> None:
    peer = recorded.peer_comparisons[0]
    raw = recorded.model_dump(mode="json")
    changed = raw["peer_comparisons"][0]
    if mutation == "finding":
        changed["finding_id"] = "finding:absent"
    elif mutation == "question":
        changed["question_id"] = "question:absent"
    elif mutation == "group":
        changed["group"]["id"] = "group:absent"
    elif mutation == "duplicate":
        raw["peer_comparisons"].append(changed)
    elif mutation == "hash":
        changed["rows"][0]["site"]["span"]["content_sha256"] = "0" * 64
    else:
        guard = next(
            g
            for row in changed["rows"]
            for g in row["guards"]
            if g["kind"] == GuardKind.OWNER.value
        )
        for row in changed["rows"]:
            for observed in row["guards"]:
                if observed["id"] == guard["id"]:
                    observed["subject"] = "invented.principal"
    # model_copy exercises boundary revalidation rather than constructor alone.
    invalid = recorded.model_copy(
        update={
            "peer_comparisons": [PeerComparison.model_validate(p) for p in raw["peer_comparisons"]]
        }
    )
    with pytest.raises(ValueError):
        render(invalid, review.store, "json")
    assert recorded.peer_comparisons[0] == peer


def test_optional_checkpoint_metadata_is_all_or_nothing() -> None:
    assert comparison({}, "finding:test", "site:test", "question:test") is None
    with pytest.raises(ValueError, match="incomplete"):
        comparison({"peer_result": {}}, "finding:test", "site:test", "question:test")


def test_redaction_cannot_silently_change_site_identity(
    recorded: ReportBundle, review: Review
) -> None:
    site_id = recorded.peer_comparisons[0].subject_site_id
    with pytest.raises(ValueError, match="citation identity"):
        render(recorded, review.store, "json", secrets=[site_id])


def test_checkpoint_association_refuses_another_subject(recorded: ReportBundle) -> None:
    # Refuse the mismatched challenge before constructing rows from its metadata.
    answer: dict[str, JsonValue] = {
        "peer_result": {
            "snapshot_id": recorded.snapshot.id,
            "groups": [],
            "checks": [],
            "limitations": [],
        },
        "peer_access": {},
        "peer_entries": [],
        "result": {"site_id": "site:other", "snapshot_id": recorded.snapshot.id},
    }
    with pytest.raises(ValueError, match="challenge subject"):
        comparison(answer, "finding:test", "site:test", "question:test")


@pytest.mark.parametrize("format", ["json", "sarif"])
def test_machine_exports_preserve_exact_recorded_peer_rows(
    recorded: ReportBundle, review: Review, format: str
) -> None:
    import json

    output = json.loads(render(recorded, review.store, format))  # ty: ignore[invalid-argument-type]
    saved = output if format == "json" else output["runs"][0]["properties"]["plumbReport"]
    assert [
        PeerComparison.model_validate(p) for p in saved["peer_comparisons"]
    ] == recorded.peer_comparisons
