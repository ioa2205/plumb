"""Construct exact frozen-source diffs in memory. Never touch the target checkout."""

import ast
import difflib
import hashlib

from analysis.snapshot import SnapshotStore
from analysis.syntax import _parser, span_sha256
from backend.contracts.code import ProjectSnapshot, SourceSpan
from backend.contracts.common import Language
from backend.contracts.verification import SourceEdit
from backend.redaction import Redactor

MAX_BYTES = 1024 * 1024
MAX_DIFF_BYTES = 16 * 1024


class TrivialEdit(ValueError):
    """A proposed protection changes only executable-source trivia."""


def _code_shape(language: Language, raw: bytes) -> str:
    digest = hashlib.sha256()
    if language is Language.PYTHON:
        pending: list[object] = [ast.parse(raw)]
        while pending:
            value = pending.pop()
            if isinstance(value, ast.AST):
                digest.update(type(value).__name__.encode() + b"(")
                pending.extend(reversed([(name, getattr(value, name)) for name in value._fields]))
            elif isinstance(value, tuple):
                name, child = value
                digest.update(str(name).encode() + b":")
                pending.append(child)
            elif isinstance(value, list):
                kept = [
                    v
                    for v in value
                    if not (
                        isinstance(v, ast.Expr)
                        and isinstance(v.value, ast.Constant)
                        and isinstance(v.value.value, str)
                    )
                ]
                digest.update(b"[" + len(kept).to_bytes(4, "big"))
                pending.extend(reversed(kept))
            else:
                token = (type(value).__name__ + ":" + repr(value)).encode()
                digest.update(len(token).to_bytes(4, "big") + token)
        return digest.hexdigest()
    root = _parser(language).parse(raw).root_node
    if root.has_error:
        raise ValueError("unsupported executable source shape")
    # Keep operators, literal contents and nesting, but no whitespace locations.
    # Iteration also handles deep valid TypeScript without Python recursion.
    nodes = [root]
    while nodes:
        node = nodes.pop()
        kind = node.type.encode()
        children = [
            c
            for c in node.children
            if c.type != "comment"
            and not (
                c.type == "jsx_expression"
                and c.named_children
                and all(n.type == "comment" for n in c.named_children)
            )
        ]
        token = (node.text or b"") if node.child_count == 0 and node.type != "program" else b""
        digest.update(len(kind).to_bytes(4, "big") + kind)
        digest.update(len(children).to_bytes(4, "big"))
        digest.update(len(token).to_bytes(4, "big") + token)
        nodes.extend(reversed(children))
    return digest.hexdigest()


def construct(
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    scope: SourceSpan,
    edits: list[SourceEdit],
    *,
    require_code_change: bool = False,
) -> str:
    if scope.snapshot_id != snapshot.id or not 1 <= len(edits) <= 4:
        raise ValueError("invalid patch scope or edit count")
    file = next((f for f in snapshot.files if f.path == scope.path), None)
    if file is None or file.language is None or file.size > MAX_BYTES:
        raise ValueError("unsupported patch source")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in scope.path):
        raise ValueError("ambiguous diff path")
    raw = store.read(snapshot, scope.path)
    if len(raw) > MAX_BYTES or b"\0" in raw or b"\r" in raw:
        raise ValueError("binary, oversized or non-LF source")
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    if not text.endswith("\n") or not 1 <= scope.start_line <= scope.end_line <= len(lines):
        raise ValueError("unsupported final newline or source scope")
    if span_sha256(raw, scope.start_line, scope.end_line) != scope.content_sha256:
        raise ValueError("patch scope content changed")
    if len({e.source.start_line for e in edits}) != len(edits):
        raise ValueError("ambiguous overlapping edits")
    for edit in sorted(edits, key=lambda e: e.source.start_line, reverse=True):
        edit = SourceEdit.model_validate(edit.model_dump())
        span = edit.source
        if (
            span.snapshot_id != snapshot.id
            or span.path != scope.path
            or not scope.start_line <= span.start_line <= scope.end_line
            or edit.file_sha256 != file.sha256
            or span_sha256(raw, span.start_line, span.end_line) != span.content_sha256
        ):
            raise ValueError("edit is not bound to the original source")
        code = edit.code
        if any(ord(ch) < 32 and ch not in "\n\t" for ch in code) or "\x7f" in code:
            raise ValueError("nontext replacement")
        replacement = code.rstrip("\n") + "\n" if code else ""
        if len(replacement.splitlines()) > 30:
            raise ValueError("replacement line limit")
        position = span.start_line - 1
        if edit.action == "insert_before":
            lines[position:position] = [replacement]
        elif edit.action == "insert_after":
            lines[position + 1 : position + 1] = [replacement]
        else:
            lines[position : position + 1] = [replacement] if replacement else []
    changed = "".join(lines)
    encoded = changed.encode("utf-8")
    if len(encoded) > MAX_BYTES or changed == text:
        raise ValueError("patch is oversized or makes no change")
    if file.language is Language.PYTHON:
        ast.parse(encoded)
    elif _parser(file.language).parse(encoded).root_node.has_error:
        raise ValueError("replacement has unsupported syntax")
    if require_code_change and _code_shape(file.language, raw) == _code_shape(
        file.language, encoded
    ):
        raise TrivialEdit("proposal makes no executable source change")
    diff = "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            changed.splitlines(keepends=True),
            fromfile="a/" + file.path,
            tofile="b/" + file.path,
            n=0,
        )
    )
    if len(diff.encode()) > MAX_DIFF_BYTES or Redactor.configured().text(diff) != diff:
        raise ValueError("diff is oversized or contains credential-shaped text")
    return diff
