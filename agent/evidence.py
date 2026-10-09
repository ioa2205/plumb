"""Evidence packets: code lines with IDs, kept apart from what developers wrote about them.

A packet shows the model one or more short excerpts (PROJECT_PLAN §3.1, §6).
Every code line carries an ID (``L1``, ``L2``, ...) that maps back to a real
line of a real file, so a citation can be checked.

Comments and docstrings are taken out of the code before it is shown. They
appear after it as developer notes, which have no ID and so cannot be cited:
"reviewed by security, safe" can be read but can never be evidence. A line
that held only a comment, or nothing, is left out.

Untrusted text is spotlighted (Hines et al., 2024): each excerpt sits inside a
delimiter with a per-packet random boundary, every line of it is marked with
its ID, and characters that could hide text or start an unmarked line are
written as visible escapes.
"""

import re
import secrets
import unicodedata
from dataclasses import dataclass, field

from analysis.syntax import remarks
from backend.contracts.common import Language
from backend.redaction import Redactor

MAX_LINES = 80  # PROJECT_PLAN §6: packets of 20-80 lines
MAX_NOTES = 6
NOTE_CHARS = 120

_LABEL = re.compile(r"[a-z][a-z0-9 -]{0,23}")
_BOUNDARY = re.compile(r"[0-9a-f]{8}")
# Control and format characters (bidirectional overrides, zero-width marks), line and
# paragraph separators, private-use and surrogate code points.
_HIDDEN = {"Cc", "Cf", "Zl", "Zp", "Co", "Cs"}
_NEWLINE = 0x0A
_SPACE = 0x20
_STRING_OPEN = re.compile(r"[rRbBuUfF]{0,2}(\"\"\"|'''|\"|')")
_COMMENT_MARKS = re.compile(r"^(#+!?|//+|/\*+|\*+/|\*+)\s?|\s*\*+/$")


def visible(text: str) -> str:
    """``text`` with every hidden or line-breaking character written as an escape.

    Such characters can make code read differently from what runs, and a stray
    line separator would begin a line that has no ID.
    """
    return "".join(
        ch if ch == "\t" or unicodedata.category(ch) not in _HIDDEN else f"\\u{{{ord(ch):x}}}"
        for ch in text
    )


@dataclass(frozen=True)
class Cut:
    """Lines ``start`` to ``end`` of one file, chosen by the deterministic side.

    ``label`` names the excerpt's part in the question ("handler", "first"). It is
    written by Plumb, never taken from the repository.
    """

    label: str
    path: str
    language: Language
    source: bytes
    start: int
    end: int

    @classmethod
    def whole(cls, label: str, path: str, language: Language, source: bytes) -> "Cut":
        return cls(label, path, language, source, 1, max(_line_count(source), 1))


@dataclass(frozen=True)
class Line:
    id: str
    number: int  # line in the file
    text: str  # code only, comments removed


@dataclass(frozen=True)
class Note:
    number: int  # line in the file where the comment or docstring starts
    text: str
    full_text: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Excerpt:
    label: str
    path: str
    lines: tuple[Line, ...]
    notes: tuple[Note, ...]

    @property
    def line_ids(self) -> list[str]:
        return [line.id for line in self.lines]


def _line_count(source: bytes) -> int:
    return source.count(b"\n") + (0 if source.endswith(b"\n") or not source else 1)


def _note_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if opening := _STRING_OPEN.match(text):  # a docstring: drop its prefix and quotes
        text = text[opening.end() :].removesuffix(opening.group(1))
    words = " ".join(_COMMENT_MARKS.sub("", line.strip()) for line in text.split("\n")).split()
    return visible(" ".join(words))


def _trim_note(text: str) -> str:
    return text if len(text) <= NOTE_CHARS else text[: NOTE_CHARS - 1].rstrip() + "…"


def _separate(cut: Cut) -> tuple[list[tuple[int, str]], list[Note]]:
    """The cut's code lines as (file line, text), and the notes taken out of them."""
    if not 1 <= cut.start <= cut.end <= _line_count(cut.source):
        raise ValueError(
            f"{cut.path}: lines {cut.start}-{cut.end} are outside 1-{_line_count(cut.source)}"
        )
    code = bytearray(cut.source)
    notes = []
    # Back to front, so that replacing one remark leaves the earlier offsets valid.
    for start, end in reversed(remarks(cut.language, cut.source)):
        raw = cut.source[start:end]
        first = cut.source.count(b"\n", 0, start) + 1
        if first <= cut.end and first + raw.count(b"\n") >= cut.start:
            text = _note_text(raw)
            if any(ch.isalnum() for ch in text):
                notes.append(Note(first, _trim_note(text), text))
        # One space keeps the code around a remark apart. A remark that spans lines is
        # blanked in place instead, so line numbers and the indentation after it stay true.
        code[start:end] = (
            bytes(b if b == _NEWLINE else _SPACE for b in raw) if _NEWLINE in raw else b" "
        )
    notes.reverse()
    kept = []
    for number, raw in enumerate(bytes(code).split(b"\n"), start=1):
        text = raw.decode("utf-8", errors="replace").rstrip()
        if cut.start <= number <= cut.end and text.strip():
            kept.append((number, visible(text)))
    return kept, notes


