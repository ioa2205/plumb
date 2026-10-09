"""CLI workflow integration; fixture judgments are not model-accuracy evidence."""

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import JsonValue

from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.peers import PeerResult
from agent.tests.test_challenge import Judge
from agent.tests.test_peers import PredicateStub
from analysis.access import AccessMap
from analysis.fastapi import FastAPIRoute
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.cli import main
from backend.contracts.code import EntryPoint
from backend.contracts.common import Family
from backend.contracts.investigation import Finding, Question, QuestionStage, QuestionStatus
from backend.contracts.runs import ReviewRun, RunLifecycle, RunType
from backend.jobs import Engine, Step
from backend.review import Review, Workflow, export
from backend.run_store import RunStore
from backend.settings import Settings

ROUTES = ["/orders/{order_id}/receipt", "/orders/{order_id}/invoice"]


class Model:
    def __init__(self, *, invalid_menu: bool = False) -> None:
        self.invalid_menu = invalid_menu
        self.requests: list[ModelRequest] = []

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.requests.append(request)
        if request.name == "gather":
            choices = request.schema["properties"]["look"]["enum"]
            choice = "execute_shell" if self.invalid_menu else choices[0]
            return JsonAnswer({"look": choice}, "", 1, 1, 0)
        if request.name == "intentional_exception":
            return Judge(["none_found"]).ask(request, spend)
        kinds = request.schema["properties"]["guards"]["items"]["properties"]["kind"]["enum"]
        if len(kinds) == 6:
            return Judge(["scoped_elsewhere"]).ask(request, spend)
        return PredicateStub().ask(request, spend)


@pytest.fixture(scope="module")
def review(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Review]:
    settings = Settings(data_dir=tmp_path_factory.mktemp("review-data"))
    snapshot = take_snapshot(
        Path(__file__).resolve().parents[2] / "labs/tandir",
        SnapshotStore(settings.cache_dir / "snapshots"),
    )
    context = Review(settings, snapshot.id)
    try:
        yield context
    finally:
        context.close()


def queued(review: Review, tmp_path: Path) -> RunStore:
    runs = RunStore(tmp_path / "runs.sqlite")
    questions, coverage, exclusions = review.questions("run:test", ["Order"], ROUTES)
    assert len(questions) == 2
    assert coverage.total == len(review.access.accesses)
    assert coverage.excluded == len(exclusions)
    runs.create(
        ReviewRun(
            id="run:test",
            snapshot_id=review.snapshot.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.QUEUED,
            created_at=datetime.now(UTC),
            coverage=coverage,
        ),
        questions,
    )
    return runs


