"""Source/raw-output associations for saved proposed changes; never executes a fix."""

import json
import re
from collections.abc import Sequence

from agent.evidence import Cut, EvidencePacket
from agent.questions import FixSketch, fix_sketch
from agent.validator import Validator
from analysis.snapshot import SnapshotStore
from analysis.syntax import extract
from backend.contracts.code import ProjectSnapshot, SymbolKind
from backend.contracts.investigation import Conclusion, Finding, Question
from backend.contracts.verification import ChangeStatus, FixProposal, SuggestedChange
from eval.candidate import RequestRecord


def saved_change(
    question: Question,
    finding: Finding,
    requests: Sequence[RequestRecord],
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
) -> SuggestedChange | None:
    """Bind a proposal to its frozen source and one exact saved sketch response."""
    if not question.answer:
        raise ValueError("A saved finding requires its question answer")
    validator = Validator(snapshot, store)
    raw = question.answer.get("proposal")
    if raw is None:
        if finding.suggested_change_id is not None:
            raise ValueError("Saved finding cites a missing proposal/change")
        return None
    proposal = FixProposal.model_validate(raw)
    if proposal.finding_id != finding.id or proposal.snapshot_id != finding.snapshot_id:
        raise ValueError("Saved proposal belongs to another finding/snapshot")
    change = proposal.change
    if change is None:
        if finding.suggested_change_id is not None:
            raise ValueError("Refused/unavailable proposal cannot supply a saved change")
        return None
    if (
        finding.conclusion is not Conclusion.SUPPORTED
        or change.id != finding.suggested_change_id
        or change.status is not ChangeStatus.PROPOSED
        or change.replay_probe_run_ids
        or not change.source_edits
        or change.source_scope is None
    ):
        raise ValueError("Saved change lacks exact proposed, unreplayed source provenance")
    scope = change.source_scope
    if validator.evidence(scope):
        raise ValueError("Saved proposal source scope is invalid")
    sketches = [r for r in requests if isinstance(r.answer, dict) and "edits" in r.answer]
    if len(sketches) != 1:
        raise ValueError("Saved proposal requires one raw sketch response")
    response = sketches[0]
    if (
        response.error is not None
        or response.raw_answer is None
        or json.loads(response.raw_answer) != response.answer
        or response.body.get("seed") != 42
    ):
        raise ValueError("Saved proposal raw response/seed is inconsistent")
    sketch = FixSketch.model_validate(response.answer)
    user = response.body.get("messages")
    if not isinstance(user, list):
        raise ValueError("Saved proposal request has no source packet")
    user_text = next(
        (m.get("content") for m in user if isinstance(m, dict) and m.get("role") == "user"),
        None,
    )
    if not isinstance(user_text, str):
        raise ValueError("Saved proposal user packet is missing")
    header = re.match(r"<evidence-([0-9a-f]{8}) part='([a-z][a-z0-9 -]{0,23})' path=", user_text)
    if header is None:
        raise ValueError("Saved proposal primary source header is invalid")
    # IDs for the primary cut precede read-only context. Rebuild them from the
    # frozen bytes rather than trusting the saved line labels or edit coordinates.
    language = next(f.language for f in snapshot.files if f.path == scope.path)
    source = store.read(snapshot, scope.path)
    if language is None:
        raise ValueError("Saved proposal primary language is unavailable")
    owners = [
        s
        for s in extract(scope.path, language, source, set()).symbols
        if s.kind in {SymbolKind.FUNCTION, SymbolKind.COMPONENT, SymbolKind.METHOD}
        and question.evidence
        and all(
            e.path == scope.path and s.start_line <= e.start_line <= e.end_line <= s.end_line
            for e in question.evidence
        )
    ]
    primary = min(owners, key=lambda s: s.end_line - s.start_line) if owners else None
    if primary is None or (primary.start_line, primary.end_line) != (
        scope.start_line,
        scope.end_line,
    ):
        raise ValueError("Saved proposal scope is not the question's exact primary callable")
    packet = EvidencePacket.build(
        Cut(header[2], scope.path, language, source, scope.start_line, scope.end_line),
        boundary=header[1],
    )
    closing = f"</evidence-{header[1]}>"
    block = packet.render().split(closing, 1)[0] + closing
    if not user_text.startswith(block):
        raise ValueError("Saved proposal packet differs from its frozen primary source")
    formatting = response.body.get("response_format")
    if formatting is not None and formatting != {
        "type": "json_schema",
        "json_schema": {
            "name": "fix_sketch",
            "strict": True,
            "schema": fix_sketch(packet, rule="Validate saved source edits.").schema,
        },
    }:
        raise ValueError("Saved proposal schema differs from its primary editable IDs")
    if sketch.intent != change.intent or len(sketch.edits) != len(change.source_edits):
        raise ValueError("Saved proposal differs from its raw sketch")
    for edit, saved in zip(sketch.edits, change.source_edits, strict=True):
        if (
            edit.line_id not in packet.line_ids
            or packet.location(edit.line_id) != (saved.source.path, saved.source.start_line)
            or edit.action.value != saved.action
            or edit.code != saved.code
        ):
            raise ValueError("Saved edit does not match its raw source anchor/code")
    # This validates frozen edit hashes/diff and finding association. It makes no
    # claim that the edit implements the intended protection or has run.
    if validator.finding(finding, change=change):
        # Rejections require guards supplied by the caller; proposals belong to
        # Supported findings, so rejected records cannot enter this path.
        raise ValueError("Saved proposed change failed its source/runtime boundary")
    return change
