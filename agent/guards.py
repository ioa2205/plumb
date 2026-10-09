"""Cited local guard summaries, canonical forms and a versioned helper cache (M3.4).

The resolver owns which helpers are on a path. This module summarizes one exact
symbol; it never follows a name, executes a target, or treats a cached claim as proof.
"""

import ast
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol

from pydantic import Field

from agent.evidence import Cut, EvidencePacket
from agent.guard_syntax import Check, checks
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.questions import GuardSummary, guard_summary
from agent.validator import Unconfirmed, Validator, check_answer
from analysis.snapshot import SnapshotStore
from analysis.syntax import code_only
from backend.contracts.code import Guard, GuardKind, ProjectSnapshot, SourceSpan, Symbol
from backend.contracts.common import Contract

VERSION = 4


def _possible_kinds(candidate: Check) -> tuple[GuardKind, ...]:
    """Policy possibilities from executable constructs, never names or model answers."""
    possible = [GuardKind.NONE, GuardKind.UNKNOWN]
    if candidate.pairs:
        possible.extend((GuardKind.OWNER, GuardKind.TENANT))
    if candidate.authentication:
        possible.append(GuardKind.AUTHENTICATED)
    if candidate.roles or candidate.role_parameter:
        possible.append(GuardKind.ROLE)
    return tuple(possible)


def recognizer_identity() -> str:
    root = Path(__file__).parent
    return hashlib.sha256(
        b"".join(
            (root / name).read_bytes()
            for name in (
                "guards.py",
                "guard_syntax.py",
                "ts_role_guards.py",
                "ts_guard_forms.py",
                "ts_paths.py",
            )
        )
    ).hexdigest()


def _orientation(
    symbol: Symbol, source: bytes, candidate: Check, resource: str | None
) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    if not candidate.pairs:
        return (), ()
    if candidate.mechanism.value == "query_filter" and (
        symbol.language.value != "python" or candidate.resource is not None
    ):
        return tuple(b for _, b in candidate.pairs), tuple(a for a, _ in candidate.pairs)
    if symbol.language.value != "python" or resource is None:
        return None, None
    try:
        tree = ast.parse(code_only(symbol.language, source))
    except SyntaxError:
        return None, None
    records = {resource}
    functions = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        and n.lineno <= candidate.focus <= (n.end_lineno or n.lineno)
    ]
    if not functions:
        return None, None
    function = max(functions, key=lambda f: f.lineno)
    for node in ast.walk(function):
        if (
            isinstance(node, ast.arg)
            and isinstance(node.annotation, ast.Name)
            and node.annotation.id == resource
        ):
            records.add(node.arg)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            call = node.value
            if (
                isinstance(node.targets[0], ast.Name)
                and isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == resource
            ):
                records.add(node.targets[0].id)
    oriented = []
    for a, b in candidate.pairs:
        a_record, b_record = a.split(".")[0] in records, b.split(".")[0] in records
        if a_record == b_record:
            return None, None
        oriented.append((b, a) if a_record else (a, b))
    return tuple(a for a, _ in oriented), tuple(b for _, b in oriented)


class Ask(Protocol):
    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer: ...


class Summary(Contract):
    symbol_id: str
    snapshot_id: str
    span: SourceSpan
    guards: list[Guard]
    issues: list[str] = Field(default_factory=list)
    # Empty guards means no recognized LOCAL check. It never proves an entire path is unguarded.


class SummaryCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS summaries (key TEXT PRIMARY KEY, payload TEXT)")

    def get(self, key: str) -> Summary | None:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT payload FROM summaries WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return Summary.model_validate_json(row[0])
        except ValueError:
            return None

    def put(self, key: str, summary: Summary) -> None:
        if summary.issues:
            return
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO summaries VALUES (?, ?)", (key, summary.model_dump_json())
            )


def canonical(
    kind: GuardKind, subject: str | None, object: str | None, role: str | None, resource: str | None
) -> str:
    if kind is GuardKind.AUTHENTICATED:
        return "AUTHN"
    if kind is GuardKind.ROLE:
        return f"ROLE({role})"
    if kind not in (GuardKind.OWNER, GuardKind.TENANT) or subject is None or object is None:
        return kind.value.upper()

    def field(value: str) -> str:
        # Only spelling is normalized; raw expressions remain in the guard for validation.
        last = value.rsplit(".", 1)[-1]
        return re.sub(r"(?<!^)(?=[A-Z])", "_", last).lower()

    target = f"{resource}.{field(object)}" if resource else object
    return f"{kind.value.upper()}({target} = principal.{field(subject)})"