def test_review_pauses_resumes_and_exports_real_snapshot(review: Review, tmp_path: Path) -> None:
    runs = queued(review, tmp_path)
    first = Workflow(
        review, runs, "run:test", Model(), tmp_path / "guards.sqlite", "test labels", 1
    )
    result = first.run()
    assert result.lifecycle is RunLifecycle.PAUSED
    assert result.coverage.completed == result.coverage.pending == 1
    partial = export(review, runs, "run:test", tmp_path / "partial")
    assert len(partial.findings) == 1
    second = Workflow(
        review, runs, "run:test", Model(), tmp_path / "guards.sqlite", "test labels", 1
    )
    assert second.run().lifecycle is RunLifecycle.COMPLETED
    bundle = export(review, runs, "run:test", tmp_path / "complete")
    by_route = {}
    for q in runs.questions("run:test"):
        path = next(p for p in review.access.accesses if p.site.id == q.subject_ids[0])
        assert q.answer is not None
        by_route[review.routes[path.site.entry_point_id].entry.route] = Finding.model_validate(
            q.answer["finding"]
        ).conclusion.value
    assert by_route == {ROUTES[0]: "supported", ROUTES[1]: "rejected"}
    assert len(bundle.findings) == 2
    supported = next(f for f in bundle.findings if f.conclusion.value == "supported")
    rejected = next(f for f in bundle.findings if f.conclusion.value == "rejected")
    assert (
        supported.severity.value == "medium"
        and "principal/tenant-scoped" in supported.severity_rationale
    )
    assert "Evidence: E" in supported.severity_rationale
    assert rejected.severity.value == "unknown" and "rejected" in rejected.severity_rationale
    assert all(f.runtime_verification.value == "not_attempted" for f in bundle.findings)
    assert {p.suffix for p in (tmp_path / "complete").iterdir()} == {
        ".md",
        ".html",
        ".json",
        ".sarif",
    }
    import json
    import re

    from backend.reports import ReportBundle

    saved = ReportBundle.model_validate_json((tmp_path / "complete/report.json").read_bytes())
    assert saved.findings == bundle.findings
    sarif = json.loads((tmp_path / "complete/report.sarif").read_text())
    recorded = [
        Finding.model_validate(r["properties"]["finding"]) for r in sarif["runs"][0]["results"]
    ]
    assert recorded == bundle.findings
    for suffix in ("md", "html"):
        output = (tmp_path / f"complete/report.{suffix}").read_text(encoding="utf-8")
        if suffix == "md":
            output = re.sub(r"\\(.)", r"\1", output)
        assert supported.severity_rationale in output
        for exhibit in supported.exhibits:
            assert f"{supported.display_id}/{exhibit.tag}" in output
    assert any(
        "scope" in limit.lower() or "families" in limit.lower() for limit in bundle.limitations
    )
    for q in runs.questions("run:test"):
        looks = runs.state("run:test", q.id)["looks"]
        assert isinstance(looks, int) and looks <= q.budget.max_looks


def test_invalid_model_menu_cannot_run_a_tool(review: Review, tmp_path: Path) -> None:
    runs = queued(review, tmp_path)
    result = Workflow(
        review,
        runs,
        "run:test",
        Model(invalid_menu=True),
        tmp_path / "guards.sqlite",
        "test labels",
        2,
    ).run()
    assert result.coverage.completed == 2
    assert all(q.status is QuestionStatus.FAILED for q in runs.questions("run:test"))
    bundle = export(review, runs, "run:test", tmp_path / "reports")
    assert not bundle.findings
    assert any("failed" in limit for limit in bundle.limitations)
    for question in runs.questions("run:test"):
        data = runs.state("run:test", question.id).get("data")
        assert not isinstance(data, dict) or "peer_result" not in data


