"""Syntax extraction with tree-sitter: symbols, imports, and directives (task M2.2).

Parsing never executes the code. Files are parsed from snapshot bytes, so line
numbers and hashes refer to the snapshot, not the live tree.
"""

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import PurePosixPath
from threading import local

import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language as Grammar
from tree_sitter import Node, Parser

from backend.contracts.code import SymbolKind
from backend.contracts.common import Language


@dataclass(frozen=True)
class SymbolFact:
    name: str
    local_name: str  # qualified within the file: "Viewer.is", "require_role.check"
    kind: SymbolKind
    start_line: int
    end_line: int
    parent: str | None = None  # local name of the enclosing symbol
    exported: bool = False
    is_default: bool = False
    is_async: bool = False
    decorators: tuple[str, ...] = ()
    directive: str | None = None  # "use server" as the first statement of a function


@dataclass(frozen=True)
class ImportFact:
    line: int
    module: str  # "fastapi", "./actions", "" for `from . import x`
    name: str | None  # imported name; None for `import x` and side-effect imports
    alias: str | None
    level: int = 0  # Python relative-import dots
    kind: str = "named"  # module | named | default | namespace | reexport | side_effect | type


@dataclass
class FileFacts:
    path: str
    language: Language
    module: str
    lines: int
    has_errors: bool
    directive: str | None = None  # file-level "use server" / "use client"
    symbols: list[SymbolFact] = field(default_factory=list)
    imports: list[ImportFact] = field(default_factory=list)


@cache
def _grammar(language: Language) -> Grammar:
    if language is Language.PYTHON:
        grammar = Grammar(tree_sitter_python.language())
    elif language is Language.TYPESCRIPT:
        grammar = Grammar(tree_sitter_typescript.language_typescript())
    else:  # TSX, and JavaScript (the TSX grammar also reads JS and JSX)
        grammar = Grammar(tree_sitter_typescript.language_tsx())
    return grammar


_parsers = local()


def _parser(language: Language) -> Parser:
    # Grammars are immutable; a parser's mutable native state belongs to one thread.
    # Saved-case APIs can validate the same snapshot on different worker threads.
    if not hasattr(_parsers, "languages"):
        _parsers.languages = {}
    parsers: dict[Language, Parser] = _parsers.languages
    if language not in parsers:
        parsers[language] = Parser(_grammar(language))
    return parsers[language]


def span_sha256(source: bytes, start_line: int, end_line: int) -> str:
    """Hash of the cited lines' text, as stored in a SourceSpan."""
    lines = source.decode("utf-8", errors="replace").split("\n")
    return hashlib.sha256("\n".join(lines[start_line - 1 : end_line]).encode()).hexdigest()


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node and node.text else ""


def _start(node: Node) -> int:
    return node.start_point.row + 1


def _end(node: Node) -> int:
    return node.end_point.row + 1


def _qualified(parent: str | None, name: str) -> str:
    return f"{parent}.{name}" if parent else name


# Python ----------------------------------------------------------------------------------------


def python_module(path: str, package_dirs: set[str]) -> str:
    """Dotted module name: the path below the topmost folder with an ``__init__.py`` chain."""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    folders = list(PurePosixPath(path).parent.parts)
    start = len(folders)
    while start > 0 and "/".join(folders[:start]) in package_dirs:
        start -= 1
    return ".".join(parts[start:]) or PurePosixPath(path).stem


def _py_block_definitions(block: Node) -> Iterator[Node]:
    """Function and class definitions among a block's statements, also inside if/try/with."""
    for child in block.named_children:
        if child.type in ("function_definition", "class_definition", "decorated_definition"):
            yield child
        elif child.type in (
            "if_statement",
            "try_statement",
            "with_statement",
            "else_clause",
            "elif_clause",
            "except_clause",
            "finally_clause",
            "block",
        ):
            yield from _py_block_definitions(child)


def _py_definition(node: Node, parent: str | None, in_class: bool, out: list[SymbolFact]) -> None:
    decorators: tuple[str, ...] = ()
    outer = node
    if node.type == "decorated_definition":
        decorators = tuple(
            _text(d)[1:].strip() for d in node.named_children if d.type == "decorator"
        )
        definition = node.child_by_field_name("definition")
        if definition is None:
            return
        node = definition
    name = _text(node.child_by_field_name("name"))
    if not name:
        return
    qualified = _qualified(parent, name)
    body = node.child_by_field_name("body")
    if node.type == "class_definition":
        out.append(
            SymbolFact(
                name,
                qualified,
                SymbolKind.CLASS,
                _start(outer),
                _end(outer),
                parent,
                decorators=decorators,
            )
        )
        if body is not None:
            for child in _py_block_definitions(body):
                _py_definition(child, qualified, True, out)
        return
    is_async = any(c.type == "async" for c in node.children)
    kind = SymbolKind.METHOD if in_class else SymbolKind.FUNCTION
    out.append(
        SymbolFact(
            name,
            qualified,
            kind,
            _start(outer),
            _end(outer),
            parent,
            is_async=is_async,
            decorators=decorators,
        )
    )
    if body is not None:
        for child in _py_block_definitions(body):
            _py_definition(child, qualified, False, out)


