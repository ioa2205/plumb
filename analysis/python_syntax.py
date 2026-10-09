"""Python call sites and conservative lexical/import bindings from snapshot ASTs.

No importlib, eval, exec, or target interpreter is involved. Unsupported binding
forms, assignments, conditional definitions and collisions deliberately block
the fallback. Instance dispatch is left to ty.
"""

import ast
import io
import tokenize
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from analysis.index import Index, SymbolRow
from backend.contracts.code import SymbolKind
from backend.contracts.common import Language

DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
CALLABLE_KINDS = {SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CLASS}


def utf16_column(line: str, byte_column: int) -> int:
    prefix = line.encode("utf-8")[:byte_column].decode("utf-8")
    return len(prefix.encode("utf-16-le")) // 2


def dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


@dataclass(frozen=True)
class Binding:
    module: str | None = None
    member: str = ""
    symbol: SymbolRow | None = None


@dataclass
class Scope:
    owner: SymbolRow
    parent: "Scope | None" = None
    bindings: dict[str, Binding | None] = field(default_factory=dict)
    star: bool = False
    is_class: bool = False

    def add(self, name: str, binding: Binding | None = None) -> None:
        # Even two identical imports can run on different branches. No arbitrary
        # first/last binding wins, and a local assignment shadows outer names.
        self.bindings[name] = None if name in self.bindings else binding

    def lookup(self, name: str) -> Binding | None:
        if self.star:
            return None
        if name in self.bindings:
            return self.bindings[name]
        return self.parent.lookup(name) if self.parent else None


@dataclass(frozen=True)
class Definition:
    symbol: SymbolRow
    line: int  # LSP zero-based
    column: int  # LSP UTF-16


@dataclass(frozen=True)
class CallSite:
    path: str
    node: ast.Call
    scope: Scope
    line: int  # final callee identifier, LSP zero-based
    column: int
    callee: str


@dataclass
class PythonFile:
    path: str
    source: bytes
    module: SymbolRow
    scope: Scope
    tree: ast.Module
    calls: list[CallSite] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)


