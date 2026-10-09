"""Three-judgment sink investigations with source-confirmed acquittal evidence."""

import ast
import hashlib
import random
from dataclasses import replace

from pydantic import Field

from agent.challenge import CHECKLISTS
from agent.evidence import Cut, EvidencePacket
from agent.guards import Ask
from agent.llm import Spend
from agent.questions import SinkKind, SinkMechanism, SinkSafety, sink_safety
from agent.validator import Validator, check_answer
from analysis.index import Index
from analysis.provenance import Provenance
from analysis.sinks import SinkFact, sinks
from analysis.snapshot import SnapshotStore
from backend.contracts.code import Guard, GuardKind, GuardMechanism, ProjectSnapshot, SourceSpan
from backend.contracts.common import Contract, Family, Language
from backend.contracts.investigation import (
    ChallengeCheck,
    Conclusion,
    EvidenceStrength,
    Exhibit,
    ExhibitRole,
    Finding,
    Severity,
)


class SinkSample(Contract):
    seed: int
    answer: SinkSafety
    violations: list[str] = Field(default_factory=list)


class SinkResult(Contract):
    signal_id: str
    family: Family
    kind: SinkKind
    conclusion: Conclusion
    rationale: str
    evidence: list[SourceSpan]
    guards: list[Guard]
    samples: list[SinkSample]
    issues: list[str]
    flow_notes: list[str] = Field(default=[])


class SinkInvestigator:
    def __init__(self, snapshot: ProjectSnapshot, store: SnapshotStore, index: Index) -> None:
        self.snapshot, self.store, self.index = snapshot, store, index
        self.validator = Validator(snapshot, store)
        provenance = Provenance(snapshot, store, index)
        self.facts: dict[str, tuple[str, SinkFact]] = {}
        for file in snapshot.files:
            if file.language is not Language.PYTHON:
                continue
            for fact in sinks(store.read(snapshot, file.path)):
                if fact.mechanism == "none_found":
                    flow = provenance.flow(file.path, fact.start, fact.focus)
                    issues = tuple(
                        i for i in fact.issues if i != "Unresolved call or stored-value provenance"
                    )
                    if not flow.inputs and flow.unknowns:
                        issues = (*issues, "Unresolved call or stored-value provenance")
                    fact = replace(
                        fact,
                        inputs=tuple(sorted(flow.inputs)),
                        risky=fact.risky and bool(flow.inputs),
                        issues=issues,
                        provenance=flow.evidence,
                        flow_notes=flow.unknowns,
                    )
                identity = (
                    "sink:"
                    + hashlib.sha256(
                        f"{file.path}:{fact.start}:{fact.focus}:{fact.kind}".encode()
                    ).hexdigest()[:24]
                )
                self.facts[identity] = (file.path, fact)

    def family(self, signal: str) -> Family:
        return Family.PATH_TRAVERSAL if self.facts[signal][1].kind == "path" else Family.INJECTION

    def cuts(self, signal: str) -> list[Cut]:
        path, fact = self.facts[signal]
        source = self.store.read(self.snapshot, path)
        cuts = [Cut("operation", path, Language.PYTHON, source, fact.start, fact.end)]
        for n, span in enumerate(fact.provenance):
            if not isinstance(span, SourceSpan) or self.validator.evidence(span):
                raise ValueError("Provenance source citation cannot be validated")
            if any(
                c.path == span.path and c.start <= span.start_line and c.end >= span.end_line
                for c in cuts
            ):
                continue
            cuts.append(
                Cut(
                    f"provenance {n + 1}",
                    span.path,
                    Language.PYTHON,
                    self.store.read(self.snapshot, span.path),
                    span.start_line,
                    span.end_line,
                )
            )
        # Literal allowlists are executable configuration, never names or comments.
        from analysis.syntax import code_only

        tree = ast.parse(code_only(Language.PYTHON, source))
        constants = [
            n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict)
        ]
        for n in constants:
            names = [t.id for t in n.targets if isinstance(t, ast.Name)]
            body = source.decode().splitlines()[fact.start - 1 : fact.end]
            if any(name in "\n".join(body) for name in names):
                cuts.append(
                    Cut(
                        "literal mapping",
                        path,
                        Language.PYTHON,
                        source,
                        n.lineno,
                        n.end_lineno or n.lineno,
                    )
                )
        return cuts

    def investigate(
        self, signal: str, model: Ask, spend: Spend, *, judgments: int = 3
    ) -> SinkResult:
        if isinstance(judgments, bool) or judgments not in (1, 3):
            raise ValueError("Only production three or experimental one judgment is supported")
        path, fact = self.facts[signal]
        family, kind = self.family(signal), SinkKind(fact.kind)
        cuts = self.cuts(signal)
        # Point at the actual operation operand, rather than the call's first
        # line alone. This supplies source locations, never a mechanism/verdict.
        from analysis.syntax import code_only

        tree = ast.parse(code_only(Language.PYTHON, self.store.read(self.snapshot, path)))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.lineno == fact.focus]
        outer = [
            n
            for n in calls
            if not any(n is not parent and n in list(ast.walk(parent)) for parent in calls)
        ]
        operand = outer[0].args[0] if len(outer) == 1 and outer[0].args else None
        operand_lines = (
            range(operand.lineno, (operand.end_lineno or operand.lineno) + 1)
            if operand is not None and kind in (SinkKind.SQL, SinkKind.COMMAND)
            else ()
        )
        samples = []
        from analysis.syntax import span_sha256

        spans = [
            SourceSpan(
                snapshot_id=self.snapshot.id,
                path=c.path,
                start_line=c.start,
                end_line=c.end,
                content_sha256=span_sha256(c.source, c.start, c.end),
            )
            for c in cuts
        ]
        guards = []
        if fact.mechanism != "none_found" and not fact.issues:
            guard = Guard(
                id="guard:" + signal.split(":", 1)[1],
                snapshot_id=self.snapshot.id,
                kind=GuardKind(fact.mechanism),
                canonical=f"{fact.mechanism}({kind}, {path}:{fact.focus})",
                mechanism=GuardMechanism.COMPARISON,
                span=spans[0],
                role=kind.value,
                object=str(fact.focus),
            )
            guards.append(self.validator.confirm(guard))
        for number in range(judgments):
            order = list(cuts)
            random.Random(42 + number).shuffle(order)  # noqa: S311 - reproducible evidence order
            packet = EvidencePacket.build(*order)
            focus = next(
                line for line in packet.line_ids if packet.location(line) == (path, fact.focus)
            )
            prompt = sink_safety(
                packet,
                sink=kind,
                at=focus,
                inputs=fact.inputs if kind is SinkKind.SQL else (),
                argument_lines=tuple(
                    line
                    for line in packet.line_ids
                    if packet.location(line)[0] == path
                    and packet.location(line)[1] in operand_lines
                ),
            )
            answer = prompt.parse(model.ask(prompt.request(seed=42 + number), spend).data)
            if not isinstance(answer, SinkSafety):
                raise TypeError("sink-safety answer required")
            errors = [v.message for v in check_answer(prompt, answer)]
            if answer.mechanism.value != fact.mechanism:
                errors.append("judgment contradicts the recognized executable sink form")
            locations = [
                packet.location(line) for line in answer.line_ids if line in packet.line_ids
            ]
            if not any(p == path and fact.start <= n <= fact.end for p, n in locations):
                errors.append("judgment does not cite the investigated function")
            samples.append(SinkSample(seed=42 + number, answer=answer, violations=errors))
        mechanisms = {s.answer.mechanism for s in samples}
        if fact.issues or len(mechanisms) != 1 or any(s.violations for s in samples):
            conclusion, rationale = (
                Conclusion.INCONCLUSIVE,
                "Unsupported flow, disagreement or unconfirmed safety evidence",
            )
        elif guards:
            conclusion, rationale = (
                Conclusion.REJECTED,
                ("Three judgments" if judgments == 3 else "One experimental judgment")
                + " agree with a source-confirmed protection for this exact sink",
            )
        elif fact.risky and next(iter(mechanisms)) is SinkMechanism.NONE_FOUND:
            conclusion, rationale = (
                Conclusion.SUPPORTED,
                "Request-derived data reaches the operation; "
                "the bounded acquittal search found no protection",
            )
        else:
            conclusion, rationale = (
                Conclusion.INCONCLUSIVE,
                "Controllable unsafe data flow was not established",
            )
        return SinkResult(
            signal_id=signal,
            family=family,
            kind=kind,
            conclusion=conclusion,
            rationale=rationale,
            evidence=spans,
            guards=guards,
            samples=samples,
            issues=list(fact.issues),
            flow_notes=list(fact.flow_notes),
        )