@dataclass(frozen=True)
class EvidencePacket:
    excerpts: tuple[Excerpt, ...]
    boundary: str

    @classmethod
    def build(cls, *cuts: Cut, boundary: str | None = None) -> "EvidencePacket":
        """Number the code lines of ``cuts`` in order. Refuses rather than trims."""
        boundary = secrets.token_hex(4) if boundary is None else boundary
        if _BOUNDARY.fullmatch(boundary) is None:
            raise ValueError("boundary must be eight hexadecimal digits")
        if not cuts:
            raise ValueError("a packet needs at least one excerpt")
        if len({cut.label for cut in cuts}) != len(cuts):
            raise ValueError("excerpt labels must be unique")
        excerpts: list[Excerpt] = []
        count = 0
        for cut in cuts:
            if _LABEL.fullmatch(cut.label) is None:
                raise ValueError(f"not an excerpt label: {cut.label!r}")
            kept, notes = _separate(cut)
            if not kept:
                raise ValueError(f"{cut.path}: lines {cut.start}-{cut.end} hold no code")
            lines = tuple(
                Line(f"L{count + n}", number, text) for n, (number, text) in enumerate(kept, 1)
            )
            count += len(lines)
            excerpts.append(Excerpt(cut.label, cut.path, lines, tuple(notes)))
        if count > MAX_LINES:
            raise ValueError(f"packet has {count} code lines; the limit is {MAX_LINES}")
        return cls(tuple(excerpts), boundary)

    @property
    def line_ids(self) -> list[str]:
        return [line.id for excerpt in self.excerpts for line in excerpt.lines]

    def excerpt(self, label: str) -> Excerpt:
        for excerpt in self.excerpts:
            if excerpt.label == label:
                return excerpt
        raise KeyError(f"no excerpt labeled {label!r}")

    def _find(self, line_id: str) -> tuple[Excerpt, Line]:
        for excerpt in self.excerpts:
            for line in excerpt.lines:
                if line.id == line_id:
                    return excerpt, line
        raise KeyError(f"{line_id} is not a line of this packet")

    def line(self, line_id: str) -> Line:
        return self._find(line_id)[1]

    def location(self, line_id: str) -> tuple[str, int]:
        """The file and line a citation points at."""
        excerpt, line = self._find(line_id)
        return excerpt.path, line.number

    def render(self, *, redactor: Redactor | None = None) -> str:
        redactor = redactor or Redactor.configured()
        blocks = []
        notes = []
        for excerpt in self.excerpts:
            # Redact before adding citation IDs. Keep every line and its location;
            # packet.line() retains original code for validation against the snapshot.
            cleaned = redactor.text(
                "\n".join(line.text for line in excerpt.lines), preserve_lines=True
            ).split("\n")
            body = "\n".join(
                f"{line.id} | {text}" for line, text in zip(excerpt.lines, cleaned, strict=True)
            )
            if redactor.text(visible(excerpt.path)) != visible(excerpt.path):
                raise ValueError("a credential occurs in an evidence path")
            blocks.append(
                f"<evidence-{self.boundary} part={excerpt.label!r} "
                f"path={visible(excerpt.path)!r}>\n{body}\n</evidence-{self.boundary}>"
            )
            for note in excerpt.notes:
                # The nearest code line at or after the note, or the excerpt's last line.
                near = next(
                    (line.id for line in excerpt.lines if line.number >= note.number),
                    excerpt.lines[-1].id,
                )
                notes.append(
                    f"near {near}: {_trim_note(redactor.text(note.full_text or note.text))}"
                )
        if notes:
            shown = notes[:MAX_NOTES]
            if len(notes) > MAX_NOTES:
                shown.append(f"({len(notes) - MAX_NOTES} more notes not shown)")
            blocks.append(
                f"<developer-notes-{self.boundary}>\n"
                + "\n".join(shown)
                + f"\n</developer-notes-{self.boundary}>"
            )
        return "\n".join(blocks)