def test_peer_records_survive_a_pause_between_challenge_and_decision(
    review: Review, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = queued(review, tmp_path)
    model = Model()
    workflow = Workflow(review, runs, "run:test", model, tmp_path / "peers.sqlite", "test", 2)

    def pause_after_challenge(
        question: Question, state: Mapping[str, JsonValue], spend: Spend
    ) -> Step:
        step = workflow.handle(question, state, spend)
        if question.stage is QuestionStage.CHALLENGE:
            runs.request("run:test", "pause")
        return step

    handlers = {
        stage: pause_after_challenge for stage in QuestionStage if stage is not QuestionStage.VERIFY
    }
    assert Engine(runs, handlers).run("run:test").lifecycle is RunLifecycle.PAUSED
    question = next(q for q in runs.questions("run:test") if q.status is QuestionStatus.RUNNING)
    assert question.stage is QuestionStage.DECIDE and question.answer is None
    state = runs.state("run:test", question.id)["data"]
    assert isinstance(state, dict)
    peers = PeerResult.model_validate(state["peer_result"])
    access = AccessMap.model_validate(state["peer_access"])
    raw_entries = state["peer_entries"]
    assert isinstance(raw_entries, list)
    entries = [EntryPoint.model_validate(e) for e in raw_entries]
    assert peers.snapshot_id == access.snapshot_id == review.snapshot.id
    assert peers.groups and all(g.snapshot_id == review.snapshot.id for g in peers.groups)
    members = {i for g in peers.groups for i in g.site_ids}
    assert members == {c.site_id for c in peers.checks} == {p.site.id for p in access.accesses}
    assert {e.id for e in entries} == {p.site.entry_point_id for p in access.accesses}
    assert all(e.snapshot_id == review.snapshot.id for e in entries)
    for check in peers.checks:
        for guard in check.guards:
            assert (
                guard.confirmed and not guard.optimistic and guard.snapshot_id == review.snapshot.id
            )
        for span in check.evidence:
            assert span.snapshot_id == review.snapshot.id
    expected = {key: state[key] for key in ("peer_result", "peer_access", "peer_entries")}
    assert (
        Workflow(review, runs, "run:test", model, tmp_path / "peers.sqlite", "test", 2)
        .run()
        .lifecycle
        is RunLifecycle.COMPLETED
    )
    answer = next(q for q in runs.questions("run:test") if q.id == question.id).answer
    assert answer is not None and {key: answer[key] for key in expected} == expected

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Export attempted to rebuild peers or call a model")

    before = len(model.requests)
    monkeypatch.setattr(Model, "ask", forbidden)
    monkeypatch.setattr("agent.peers.PeerCheck.build", forbidden)
    bundle = export(review, runs, "run:test", tmp_path / "checkpoint-export")
    assert len(bundle.findings) == 2 and len(model.requests) == before
    assert len(bundle.peer_comparisons) == 2
    peer = next(p for p in bundle.peer_comparisons if p.question_id == question.id)
    assert peer.subject_site_id == question.subject_ids[0]
    assert peer.group == peers.groups[0]
    assert {r.site.id for r in peer.rows} == members
    assert peer.finding_id in {f.id for f in bundle.findings}
    from backend.reports import ReportBundle

    saved = ReportBundle.model_validate_json(
        (tmp_path / "checkpoint-export/report.json").read_bytes()
    )
    assert saved.peer_comparisons == bundle.peer_comparisons

    # Existing answers lacking the new optional metadata remain exportable. No backfill
    # and no synthesized peer denominator while viewing an old record.
    legacy = RunStore(tmp_path / "legacy.sqlite")
    run = runs.run("run:test")
    assert run is not None
    legacy_questions = []
    for item in runs.questions("run:test"):
        assert item.answer is not None
        old_answer = {key: value for key, value in item.answer.items() if key not in expected}
        legacy_questions.append(item.model_copy(update={"answer": old_answer}))
    legacy.create(run, legacy_questions)
    old_bundle = export(review, legacy, "run:test", tmp_path / "legacy-export")
    assert old_bundle.findings == bundle.findings
    assert old_bundle.peer_comparisons == []
    assert all(q.answer and "peer_result" not in q.answer for q in legacy.questions("run:test"))


def test_unknown_scope_does_not_silently_review_everything(review: Review) -> None:
    questions, coverage, _ = review.questions("run:test", [], ["/missing"])
    assert not questions
    assert coverage.excluded == coverage.total


def test_preparation_combines_cached_peers_and_pattern_leads_without_model_requests(
    review: Review,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from analysis.opengrep import Signal
    from backend.scheduling import Preparation, order_questions, prepare

    model = Model()
    cache = tmp_path / "summaries.sqlite"
    warm = Workflow(review, queued(review, tmp_path), "run:test", model, cache, "test", 2)
    # Fixture answers, not a fresh accuracy claim. Preparation itself cannot ask this model.
    assert warm.challenge.result.groups
    preparation = prepare(review, "run:test", cache, "test")
    hits = preparation.peer_observation.inputs["cached_summaries_used"]
    assert isinstance(hits, int) and hits > 0
    assert preparation.peer_observation.inputs["fresh_requests"] == 0
    assert preparation.scan.observation.status.value == "refused"  # no installed tool in fixture
    questions, coverage, exclusions = review.questions("run:test", ["Order"], ROUTES)
    receipt = next(
        q
        for q in questions
        if review.routes[
            next(
                a.site.entry_point_id
                for a in review.access.accesses
                if a.site.id == q.subject_ids[0]
            )
        ].entry.route
        == ROUTES[0]
    )
    signal = Signal(
        rule="plumb.authz.load-by-id-without-owner-comparison",
        family=Family.AUTHORIZATION,
        span=receipt.evidence[0],
    )
    preparation = preparation.model_copy(
        update={
            "scan": preparation.scan.model_copy(update={"signals": [signal, signal]}),
        }
    )
    review.preparation = Preparation.model_validate_json(preparation.model_dump_json())
    before_calls = len(model.requests)
    try:
        ordered = order_questions(review, questions)
        ranked_receipt = next(q for q in ordered if q.id == receipt.id)
        assert any("Cached peer lead" in r for r in ranked_receipt.priority_reasons)
        assert any("Opengrep lead" in r for r in ranked_receipt.priority_reasons)
        assert ranked_receipt.observation_ids == [
            preparation.scan.observation.id,
            preparation.peer_observation.id,
        ]
        assert all(q.answer is None and q.status is QuestionStatus.PENDING for q in ordered)
        assert len(model.requests) == before_calls
        assert {q.id for q in ordered} == {q.id for q in questions}
        assert coverage.pending + len(exclusions) == coverage.total
        other = next(q for q in ordered if q.id != receipt.id)
        assert not any("Opengrep lead" in r for r in other.priority_reasons)
        mismatched = signal.model_copy(update={"family": Family.INJECTION})
        review.preparation = preparation.model_copy(
            update={
                "scan": preparation.scan.model_copy(update={"signals": [mismatched]}),
            }
        )
        assert not any(
            "Opengrep lead" in reason
            for q in order_questions(review, questions)
            for reason in q.priority_reasons
        )
    finally:
        review.preparation = None
        review.scheduling_limits = ["Static pattern and cached-peer queue preparation was not run."]


def test_mixed_family_queue_preserves_global_exploration_and_all_scope(review: Review) -> None:
    questions, coverage, exclusions = review.questions("run:mixed", [], [], tuple(Family))
    assert len(questions) + len(exclusions) == coverage.total
    assert len({q.id for q in questions}) == len(questions)
    assert {q.family for q in questions} == set(Family)
    assert [i for i, q in enumerate(questions, 1) if q.exploration] == list(
        range(5, len(questions), 5)
    )


def test_public_cli_persists_preparation_and_resume_never_rebuilds_it(
    review: Review,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from backend import cli, scheduling
    from backend.profiles import Profile

    monkeypatch.setenv("PLUMB_DATA_DIR", str(review.settings.data_dir))
    monkeypatch.setattr(cli, "Review", lambda *_: review)
    monkeypatch.setattr(review, "close", lambda: None)
    monkeypatch.setattr(cli, "select", lambda *_: Profile())
    monkeypatch.setattr(cli, "validate_resume", lambda *_: None)
    monkeypatch.setattr(cli, "machine_state", lambda: {})
    created, stopped = [], []

    def create(*args: object) -> SimpleNamespace:
        created.append(True)
        return SimpleNamespace(
            config=SimpleNamespace(argv=lambda *_: ["fixture"]),
            preflight=lambda: None,
            stop=lambda: stopped.append(True),
            memory_abort=None,
        )

    def workflow(context: object, runs: RunStore, run_id: str, *args: object) -> SimpleNamespace:
        def run() -> ReviewRun:
            runs.request(run_id, "pause")
            return Engine(runs, {}).run(run_id)

        return SimpleNamespace(run=run, _challenge=None)

    monkeypatch.setattr(cli, "create", create)
    monkeypatch.setattr(cli, "ModelAdapter", lambda *_a, **_k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cli, "Workflow", workflow)
    root = str(Path(__file__).resolve().parents[2] / "labs/tandir")
    try:
        assert cli.main(["review", root, "--resource", "Order", "--route", ROUTES[0]]) == 2
        directory = next((review.settings.data_dir / "reviews").iterdir())
        config = json.loads((directory / "context.json").read_bytes())
        assert config["scheduling_sha256"]
        original = (directory / "scheduling.json").read_bytes()

        def forbidden(*_a: object, **_k: object) -> None:
            pytest.fail("Resume reran queue preparation")

        monkeypatch.setattr(scheduling, "prepare", forbidden)
        assert cli.main(["resume", directory.name]) == 2
        assert (directory / "scheduling.json").read_bytes() == original
        assert len(created) == len(stopped) == 2
        (directory / "scheduling.json").write_bytes(original + b" ")
        assert cli.main(["resume", directory.name]) == 1
        assert len(created) == 2, "Altered observations reached model setup"
    finally:
        review.preparation = None
        review.scheduling_limits = ["Static pattern and cached-peer queue preparation was not run."]


@pytest.mark.parametrize("outcome", ["passed", "failed", "refused"])
def test_first_review_on_a_computer_checks_the_runner_before_any_question(
    review: Review, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from backend import cli
    from backend.profiles import CPU_PROFILE_ID, REGISTRY

    monkeypatch.setenv("PLUMB_DATA_DIR", str(review.settings.data_dir))
    monkeypatch.setattr(cli, "Review", lambda *_: review)
    monkeypatch.setattr(review, "close", lambda: None)
    monkeypatch.setattr(cli, "select", lambda *_: REGISTRY[CPU_PROFILE_ID])
    monkeypatch.setattr(cli, "machine_state", lambda: {})
    monkeypatch.setattr(
        cli,
        "create",
        lambda *_: SimpleNamespace(
            config=SimpleNamespace(argv=lambda *_: ["fixture"]),
            preflight=lambda: None,
            stop=lambda: None,
            memory_abort=None,
        ),
    )
    events: list[str] = []

    def check(settings: object, profile: object, log_name: str) -> dict[str, object]:
        events.append("check")
        return {"outcome": outcome, "path": "saved-record.json", "reason": "1.0 GB free."}

    def workflow(context: object, runs: RunStore, run_id: str, *args: object) -> SimpleNamespace:
        def run() -> ReviewRun:
            events.append("review")
            runs.request(run_id, "pause")
            return Engine(runs, {}).run(run_id)

        return SimpleNamespace(run=run, _challenge=None)

    monkeypatch.setattr(cli, "first_use_pending", lambda *_: True)
    monkeypatch.setattr(cli, "first_use_check", check)
    monkeypatch.setattr(cli, "ModelAdapter", lambda *_a, **_k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cli, "Workflow", workflow)
    root = str(Path(__file__).resolve().parents[2] / "labs/tandir")
    try:
        code = cli.main(["review", root, "--resource", "Order", "--route", ROUTES[0]])
        # Only a pass lets the review ask its first question.
        assert (code, events) == (
            (2, ["check", "review"]) if outcome == "passed" else (1, ["check"])
        )
        # The shared fixture keeps earlier reviews; this one's record names its outcome.
        saved = (review.settings.data_dir / "reviews").glob("*/invocation-*.json")
        assert any(f'"outcome": "{outcome}"' in p.read_text(encoding="utf-8") for p in saved)
    finally:
        review.preparation = None
        review.scheduling_limits = ["Static pattern and cached-peer queue preparation was not run."]


def test_authorization_severity_requires_source_scope_not_resource_names(
    review: Review,
    tmp_path: Path,
) -> None:
    from agent.challenge import finding
    from agent.severity import authorization
    from backend.contracts.investigation import Budget, Severity

    workflow = Workflow(
        review,
        queued(review, tmp_path),
        "run:test",
        Model(),
        tmp_path / "guards.sqlite",
        "fixture",
        2,
    )
    challenge = workflow.challenge
    path = next(
        p
        for p in challenge.access.accesses
        if challenge.routes[p.site.entry_point_id].entry.route == ROUTES[0]
        and p.site.resource == "Order"
    )
    result = challenge.investigate(path.site.id, Spend(Budget()))
    case = finding(result, run_id="run:test", display_id="F-01")

    def assess(peers: PeerResult, routes: Mapping[str, FastAPIRoute]) -> Finding:
        return authorization(case, result, challenge.access, peers, routes, challenge.peers)

    assert assess(challenge.result, challenge.routes).severity is Severity.MEDIUM
    empty = challenge.result.model_copy(update={"checks": []})
    assert assess(empty, challenge.routes).severity is Severity.UNKNOWN
    assert assess(challenge.result, {}).severity is Severity.UNKNOWN
    wrong = challenge.result.model_copy(update={"snapshot_id": "0" * 64})
    assert assess(wrong, challenge.routes).severity is Severity.UNKNOWN
    corrupt = challenge.result.model_copy(
        update={
            "checks": [
                check.model_copy(
                    update={
                        "guards": [
                            guard.model_copy(
                                update={
                                    "span": guard.span.model_copy(
                                        update={"content_sha256": "0" * 64}
                                    ),
                                }
                            )
                            for guard in check.guards
                        ]
                    }
                )
                for check in challenge.result.checks
            ]
        }
    )
    assert assess(corrupt, challenge.routes).severity is Severity.UNKNOWN


def test_other_families_are_checkpointed_and_exported(review: Review, tmp_path: Path) -> None:
    from agent.tests.test_families import Model as SinkModel

    questions, coverage, exclusions = review.questions(
        "run:sinks", [], ["/admin/orders", "/admin/customers"], (Family.INJECTION,)
    )
    assert len(questions) == 2
    assert coverage.pending + len(exclusions) == coverage.total
    runs = RunStore(tmp_path / "sinks.sqlite")
    runs.create(
        ReviewRun(
            id="run:sinks",
            snapshot_id=review.snapshot.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.QUEUED,
            created_at=datetime.now(UTC),
            coverage=coverage,
        ),
        questions,
    )

    class SinkJudge:
        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            if request.name == "gather":
                return JsonAnswer({"look": "enough"}, "", 1, 1, 0)
            mechanism = "allowlisted" if "CUSTOMER_SORTS.get" in request.user else "none_found"
            return SinkModel([mechanism]).ask(request, spend)

    first = Workflow(review, runs, "run:sinks", SinkJudge(), tmp_path / "unused.sqlite", "test", 1)
    assert first.run().lifecycle is RunLifecycle.PAUSED
    second = Workflow(review, runs, "run:sinks", SinkJudge(), tmp_path / "unused.sqlite", "test", 1)
    assert second.run().lifecycle is RunLifecycle.COMPLETED
    bundle = export(review, runs, "run:sinks", tmp_path / "sink-reports")
    assert {f.conclusion.value for f in bundle.findings} == {"supported", "rejected"}
    assert all(f.family is Family.INJECTION for f in bundle.findings)


def test_resource_filter_cannot_silently_ignore_other_families(review: Review) -> None:
    with pytest.raises(ValueError, match="--resource"):
        review.questions("run:test", ["Order"], [], (Family.PATH_TRAVERSAL,))


@pytest.mark.parametrize(
    "route,gap",
    [
        ("/api/admin/export", "required authorization policy"),
        ("/api/admin/reports", "judgment does not confirm the source-bound admin guard"),
    ],
)
def test_next_boundary_stays_inconclusive_with_visible_reason(
    review: Review,
    tmp_path: Path,
    route: str,
    gap: str,
) -> None:
    questions, coverage, _ = review.questions("run:next", [], [route], (Family.NEXTJS_EXPOSURE,))
    assert len(questions) == 1
    runs = RunStore(tmp_path / "next.sqlite")
    runs.create(
        ReviewRun(
            id="run:next",
            snapshot_id=review.snapshot.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.QUEUED,
            created_at=datetime.now(UTC),
            coverage=coverage,
        ),
        questions,
    )
    model = Model()
    assert (
        Workflow(review, runs, "run:next", model, tmp_path / "guards-next.sqlite", "test", 1)
        .run()
        .lifecycle
        is RunLifecycle.COMPLETED
    )
    bundle = export(review, runs, "run:next", tmp_path / "next-reports")
    assert bundle.findings[0].conclusion.value == "inconclusive"
    assert gap in " ".join(bundle.findings[0].gaps)


def test_actual_tandir_dal_constraints_bind_to_saved_accesses(
    review: Review, tmp_path: Path
) -> None:
    from agent.guards import Classifier, SummaryCache
    from agent.peers import PeerCheck
    from agent.tests.test_ts_paths import Model as QueryModel

    classifier = Classifier(
        review.snapshot,
        review.store,
        QueryModel(),
        SummaryCache(tmp_path / "dal.sqlite"),
        identity="source integration fixture",
    )
    peers = PeerCheck(
        classifier, review.index, review.python, review.settings, typescript_graph=review.typescript
    )
    selected = [
        p
        for p in review.access.accesses
        if peers.symbols[p.owner_symbol_id].name in {"getOrderDTO", "cancelOrderFor"}
    ]
    assert selected
    result = peers.build(AccessMap(snapshot_id=review.snapshot.id, accesses=selected))
    assert len(result.checks) == len(selected)
    protected = {
        p.site.id for p in selected if peers.symbols[p.owner_symbol_id].name == "getOrderDTO"
    }
    assert protected
    assert any(c.site_id in protected and c.guards for c in result.checks)
    assert not any(c.exclusion for c in result.checks)


def test_resume_rejects_path_escape_before_touching_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path))
    assert main(["resume", "../../escape"]) == 1
    assert not (tmp_path / "reviews").exists()


def test_review_refuses_to_write_cache_inside_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "data"))
    assert main(["review", str(tmp_path)]) == 1
    assert not (tmp_path / "data/reviews").exists()