def _py_imports(root: Node) -> Iterator[ImportFact]:
    for node in root.named_children:
        targets = [node]
        if node.type in ("if_statement", "try_statement"):
            kinds = ("import_statement", "import_from_statement")
            targets = [n for n in _walk(node) if n.type in kinds]
        for stmt in targets:
            if stmt.type == "import_statement":
                for item in stmt.named_children:
                    if item.type == "aliased_import":
                        module = _text(item.child_by_field_name("name"))
                        alias = _text(item.child_by_field_name("alias"))
                        yield ImportFact(_start(stmt), module, None, alias, kind="module")
                    elif item.type == "dotted_name":
                        yield ImportFact(_start(stmt), _text(item), None, None, kind="module")
            elif stmt.type == "import_from_statement":
                module_node = stmt.child_by_field_name("module_name")
                module_text = _text(module_node)
                level = len(module_text) - len(module_text.lstrip("."))
                module = module_text.lstrip(".")
                for item in stmt.children_by_field_name("name"):
                    if item.type == "aliased_import":
                        name = _text(item.child_by_field_name("name"))
                        alias = _text(item.child_by_field_name("alias"))
                        yield ImportFact(_start(stmt), module, name, alias, level)
                    else:
                        yield ImportFact(_start(stmt), module, _text(item), None, level)
                if any(c.type == "wildcard_import" for c in stmt.named_children):
                    yield ImportFact(_start(stmt), module, "*", None, level, kind="namespace")


def _walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.named_children:
        yield from _walk(child)


def remarks(language: Language, source: bytes) -> list[tuple[int, int]]:
    """Byte ranges of text that never executes: comments, and Python strings used as statements.

    A docstring is the usual string statement. A TypeScript directive such as
    ``'use server'`` is a statement with a meaning, so it is not a remark.
    """
    ranges = []
    tree = _parser(language).parse(source)
    for node in _walk(tree.root_node):
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
        elif language is Language.PYTHON and node.type == "expression_statement":
            values = [child for child in node.named_children if child.type != "comment"]
            if len(values) == 1 and values[0].type in ("string", "concatenated_string"):
                ranges.append((values[0].start_byte, values[0].end_byte))
    return sorted(ranges)


def code_only(language: Language | None, source: bytes) -> bytes:
    """``source`` with every remark blanked to spaces; offsets and line numbers are unchanged.

    A file in no supported language has no known comment syntax and is returned as it is.
    """
    if language is None:
        return source
    code = bytearray(source)
    for start, end in remarks(language, source):
        code[start:end] = bytes(b if b == 0x0A else 0x20 for b in source[start:end])
    return bytes(code)


@dataclass(frozen=True)
class Comparison:
    """An equality or membership test: the syntax a direct access check is made of."""

    start_line: int
    end_line: int
    operator: str
    operands: tuple[str, ...]


_PY_TESTS = {"==", "!=", "in", "not in"}
_TS_TESTS = {"===", "!==", "==", "!="}


def comparisons(language: Language, source: bytes) -> list[Comparison]:
    """Every single equality or membership test in the file, wherever it is nested.

    Ordering tests and chained comparisons are left out: neither states that a
    caller is the owner, a member, or a role holder.
    """
    found = []
    tree = _parser(language).parse(source)
    for node in _walk(tree.root_node):
        if language is Language.PYTHON and node.type == "comparison_operator":
            operators = [child.type for child in node.children_by_field_name("operators")]
            operands = [child for child in node.named_children if child.type != "comment"]
            if len(operators) != 1 or operators[0] not in _PY_TESTS or len(operands) != 2:
                continue
            operator = operators[0]
        elif language is not Language.PYTHON and node.type == "binary_expression":
            sign = node.child_by_field_name("operator")
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            if sign is None or sign.type not in _TS_TESTS or left is None or right is None:
                continue
            operator, operands = sign.type, [left, right]
        else:
            continue
        found.append(
            Comparison(_start(node), _end(node), operator, tuple(_text(o) for o in operands))
        )
    return found


def _py_variables(root: Node) -> Iterator[SymbolFact]:
    for node in root.named_children:
        if node.type != "expression_statement" or not node.named_children:
            continue
        assignment = node.named_children[0]
        if assignment.type != "assignment":
            continue
        left = assignment.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            name = _text(left)
            yield SymbolFact(name, name, SymbolKind.VARIABLE, _start(node), _end(node))


