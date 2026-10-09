"""Static synthetic source only. No fixture code is installed, imported or executed."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent.families import SinkInvestigator
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.tests.test_families import Model
from analysis.index import Index, index_path
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.investigation import Budget, Conclusion

MODEL = """from sqlalchemy.orm import DeclarativeBase, Mapped
class Base(DeclarativeBase):
    pass
class Record(Base):
    id: Mapped[int]
    text: Mapped[str]
    other: Mapped[str]
"""
WRITER = """from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import Record
router = APIRouter()
@router.post('/records')
def create(body, db: Session = Depends(get_db)):
    record = Record(text=body.text)
    db.add(record)
    db.commit()
"""
READER = """from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import subprocess
from models import Record
router = APIRouter()
@router.get('/records/{record_id}')
def print_text(record_id: int, db: Session = Depends(get_db)):
    record = db.get(Record, record_id)
    subprocess.run(f'printer {record.text}', shell=True)
"""


class FocusModel(Model):
    """Fixture answer cites the actual asked operation across shuffled excerpts."""

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        answer = super().ask(request, spend)
        focus = re.search(r" on (L\d+)", request.user)
        assert focus is not None
        return JsonAnswer({**answer.data, "line_ids": [focus.group(1)]}, "", 1, 1, 0)


def source_context(tmp_path: Path, sources: dict[str, str]) -> Iterator[SinkInvestigator]:
    root = tmp_path / "source"
    root.mkdir()
    for path, source in sources.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source, encoding="utf-8", newline="\n")
    store = SnapshotStore(tmp_path / "cache/snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(tmp_path / "cache", snapshot.id))
    try:
        yield SinkInvestigator(snapshot, store, index)
    finally:
        index.close()


def test_request_write_to_exact_stored_field_is_cited_and_challenged_three_times(
    tmp_path: Path,
) -> None:
    for check in source_context(
        tmp_path, {"models.py": MODEL, "write.py": WRITER, "read.py": READER}
    ):
        signal = next(i for i, (p, _) in check.facts.items() if p == "read.py")
        fact = check.facts[signal][1]
        assert fact.inputs == ("record.text",) and fact.risky and not fact.issues
        assert {s.path for s in fact.provenance} == {"models.py", "read.py", "write.py"}
        cuts = check.cuts(signal)
        assert any(c.path == "write.py" for c in cuts)
        invalid = check.investigate(
            signal, Model(["none_found"] * 3), Spend(Budget(max_prompt_tokens=16000))
        )
        assert invalid.conclusion is Conclusion.INCONCLUSIVE
        assert any(s.violations for s in invalid.samples)
        model = FocusModel(["none_found"] * 3)
        result = check.investigate(signal, model, Spend(Budget(max_prompt_tokens=16000)))
        assert result.conclusion is Conclusion.SUPPORTED and len(result.samples) == 3
        assert any(s.path == "write.py" for s in result.evidence)
        from agent.families import finding

        case = finding(result, run_id="run:provenance", display_id="F-01")
        assert not check.validator.finding(case, guards=result.guards)
        disagree = check.investigate(
            signal,
            FocusModel(["none_found", "parameterized", "none_found"]),
            Spend(Budget(max_prompt_tokens=16000)),
        )
        assert disagree.conclusion is Conclusion.INCONCLUSIVE


@pytest.mark.parametrize(
    "change",
    [
        "wrong_field",
        "uncommitted",
        "commit_before_add",
        "rebound_record",
        "unsafe_helper",
        "sanitized_write",
        "different_resource",
        "fake_session",
        "conditional_write",
    ],
)
def test_a_selector_or_unproven_wrong_write_cannot_taint_a_stored_field(
    tmp_path: Path, change: str
) -> None:
    sources = {"models.py": MODEL, "write.py": WRITER, "read.py": READER}
    if change == "wrong_field":
        sources["write.py"] = WRITER.replace("text=body.text", "other=body.text")
    elif change == "uncommitted":
        sources["write.py"] = WRITER.replace("    db.commit()\n", "")
    elif change == "commit_before_add":
        sources["write.py"] = WRITER.replace(
            "    db.add(record)\n    db.commit()", "    db.commit()\n    db.add(record)"
        )
    elif change == "rebound_record":
        sources["write.py"] = WRITER.replace(
            "    db.add(record)", "    record = Record(text='fixed')\n    db.add(record)"
        )
    elif change == "unsafe_helper":
        sources["write.py"] = WRITER.replace("text=body.text", "text=unknown(body.text)")
    elif change == "sanitized_write":
        sources["write.py"] = WRITER.replace(
            "router = APIRouter()", "def sanitize(value):\n    return 'fixed'\nrouter = APIRouter()"
        ).replace("text=body.text", "text=sanitize(body.text)")
    elif change == "different_resource":
        sources["other.py"] = MODEL
        sources["write.py"] = WRITER.replace(
            "from models import Record", "from other import Record"
        )
    elif change == "fake_session":
        sources["write.py"] = WRITER.replace(
            "from sqlalchemy.orm import Session", "class Session:\n    pass"
        )
    elif change == "conditional_write":
        sources["write.py"] = WRITER.replace(
            "    db.add(record)", "    if body.flag:\n        db.add(record)"
        )
    for check in source_context(tmp_path, sources):
        fact = next(f for p, f in check.facts.values() if p == "read.py")
        assert not fact.risky and not fact.inputs and fact.issues


@pytest.mark.parametrize(
    "helper",
    [
        "def helper(value):\n    alias = value\n    return alias\n",
        "def helper(value):\n    return str(value)\n",
    ],
)
def test_exact_resolved_helper_arguments_and_returns_keep_the_source_chain(
    tmp_path: Path, helper: str
) -> None:
    source = (
        "from fastapi.responses import FileResponse\nfrom helpers import helper\n"
        "def read(name):\n    return FileResponse(helper(value=name))\n"
    )
    for check in source_context(tmp_path, {"helpers.py": helper, "read.py": source}):
        fact = next(iter(check.facts.values()))[1]
        assert fact.inputs == ("name",) and fact.risky and not fact.issues
        assert any(s.path == "helpers.py" for s in fact.provenance)


@pytest.mark.parametrize(
    "helper",
    [
        "def helper(value):\n    return external(value)\n",
        "def helper(value):\n    try:\n        return value\n"
        "    except Exception:\n        return 'safe'\n",
        "def helper(value):\n    if value:\n        return value\n    return 'safe'\n",
        "def helper(value):\n    str = external\n    return str(value)\n",
        "def helper(value):\n    return 'safe'\n",
        "def helper(value):\n    return int(value)\n",
        "@decorate\ndef helper(value):\n    return value\n",
        "async def helper(value):\n    return value\n",
    ],
)
def test_unresolved_or_sanitizing_helpers_do_not_preserve_attacker_control(
    tmp_path: Path, helper: str
) -> None:
    source = (
        "from fastapi.responses import FileResponse\nfrom helpers import helper\n"
        "def read(name):\n    return FileResponse(helper(name))\n"
    )
    for check in source_context(tmp_path, {"helpers.py": helper, "read.py": source}):
        fact = next(iter(check.facts.values()))[1]
        assert not fact.inputs and not fact.risky


@pytest.mark.parametrize(
    "middle",
    [
        "record = Record(text='fixed')",
        "record = unknown(record)",
        "sanitize(record)",
        "alias = record\n    sanitize(alias)",
    ],
)
def test_rebound_or_mutated_read_is_not_the_proven_field(tmp_path: Path, middle: str) -> None:
    reader = READER.replace("    subprocess.run", f"    {middle}\n    subprocess.run")
    for check in source_context(
        tmp_path, {"models.py": MODEL, "write.py": WRITER, "read.py": reader}
    ):
        fact = next(f for p, f in check.facts.values() if p == "read.py")
        assert not fact.inputs and not fact.risky and fact.issues


@pytest.mark.parametrize(
    "helper,argument",
    [
        ("def helper(value, /):\n    return value\n", "value=name"),
        ("def helper(value):\n    return value\n", "missing=name"),
        ("def helper(value):\n    return value\n", "name, value=name"),
        ("def helper(value):\n    return value\n", "*name"),
    ],
)
def test_ambiguous_helper_binding_keeps_an_unknown_edge(
    tmp_path: Path, helper: str, argument: str
) -> None:
    source = (
        "from fastapi.responses import FileResponse\nfrom helpers import helper\n"
        f"def read(name):\n    return FileResponse(helper({argument}))\n"
    )
    for check in source_context(tmp_path, {"helpers.py": helper, "read.py": source}):
        fact = next(iter(check.facts.values()))[1]
        assert not fact.inputs and not fact.risky and fact.issues and fact.flow_notes


def test_truthy_fixed_fallback_does_not_reach_its_request_operand(tmp_path: Path) -> None:
    source = (
        "from fastapi.responses import FileResponse\ndef read(name):\n"
        "    return FileResponse('fixed' or name)\n"
    )
    for check in source_context(tmp_path, {"read.py": source}):
        fact = next(iter(check.facts.values()))[1]
        assert not fact.inputs and not fact.risky


@pytest.mark.parametrize(
    "mode", ["normal", "after_commit", "viewonly", "no_cascade", "custom_validation"]
)
def test_related_field_requires_persistence_after_the_exact_write(
    tmp_path: Path, mode: str
) -> None:
    models = MODEL.replace("DeclarativeBase, Mapped", "DeclarativeBase, Mapped, relationship")
    models += 'class Parent(Base):\n    items: Mapped[list["Record"]] = relationship()\n'
    if mode == "viewonly":
        models = models.replace("relationship()", "relationship(viewonly=True)")
    elif mode == "no_cascade":
        models = models.replace("relationship()", "relationship(cascade='merge')")
    elif mode == "custom_validation":
        models = models.replace(
            "class Record(Base):",
            "class Record(Base):\n    def __init__(self, **values):\n        self.text = 'fixed'",
        )
    writer = WRITER.replace("from models import Record", "from models import Record, Parent")
    writer = writer.replace(
        "    record = Record(text=body.text)\n    db.add(record)\n    db.commit()",
        "    parent = Parent()\n    db.add(parent)\n"
        "    parent.items.append(Record(text=body.text))\n    db.commit()",
    )
    if mode == "after_commit":
        writer = writer.replace(
            "    parent.items.append(Record(text=body.text))\n    db.commit()",
            "    db.commit()\n    parent.items.append(Record(text=body.text))",
        )
    for check in source_context(
        tmp_path, {"models.py": models, "write.py": writer, "read.py": READER}
    ):
        fact = next(f for p, f in check.facts.values() if p == "read.py")
        assert fact.risky is (mode == "normal")
        if mode != "normal":
            assert not fact.inputs and fact.issues


def test_unrelated_uncertainty_cannot_hide_an_exact_request_path_segment(tmp_path: Path) -> None:
    source = (
        "from fastapi.responses import FileResponse\ndef read(name, root):\n"
        "    prefix = unknown(root)\n    path = prefix / name\n"
        "    return FileResponse(path)\n"
    )
    for check in source_context(tmp_path, {"read.py": source}):
        fact = next(iter(check.facts.values()))[1]
        assert fact.inputs == ("name",) and fact.risky and not fact.issues
        assert "Unresolved transformation unknown" in fact.flow_notes


def test_actual_tandir_stored_field_and_path_replay_without_inference(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2] / "labs/tandir"
    store = SnapshotStore(tmp_path / "cache/snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(tmp_path / "cache", snapshot.id))
    try:
        check = SinkInvestigator(snapshot, store, index)
        facts = {f.function: f for _, f in check.facts.values()}
        assert facts["print_cake_label"].risky and not facts["print_cake_label"].issues
        assert "item.inscription" in facts["print_cake_label"].inputs
        assert any(
            s.path.endswith("routers/orders.py") for s in facts["print_cake_label"].provenance
        )
        assert facts["download_photo"].risky and "name" in facts["download_photo"].inputs
        assert not facts["download_photo"].issues
        assert facts["get_avatar"].mechanism == "contained"
        assert facts["print_receipt"].mechanism == "parameterized"
        assert facts["search_orders"].inputs == ("sort",)
        # Citations and complete packets validate against the actual frozen source.
        for signal, (_, fact) in check.facts.items():
            if fact.function in {"print_cake_label", "download_photo"}:
                assert check.cuts(signal)
                result = check.investigate(
                    signal, Model(["none_found"] * 3), Spend(Budget(max_prompt_tokens=20000))
                )
                assert result.conclusion is Conclusion.SUPPORTED
    finally:
        index.close()
