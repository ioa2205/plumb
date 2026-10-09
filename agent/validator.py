"""The validator: claims are checked against the snapshot before they are recorded (§6).

It rejects:

- a span whose path, lines or content hash do not match the snapshot;
- a comment or docstring cited as evidence;
- an answer that cites a line it was not shown, leaves a claim uncited, or names
  something that is not on the lines it cites;
- a rejection without a guard confirmed in code;
- "reproduced", or any other statement about a test, without the probe run that
  shows it.

A guard is confirmed only when the code at its span performs the check: an
equality or membership test with the caller on one side and the resource, or
the role, on the other. A comment that describes a check, a helper whose name
promises one, and a call that merely passes both values are not checks; such a
guard has to be confirmed where the comparison is, inside the helper.

Passing the validator proves that a report is grounded in the code, not that
its interpretation is right. Evaluation measures the second (PROJECT_PLAN §11).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from agent.guard_syntax import checks
from agent.questions import (
    Answer,
    ClientExposure,
    EditAction,
    ExceptionReason,
    FixSketch,
    GuardEquivalent,
    GuardSummary,
    InputOriginAnswer,
    IntentionalException,
    Prompt,
    SinkSafety,
    Ternary,
)
from analysis.snapshot import SnapshotStore
from analysis.syntax import code_only, comparisons, span_sha256
from backend.contracts.code import Guard, GuardKind, ProjectSnapshot, SourceSpan
from backend.contracts.common import InputOrigin
from backend.contracts.investigation import (
    Conclusion,
    ExhibitRole,
    Finding,
    RuntimeVerification,
)
from backend.contracts.verification import (
    ChangeStatus,
    ProbeOutcome,
    ProbeRun,
    SnapshotRole,
    SuggestedChange,
)


class Rule(StrEnum):
    BAD_SPAN = "bad_span"
    COMMENT_CITATION = "comment_citation"
    UNKNOWN_LINE = "unknown_line"
    MISSING_CITATION = "missing_citation"
    CONSTRUCT_NOT_FOUND = "construct_not_found"
    UNCONFIRMED_REJECTION = "unconfirmed_rejection"
    UNPROVEN_RUNTIME_CLAIM = "unproven_runtime_claim"


@dataclass(frozen=True)
class Violation:
    rule: Rule
    message: str


class Unconfirmed(ValueError):
    """The code at a guard's span does not perform the check the guard claims."""

    def __init__(self, violations: list[Violation]) -> None:
        super().__init__("; ".join(violation.message for violation in violations))
        self.violations = violations


def mentions(code: str, name: str) -> bool:
    """Whether ``name`` occurs in ``code`` as a whole name.

    ``user.id`` is not in ``admin_user.id``, and ``id`` is not in ``user.id``.
    """
    return re.search(rf"(?<![\w$.]){re.escape(name)}(?![\w$])", code) is not None


# --- answers -------------------------------------------------------------------------------