class Classifier:
    def __init__(
        self,
        snapshot: ProjectSnapshot,
        store: SnapshotStore,
        model: Ask,
        cache: SummaryCache,
        *,
        identity: str,
        cached_only: bool = False,
    ) -> None:
        if not identity:
            raise ValueError("model/runtime/profile identity must be explicit")
        self.snapshot, self.store, self.model, self.cache = snapshot, store, model, cache
        self.identity = identity
        self.recognizer_sha256 = recognizer_identity()
        self.cached_only = cached_only
        self.validator = Validator(snapshot, store)
        self.cache_hits = 0

    def classify(
        self,
        symbol: Symbol,
        spend: Spend,
        *,
        resource: str | None = None,
        context: tuple[Symbol, ...] = (),
        required_kind: GuardKind | None = None,
    ) -> Summary:
        # Scoped summaries omit only checks structurally unable to establish this kind.
        # An unknown candidate still needs investigation; selection supplies no verdict.
        if required_kind is not None and required_kind not in (
            GuardKind.AUTHENTICATED,
            GuardKind.OWNER,
            GuardKind.TENANT,
            GuardKind.ROLE,
        ):
            raise ValueError("required kind must be an executable authorization guard kind")
        if resource is not None and re.fullmatch(r"[A-Za-z_]\w*", resource) is None:
            raise ValueError("resource must be a plain identifier")
        if symbol.snapshot_id != self.snapshot.id or symbol.span.snapshot_id != self.snapshot.id:
            raise ValueError("summary and symbol must use this snapshot")
        if violations := self.validator.evidence(symbol.span):
            raise Unconfirmed(violations)
        source = self.store.read(self.snapshot, symbol.span.path)
        related = []
        for index, extra in enumerate(context):
            if extra.snapshot_id != self.snapshot.id or (
                violations := self.validator.evidence(extra.span)
            ):
                raise ValueError("context must cite valid code in this snapshot")
            if (
                next(f.language for f in self.snapshot.files if f.path == extra.span.path)
                != extra.language
            ):
                raise ValueError("context language differs from the snapshot file")
            related.append(
                Cut(
                    f"context {index}",
                    extra.span.path,
                    extra.language,
                    self.store.read(self.snapshot, extra.span.path),
                    extra.span.start_line,
                    extra.span.end_line,
                )
            )
        if (
            next(f.language for f in self.snapshot.files if f.path == symbol.span.path)
            != symbol.language
        ):
            raise ValueError("symbol language differs from the snapshot file")
        candidates = checks(
            symbol.language,
            source,
            symbol.span.start_line,
            symbol.span.end_line,
            path=symbol.span.path,
            read=self.validator.source_if_present,
        )
        if required_kind is not None:
            candidates = [
                candidate
                for candidate in candidates
                if required_kind in _possible_kinds(candidate)
                or _possible_kinds(candidate) == (GuardKind.NONE, GuardKind.UNKNOWN)
            ]
        prompts = []
        for candidate in candidates:
            packet = EvidencePacket.build(
                Cut(
                    "check",
                    symbol.span.path,
                    symbol.language,
                    source,
                    candidate.start,
                    candidate.end,
                ),
                *candidate.context,
                *related,
            )
            at = next(
                line.id for line in packet.excerpts[0].lines if line.number == candidate.focus
            )
            subjects, objects = _orientation(symbol, source, candidate, resource)
            prompts.append(
                guard_summary(
                    packet,
                    at=at,
                    fields=candidate.fields,
                    subjects=subjects,
                    objects=objects,
                    kinds=_possible_kinds(candidate),
                )
            )
        # Stable boundary only for identity; each actual request keeps randomized spotlighting.
        encoded = json.dumps(
            {
                "version": VERSION,
                "identity": self.identity,
                "recognizer_sha256": self.recognizer_sha256,
                "symbol": symbol.model_dump(mode="json"),
                "file_sha256": hashlib.sha256(source).hexdigest(),
                "resource": resource,
                "required_kind": required_kind,
                "context": [s.model_dump(mode="json") for s in context],
                "prompts": [
                    {
                        "system": p.system,
                        "schema": p.schema,
                        "user": p.request()
                        .body()["messages"][1]["content"]
                        .replace(p.packet.boundary, "00000000"),
                    }
                    for p in prompts
                ],
            },
            sort_keys=True,
        )
        key = hashlib.sha256(encoded.encode()).hexdigest()
        if (cached := self.cache.get(key)) and self._valid_cache(
            cached, symbol, candidates, resource
        ):
            self.cache_hits += 1
            return cached
        if self.cached_only and prompts:
            return Summary(
                symbol_id=symbol.id,
                snapshot_id=self.snapshot.id,
                span=symbol.span,
                guards=[],
                issues=["Guard classification is not cached for this exact source/profile"],
            )
        guards = []
        issues = []
        for index, prompt in enumerate(prompts):
            packet = prompt.packet
            answer = prompt.parse(self.model.ask(prompt.request(), spend).data)
            if not isinstance(answer, GuardSummary):
                raise TypeError("guard-summary answer required")
            violations = check_answer(prompt, answer)
            if violations:
                issues.extend(v.message for v in violations)
                continue
            candidate = candidates[index] if candidates else None
            for item in answer.guards:
                if item.kind is GuardKind.NONE:
                    if candidate is not None:
                        issues.append(f"unclassified executable check at line {candidate.focus}")
                    continue
                if candidate is None or item.kind is GuardKind.UNKNOWN:
                    issues.append(
                        "unrecognized local check; helper bodies or control flow need investigation"
                    )
                    continue
                locations = [packet.location(line_id) for line_id in item.line_ids]
                if (symbol.span.path, candidate.focus) not in locations:
                    issues.append("answer did not cite the check it was asked to classify")
                    continue
                role = None
                if item.kind is GuardKind.ROLE:
                    role = "|".join(candidate.roles) or candidate.role_parameter
                span = symbol.span.model_copy(
                    update={
                        "start_line": candidate.start,
                        "end_line": candidate.end,
                        "content_sha256": _span_hash(source, candidate.start, candidate.end),
                    }
                )
                guard = Guard(
                    id=f"guard:{hashlib.sha256(f'{key}:{index}:{item.kind}'.encode()).hexdigest()[:24]}",
                    snapshot_id=self.snapshot.id,
                    kind=item.kind,
                    canonical=canonical(item.kind, item.subject, item.object, role, resource),
                    mechanism=candidate.mechanism,
                    subject=item.subject,
                    object=item.object,
                    role=role,
                    span=span,
                    via_symbol_id=symbol.id,
                )
                try:
                    guards.append(
                        self.validator.confirm(guard, subject=item.subject, object=item.object)
                    )
                except Unconfirmed as error:
                    issues.extend(v.message for v in error.violations)
        # Two sign-in predicates or repeated equivalent checks have one canonical guard.
        unique = {guard.canonical: guard for guard in reversed(guards)}
        summary = Summary(
            symbol_id=symbol.id,
            snapshot_id=self.snapshot.id,
            span=symbol.span,
            guards=list(unique.values()),
            issues=list(dict.fromkeys(issues)),
        )
        self.cache.put(key, summary)
        return summary

    def _valid_cache(
        self, summary: Summary, symbol: Symbol, candidates: list[Check], resource: str | None
    ) -> bool:
        if (
            summary.symbol_id != symbol.id
            or summary.snapshot_id != self.snapshot.id
            or summary.span != symbol.span
            or summary.issues
        ):
            return False
        if not summary.guards and candidates:
            return False
        for candidate in candidates:
            covered = any(
                (g.kind is GuardKind.AUTHENTICATED and candidate.authentication)
                or (
                    g.kind is GuardKind.ROLE
                    and g.role == ("|".join(candidate.roles) or candidate.role_parameter)
                )
                or (
                    g.kind in (GuardKind.OWNER, GuardKind.TENANT)
                    and (
                        (g.subject, g.object) in candidate.pairs
                        or (g.object, g.subject) in candidate.pairs
                    )
                )
                for g in summary.guards
            )
            if not covered:
                return False
        for guard in summary.guards:
            matching = [
                c
                for c in candidates
                if c.start == guard.span.start_line
                and c.end == guard.span.end_line
                and c.mechanism == guard.mechanism
            ]
            if (
                not matching
                or guard.via_symbol_id != symbol.id
                or not guard.confirmed
                or guard.snapshot_id != self.snapshot.id
                or not symbol.span.start_line
                <= guard.span.start_line
                <= guard.span.end_line
                <= symbol.span.end_line
                or guard.span.path != symbol.span.path
                or guard.canonical
                != canonical(guard.kind, guard.subject, guard.object, guard.role, resource)
            ):
                return False
            try:
                self.validator.confirm(guard, subject=guard.subject, object=guard.object)
            except Unconfirmed:
                return False
        return True


def _span_hash(source: bytes, start: int, end: int) -> str:
    from analysis.syntax import span_sha256

    return span_sha256(source, start, end)