def _python(facts: FileFacts, root: Node) -> None:
    for node in _py_block_definitions(root):
        _py_definition(node, None, False, facts.symbols)
    facts.symbols.extend(_py_variables(root))
    facts.imports.extend(_py_imports(root))


# TypeScript and TSX ----------------------------------------------------------------------------

_FUNCTION_VALUES = ("arrow_function", "function_expression", "function")
_DIRECTIVES = ("use server", "use client")


def _string_value(node: Node) -> str:
    return _text(node)[1:-1] if node.type == "string" else ""


def _leading_directive(statements: list[Node]) -> str | None:
    for stmt in statements:
        if stmt.type == "comment":
            continue
        if stmt.type == "expression_statement" and stmt.named_children:
            value = _string_value(stmt.named_children[0])
            if value in _DIRECTIVES:
                return value
            if stmt.named_children[0].type == "string":
                continue  # another directive-like string, keep looking
        return None
    return None


def _function_body_directive(fn: Node) -> str | None:
    body = fn.child_by_field_name("body")
    if body is None or body.type != "statement_block":
        return None
    return _leading_directive(list(body.named_children))


def _is_component(name: str, language: Language) -> bool:
    return language in (Language.TSX, Language.JAVASCRIPT) and name[:1].isupper()


def _ts_function_kind(name: str, language: Language) -> SymbolKind:
    return SymbolKind.COMPONENT if _is_component(name, language) else SymbolKind.FUNCTION


def _ts_value_function(value: Node | None) -> Node | None:
    """The function behind a value: itself, or one wrapped in a call such as cache(...)."""
    if value is None:
        return None
    if value.type in _FUNCTION_VALUES:
        return value
    if value.type == "call_expression":
        arguments = value.child_by_field_name("arguments")
        for argument in arguments.named_children if arguments else []:
            if argument.type in _FUNCTION_VALUES:
                return argument
    return None


@dataclass(frozen=True)
class _Context:
    language: Language
    parent: str | None = None
    exported: bool = False
    is_default: bool = False


def _ts_nested(fn: Node, qualified: str, ctx: _Context, out: list[SymbolFact]) -> None:
    body = fn.child_by_field_name("body")
    if body is not None and body.type == "statement_block":
        for stmt in body.named_children:
            _ts_declaration(stmt, _Context(ctx.language, qualified), out, stmt)


def _ts_declaration(node: Node, ctx: _Context, out: list[SymbolFact], outer: Node) -> None:
    language = ctx.language
    if node.type in ("function_declaration", "generator_function_declaration"):
        name = _text(node.child_by_field_name("name"))
        if not name:
            return
        qualified = _qualified(ctx.parent, name)
        out.append(
            SymbolFact(
                name,
                qualified,
                _ts_function_kind(name, language),
                _start(outer),
                _end(outer),
                ctx.parent,
                ctx.exported,
                ctx.is_default,
                is_async=any(c.type == "async" for c in node.children),
                directive=_function_body_directive(node),
            )
        )
        _ts_nested(node, qualified, ctx, out)
    elif node.type in ("class_declaration", "abstract_class_declaration"):
        name = _text(node.child_by_field_name("name"))
        if not name:
            return
        qualified = _qualified(ctx.parent, name)
        out.append(
            SymbolFact(
                name,
                qualified,
                SymbolKind.CLASS,
                _start(outer),
                _end(outer),
                ctx.parent,
                ctx.exported,
                ctx.is_default,
            )
        )
        body = node.child_by_field_name("body")
        for member in body.named_children if body else []:
            if member.type == "method_definition":
                method = _text(member.child_by_field_name("name"))
                out.append(
                    SymbolFact(
                        method,
                        f"{qualified}.{method}",
                        SymbolKind.METHOD,
                        _start(member),
                        _end(member),
                        qualified,
                        is_async=any(c.type == "async" for c in member.children),
                    )
                )
    elif node.type in ("lexical_declaration", "variable_declaration"):
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None or name_node.type != "identifier":
                continue  # destructuring
            name = _text(name_node)
            qualified = _qualified(ctx.parent, name)
            fn = _ts_value_function(declarator.child_by_field_name("value"))
            if fn is None and ctx.parent is not None:
                continue  # a local variable, not a symbol
            kind = _ts_function_kind(name, language) if fn else SymbolKind.VARIABLE
            out.append(
                SymbolFact(
                    name,
                    qualified,
                    kind,
                    _start(outer),
                    _end(outer),
                    ctx.parent,
                    ctx.exported,
                    ctx.is_default,
                    is_async=fn is not None and any(c.type == "async" for c in fn.children),
                    directive=_function_body_directive(fn) if fn else None,
                )
            )
            if fn is not None:
                _ts_nested(fn, qualified, ctx, out)
    elif node.type in ("type_alias_declaration", "interface_declaration"):
        name = _text(node.child_by_field_name("name"))
        if name and ctx.parent is None:
            out.append(
                SymbolFact(
                    name,
                    name,
                    SymbolKind.TYPE,
                    _start(outer),
                    _end(outer),
                    None,
                    ctx.exported,
                    ctx.is_default,
                )
            )


