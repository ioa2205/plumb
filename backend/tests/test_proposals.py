"""Actual workflow/store/export/API fixture; no inference or target execution."""

import json
import re
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from agent.llm import JsonAnswer, ModelRequest, Spend
from backend.app import create_app
from backend.case_reads import CaseReads
from backend.contracts.investigation import Finding, Question, QuestionStage
from backend.contracts.runs import RunLifecycle
from backend.contracts.verification import FixProposal
from backend.jobs import Engine, Step
from backend.review import Review, Workflow, export
from backend.tests.support import PORT, signed_in
from backend.tests.test_review import Model, queued
from backend.tests.test_review import review as review


class FixModel(Model):
    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        if request.name != "fix_sketch":
            return super().ask(request, spend)
        self.requests.append(request)
        assert "signing in alone does not enforce ownership" in request.user
        assert "repair precedent" in request.user
        assert "customer_id" in request.user and "user.id" in request.user
        match = re.search(r"(L\d+) \|     return ReceiptOut\.from_order\(order\)", request.user)
        assert match is not None
        editable = request.schema["properties"]["edits"]["items"]["properties"]["line_id"]["enum"]
        assert match[1] in editable
        assert len(editable) == 10  # exact receipt function; helpers remain read-only
        return JsonAnswer(
            {
                "intent": "Require ownership before returning the receipt.",
                "edits": [
                    {
                        "line_id": match[1],
                        "action": "insert_before",
                        "code": (
                            "    if order.customer_id != user.id:\n"
                            "        raise HTTPException(status_code=404)"
                        ),
                    }
                ],
                "probe": {"parameter": "order_id", "denied": "other_user", "allowed": "owner"},
            },
            "",
            30,
            40,
            0,
        )


def test_fix_sketch_survives_checkpoint_export_and_protected_case_reads(
    review: Review, tmp_path: Path
) -> None:
    runs = queued(review, tmp_path)
    model = FixModel()
    workflow = Workflow(review, runs, "run:test", model, tmp_path / "guards.sqlite", "fixture", 10)

    def pause_after_proposal(
        question: Question, state: Mapping[str, JsonValue], spend: Spend
    ) -> Step:
        step = workflow.handle(question, state, spend)
        if question.stage is QuestionStage.RECORD and step.answer and "proposal" in step.answer:
            runs.request("run:test", "pause")
        return step

    handlers = {
        stage: pause_after_proposal for stage in QuestionStage if stage is not QuestionStage.VERIFY
    }
    assert Engine(runs, handlers).run("run:test").lifecycle is RunLifecycle.PAUSED
    partial = export(review, runs, "run:test", tmp_path / "partial")
    assert len(partial.proposals) == len(partial.suggested_changes) == 1
    proposal = partial.proposals[0]
    assert proposal.status == "proposed" and proposal.probe_status == "available"
    assert proposal.probe_spec is not None and proposal.change is not None
    assert len(proposal.probe_spec.requests) == 3
    finding = next(f for f in partial.findings if f.id == proposal.finding_id)
    assert finding.runtime_verification == "not_attempted"
    assert finding.suggested_change_id == proposal.change.id
    original_answer = next(
        q.answer for q in runs.questions("run:test") if q.answer and "proposal" in q.answer
    )
    assert original_answer is not None
    frozen = json.dumps(original_answer["proposal"], sort_keys=True)
    later = FixModel()
    assert (
        Workflow(review, runs, "run:test", later, tmp_path / "guards.sqlite", "fixture", 1)
        .run()
        .lifecycle
        is RunLifecycle.COMPLETED
    )
    bundle = export(review, runs, "run:test", tmp_path / "finished")
    assert not any(r.name == "fix_sketch" for r in later.requests)
    assert (
        json.dumps(
            next(
                q.answer["proposal"]
                for q in runs.questions("run:test")
                if q.answer and "proposal" in q.answer
            ),
            sort_keys=True,
        )
        == frozen
    )
    assert (
        bundle.proposals[0] == proposal and bundle.run.coverage.total == partial.run.coverage.total
    )
    assert not bundle.probe_runs
    for name in ("report.json", "report.html", "report.md", "report.sarif"):
        text = (tmp_path / "finished" / name).read_text(encoding="utf-8")
        if name == "report.md":
            text = text.replace("\\.", ".").replace("\\_", "_")
        assert proposal.id in text and "order.customer_id != user.id" in text
        assert "proposed" in text and "No probe was executed" in text
    wrong = proposal.probe_spec.model_copy(
        update={
            "requests": [
                proposal.probe_spec.requests[0],
                proposal.probe_spec.requests[1].model_copy(update={"path": "/unrelated"}),
                proposal.probe_spec.requests[2],
            ]
        }
    )
    from backend.reports import render

    with pytest.raises(ValueError):
        render(
            bundle.model_copy(
                update={"proposals": [proposal.model_copy(update={"probe_spec": wrong})]}
            ),
            review.store,
            "json",
        )
    with pytest.raises(ValueError):
        render(bundle, review.store, "json", secrets=["order.customer_id"])


def test_saved_api_displays_proposal_and_refuses_stale_association(
    review: Review, tmp_path: Path
) -> None:
    settings = review.settings
    from datetime import UTC, datetime

    from backend.contracts.runs import ReviewRun, RunType
    from backend.run_store import RunStore

    run_id = "review-" + "e" * 32
    questions, coverage, _ = review.questions(run_id, ["Order"], ["/orders/{order_id}/receipt"])
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    runs.create(
        ReviewRun(
            id=run_id,
            snapshot_id=review.snapshot.id,
            run_type=RunType.LIVE,
            lifecycle=RunLifecycle.QUEUED,
            created_at=datetime.now(UTC),
            coverage=coverage,
        ),
        questions,
    )
    assert (
        Workflow(review, runs, run_id, FixModel(), tmp_path / "guards.sqlite", "fixture", 10)
        .run()
        .lifecycle
        is RunLifecycle.COMPLETED
    )
    directory = settings.data_dir / "reviews" / run_id
    bundle = export(review, runs, run_id, directory)
    finding = bundle.findings[0]
    detail = CaseReads(settings).case(run_id, finding.id)
    assert detail.proposal == bundle.proposals[0]
    client = signed_in(create_app(settings, port=PORT))
    response = client.get(f"/api/runs/{run_id}/findings/{finding.id}")
    assert (
        response.status_code == 200 and response.json()["proposal"]["probe_status"] == "available"
    )
    with pytest.raises(ValidationError):
        FixProposal.model_validate({**detail.proposal.model_dump(), "snapshot_id": "0" * 64})
    assert Finding.model_validate(detail.finding.model_dump()).conclusion == "supported"
