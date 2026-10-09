"""Fix suggestions are fixtures, never fresh model quality or executed target code."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from agent.evidence import Cut, EvidencePacket
from agent.llm import AnswerTruncated, JsonAnswer, ModelRequest, Spend
from agent.proposals import propose
from agent.tests.test_validator import Lab
from agent.validator import Validator
from analysis.patches import construct
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.code import SourceSpan
from backend.contracts.common import Language
from backend.contracts.investigation import Budget, Finding
from backend.contracts.verification import SourceEdit


@pytest.mark.parametrize("case_id", ["TANDIR-A1", "TANDIR-B2"])
@pytest.mark.parametrize("corrected_fixture", [False, True], ids=["saved-replay", "new-fixture"])
def test_saved_proposal_failures_stay_refused_and_bounded_fixtures_can_propose(
    tmp_path: Path, recorded_lab: Path, case_id: str, corrected_fixture: bool
) -> None:
    """Exact primary source and saved answers; fixtures are not new model acceptance."""
    root = Path(__file__).resolve().parents[2]
    execution: Any = json.loads(
        (root / "docs/results/2026-10-08-m6.9f-current-tandir-execution.json").read_bytes()
    )
    preparation: Any = json.loads(
        (root / "docs/results/2026-10-08-m6.9f-current-tandir-preparation.json").read_bytes()
    )
    record = next(r for r in execution["records"] if r["case_id"] == case_id)
    previous = record["requests"][-1]
    assert previous["body"]["response_format"]["json_schema"]["name"] == "fix_sketch"
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(recorded_lab, store)
    assert snapshot.id == record["snapshot"]["id"]
    source = SourceSpan.model_validate(
        next(c for c in preparation["cases"] if c["id"] == case_id)["source"]
    )
    file = next(f for f in snapshot.files if f.path == source.path)
    assert file.language is not None
    cut = Cut(
        "part 1" if case_id == "TANDIR-A1" else "operation",
        source.path,
        file.language,
        store.read(snapshot, source.path),
        source.start_line,
        source.end_line,
    )
    finding = Finding.model_validate(record["questions"][0]["answer"]["finding"])

    class ReplayOrFixture:
        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            def normalize_nonce(text: str) -> str:
                return re.sub(r"(</?evidence-)[a-f0-9]{8}", r"\1<nonce>", text)

            original = previous["body"]["messages"][1]["content"]
            first = original[: original.index("</evidence-")]
            assert normalize_nonce(
                request.user[: request.user.index("</evidence-")]
            ) == normalize_nonce(first)
            assert request.max_tokens == 768
            data = previous["answer"]
            if corrected_fixture:
                edits = (
                    [
                        {
                            "line_id": "L8",
                            "action": "replace",
                            "code": "    if order is None or order.customer_id != user.id:",
                        }
                    ]
                    if case_id == "TANDIR-A1"
                    else [
                        {
                            "line_id": "L14",
                            "action": "replace",
                            "code": (
                                '    command = ["tandir-label", "--order", str(order.id), '
                                '"--text", item.inscription or item.name]'
                            ),
                        },
                        {
                            "line_id": "L15",
                            "action": "replace",
                            "code": (
                                "    subprocess.run(command, shell=False, check=True, timeout=10)"
                            ),
                        },
                    ]
                )
                data = {
                    "intent": "Fixture repair of the cited invariant.",
                    "edits": edits,
                    "probe": previous["answer"]["probe"]
                    if case_id == "TANDIR-A1"
                    else {
                        "parameter": "inscription",
                        "denied": "unsafe_value",
                        "allowed": "safe_value",
                    },
                }
            return JsonAnswer(data, json.dumps(data), 1, 1, 0)

    proposal = propose(
        finding,
        cut,
        [],
        snapshot,
        store,
        ReplayOrFixture(),
        Spend(Budget()),
        rule="Enforce the specific confirmed invariant in this frozen function.",
    )
    assert proposal.status == ("proposed" if corrected_fixture else "refused")
    assert store.read(snapshot, source.path) == cut.source
    assert finding.suggested_change_id is None and finding.runtime_verification == "not_attempted"
    if corrected_fixture:
        assert proposal.change is not None
        assert proposal.probe_status == ("available" if case_id == "TANDIR-A1" else "unavailable")
        assert not Validator(snapshot, store)._change(
            finding.model_copy(update={"suggested_change_id": proposal.change.id}),
            [],
            proposal.change,
        )
    else:
        assert proposal.change is None and "invalid syntax" in proposal.reason


def test_forged_read_only_context_refuses_before_model_request(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    main = scope(lab)
    context = Cut("peer", main.path, main.language, b"changed\n", 1, 1)
    model = SketchModel()
    result = propose(
        lab.finding(),
        main,
        [context],
        lab.snapshot,
        lab.store,
        model,
        Spend(Budget()),
        rule="Require ownership.",
    )
    assert result.status == "refused" and model.calls == 0


class SketchModel:
    def __init__(
        self, edits: list[dict[str, str]] | None = None, *, truncated: bool = False
    ) -> None:
        self.edits, self.truncated, self.calls = edits, truncated, 0

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.calls += 1
        assert request.name == "fix_sketch" and request.max_tokens == 768
        if self.truncated:
            raise AnswerTruncated("fixture partial JSON")
        # Identifiers must come from the exact packet. Default inserts an owner guard
        # before the existing return line; tests below control the selected source ID.
        edits = self.edits or [
            {
                "line_id": request.schema["properties"]["edits"]["items"]["properties"]["line_id"][
                    "enum"
                ][-1],
                "action": "insert_before",
                "code": "    if order.customer_id != user.id:\n        raise HTTPException(403)",
            }
        ]
        return JsonAnswer(
            {
                "intent": "Require the order owner before returning its receipt.",
                "edits": edits,
                "probe": {"parameter": "order_id", "denied": "other_user", "allowed": "owner"},
            },
            "",
            10,
            10,
            0,
        )


def scope(lab: Lab) -> Cut:
    return Cut(
        "handler",
        "api/routes/orders.py",
        Language.PYTHON,
        lab.store.read(lab.snapshot, "api/routes/orders.py"),
        9,
        13,
    )


def test_source_bound_proposal_has_exact_diff_and_no_target_write(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    cut = scope(lab)
    model = SketchModel()
    result = propose(
        lab.finding(),
        cut,
        [],
        lab.snapshot,
        lab.store,
        model,
        Spend(Budget()),
        rule="Enforce record ownership before returning the receipt.",
    )
    assert result.status == "proposed" and result.change is not None
    assert result.probe_status == "unavailable" and result.probe_spec is None
    change = result.change
    assert change.source_scope is not None
    assert change.status == "proposed" and change.snapshot_id == lab.snapshot.id
    assert "order.customer_id != user.id" in change.diff
    assert not Validator(lab.snapshot, lab.store)._change(
        lab.finding(suggested_change_id=change.id), [], change
    )
    assert model.calls == 1 and lab.store.read(lab.snapshot, cut.path) == cut.source
    # Exact same frozen file hashes/lines; an unrelated diff or hash cannot be replayed.
    with pytest.raises(ValueError):
        construct(
            lab.snapshot,
            lab.store,
            change.source_scope,
            [change.source_edits[0].model_copy(update={"file_sha256": "0" * 64})],
        )
    corrupt = change.model_copy(update={"diff": change.diff + "\n+unrelated"})
    assert Validator(lab.snapshot, lab.store)._change(
        lab.finding(suggested_change_id=change.id), [], corrupt
    )


@pytest.mark.parametrize(
    "edits",
    [
        [{"line_id": "L999", "action": "replace", "code": "pass"}],
        [{"line_id": "L1", "action": "delete", "code": "not empty"}],
        [{"line_id": "L1", "action": "replace", "code": "\0"}],
        [{"line_id": "L1", "action": "replace", "code": "def broken(:"}],
        [{"line_id": "L1", "action": "delete", "code": ""}] * 2,
        [{"line_id": "L1", "action": "replace", "code": "x" * 4001}],
        [{"line_id": "L1", "action": "replace", "code": 'api_key="synthetic-credential"'}],
    ],
)
def test_invalid_edits_are_refused_without_losing_the_supported_finding(
    tmp_path: Path, edits: list[dict[str, str]]
) -> None:
    lab = Lab(tmp_path)
    finding = lab.finding()
    result = propose(
        finding,
        scope(lab),
        [],
        lab.snapshot,
        lab.store,
        SketchModel(edits),
        Spend(Budget()),
        rule="Require ownership.",
    )
    assert result.status == "refused" and result.change is None
    assert finding.conclusion == "supported" and finding.suggested_change_id is None


def test_context_edits_partial_answers_and_overwrites_are_refused(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    main = scope(lab)
    context = Cut("peer", main.path, main.language, main.source, 15, 18)
    packet = EvidencePacket.build(main, context)
    edit = {"line_id": packet.excerpt("peer").line_ids[0], "action": "delete", "code": ""}
    result = propose(
        lab.finding(),
        main,
        [context],
        lab.snapshot,
        lab.store,
        SketchModel([edit]),
        Spend(Budget()),
        rule="Require ownership.",
    )
    assert result.status == "refused" and "outside" in result.reason
    result = propose(
        lab.finding(),
        main,
        [],
        lab.snapshot,
        lab.store,
        SketchModel(truncated=True),
        Spend(Budget()),
        rule="Require ownership.",
    )
    assert result.status == "unavailable"
    model = SketchModel()
    result = propose(
        lab.finding(suggested_change_id="change:existing"),
        main,
        [],
        lab.snapshot,
        lab.store,
        model,
        Spend(Budget()),
        rule="Require ownership.",
    )
    assert result.status == "refused" and model.calls == 0
    result = propose(
        lab.rejected(),
        main,
        [],
        lab.snapshot,
        lab.store,
        model,
        Spend(Budget()),
        rule="Require ownership.",
    )
    assert result.status == "refused" and model.calls == 0


def test_exhausted_budget_preserves_verdict_without_model_request(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    model = SketchModel()
    result = propose(
        lab.finding(),
        scope(lab),
        [],
        lab.snapshot,
        lab.store,
        model,
        Spend(Budget(), prompt_tokens=3000),
        rule="Require ownership.",
    )
    assert result.status == "unavailable" and model.calls == 0


def test_no_final_newline_and_non_source_file_are_not_patchable(tmp_path: Path) -> None:
    root = tmp_path / "target"
    root.mkdir()
    (root / "x.py").write_bytes(b"x = 1")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    from analysis.syntax import span_sha256
    from backend.contracts.code import SourceSpan

    span = SourceSpan(
        snapshot_id=snapshot.id,
        path="x.py",
        start_line=1,
        end_line=1,
        content_sha256=span_sha256(b"x = 1", 1, 1),
    )
    edit = SourceEdit(
        source=span,
        file_sha256=hashlib.sha256(b"x = 1").hexdigest(),
        action="replace",
        code="x = 2",
    )
    with pytest.raises(ValueError):
        construct(snapshot, store, span, [edit])


def test_excluded_file_path_escape_and_stale_packet_refuse_without_request(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    model = SketchModel()
    for path, data in [
        (".env", b"private\n"),
        ("../../outside.py", b"pass\n"),
        (scope(lab).path, b"changed\n"),
    ]:
        cut = Cut("handler", path, Language.PYTHON, data, 1, 1)
        result = propose(
            lab.finding(),
            cut,
            [],
            lab.snapshot,
            lab.store,
            model,
            Spend(Budget()),
            rule="Require ownership.",
        )
        assert result.status == "refused"
    assert model.calls == 0


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"x = 1\0\n", "x = 2"),
        (b"#" + b"x" * (1024 * 1024) + b"\n", "x = 2"),
        (b"x = 1\r\n", "x = 2"),
        (b"x = 1\n", "x = 1"),
        (b"x = 1\n", "\n".join(["x = 2"] * 31)),
    ],
    ids=["binary", "oversized", "non-LF", "no-op", "replacement-line-limit"],
)
def test_patch_file_and_replacement_bounds(tmp_path: Path, raw: bytes, code: str) -> None:
    from analysis.syntax import span_sha256
    from backend.contracts.code import SourceSpan

    root = tmp_path / "target"
    root.mkdir()
    target = root / "x.py"
    target.write_bytes(raw)
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    span = SourceSpan(
        snapshot_id=snapshot.id,
        path="x.py",
        start_line=1,
        end_line=1,
        content_sha256=span_sha256(raw, 1, 1),
    )
    edit = SourceEdit(
        source=span, file_sha256=hashlib.sha256(raw).hexdigest(), action="replace", code=code
    )
    with pytest.raises(ValueError):
        construct(snapshot, store, span, [edit])
    assert target.read_bytes() == raw


def test_excluded_link_catalog_is_not_editable(tmp_path: Path) -> None:
    from backend.contracts.code import ExcludedFile, ExclusionReason

    lab = Lab(tmp_path)
    snapshot = lab.snapshot.model_copy(
        update={"excluded": [ExcludedFile(path="linked.py", reason=ExclusionReason.LINK)]}
    )
    model = SketchModel()
    result = propose(
        lab.finding(),
        Cut("handler", "linked.py", Language.PYTHON, b"pass\n", 1, 1),
        [],
        snapshot,
        lab.store,
        model,
        Spend(Budget()),
        rule="Require ownership.",
    )
    assert result.status == "refused" and model.calls == 0


def test_typescript_patch_is_parsed_without_execution(tmp_path: Path) -> None:
    from analysis.syntax import span_sha256
    from backend.contracts.code import SourceSpan

    root = tmp_path / "target"
    root.mkdir()
    raw = b"export function read() { return true; }\n"
    target = root / "x.ts"
    target.write_bytes(raw)
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    span = SourceSpan(
        snapshot_id=snapshot.id,
        path="x.ts",
        start_line=1,
        end_line=1,
        content_sha256=span_sha256(raw, 1, 1),
    )
    edit = SourceEdit(
        source=span,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        action="replace",
        code="export function read() { return false; }",
    )
    assert "+export function read() { return false; }" in construct(snapshot, store, span, [edit])
    with pytest.raises(ValueError):
        construct(snapshot, store, span, [edit.model_copy(update={"code": "export function ("})])
    assert target.read_bytes() == raw