def import_module(file: PythonFile, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module or ""
    package = file.module.qualified_name.split(".")
    if PurePosixPath(file.path).stem != "__init__":
        package = package[:-1]
    if node.level > len(package):
        return None
    prefix = package[: len(package) - node.level + 1]
    return ".".join(prefix + ([node.module] if node.module else []))


class _Collector(ast.NodeVisitor):
    def __init__(self, file: PythonFile, symbols: list[SymbolRow]) -> None:
        self.file = file
        self.scope = file.scope
        self.rows = {(s.local_name, s.start_line): s for s in symbols}
        self.lines = file.source.decode("utf-8").splitlines()
        self.names: dict[tuple[int, str], tuple[int, int]] = {}
        tokens = iter(tokenize.generate_tokens(io.StringIO(file.source.decode("utf-8")).readline))
        for token in tokens:
            if token.type == tokenize.NAME and token.string in {"def", "class"}:
                name = next(tokens)
                if name.type == tokenize.NAME:
                    line, col = name.start
                    prefix = self.lines[line - 1][:col]
                    self.names[(token.start[0], name.string)] = (
                        line - 1,
                        len(prefix.encode("utf-16-le")) // 2,
                    )

    def row(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> SymbolRow | None:
        parent = self.scope.owner.local_name
        name = f"{parent}.{node.name}" if parent else node.name
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        return self.rows.get((name, start))

    def bind(self, node: ast.AST, conditional: bool = False) -> None:
        """Collect bindings for the whole lexical scope before resolving calls."""
        if isinstance(node, DEFINITIONS):
            row = self.row(node)
            self.scope.add(node.name, Binding(symbol=row) if row and not conditional else None)
            return
        if isinstance(node, ast.Import):
            for item in node.names:
                name = item.asname or item.name.split(".")[0]
                target = item.name if item.asname else name
                self.scope.add(name, None if conditional else Binding(module=target))
            return
        if isinstance(node, ast.ImportFrom):
            module = import_module(self.file, node)
            for item in node.names:
                if item.name == "*":
                    self.scope.star = True
                else:
                    binding = Binding(module=module, member=item.name)
                    self.scope.add(item.asname or item.name, None if conditional else binding)
            return
        if isinstance(node, (ast.Name, ast.arg)):
            if isinstance(node, ast.arg):
                self.scope.add(node.arg)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                self.scope.add(node.id)
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                self.scope.add(name)
            return
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            name = dotted(node)
            if name:
                self.scope.add(name.split(".")[0])
            return
        if isinstance(node, ast.ExceptHandler) and node.name:
            self.scope.add(node.name)
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            self.scope.add(node.name)
        if isinstance(node, ast.MatchMapping) and node.rest:
            self.scope.add(node.rest)
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            # Walrus binds outside the comprehension. Iteration variables do not.
            for child in ast.walk(node):
                if isinstance(child, ast.NamedExpr):
                    self.bind(child.target)
            return
        conditional |= isinstance(
            node, (ast.If, ast.Try, ast.TryStar, ast.For, ast.AsyncFor, ast.While, ast.Match)
        )
        for child in ast.iter_child_nodes(node):
            self.bind(child, conditional)

    def visit_Call(self, node: ast.Call) -> None:
        callee = node.func
        line = callee.lineno
        if isinstance(callee, ast.Attribute):
            line = callee.end_lineno or line
        col = callee.col_offset
        if isinstance(callee, ast.Attribute):
            col = (callee.end_col_offset or col) - len(callee.attr.encode("utf-8"))
        self.file.calls.append(
            CallSite(
                self.file.path,
                node,
                self.scope,
                line - 1,
                utf16_column(self.lines[line - 1], col),
                ast.get_source_segment(self.file.source.decode("utf-8"), callee) or "<call>",
            )
        )
        self.generic_visit(node)

    def _definition(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        row = self.row(node)
        if row:
            position = self.names.get((node.lineno, node.name))
            if position:
                self.file.definitions.append(Definition(row, *position))
        for decorator in node.decorator_list:
            self.visit(decorator)
        if isinstance(node, ast.ClassDef):
            for expression in [*node.bases, *node.keywords]:
                self.visit(expression)
        else:
            self.visit(node.args)  # defaults/annotations execute in the enclosing scope
            if node.returns:
                self.visit(node.returns)
        previous = self.scope
        # Method bodies do not inherit the class namespace as a lexical scope.
        parent = previous.parent if previous.is_class else previous
        self.scope = Scope(row or previous.owner, parent, is_class=isinstance(node, ast.ClassDef))
        if not isinstance(node, ast.ClassDef):
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                self.scope.add(arg.arg)
            for arg in (node.args.vararg, node.args.kwarg):
                if arg:
                    self.scope.add(arg.arg)
        for statement in node.body:
            self.bind(statement)
        for statement in node.body:
            self.visit(statement)
        self.scope = previous

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._definition(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._definition(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.visit(node.args)
        previous = self.scope
        self.scope = Scope(previous.owner, previous)
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            self.scope.add(arg.arg)
        for arg in (node.args.vararg, node.args.kwarg):
            if arg:
                self.scope.add(arg.arg)
        self.bind(node.body)
        self.visit(node.body)
        self.scope = previous

    def _comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        previous = self.scope
        self.visit(node.generators[0].iter)
        self.scope = Scope(previous.owner, previous)
        for generator in node.generators:
            self.bind(generator.target)
        for i, generator in enumerate(node.generators):
            if i:
                self.visit(generator.iter)
            for expression in generator.ifs:
                self.visit(expression)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.scope = previous

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension


def collect(path: str, source: bytes, index: Index) -> PythonFile:
    rows = index.symbols(path=path)
    module = next(row for row in rows if row.kind is SymbolKind.MODULE)
    tree = ast.parse(source.decode("utf-8"))
    file = PythonFile(path, source, module, Scope(module), tree)
    visitor = _Collector(file, rows)
    for statement in tree.body:
        visitor.bind(statement)
    visitor.visit(tree)
    return file


class ImportResolver:
    def __init__(self, files: dict[str, PythonFile], index: Index) -> None:
        self.files = files
        self.modules: dict[str, list[PythonFile]] = defaultdict(list)
        self.members: dict[tuple[str, str], list[SymbolRow]] = defaultdict(list)
        for file in files.values():
            self.modules[file.module.qualified_name].append(file)
        for row in index.symbols():
            if row.language is Language.PYTHON:
                self.members[(row.path, row.local_name)].append(row)

    def module_member(
        self, module: str, member: str, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> SymbolRow | None:
        key = (module, member)
        if key in seen or len(seen) >= 32:
            return None
        seen = seen | {key}
        files = self.modules.get(module, [])
        if len(files) > 1:
            return None
        if not files:
            # Namespace packages have no __init__.py, but their children may exist.
            head, _, tail = member.partition(".")
            return self.module_member(f"{module}.{head}", tail, seen) if head else None
        file = files[0]
        if not member:
            return file.module
        head, _, tail = member.partition(".")
        if file.scope.star:
            return None
        if head in file.scope.bindings:
            binding = file.scope.bindings[head]
            return self.binding(binding, tail, seen)
        return self.module_member(f"{module}.{head}", tail, seen)

    def binding(
        self,
        binding: Binding | None,
        suffix: str,
        seen: frozenset[tuple[str, str]] = frozenset(),
    ) -> SymbolRow | None:
        if binding is None:
            return None
        if binding.symbol:
            row = binding.symbol
            if not suffix:
                return row
            if row.kind is SymbolKind.CLASS:
                members = self.members.get((row.path, f"{row.local_name}.{suffix}"), [])
                return members[0] if len(members) == 1 else None
            return None
        if binding.module:
            member = ".".join(p for p in (binding.member, suffix) if p)
            return self.module_member(binding.module, member, seen)
        return None

    def resolve(self, call: CallSite) -> SymbolRow | None:
        name = dotted(call.node.func)
        if name is None:
            return None
        head, _, tail = name.partition(".")
        result = self.binding(call.scope.lookup(head), tail)
        return result if result and result.kind in CALLABLE_KINDS else None
