"""One bounded fix-sketch request after Supported, distinct from the verdict."""

import hashlib

from agent.evidence import Cut, EvidencePacket
from agent.guards import Ask
from agent.llm import BudgetStop, ModelError, Spend
from agent.questions import FixSketch, fix_sketch
from agent.validator import Validator, check_answer
from analysis.patches import TrivialEdit, construct
from analysis.snapshot import SnapshotStore
from analysis.syntax import span_sha256
from backend.contracts.code import ProjectSnapshot, SourceSpan
from backend.contracts.investigation import Conclusion, Finding
from backend.contracts.verification import FixProposal, SourceEdit, SuggestedChange
from backend.redaction import Redactor
from verification.proposals import regression

VERSION = "frozen-fix-proposal-3"


def propose(
    finding: Finding,
    scope: Cut,
    context: list[Cut],
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    model: Ask,
    spend: Spend,
    *,
    rule: str,
) -> FixProposal:
    identity = (
        "proposal:"
        + hashlib.sha256(f"{finding.id}:{snapshot.id}:{VERSION}".encode()).hexdigest()[:24]
    )

    def stopped(status: str, reason: str) -> FixProposal:
        return FixProposal.model_validate(
            dict(
                id=identity,
                finding_id=finding.id,
                snapshot_id=snapshot.id,
                status=status,
                reason=reason,
                probe_reason=(
                    "No validated change/probe mapping was produced; verification unavailable."
                ),
            )
        )

    if finding.conclusion is not Conclusion.SUPPORTED or finding.suggested_change_id is not None:
        return stopped(
            "refused",
            "Only a Supported finding without a saved change is eligible; overwrite refused.",
        )
    try:
        if finding.snapshot_id != snapshot.id or any(
            cut.source != store.read(snapshot, cut.path) for cut in [scope, *context]
        ):
            return stopped("refused", "Proposal evidence does not match the frozen source.")
    except (ValueError, OSError):
        return stopped("refused", "Proposal source is not an included frozen file.")
    if spend.prompt_tokens_left <= 0 or spend.seconds_left <= 0:
        return stopped("unavailable", "The finding's remaining proposal budget is exhausted.")
    try:
        packet = EvidencePacket.build(scope, *context)
        allowed = packet.excerpt(scope.label).line_ids
        prompt = fix_sketch(packet, rule=rule, editable=tuple(allowed))
        raw = model.ask(prompt.request(max_tokens=768), spend)
        try:
            sketch = FixSketch.model_validate(raw.data)
        except ValueError:
            return stopped("refused", "Fix sketch does not match the bounded answer schema.")
        if check_answer(prompt, sketch) or not 1 <= len(sketch.edits) <= 4:
            return stopped("refused", "Fix sketch has invalid or missing source-line edits.")
        if not sketch.intent.strip() or len(sketch.intent) > 400:
            return stopped("refused", "Fix sketch intent is empty or exceeds its bound.")
        file = next(f for f in snapshot.files if f.path == scope.path)
        source_scope = SourceSpan(
            snapshot_id=snapshot.id,
            path=scope.path,
            start_line=scope.start,
            end_line=scope.end,
            content_sha256=span_sha256(scope.source, scope.start, scope.end),
        )
        edits = []
        for edit in sketch.edits:
            if edit.line_id not in allowed:
                return stopped(
                    "refused",
                    "Edit attempts to change context outside the finding's primary source unit.",
                )
            line = packet.line(edit.line_id).number
            edits.append(
                SourceEdit.model_validate(
                    dict(
                        source=SourceSpan(
                            snapshot_id=snapshot.id,
                            path=scope.path,
                            start_line=line,
                            end_line=line,
                            content_sha256=span_sha256(scope.source, line, line),
                        ),
                        file_sha256=file.sha256,
                        action=edit.action.value,
                        code=edit.code,
                    )
                )
            )
        try:
            diff = construct(snapshot, store, source_scope, edits, require_code_change=True)
        except TrivialEdit:
            return stopped(
                "refused",
                "Proposed edits only change whitespace, comments or docstrings; "
                "no executable protection was added.",
            )
        except SyntaxError:
            return stopped(
                "refused", "Proposed code has invalid syntax; preserve indentation and punctuation."
            )
        except ValueError:
            return stopped(
                "refused",
                "Frozen-source patch construction refused: syntax, no-change, overlap "
                "or source bounds.",
            )
        if Redactor.configured().text(sketch.intent) != sketch.intent:
            return stopped("refused", "Proposal text contains credential-shaped content.")
        change = SuggestedChange(
            id="change:" + identity.split(":", 1)[1],
            finding_id=finding.id,
            intent=sketch.intent,
            diff=diff,
            files=[scope.path],
            snapshot_id=snapshot.id,
            source_scope=source_scope,
            source_edits=edits,
        )
        updated = finding.model_copy(update={"suggested_change_id": change.id})
        if Validator(snapshot, store)._change(updated, [], change):
            return stopped(
                "refused", "Proposed edit did not pass the frozen finding/evidence boundary."
            )
        try:
            spec, manifest, reason = regression(finding, sketch.probe, snapshot, store)
        except (ValueError, OSError, KeyError, TypeError):
            spec, manifest, reason = (
                None,
                None,
                "Trusted probe fixture/adapter mapping is unavailable; no probe was executed.",
            )
        return FixProposal(
            id=identity,
            finding_id=finding.id,
            snapshot_id=snapshot.id,
            status="proposed",
            reason=(
                "Validated frozen-source proposal; not applied, tested or proven "
                "to fix the finding."
            ),
            change=change,
            probe_status="available" if spec else "unavailable",
            probe_reason=reason,
            probe_spec=spec,
            adapter_manifest_sha256=manifest,
        )
    except (BudgetStop, ModelError):
        return stopped(
            "unavailable", "The bounded fix-sketch request ended without a complete answer."
        )
    except (ValueError, KeyError, TypeError, SyntaxError, UnicodeError, OSError):
        return stopped(
            "refused",
            "Fix sketch, source edit or adapter mapping is invalid or unsupported; "
            "no target was changed.",
        )
