"""Executable source changes are checked as data, never executed as fixes."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent.evidence import Cut
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.proposals import propose
from analysis.patches import TrivialEdit, construct
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from backend.contracts.code import SourceSpan
from backend.contracts.investigation import Budget, Finding
from backend.contracts.verification import SourceEdit


@pytest.mark.parametrize(
    "path,source,line,code",
    [
        ("x.py", "def f(x):\n    return x\n", 2, "    return  x  "),
        ("x.py", "def f(x):\n    return x\n", 2, "    return x # claimed protection"),
        ("x.py", 'def f(x):\n    """old notes"""\n    return x\n', 2, '    """new notes"""'),
        ("x.py", 'def f():\n    """only notes"""\n', 2, '    """changed notes"""'),
        ("x.ts", "export function f(x: number) {\n  return x;\n}\n", 2, "return x;"),
        (
            "x.ts",
            "export function f(x: number) {\n  return x;\n}\n",
            2,
            "  return x /* claimed protection */;",
        ),
        (
            "x.tsx",
            "export function View({x}: any) {\n  return <p>{x}</p>;\n}\n",
            2,
            "  return <p>{ x }</p>;",
        ),
        (
            "x.tsx",
            "export function View({x}: any) {\n  return <p>{x}</p>;\n}\n",
            2,
            "  return <p>{/* claimed protection */}{x}</p>;",
        ),
        (
            "x.py",
            "def f(x):\n    return x\n",
            2,
            '    "claimed protection"\n    # another claim\n    return x',
        ),
        (
            "x.ts",
            "export function f(x: number) {\n  return x;\n}\n",
            2,
            "  // claimed protection\n  return x;",
        ),
    ],
)
def test_protection_edits_refuse_trivia_but_mechanical_diffs_remain_available(
    tmp_path: Path,
    path: str,
    source: str,
    line: int,
    code: str,
) -> None:
    root = tmp_path / "owned"
    root.mkdir()
    target = root / path
    target.write_text(source, encoding="utf-8", newline="\n")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    raw = source.encode()
    scope = SourceSpan(
        snapshot_id=snapshot.id,
        path=path,
        start_line=1,
        end_line=len(source.splitlines()),
        content_sha256=span_sha256(raw, 1, len(source.splitlines())),
    )
    edit = SourceEdit(
        source=scope.model_copy(
            update={
                "start_line": line,
                "end_line": line,
                "content_sha256": span_sha256(raw, line, line),
            }
        ),
        file_sha256=snapshot.files[0].sha256,
        action="replace",
        code=code,
    )
    assert construct(snapshot, store, scope, [edit])
    with pytest.raises(TrivialEdit, match="executable"):
        construct(snapshot, store, scope, [edit], require_code_change=True)
    assert target.read_bytes() == raw == store.read(snapshot, path)


@pytest.mark.parametrize(
    "path,source,line,code",
    [
        ("x.py", "def f(x):\n    return 'a b'\n", 2, "    return 'ab'"),
        ("x.py", "def f(x):\n    return x == 1\n", 2, "    return x != 1"),
        ("x.py", "def f(x):\n    if x:\n        allowed()\n    return x\n", 4, "        return x"),
        ("x.py", 'f"value {first()}"\n', 1, 'f"value {second()}"'),
        ("x.ts", "export function f(x: number) {\n  return x == 1;\n}\n", 2, "  return x != 1;"),
        ("x.ts", '"use server";\nexport function f() { return 1; }\n', 1, '"use client";'),
        ("x.ts", "export function f() {\n  return 'a b';\n}\n", 2, "  return 'ab';"),
        ("x.ts", "export function f() {\n  return `a b`;\n}\n", 2, "  return `ab`;"),
        (
            "x.ts",
            "export function f() {\n  return `${first()}`;\n}\n",
            2,
            "  return `${second()}`;",
        ),
        ("x.ts", "export function f(x: number) {\n  return\n  x;\n}\n", 2, "  return x;"),
        ("x.tsx", "export function View() {\n  return <p>a b</p>;\n}\n", 2, "  return <p>ab</p>;"),
    ],
)
def test_literals_operators_directives_and_control_flow_are_not_erased(
    tmp_path: Path,
    path: str,
    source: str,
    line: int,
    code: str,
) -> None:
    root = tmp_path / "owned"
    root.mkdir()
    (root / path).write_text(source, encoding="utf-8", newline="\n")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    raw = source.encode()
    scope = SourceSpan(
        snapshot_id=snapshot.id,
        path=path,
        start_line=1,
        end_line=len(source.splitlines()),
        content_sha256=span_sha256(raw, 1, len(source.splitlines())),
    )
    edit = SourceEdit(
        source=scope.model_copy(
            update={
                "start_line": line,
                "end_line": line,
                "content_sha256": span_sha256(raw, line, line),
            }
        ),
        file_sha256=snapshot.files[0].sha256,
        action="replace",
        code=code,
    )
    assert construct(snapshot, store, scope, [edit], require_code_change=True)
    assert store.read(snapshot, path) == raw


def test_multiple_edits_are_compared_as_one_complete_change(tmp_path: Path) -> None:
    source = "def f(x):\n    allowed()\n    return x\n"
    root = tmp_path / "owned"
    root.mkdir()
    (root / "x.py").write_text(source, encoding="utf-8", newline="\n")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    raw = source.encode()
    scope = SourceSpan(
        snapshot_id=snapshot.id,
        path="x.py",
        start_line=1,
        end_line=3,
        content_sha256=span_sha256(raw, 1, 3),
    )
    edits = [
        SourceEdit(
            source=scope.model_copy(
                update={
                    "start_line": line,
                    "end_line": line,
                    "content_sha256": span_sha256(raw, line, line),
                }
            ),
            file_sha256=snapshot.files[0].sha256,
            action="replace",
            code=code,
        )
        for line, code in [(2, "    # claimed protection"), (3, "    allowed()\n    return x")]
    ]
    with pytest.raises(TrivialEdit, match="executable"):
        construct(snapshot, store, scope, edits, require_code_change=True)
    assert store.read(snapshot, "x.py") == raw


def test_saved_r_whitespace_sketch_is_refused_without_a_new_model(
    tmp_path: Path, recorded_lab: Path
) -> None:
    root = Path(__file__).resolve().parents[2]
    saved: Any = json.loads(
        (root / "docs/results/2026-10-08-m6.9r-action-phone-execution.json").read_bytes()
    )
    record = next(r for r in saved["records"] if r["case_id"] == "TANDIR-D1")
    previous = next(r for r in record["requests"] if "edits" in r["answer"])
    finding = Finding.model_validate(record["questions"][0]["answer"]["finding"])
    finding = finding.model_copy(update={"suggested_change_id": None})
    scope = SourceSpan.model_validate(
        record["questions"][0]["answer"]["proposal"]["change"]["source_scope"]
    )
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(recorded_lab, store)
    assert snapshot.id == record["snapshot"]["id"]
    file = next(f for f in snapshot.files if f.path == scope.path)
    assert file.language is not None

    class SavedAnswer:
        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            assert request.name == "fix_sketch"
            return JsonAnswer(previous["answer"], previous["raw_answer"], 0, 0, 0)

    result = propose(
        finding,
        Cut(
            "part 1",
            scope.path,
            file.language,
            store.read(snapshot, scope.path),
            scope.start_line,
            scope.end_line,
        ),
        [],
        snapshot,
        store,
        SavedAnswer(),
        Spend(Budget()),
        rule="Require a verified session before the resource mutation.",
    )
    assert result.status == "refused" and result.change is None
    assert "whitespace" in result.reason
    assert finding.suggested_change_id is None and finding.runtime_verification == "not_attempted"
