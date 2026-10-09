"""Deterministic boundary tests; fixture answers are not model-accuracy evidence."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent.families import SinkInvestigator, finding
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.validator import Unconfirmed
from analysis.index import Index, index_path
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.investigation import Budget, Conclusion

SOURCE = b"""from sqlalchemy import text
import subprocess
from fastapi.responses import FileResponse
SORTS = {"id": "id", "name": "name"}
def sql_bad(db, sort):
    return db.execute(text(f"SELECT id FROM users ORDER BY {sort}"))
def sql_good(db, sort):
    column = SORTS.get(sort)
    if column is None:
        raise ValueError()
    return db.execute(text(f"SELECT id FROM users ORDER BY {column}"))
def command_bad(customer):
    subprocess.run(f"print {customer}", shell=True)
def command_good(customer):
    subprocess.run(["print", customer], shell=False)
def path_bad(name, request: Request):
    return FileResponse(request.app.state.settings.files / name)
def path_good(name, request: Request):
    root = request.app.state.settings.files.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError()
    return FileResponse(path)
"""


class Model:
    def __init__(self, answers: list[str]) -> None:
        self.answers = iter(answers)
        self.requests: list[ModelRequest] = []

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.requests.append(request)
        ids = request.schema["properties"]["line_ids"]["items"]["enum"]
        import re

        defs = re.findall(r"(L\d+).*?def ", request.user)
        return JsonAnswer(
            {"mechanism": next(self.answers), "line_ids": defs[:1] or ids[:1]}, "", 1, 1, 0
        )


@pytest.fixture
def investigator(tmp_path: Path) -> Iterator[SinkInvestigator]:
    root = tmp_path / "project"
    root.mkdir()
    (root / "forms.py").write_bytes(SOURCE)
    store = SnapshotStore(tmp_path / "cache/snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(tmp_path / "cache", snapshot.id))
    try:
        yield SinkInvestigator(snapshot, store, index)
    finally:
        index.close()


@pytest.mark.parametrize(
    "name,mechanism,expected",
    [
        ("sql_bad", "none_found", Conclusion.SUPPORTED),
        ("sql_good", "allowlisted", Conclusion.REJECTED),
        ("command_bad", "none_found", Conclusion.SUPPORTED),
        ("command_good", "parameterized", Conclusion.REJECTED),
        ("path_bad", "none_found", Conclusion.SUPPORTED),
        ("path_good", "contained", Conclusion.REJECTED),
    ],
)
def test_exact_sink_protection_and_validated_findings(
    investigator: SinkInvestigator, name: str, mechanism: str, expected: Conclusion
) -> None:
    signal = next(s for s, (_, f) in investigator.facts.items() if f.function == name)
    model = Model([mechanism] * 3)
    result = investigator.investigate(signal, model, Spend(Budget()))
    assert result.conclusion is expected
    assert [r.seed for r in model.requests] == [42, 43, 44]
    case = finding(result, run_id="run:test", display_id="F-01")
    assert not investigator.validator.finding(case, guards=result.guards)
    if result.guards:
        assert result.guards[0].confirmed
        forged = result.guards[0].model_copy(update={"object": "9999"})
        with pytest.raises(Unconfirmed):
            investigator.validator.confirm(forged)


@pytest.mark.parametrize(
    "answers",
    [
        ["contained", "none_found", "none_found"],
        ["contained"] * 3,
    ],
)
def test_disagreement_or_invented_protection_is_never_a_verdict(
    investigator: SinkInvestigator, answers: list[str]
) -> None:
    signal = next(s for s, (_, f) in investigator.facts.items() if f.function == "path_bad")
    result = investigator.investigate(signal, Model(answers), Spend(Budget()))
    assert result.conclusion is Conclusion.INCONCLUSIVE
    assert not result.guards


def test_sql_focus_comes_from_text_flow_not_other_bound_arguments(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "query.py").write_text(
        "from sqlalchemy import text\n"
        "def search(db, sort, q):\n"
        '    return db.execute(text(f"SELECT id FROM users WHERE name=:q ORDER BY {sort}"), '
        '{"q": q})\n',
        encoding="utf-8",
    )
    store = SnapshotStore(tmp_path / "cache/snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(tmp_path / "cache", snapshot.id))
    try:
        investigator = SinkInvestigator(snapshot, store, index)
        signal = next(iter(investigator.facts))
        model = Model(["none_found"] * 3)
        result = investigator.investigate(signal, model, Spend(Budget()))
        assert result.conclusion is Conclusion.SUPPORTED
        for request in model.requests:
            question = request.user.split("Question: ")[-1]
            assert "Focus on SQL-text input(s): sort." in question
            assert "input(s): q" not in question
            assert "SELECT id FROM users WHERE name=:q ORDER BY {sort}" in request.user
            assert "supported" not in question.lower()
            assert "rejected" not in question.lower()
            assert "first argument on L2." in question
    finally:
        index.close()


def test_command_operand_focus_cites_argument_list_not_call_options(
    investigator: SinkInvestigator,
) -> None:
    signal = next(s for s, (_, f) in investigator.facts.items() if f.function == "command_good")
    model = Model(["parameterized"] * 3)
    result = investigator.investigate(signal, model, Spend(Budget()))
    assert result.conclusion is Conclusion.REJECTED
    for request in model.requests:
        command = next(
            line
            for line in request.user.splitlines()
            if 'subprocess.run(["print", customer]' in line
        )
        line_id = re.match(r"(L\d+)", command)
        assert line_id is not None
        assert f"first argument on {line_id.group(1)}." in request.user


@pytest.mark.parametrize(
    "case_id,function", [("TANDIR-B1", "search_orders"), ("TANDIR-B2-L", "print_receipt")]
)
def test_saved_real_sink_failures_remain_inconclusive_replay(
    tmp_path: Path, case_id: str, function: str
) -> None:
    """Saved actual answers are replay, never fresh acceptance of the changed prompt."""
    from eval.ground_truth import load

    root = Path(__file__).resolve().parents[2]
    saved: Any = json.loads(
        (root / "docs/results/2026-10-08-m6.9f-current-tandir-execution.json").read_bytes()
    )
    record = next(r for r in saved["records"] if r["case_id"] == case_id)
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(load().lab_root(), store)
    assert snapshot.id == record["snapshot"]["id"]
    index = Index.build(snapshot, store, tmp_path / "index.sqlite")

    class SavedReplay:
        def __init__(self) -> None:
            self.count = 0

        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            previous = next(
                a
                for a in record["requests"]
                if a["body"]["seed"] == request.seed
                and a["body"]["messages"][0]["content"] == request.system
            )

            def evidence(text: str) -> str:
                # Packet delimiters use a fresh random nonce. Preserve every
                # path, part, line ID and source byte while normalizing only it.
                return re.sub(
                    r"(</?(?:evidence|developer-notes)-)[a-f0-9]{8}",
                    r"\1<nonce>",
                    text.split("\n\nQuestion: ")[0],
                )

            assert evidence(request.user) == evidence(previous["body"]["messages"][1]["content"])
            self.count += 1
            return JsonAnswer(previous["answer"], previous["raw_answer"], 1, 1, 0)

    try:
        investigator = SinkInvestigator(snapshot, store, index)
        signal = next(s for s, (_, f) in investigator.facts.items() if f.function == function)
        replay = SavedReplay()
        result = investigator.investigate(signal, replay, Spend(Budget()))
        assert replay.count == 3
        assert result.conclusion is Conclusion.INCONCLUSIVE
        assert any(s.violations for s in result.samples)
        assert [s.answer.model_dump(mode="json") for s in result.samples] == [
            s["answer"] for s in record["questions"][0]["answer"]["result"]["samples"]
        ]
    finally:
        index.close()


def test_ambiguous_same_line_operations_omit_operand_hint(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "queries.py").write_text(
        "from sqlalchemy import text\n"
        "def query(db, sort, other):\n"
        '    return db.execute(text(f"SELECT id FROM users ORDER BY {sort}")), '
        'db.execute(text(f"SELECT id FROM users ORDER BY {other}"))\n',
        encoding="utf-8",
    )
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, tmp_path / "index.sqlite")
    try:
        investigator = SinkInvestigator(snapshot, store, index)
        model = Model(["none_found"] * 3)
        investigator.investigate(next(iter(investigator.facts)), model, Spend(Budget()))
        assert all("first argument on" not in r.user for r in model.requests)
    finally:
        index.close()