def _ts_imports(node: Node) -> Iterator[ImportFact]:
    source = node.child_by_field_name("source")
    module = _string_value(source) if source is not None else ""
    line = _start(node)
    # `import type { X }` creates no runtime dependency.
    type_only = node.type == "import_statement" and any(c.type == "type" for c in node.children)
    if node.type == "export_statement":
        # export { a as b } from "./x"  /  export * from "./x"
        clause = next((c for c in node.named_children if c.type == "export_clause"), None)
        if clause is None:
            yield ImportFact(line, module, "*", None, kind="reexport")
            return
        for spec in clause.named_children:
            if spec.type == "export_specifier":
                name = _text(spec.child_by_field_name("name"))
                alias = _text(spec.child_by_field_name("alias")) or None
                yield ImportFact(line, module, name, alias, kind="reexport")
        return
    clause = next((c for c in node.named_children if c.type == "import_clause"), None)
    if clause is None:
        yield ImportFact(line, module, None, None, kind="side_effect")
        return
    for part in clause.named_children:
        if part.type == "identifier":
            yield ImportFact(line, module, "default", _text(part), kind="default")
        elif part.type == "namespace_import":
            alias = next((_text(c) for c in part.named_children if c.type == "identifier"), None)
            yield ImportFact(line, module, "*", alias, kind="namespace")
        elif part.type == "named_imports":
            for spec in part.named_children:
                if spec.type == "import_specifier":
                    name = _text(spec.child_by_field_name("name"))
                    alias = _text(spec.child_by_field_name("alias")) or None
                    spec_type_only = type_only or any(c.type == "type" for c in spec.children)
                    yield ImportFact(
                        line, module, name, alias, kind="type" if spec_type_only else "named"
                    )


def _typescript(facts: FileFacts, root: Node) -> None:
    statements = list(root.named_children)
    facts.directive = _leading_directive(statements)
    for node in statements:
        if node.type == "import_statement":
            facts.imports.extend(_ts_imports(node))
        elif node.type == "export_statement":
            if node.child_by_field_name("source") is not None:
                facts.imports.extend(_ts_imports(node))
                continue
            is_default = any(c.type == "default" for c in node.children)
            declaration = node.child_by_field_name("declaration")
            if declaration is not None:
                ctx = _Context(facts.language, None, True, is_default)
                _ts_declaration(declaration, ctx, facts.symbols, node)
            elif is_default:
                value = node.child_by_field_name("value")
                fn = _ts_value_function(value)
                if fn is not None:
                    name = _text(fn.child_by_field_name("name")) or "default"
                    facts.symbols.append(
                        SymbolFact(
                            name,
                            name,
                            _ts_function_kind(name, facts.language),
                            _start(node),
                            _end(node),
                            None,
                            True,
                            True,
                            is_async=any(c.type == "async" for c in fn.children),
                            directive=_function_body_directive(fn),
                        )
                    )
        else:
            _ts_declaration(node, _Context(facts.language), facts.symbols, node)


def ts_module(path: str) -> str:
    return PurePosixPath(path).with_suffix("").as_posix()


def extract(path: str, language: Language, source: bytes, package_dirs: set[str]) -> FileFacts:
    """Symbols, imports, and directives of one file."""
    tree = _parser(language).parse(source)
    root = tree.root_node
    module = python_module(path, package_dirs) if language is Language.PYTHON else ts_module(path)
    lines = source.count(b"\n") + (0 if source.endswith(b"\n") or not source else 1)
    facts = FileFacts(path, language, module, lines, root.has_error)
    # The module itself; its local name is empty, so its qualified name is the module's.
    facts.symbols.append(
        SymbolFact(PurePosixPath(path).stem, "", SymbolKind.MODULE, 1, max(lines, 1))
    )
    if language is Language.PYTHON:
        _python(facts, root)
    else:
        _typescript(facts, root)
    return facts


_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z0-9])|[A-Z]?[a-z0-9]+|[A-Z]+")


def words(identifier: str) -> str:
    """``load_order_scoped`` and ``getOrderDTO`` as searchable words."""
    return " ".join(w.lower() for w in _WORD.findall(identifier))