def check_answer(prompt: Prompt, answer: Answer) -> list[Violation]:
    """What an answer claims, held against the evidence packet it was given."""
    packet = prompt.packet
    known = set(packet.line_ids)
    found = [
        Violation(Rule.UNKNOWN_LINE, f"{line_id} is not a line of the evidence")
        for line_id in dict.fromkeys(answer.cited())
        if line_id not in known
    ]

    def code(line_ids: list[str]) -> str:
        return "\n".join(packet.line(line_id).text for line_id in line_ids if line_id in known)

    def uncited(what: str) -> None:
        found.append(Violation(Rule.MISSING_CITATION, f"{what} cites no line"))

    def absent(name: str, line_ids: list[str]) -> None:
        found.append(
            Violation(
                Rule.CONSTRUCT_NOT_FOUND,
                f"{name} does not appear in the code of {', '.join(line_ids) or 'the cited lines'}",
            )
        )

    if isinstance(answer, GuardSummary):
        for guard in answer.guards:
            if not guard.line_ids:
                uncited(f"the {guard.kind.value} guard")
            compares = guard.kind in (GuardKind.OWNER, GuardKind.TENANT)
            if compares and (guard.subject is None or guard.object is None):
                found.append(
                    Violation(
                        Rule.CONSTRUCT_NOT_FOUND,
                        f"the {guard.kind.value} guard does not name both sides it compares",
                    )
                )
            for name in (guard.subject, guard.object):
                if name is not None and not mentions(code(guard.line_ids), name):
                    absent(name, guard.line_ids)
    elif isinstance(answer, GuardEquivalent):
        for part, line_ids in (
            ("first", answer.first_line_ids),
            ("second", answer.second_line_ids),
        ):
            own = set(packet.excerpt(part).line_ids)
            found.extend(
                Violation(Rule.UNKNOWN_LINE, f"{line_id} is not a line of the {part} part")
                for line_id in line_ids
                if line_id in known and line_id not in own
            )
            if answer.same is Ternary.YES and not line_ids:
                uncited(f"the {part} guard")
    elif isinstance(answer, InputOriginAnswer):
        if answer.origin is not InputOrigin.UNKNOWN and not answer.line_ids:
            uncited(f"the {answer.origin.value} origin")
    elif isinstance(answer, SinkSafety):
        if not answer.line_ids:
            uncited(f"the {answer.mechanism.value} answer")
    elif isinstance(answer, IntentionalException):
        if answer.reason is not ExceptionReason.NONE_FOUND and not answer.line_ids:
            uncited(f"the {answer.reason.value} reason")
    elif isinstance(answer, ClientExposure):
        for field in answer.fields:
            if not field.line_ids:
                uncited(f"the field {field.name}")
            elif not mentions(code(field.line_ids), field.name):
                absent(field.name, field.line_ids)
    elif isinstance(answer, FixSketch):
        if not answer.edits:
            uncited("the fix")
        for edit in answer.edits:
            if edit.action is not EditAction.DELETE and not edit.code.strip():
                found.append(
                    Violation(Rule.CONSTRUCT_NOT_FOUND, f"the edit on {edit.line_id} gives no code")
                )
    return found


# --- spans, guards and findings ------------------------------------------------------------


