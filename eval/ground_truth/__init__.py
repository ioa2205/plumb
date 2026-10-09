"""Ground truth for the hand-written Tandir lab (PROJECT_PLAN §10.1, task M1.4).

The manifest (``tandir.toml``) declares every intentional flaw, its protected
lookalike, and further defended controls, with location, family, CWE, and the
expected conclusion. ADR-0005 makes it the evidence for the flaws, so it is
validated against the code, not trusted:

- each path exists under the lab root, and each span is exactly the symbol's
  span (decorators through the end of the function, as for the mutation corpus);
- each anchor appears in the span, and each guard of a lookalike or control too;
- on the fixed snapshot (labs/tandir/fixed), each flaw's fix removes and adds
  what it declares, and lookalikes and controls are byte-for-byte unchanged.
"""

import re
import subprocess
import sys
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.common import Family
from backend.contracts.investigation import Conclusion
from eval.mutation.corpus import handler_lines
from eval.scoring.score import Truth

REPOSITORY = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("tandir.toml")
SNAPSHOT_SCRIPT = REPOSITORY / "labs" / "tandir" / "fixed" / "snapshot.py"


class Kind(StrEnum):
    FLAW = "flaw"
    LOOKALIKE = "lookalike"
    CONTROL = "control"


class FixCheck(BaseModel):
    """What the fixed snapshot changes for a flaw; path and symbol default to the case's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str | None = None
    symbol: str | None = None
    removes: tuple[str, ...] = ()
    adds: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _says_something(self) -> Self:
        if not self.removes and not self.adds:
            raise ValueError("a fix check needs `removes` or `adds`")
        return self


class Case(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^TANDIR-[A-Z0-9-]+$")
    kind: Kind
    family: Family
    cwe: str = Field(pattern=r"^CWE-\d+$")
    title: str
    route: str
    path: str
    symbol: str
    lines: tuple[int, int]
    expected: Literal[Conclusion.SUPPORTED, Conclusion.REJECTED]
    anchors: tuple[str, ...] = Field(min_length=1)
    pair: str | None = None
    guard: str | None = None
    guard_definition: str | None = None  # "path::symbol" where the guard is defined
    note: str | None = None
    fix: FixCheck | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if Path(self.path).is_absolute() or ".." in Path(self.path).parts or "\\" in self.path:
            raise ValueError(f"{self.id}: path must be relative to the lab root, in POSIX form")
        if self.lines[0] > self.lines[1]:
            raise ValueError(f"{self.id}: lines run backwards")
        if self.kind is Kind.FLAW:
            if self.expected != Conclusion.SUPPORTED or self.fix is None or self.guard:
                raise ValueError(f"{self.id}: a flaw is supported, has a fix check, no guard")
        else:
            if self.expected != Conclusion.REJECTED or self.fix is not None or not self.guard:
                raise ValueError(f"{self.id}: a {self.kind} is rejected, cites a guard, no fix")
        if self.kind is not Kind.CONTROL and self.pair is None:
            raise ValueError(f"{self.id}: flaws and lookalikes come in pairs")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root: str
    cases: tuple[Case, ...] = Field(alias="case")

    @model_validator(mode="after")
    def _pairs(self) -> Self:
        ids = [c.id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case ids")
        pairs: dict[str, list[Kind]] = {}
        for case in self.cases:
            if case.pair:
                pairs.setdefault(case.pair, []).append(case.kind)
        for pair, kinds in pairs.items():
            if sorted(kinds) != [Kind.FLAW, Kind.LOOKALIKE]:
                raise ValueError(f"pair {pair} needs exactly one flaw and one lookalike")
        return self

    def lab_root(self) -> Path:
        return REPOSITORY / self.root


def load(path: Path = MANIFEST) -> Manifest:
    with path.open("rb") as f:
        return Manifest.model_validate(tomllib.load(f))


_TS_FUNCTION = r"^export (?:default )?(?:async )?function {name}\b"


def symbol_span(source: str, path: str, symbol: str) -> tuple[int, int]:
    """Span of a top-level function: decorators through its last line."""
    if path.endswith(".py"):
        return handler_lines(source, symbol)
    lines = source.split("\n")
    pattern = re.compile(_TS_FUNCTION.format(name=re.escape(symbol)))
    for index, line in enumerate(lines):
        if pattern.match(line):
            # Formatted code: the function closes at the next line that is just "}".
            for end in range(index + 1, len(lines)):
                if lines[end] == "}":
                    return (index + 1, end + 1)
            break
    raise LookupError(f"function {symbol} not found in {path}")


def span_text(source: str, span: tuple[int, int]) -> str:
    return "\n".join(source.split("\n")[span[0] - 1 : span[1]])


def _read(root: Path, path: str) -> str | None:
    file = root / path
    return file.read_text(encoding="utf-8") if file.is_file() else None


def _guard_defined(root: Path, definition: str) -> bool:
    path, _, symbol = definition.partition("::")
    source = _read(root, path)
    if source is None:
        return False
    try:
        symbol_span(source, path, symbol)
    except LookupError:
        return False
    return True


def problems(manifest: Manifest, root: Path | None = None) -> list[str]:
    """Check every case against the vulnerable lab. Empty when the manifest holds."""
    root = root or manifest.lab_root()
    found: list[str] = []
    for case in manifest.cases:
        source = _read(root, case.path)
        if source is None:
            found.append(f"{case.id}: {case.path} does not exist")
            continue
        try:
            span = symbol_span(source, case.path, case.symbol)
        except LookupError as e:
            found.append(f"{case.id}: {e}")
            continue
        if span != case.lines:
            found.append(f"{case.id}: {case.symbol} spans lines {span}, manifest says {case.lines}")
        text = span_text(source, span)
        for anchor in case.anchors:
            if anchor not in text:
                found.append(f"{case.id}: anchor not in {case.symbol}: {anchor!r}")
        if case.guard and case.guard not in text:
            found.append(f"{case.id}: guard not in {case.symbol}: {case.guard!r}")
        if case.guard_definition and not _guard_defined(root, case.guard_definition):
            found.append(f"{case.id}: guard definition not found: {case.guard_definition}")
        if case.fix:
            fix_path = case.fix.path or case.path
            fix_source = _read(root, fix_path)
            if fix_source is None:
                found.append(f"{case.id}: {fix_path} does not exist")
                continue
            fix_text = span_text(
                fix_source, symbol_span(fix_source, fix_path, case.fix.symbol or case.symbol)
            )
            found += [
                f"{case.id}: the vulnerable lab lacks what the fix removes: {s!r}"
                for s in case.fix.removes
                if s not in fix_text
            ]
            found += [
                f"{case.id}: the vulnerable lab already has what the fix adds: {s!r}"
                for s in case.fix.adds
                if s in fix_text
            ]
    return found


def fixed_problems(manifest: Manifest, fixed_root: Path, root: Path | None = None) -> list[str]:
    """Check the fixed snapshot: flaws repaired as declared, everything else untouched."""
    root = root or manifest.lab_root()
    found: list[str] = []
    for case in manifest.cases:
        if case.fix:
            path = case.fix.path or case.path
            symbol = case.fix.symbol or case.symbol
            source = _read(fixed_root, path)
            if source is None:
                found.append(f"{case.id}: fixed snapshot lacks {path}")
                continue
            text = span_text(source, symbol_span(source, path, symbol))
            found += [f"{case.id}: fix left {s!r}" for s in case.fix.removes if s in text]
            found += [f"{case.id}: fix lacks {s!r}" for s in case.fix.adds if s not in text]
        else:
            before = _read(root, case.path)
            after = _read(fixed_root, case.path)
            if before is None or after is None:
                found.append(f"{case.id}: {case.path} missing on one side")
                continue
            old = span_text(before, symbol_span(before, case.path, case.symbol))
            new = span_text(after, symbol_span(after, case.path, case.symbol))
            if old != new:
                found.append(f"{case.id}: the fixed snapshot changed a {case.kind}")
    return found


def build_fixed(dest: Path) -> Path:
    """The fixed snapshot at ``dest`` (outside the repository), built by the lab's own script."""
    subprocess.run(  # noqa: S603 - the repository's own script, fixed arguments
        [sys.executable, str(SNAPSHOT_SCRIPT), "make", str(dest)],
        check=True,
        capture_output=True,
    )
    return dest


def truths(manifest: Manifest) -> list[Truth]:
    """The manifest as scoring truths (eval.scoring), clustered by pair."""
    return [
        Truth(
            id=case.id,
            family=case.family,
            label="vulnerable" if case.kind is Kind.FLAW else "safe",
            path=case.path,
            start_line=case.lines[0],
            end_line=case.lines[1],
            template_family=case.pair or case.id,
            pair_id=case.pair,
        )
        for case in manifest.cases
    ]