def finding(result: SinkResult, *, run_id: str, display_id: str) -> Finding:
    exhibits = [
        Exhibit(
            tag=f"E{i:02d}",
            span=s,
            role=ExhibitRole.GUARD if i == 1 and result.guards else ExhibitRole.SINK,
            gloss="Code searched for sink protections",
        )
        for i, s in enumerate(result.evidence, 1)
    ]
    checks = [
        ChallengeCheck(
            item=item,
            searched="; ".join(f"{s.path}:{s.start_line}-{s.end_line}" for s in result.evidence),
            found=bool(result.guards) and i == (1 if result.kind is SinkKind.COMMAND else 0),
            exhibit_tag="E01"
            if result.guards and i == (1 if result.kind is SinkKind.COMMAND else 0)
            else None,
        )
        for i, item in enumerate(CHECKLISTS[result.family])
    ]
    return Finding(
        id="finding:" + hashlib.sha256(f"{run_id}:{result.signal_id}".encode()).hexdigest()[:24],
        display_id=display_id,
        run_id=run_id,
        snapshot_id=result.evidence[0].snapshot_id,
        family=result.family,
        cwe=[89 if result.kind is SinkKind.SQL else 78 if result.kind is SinkKind.COMMAND else 22],
        title=f"{result.kind.value} operation safety",
        lede=result.rationale,
        conclusion=result.conclusion,
        severity=Severity.UNKNOWN,
        severity_rationale="Impact has not been assessed",
        strength=EvidenceStrength.PARTIAL,
        gaps=["Bounded local source flow; runtime verification not attempted", *result.issues],
        exhibits=exhibits,
        checks=checks,
        unknowns=result.flow_notes,
    )