class Validator:
    """Checks claims against one snapshot. Files are read only through the snapshot store."""

    def __init__(self, snapshot: ProjectSnapshot, store: SnapshotStore) -> None:
        self._snapshot = snapshot
        self._store = store
        self._files = {file.path: file for file in snapshot.files}
        self._sources: dict[str, bytes] = {}
        self._code: dict[str, bytes] = {}
        self._confirmed: dict[tuple[str, str | None, str | None], Guard] = {}

    def _source(self, path: str) -> bytes:
        if path not in self._sources:
            self._sources[path] = self._store.read(self._snapshot, path)
        return self._sources[path]

    def source_if_present(self, path: str) -> bytes | None:
        return self._source(path) if path in self._files else None

    def span(self, span: SourceSpan) -> list[Violation]:
        """Does this citation point at lines that exist, with the content it recorded?"""
        where = f"{span.path}:{span.start_line}-{span.end_line}"
        if span.snapshot_id != self._snapshot.id:
            return [Violation(Rule.BAD_SPAN, f"{where} cites another snapshot")]
        if span.path not in self._files:
            return [Violation(Rule.BAD_SPAN, f"{span.path} is not a file of the snapshot")]
        source = self._source(span.path)
        total = source.count(b"\n") + (0 if source.endswith(b"\n") or not source else 1)
        if span.end_line > total:
            return [Violation(Rule.BAD_SPAN, f"{where} is outside the file ({total} lines)")]
        if span_sha256(source, span.start_line, span.end_line) != span.content_sha256:
            return [Violation(Rule.BAD_SPAN, f"{where} does not have the content it was cited for")]
        return []

    def evidence(self, span: SourceSpan) -> list[Violation]:
        """A valid span that holds code, so that it can count as evidence."""
        if violations := self.span(span):
            return violations
        if span.path not in self._code:
            self._code[span.path] = code_only(
                self._files[span.path].language, self._source(span.path)
            )
        code = self._code[span.path]
        lines = code.decode("utf-8", errors="replace").split("\n")
        if not any(line.strip() for line in lines[span.start_line - 1 : span.end_line]):
            return [
                Violation(
                    Rule.COMMENT_CITATION,
                    f"{span.path}:{span.start_line}-{span.end_line} holds no code; "
                    "comments and docstrings are never evidence",
                )
            ]
        return []

    def confirm(
        self, guard: Guard, *, subject: str | None = None, object: str | None = None
    ) -> Guard:
        # This validator already owns verified immutable source bytes for one snapshot.
        # Repeated peer rows often cite the same guard. Cache the full record and caller
        # operands, never just an ID; a changed claim must undergo validation again.
        key = (guard.model_dump_json(), subject, object)
        if key not in self._confirmed:
            self._confirmed[key] = self._confirm(guard, subject=subject, object=object)
        return self._confirmed[key].model_copy(deep=True)

    def _confirm(
        self, guard: Guard, *, subject: str | None = None, object: str | None = None
    ) -> Guard:
        """``guard`` marked confirmed, with its span narrowed to the check found in code.

        ``subject`` and ``object`` are the two sides as the code writes them (``user.id``,
        ``order.customer_id``); the guard's own fields may hold canonical names. A role
        guard is looked up by ``guard.role``. Raises ``Unconfirmed`` when the span holds
        no such test.
        """

        def refuse(message: str) -> Unconfirmed:
            return Unconfirmed([Violation(Rule.UNCONFIRMED_REJECTION, message)])

        if violations := self.evidence(guard.span):
            raise Unconfirmed(violations)
        if guard.optimistic:
            raise refuse("a proxy matcher is an optimistic routing layer, never a guard")
        if guard.kind is GuardKind.MINIMIZED:
            import json
            from pathlib import Path
            from tempfile import TemporaryDirectory

            from analysis.index import Index, index_path
            from analysis.nextjs import extract_nextjs
            from analysis.serialization import minimized
            from analysis.typescript_resolution import TypeScriptUnavailable

            try:
                names = json.loads(guard.role or "null")
                if (
                    not isinstance(names, list)
                    or not 0 < len(names) <= 100
                    or any(not isinstance(n, str) or not n.isidentifier() for n in names)
                    or guard.mechanism.value != "data_access_layer"
                    or guard.via_symbol_id is None
                    or guard.object is None
                ):
                    raise refuse(
                        "minimization needs explicit source fields and callable/query identities"
                    )
                # Rebuild from immutable source, never accept caller-supplied flow facts.
                if not hasattr(self, "_serialization"):
                    with TemporaryDirectory(prefix="plumb-serialization-") as directory:
                        cache = Path(directory)
                        index = Index.build(
                            self._snapshot, self._store, index_path(cache, self._snapshot.id)
                        )
                        try:
                            self._serialization = extract_nextjs(
                                self._snapshot, self._store, index, cache
                            )
                        finally:
                            index.close()
                if not minimized(
                    self._serialization, guard.via_symbol_id, guard.object, guard.span, names
                ):
                    raise refuse(
                        "complete source-bound omission of the declared fields was not proven"
                    )
            except (ValueError, TypeError, TypeScriptUnavailable) as error:
                raise refuse(f"minimization source confirmation unavailable: {error}") from error
            return Guard.model_validate({**guard.model_dump(), "confirmed": True})
        language = self._files[guard.span.path].language
        source = self._source(guard.span.path)
        if guard.kind in (GuardKind.PARAMETERIZED, GuardKind.ALLOWLISTED, GuardKind.CONTAINED):
            from analysis.sinks import sinks

            matches = [
                s
                for s in sinks(source)
                if s.kind == guard.role
                and str(s.focus) == guard.object
                and s.mechanism == guard.kind.value
                and not s.issues
                and guard.span.start_line <= s.start <= s.end <= guard.span.end_line
            ]
            if language is None or language.value != "python" or len(matches) != 1:
                raise refuse("no source-confirmed safety check applies to this exact sink")
            return Guard.model_validate({**guard.model_dump(), "confirmed": True})
        if language is not None:
            for check in checks(
                language,
                source,
                guard.span.start_line,
                guard.span.end_line,
                path=guard.span.path,
                read=self.source_if_present,
            ):
                pair = (subject, object)
                held = (
                    (
                        guard.kind in (GuardKind.OWNER, GuardKind.TENANT)
                        and subject is not None
                        and object is not None
                        and (pair in check.pairs or pair[::-1] in check.pairs)
                    )
                    or (guard.kind is GuardKind.AUTHENTICATED and check.authentication)
                    or (
                        guard.kind is GuardKind.ROLE
                        and guard.role is not None
                        and guard.role == ("|".join(check.roles) or check.role_parameter)
                    )
                )
                if held:
                    # Keep denial/query arguments in the proof span so exports can recheck it.
                    span = SourceSpan(
                        snapshot_id=self._snapshot.id,
                        path=guard.span.path,
                        start_line=check.start,
                        end_line=check.end,
                        content_sha256=span_sha256(source, check.start, check.end),
                    )
                    return Guard.model_validate(
                        {**guard.model_dump(), "span": span.model_dump(), "confirmed": True}
                    )
        if guard.mechanism.value == "query_filter":
            raise refuse("no enforced query filter with those bound expressions was found")
        if guard.kind in (GuardKind.OWNER, GuardKind.TENANT):
            if subject is None or object is None:
                raise refuse(f"a {guard.kind.value} guard needs both sides it compares")
            sides = [subject, object]
            wanted = f"{subject} against {object}"
        elif guard.kind is GuardKind.ROLE:
            if guard.role is None:
                raise refuse("a role guard needs the role it requires")
            sides = [f'"{guard.role}"', f"'{guard.role}'"]
            wanted = f"the role {guard.role}"
        else:
            raise refuse(f"no check in code can be recognized for a {guard.kind.value} guard yet")
        language = self._files[guard.span.path].language
        if language is None:
            raise refuse(f"{guard.span.path} is not in a language whose checks can be read")
        source = self._source(guard.span.path)
        for test in comparisons(language, code_only(language, source)):
            if not guard.span.start_line <= test.start_line <= test.end_line <= guard.span.end_line:
                continue
            left, right = test.operands
            if guard.kind is GuardKind.ROLE:
                held = any(side in left or side in right for side in sides)
            else:
                held = (mentions(left, sides[0]) and mentions(right, sides[1])) or (
                    mentions(left, sides[1]) and mentions(right, sides[0])
                )
            if held:
                span = SourceSpan(
                    snapshot_id=self._snapshot.id,
                    path=guard.span.path,
                    start_line=test.start_line,
                    end_line=test.end_line,
                    content_sha256=span_sha256(source, test.start_line, test.end_line),
                )
                return Guard.model_validate(
                    {**guard.model_dump(), "span": span.model_dump(), "confirmed": True}
                )
        raise refuse(
            f"{guard.span.path}:{guard.span.start_line}-{guard.span.end_line} "
            f"holds no test of {wanted}"
        )

    def finding(
        self,
        finding: Finding,
        *,
        guards: Sequence[Guard] = (),
        probe_runs: Sequence[ProbeRun] = (),
        change: SuggestedChange | None = None,
    ) -> list[Violation]:
        """Everything a finding claims, held against the snapshot and the records."""
        if finding.snapshot_id != self._snapshot.id:
            return [Violation(Rule.BAD_SPAN, f"{finding.display_id} belongs to another snapshot")]
        found: list[Violation] = []
        for exhibit in finding.exhibits:
            note = exhibit.role is ExhibitRole.DEVELOPER_NOTE
            found.extend(self.span(exhibit.span) if note else self.evidence(exhibit.span))
        found.extend(self._rejection(finding, guards))
        found.extend(self._runtime(finding, probe_runs))
        found.extend(self._change(finding, probe_runs, change))
        return found

    def _rejection(self, finding: Finding, guards: Sequence[Guard]) -> list[Violation]:
        if finding.conclusion is not Conclusion.REJECTED:
            return []
        by_tag = {exhibit.tag: exhibit for exhibit in finding.exhibits}
        cited = [
            by_tag[check.exhibit_tag].span
            for check in finding.checks
            if check.found
            and check.exhibit_tag is not None
            and by_tag[check.exhibit_tag].role is ExhibitRole.GUARD
        ]
        for guard in guards:
            usable = (
                guard.confirmed
                and not guard.optimistic
                and guard.kind not in (GuardKind.NONE, GuardKind.UNKNOWN)
                and not self.evidence(guard.span)
            )
            # The exhibit may show context around the check; the guard must lie inside it.
            if usable and any(
                span.path == guard.span.path
                and span.start_line <= guard.span.start_line
                and guard.span.end_line <= span.end_line
                for span in cited
            ):
                return []
        return [
            Violation(
                Rule.UNCONFIRMED_REJECTION,
                f"{finding.display_id} is rejected without a guard confirmed in code",
            )
        ]

    def _runtime(self, finding: Finding, probe_runs: Sequence[ProbeRun]) -> list[Violation]:
        def unproven(message: str) -> Violation:
            return Violation(Rule.UNPROVEN_RUNTIME_CLAIM, f"{finding.display_id} {message}")

        on_record = {run.id: run for run in probe_runs}
        found = [
            unproven(f"cites probe run {run_id}, which is not on record")
            for run_id in finding.probe_run_ids
            if run_id not in on_record
        ]
        runs = [on_record[run_id] for run_id in finding.probe_run_ids if run_id in on_record]
        own = [
            run
            for run in runs
            if run.finding_id == finding.id
            and run.snapshot_id == finding.snapshot_id
            and run.snapshot_role is SnapshotRole.VULNERABLE
        ]
        if len(own) != len(runs):
            found.append(unproven("cites a probe run of another finding or snapshot"))
        outcomes = {run.outcome for run in own}
        claim = finding.runtime_verification
        needs = {
            RuntimeVerification.REPRODUCED: ProbeOutcome.REPRODUCED,
            RuntimeVerification.NOT_REPRODUCED: ProbeOutcome.NOT_REPRODUCED,
            RuntimeVerification.INCONCLUSIVE: ProbeOutcome.INCONCLUSIVE,
        }
        if claim in needs and needs[claim] not in outcomes:
            found.append(
                unproven(
                    f"says '{claim.value}', and no probe run on record ended that way: "
                    "an attack and a control must both have run"
                )
            )
        if claim is RuntimeVerification.NOT_REPRODUCED and ProbeOutcome.REPRODUCED in outcomes:
            found.append(unproven("says 'not_reproduced', and a probe run reproduced it"))
        untested = (RuntimeVerification.NOT_ATTEMPTED, RuntimeVerification.UNAVAILABLE)
        if claim in untested and finding.probe_run_ids:
            found.append(unproven(f"says '{claim.value}' and cites probe runs"))
        return found

    def _change(
        self, finding: Finding, probe_runs: Sequence[ProbeRun], change: SuggestedChange | None
    ) -> list[Violation]:
        def unproven(message: str) -> Violation:
            return Violation(Rule.UNPROVEN_RUNTIME_CLAIM, f"{finding.display_id} {message}")

        if change is None:
            cited = finding.suggested_change_id is not None
            return [unproven("cites a suggested change that is not on record")] if cited else []
        if change.id != finding.suggested_change_id or change.finding_id != finding.id:
            return [unproven("and the suggested change do not refer to each other")]
        if change.source_edits:
            from analysis.patches import construct

            try:
                scope = change.source_scope
                if scope is None or change.snapshot_id != finding.snapshot_id:
                    raise ValueError("wrong frozen change snapshot")
                if self.evidence(scope):
                    raise ValueError("invalid change scope citation")
                if not any(
                    e.role is not ExhibitRole.DEVELOPER_NOTE
                    and e.span.path == scope.path
                    and scope.start_line <= e.span.end_line
                    and e.span.start_line <= scope.end_line
                    for e in finding.exhibits
                ):
                    raise ValueError("change scope is unrelated to finding evidence")
                if (
                    construct(self._snapshot, self._store, scope, change.source_edits)
                    != change.diff
                ):
                    raise ValueError("diff differs from its frozen edits")
            except (ValueError, OSError, UnicodeError, SyntaxError):
                return [
                    Violation(
                        Rule.BAD_SPAN, "the proposed diff does not match its frozen source edits"
                    )
                ]
        found = [
            Violation(Rule.BAD_SPAN, f"the suggested change edits {path}, not a snapshot file")
            for path in change.files
            if path not in self._files
        ]
        on_record = {run.id: run for run in probe_runs}
        replays = [
            on_record[run_id]
            for run_id in change.replay_probe_run_ids
            if run_id in on_record
            and on_record[run_id].finding_id == finding.id
            and on_record[run_id].snapshot_role is SnapshotRole.PATCHED
        ]
        if len(replays) != len(change.replay_probe_run_ids):
            found.append(unproven("cites a fix replay that is not on record for its patched copy"))
        outcomes = {run.outcome for run in replays}
        fixed = change.status is ChangeStatus.REPLAYED_FIXED
        if fixed and (ProbeOutcome.FIXED not in outcomes or ProbeOutcome.NOT_FIXED in outcomes):
            found.append(
                unproven(
                    "says the fix was replayed, and no replay shows the attack denied "
                    "with the control still allowed"
                )
            )
        not_fixed = change.status is ChangeStatus.REPLAYED_NOT_FIXED
        if not_fixed and ProbeOutcome.NOT_FIXED not in outcomes:
            found.append(unproven("says the fix failed its replay, and no replay shows that"))
        return found
