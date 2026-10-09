"""Saved source/edit/raw associations only; fixtures never execute reviewed code."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from agent.evidence import Cut, EvidencePacket
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.questions import fix_sketch
from analysis.patches import construct
from analysis.syntax import span_sha256
from backend.contracts.code import SourceSpan
from backend.contracts.investigation import Conclusion, Finding
from backend.contracts.verification import SourceEdit
from backend.settings import Settings
from eval import candidate, plumb, tandir
from eval.baselines import development as base
from eval.mutation import development as corpus
from eval.proposals import saved_change
from eval.tests.test_plumb import Judge as BaseJudge


class Judge(BaseJudge):
    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        if request.name != "fix_sketch":
            return super().ask(request, spend)
        self.requests.append(request)
        target = next(
            line
            for line in request.user.splitlines()
            if " | " in line and ("shell=True" in line or 'run("UPDATE orders' in line)
        )
        line_id, code = target.split(" | ", 1)
        changed = code.replace("shell=True", "shell=False").replace(
            "status = 'refunded'", "status = 'cancelled'", 1
        )
        assert changed != code
        data = {
            "intent": "Fixture source change; intended security protection remains unproved.",
            "edits": [{"line_id": line_id, "action": "replace", "code": changed}],
            "probe": {"parameter": None, "denied": "unsafe_value", "allowed": "safe_value"},
        }
        spend.requests += 1
        spend.prompt_tokens += 10
        spend.completion_tokens += 5
        return JsonAnswer(data, json.dumps(data), 10, 5, 0)


@pytest.fixture(scope="module")
def current(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[candidate.Preparation, tandir.Execution, Any]:
    from analysis.snapshot import SnapshotStore

    folder = tmp_path_factory.mktemp("proposal-tandir")
    store = SnapshotStore(folder / "snapshots")
    prepared = candidate.prepare(
        store,
        hypothesis="Current saved change associations; software fixture",
        max_requests=50,
        max_seconds=300,
        case_ids=("TANDIR-D1", "TANDIR-D1-L"),
        machine={"software_fixture": True},
        with_requirements=True,
    )
    execution = tandir.execute(
        prepared,
        store,
        folder / "execution.json",
        Settings(data_dir=folder / "data"),
        fixture_model=Judge(),
    )
    assert execution.state == "completed"
    answer: Any = execution.records[0].questions[0].answer
    assert answer["proposal"]["status"] == "proposed"
    return prepared, execution, store


def test_current_tandir_accounting_accepts_source_proposal_without_runtime_credit(
    current: tuple[candidate.Preparation, tandir.Execution, Any],
) -> None:
    prepared, execution, store = current
    projected = tandir.result(prepared, store, execution)
    metrics: Any = candidate.account(prepared, projected, store)
    assert metrics["release_acceptance"] == "unassessed"
    assert projected.evidence_kind == "software_fixture"
    answer: Any = execution.records[0].questions[0].answer
    assert answer["finding"]["runtime_verification"] == "not_attempted"
    assert answer["proposal"]["change"]["status"] == "proposed"


@pytest.mark.parametrize("method", ["full_plumb", "no_grammar"])
def test_matched_accounting_keeps_valid_proposed_changes_and_grammar_modes(
    tmp_path: Path,
    method: plumb.Method,
) -> None:
    ids = {"v2_command_arguments/original", "v2_command_arguments/shell_input"}
    prepared = base.prepare(
        [c for c in corpus.make_cases() if c.id in ids],
        hypothesis="Saved change matched fixture",
        max_attempts=2,
        max_seconds=120,
    )
    plan = plumb.prepare(prepared, 40, method=method)
    execution = plumb.execute(
        prepared,
        plan,
        tmp_path / "execution.json",
        Settings(data_dir=tmp_path / "data"),
        fixture_model=Judge(),
    )
    assert execution.state == "completed"
    proposed = [
        q.answer["proposal"]
        for r in execution.records
        for q in r.questions
        if q.answer and q.answer.get("proposal")
    ]
    assert any(isinstance(p, dict) and p.get("status") == "proposed" for p in proposed)
    metrics = plumb.account(prepared, plan, execution)
    assert metrics["release_acceptance"] == "unassessed"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "foreign_finding",
        "foreign_snapshot",
        "pointer",
        "diff",
        "file_hash",
        "raw_code",
        "raw_intent",
        "raw_seed",
        "raw_packet",
        "raw_missing",
        "raw_duplicate",
        "replayed",
        "runtime",
        "refused",
        "scope",
        "schema",
    ],
)
def test_missing_corrupt_foreign_and_replayed_proposals_refuse(
    current: tuple[candidate.Preparation, tandir.Execution, Any],
    change: str,
) -> None:
    prepared, execution, store = current
    raw: Any = execution.model_dump(mode="json")
    record = raw["records"][0]
    answer = record["questions"][0]["answer"]
    proposal = answer["proposal"]
    request = next(r for r in record["requests"] if "edits" in r["answer"])
    if change == "missing":
        del answer["proposal"]
    elif change == "foreign_finding":
        proposal["finding_id"] = proposal["change"]["finding_id"] = "finding:foreign"
    elif change == "foreign_snapshot":
        proposal["snapshot_id"] = "0" * 64
    elif change == "pointer":
        answer["finding"]["suggested_change_id"] = "change:foreign"
    elif change == "diff":
        proposal["change"]["diff"] += "\n+ invented"
    elif change == "file_hash":
        proposal["change"]["source_edits"][0]["file_sha256"] = "0" * 64
    elif change in {"raw_code", "raw_intent"}:
        if change == "raw_code":
            request["answer"]["edits"][0]["code"] = "throw new Error('changed');"
        else:
            request["answer"]["intent"] = "Altered intent"
        request["raw_answer"] = json.dumps(request["answer"])
    elif change == "raw_seed":
        request["body"]["seed"] = 7
    elif change == "raw_packet":
        user = request["body"]["messages"][1]
        user["content"] = user["content"].replace("UPDATE orders", "UPDATE foreign")
    elif change == "raw_missing":
        record["requests"].remove(request)
    elif change == "raw_duplicate":
        record["requests"].append(request)
    elif change == "replayed":
        proposal["change"]["status"] = "replayed_fixed"
        proposal["change"]["replay_probe_run_ids"] = ["probe:invented"]
    elif change == "runtime":
        answer["finding"]["runtime_verification"] = "reproduced"
    elif change == "schema":
        request["body"]["response_format"]["json_schema"]["name"] = "guard_summary"
    elif change == "scope":
        saved = proposal["change"]
        path = saved["source_scope"]["path"]
        source = store.read(prepared.snapshot, path)
        scope = SourceSpan(
            snapshot_id=prepared.snapshot.id,
            path=path,
            start_line=1,
            end_line=len(source.splitlines()),
            content_sha256=span_sha256(source, 1, len(source.splitlines())),
        )
        file = next(f for f in prepared.snapshot.files if f.path == path)
        assert file.language is not None
        edit = SourceEdit(
            source=scope.model_copy(
                update={"end_line": 1, "content_sha256": span_sha256(source, 1, 1)}
            ),
            file_sha256=file.sha256,
            action="replace",
            code='"use client";',
        )
        # A self-consistent whole-file packet must not widen editable permission
        # to the source directive outside the finding's primary callable.
        saved["source_scope"] = scope.model_dump(mode="json")
        saved["source_edits"] = [edit.model_dump(mode="json")]
        saved["diff"] = construct(prepared.snapshot, store, scope, [edit])
        user = request["body"]["messages"][1]
        header = re.match(r"<evidence-([0-9a-f]{8}) part='([^']+)'", user["content"])
        assert header
        packet = EvidencePacket.build(
            Cut(header[2], path, file.language, source, 1, scope.end_line), boundary=header[1]
        )
        user["content"] = packet.render() + "\n\nQuestion: Make a fixture edit."
        request["answer"]["edits"] = [{"line_id": "L1", "action": "replace", "code": edit.code}]
        request["raw_answer"] = json.dumps(request["answer"])
        request["body"]["response_format"]["json_schema"]["schema"] = fix_sketch(
            packet, rule="Validate saved source edits."
        ).schema
    else:
        proposal["status"] = "refused"
        proposal["change"] = None
    with pytest.raises(ValueError):
        tandir.result(prepared, store, tandir.Execution.model_validate(raw))


def test_original_r_driver_pin_refuses_after_the_accounting_repair() -> None:
    root = Path(__file__).resolve().parents[2]
    saved = tandir.Execution.model_validate_json(
        (root / "docs/results/2026-10-08-m6.9r-action-phone-execution.json").read_bytes()
    )
    assert saved.driver != tandir.identity()
    # Do not mutate its old driver or preparation to turn a failed accounting
    # observation into current fresh metrics. Current fixture inputs are separate.
    assert saved.evidence_kind == "fresh_local"


@pytest.mark.parametrize(
    "conclusion", [Conclusion.SUPPORTED, Conclusion.REJECTED, Conclusion.INCONCLUSIVE]
)
def test_only_supported_findings_can_carry_a_saved_proposed_change(
    current: tuple[candidate.Preparation, tandir.Execution, Any],
    conclusion: Conclusion,
) -> None:
    prepared, execution, store = current
    record = execution.records[0]
    question = record.questions[0]
    assert question.answer
    finding = Finding.model_validate(question.answer["finding"]).model_copy(
        update={"conclusion": conclusion}
    )
    if conclusion is Conclusion.SUPPORTED:
        assert saved_change(question, finding, record.requests, prepared.snapshot, store)
    else:
        with pytest.raises(ValueError, match="proposed"):
            saved_change(question, finding, record.requests, prepared.snapshot, store)