def test_review_refuses_guard_cache_inside_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "data"))
    assert main(["review", str(project), "--guard-cache", str(project / "guards.sqlite")]) == 1
    assert not (project / "guards.sqlite").exists()


# --- A.7: an empty default selection names the families that do have checks ---


def test_a_nextjs_only_project_is_told_which_family_to_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend import cli

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("An empty selection reached profile selection or the model")

    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "select", forbidden)
    monkeypatch.setattr(cli, "create", forbidden)
    monkeypatch.setattr(cli, "machine_state", lambda: {})
    web = Path(__file__).resolve().parents[2] / "labs/tandir/web"
    assert cli.main(["review", str(web)]) == 1
    printed = capsys.readouterr().out
    assert "No authorization checks match this scope" in printed
    assert "nextjs_exposure (" in printed and f"plumb review '{web}'" in printed
    assert "--family nextjs_exposure" in printed


def test_an_empty_scope_with_no_other_family_says_so_without_a_false_hint(
    review: Review,
) -> None:
    import argparse

    from backend import cli

    nothing = argparse.Namespace(
        family=["nextjs_exposure"], resource=[], route=["/no/such/route"], folder=Path("project")
    )
    message = cli.no_checks_message(review, "run:empty", nothing)
    assert "no other family has checks here either" in message and "--family" not in message
    assert "not a safety verdict" in message
    # The bundled lab has FastAPI routes: an unrelated selection points back to them.
    other = argparse.Namespace(
        family=["nextjs_exposure"], resource=[], route=[ROUTES[0]], folder=Path("p")
    )
    assert "--family authorization" in cli.no_checks_message(review, "run:empty", other)
