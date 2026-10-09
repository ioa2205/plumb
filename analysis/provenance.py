"""Bounded executable argument/return and exact ORM-field provenance over frozen ASTs.

Unknown calls consume their input (they may sanitize it); a known sibling segment
in a concatenation keeps its own provenance. Database selectors never taint fields.
"""

import ast
from dataclasses import dataclass, replace

from analysis.fastapi import FastAPIMap, extract_fastapi
from analysis.index import Index, SymbolRow
from analysis.python_syntax import ImportResolver, PythonFile, Scope, collect, dotted
from analysis.snapshot import SnapshotStore
from backend.contracts.code import ProjectSnapshot, SourceSpan
from backend.contracts.common import Language

VERSION = "python-provenance-1"
MAX_DEPTH = 4
MAX_STEPS = 256


@dataclass(frozen=True)
class Flow:
    inputs: frozenset[str] = frozenset()
    evidence: tuple[SourceSpan, ...] = ()
    unknowns: tuple[str, ...] = ()
    resource: str | None = None
    session: str | None = None


def combine(values: list[Flow]) -> Flow:
    return Flow(
        frozenset().union(*(v.inputs for v in values)),
        tuple(_unique_spans(values)),
        tuple(dict.fromkeys(s for v in values for s in v.unknowns)),
    )


def _unique_spans(values: list[Flow]) -> list[SourceSpan]:
    return list({s.model_dump_json(): s for v in values for s in v.evidence}.values())


def builtin(scope: Scope, name: str) -> bool:
    while True:
        if scope.star or name in scope.bindings:
            return False
        if scope.parent is None:
            return True
        scope = scope.parent


class Provenance:
    def __init__(
        self,
        snapshot: ProjectSnapshot,
        store: SnapshotStore,
        index: Index,
        *,
        fastapi: FastAPIMap | None = None,
    ) -> None:
        self.snapshot, self.store, self.index = snapshot, store, index
        self.files: dict[str, PythonFile] = {}
        for file in snapshot.files:
            if file.language is Language.PYTHON:
                try:
                    self.files[file.path] = collect(
                        file.path, store.read(snapshot, file.path), index
                    )
                except (SyntaxError, UnicodeError):
                    continue
        self.resolver = ImportResolver(self.files, index)
        self.rows = {r.id: r for r in index.symbols() if r.language is Language.PYTHON}
        self.functions: dict[str, tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, Scope]] = {}
        self.calls = {
            (p, c.node.lineno, c.node.col_offset): c
            for p, file in self.files.items()
            for c in file.calls
        }
        self.classes: dict[str, ast.ClassDef] = {}
        for path, file in self.files.items():
            for node in ast.walk(file.tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    continue
                start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
                rows = [
                    r
                    for r in index.symbols(path=path)
                    if r.name == node.name and r.start_line == start
                ]
                if len(rows) != 1:
                    continue
                row = rows[0]
                if isinstance(node, ast.ClassDef):
                    self.classes[row.id] = node
                else:
                    scopes = [c.scope for c in file.calls if c.scope.owner.id == row.id]
                    self.functions[row.id] = (path, node, scopes[0] if scopes else file.scope)
        self.writes: dict[tuple[str, str], Flow] = {}
        routes = fastapi or extract_fastapi(snapshot, store, index)
        for route in routes.routes:
            if route.entry.handler_symbol_id in self.functions:
                self._writer(route.entry.handler_symbol_id)

    def span(self, path: str, node: ast.AST) -> SourceSpan:
        from analysis.syntax import span_sha256

        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start) or start
        return SourceSpan(
            snapshot_id=self.snapshot.id,
            path=path,
            start_line=start,
            end_line=end,
            content_sha256=span_sha256(self.files[path].source, start, end),
        )

    def binding(self, scope: Scope, node: ast.expr) -> SymbolRow | None:
        name = dotted(node)
        if not name:
            return None
        head, _, tail = name.partition(".")
        return self.resolver.binding(scope.lookup(head), tail)

    def external(self, scope: Scope, node: ast.expr | None, name: str) -> bool:
        value = dotted(node) if node is not None else None
        if not value:
            return False
        head, _, tail = value.partition(".")
        bound = scope.lookup(head)
        return bool(
            bound
            and bound.module
            and bound.symbol is None
            and ".".join(p for p in (bound.module, bound.member, tail) if p) == name
            and not any(
                m == name.split(".")[0] or m.startswith(name.split(".")[0] + ".")
                for m in self.resolver.modules
            )
        )

    def orm(self, row: SymbolRow | None, seen: frozenset[str] = frozenset()) -> bool:
        if row is None or row.id in seen or len(seen) >= MAX_DEPTH or row.id not in self.classes:
            return False
        node = self.classes[row.id]
        if node.decorator_list or any(
            isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in node.body
        ):
            return False  # custom construction/field validation may transform values
        scope = self.files[row.path].scope
        return any(
            self.external(scope, base, "sqlalchemy.orm.DeclarativeBase")
            or self.orm(self.binding(scope, base), seen | {row.id})
            for base in node.bases
        )

    def parameters(
        self, path: str, fn: ast.FunctionDef | ast.AsyncFunctionDef, scope: Scope
    ) -> dict[str, Flow]:
        args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
        defaults = (
            dict(
                zip(
                    [a.arg for a in [*fn.args.posonlyargs, *fn.args.args]][
                        -len(fn.args.defaults) :
                    ],
                    fn.args.defaults,
                    strict=False,
                )
            )
            if fn.args.defaults
            else {}
        )
        defaults.update(
            {
                a.arg: v
                for a, v in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True)
                if v is not None
            }
        )
        values = {}
        for arg in args:
            default = defaults.get(arg.arg)
            if self.external(scope, arg.annotation, "sqlalchemy.orm.Session"):
                values[arg.arg] = Flow(session=arg.arg, evidence=(self.span(path, arg),))
            elif (
                isinstance(default, ast.Call)
                and self.external(scope, default.func, "fastapi.Depends")
            ) or self.external(scope, arg.annotation, "fastapi.Request"):
                values[arg.arg] = Flow()
            elif (
                isinstance(arg.annotation, ast.Name)
                and arg.annotation.id in {"int", "bool"}
                and builtin(scope, arg.annotation.id)
            ):
                values[arg.arg] = Flow(evidence=(self.span(path, arg),))
            else:
                values[arg.arg] = Flow(frozenset({arg.arg}), (self.span(path, arg),))
        return values

    def expression(
        self,
        path: str,
        scope: Scope,
        node: ast.AST,
        values: dict[str, Flow],
        depth: int = 0,
        seen: frozenset[str] = frozenset(),
    ) -> Flow:
        if depth > MAX_DEPTH:
            return Flow(unknowns=("Argument/return provenance exceeds the bounded depth",))
        if isinstance(node, ast.Constant):
            return Flow()
        if isinstance(node, ast.Name):
            return values.get(node.id, Flow(unknowns=(f"Unresolved value {node.id}",)))
        if isinstance(node, ast.Attribute):
            base = self.expression(path, scope, node.value, values, depth, seen)
            if base.resource:
                field = self.writes.get((base.resource, node.attr))
                if field is not None:
                    # The stored write carries request source, not the read's numeric selector.
                    return Flow(
                        frozenset({dotted(node) or node.attr}),
                        (*base.evidence, *field.evidence, self.span(path, node)),
                        field.unknowns,
                    )
                return Flow(
                    evidence=base.evidence,
                    unknowns=(f"Stored field {node.attr} has no proven request-derived write",),
                )
            if base.inputs:
                return replace(
                    base,
                    inputs=frozenset({dotted(node) or i for i in base.inputs}),
                    evidence=(*base.evidence, self.span(path, node)),
                )
            return Flow(unknowns=base.unknowns or ("Unresolved attribute segment",))
        if isinstance(node, ast.Call):
            call = self.calls.get((path, node.lineno, node.col_offset))
            if call is None:
                return Flow(unknowns=("Unresolved call site",))
            name = dotted(node.func)
            # A genuine builtin conversion cannot sanitize another sibling segment.
            if (
                name in {"str", "int"}
                and name not in values
                and builtin(scope, name)
                and len(node.args) == 1
                and not node.keywords
            ):
                raw = self.expression(path, scope, node.args[0], values, depth, seen)
                if name == "int":
                    return Flow(evidence=(*raw.evidence, self.span(path, node)))
                return replace(raw, evidence=(*raw.evidence, self.span(path, node)))
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and not node.keywords
            ):
                db = self.expression(path, scope, node.func.value, values, depth, seen)
                resource = self.binding(call.scope, node.args[0])
                if db.session and resource is not None and self.orm(resource):
                    return Flow(
                        evidence=(self.span(path, node),), resource=resource.id, session=db.session
                    )
            target = self.resolver.resolve(call)
            if target is not None and target.id in self.functions and target.id not in seen:
                target_path, fn, target_scope = self.functions[target.id]
                if fn.decorator_list or isinstance(fn, ast.AsyncFunctionDef):
                    return Flow(unknowns=("Decorated or asynchronous helper is unresolved",))
                parameters = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
                if fn.args.vararg or fn.args.kwarg or any(k.arg is None for k in node.keywords):
                    return Flow(unknowns=("Variadic helper binding is unresolved",))
                names = [a.arg for a in parameters]
                positional = [a.arg for a in [*fn.args.posonlyargs, *fn.args.args]]
                if len(node.args) > len(positional):
                    return Flow(unknowns=("Helper argument binding is ambiguous",))
                bound = {
                    n: self.expression(path, scope, a, values, depth, seen)
                    for n, a in zip(positional, node.args, strict=False)
                }
                for kw in node.keywords:
                    if (
                        kw.arg is None
                        or kw.arg not in names
                        or kw.arg in bound
                        or kw.arg in {a.arg for a in fn.args.posonlyargs}
                    ):
                        return Flow(unknowns=("Helper keyword binding is ambiguous",))
                    bound[kw.arg] = self.expression(path, scope, kw.value, values, depth, seen)
                if set(bound) != set(names):
                    return Flow(unknowns=("Helper default/argument binding is unresolved",))
                flow = self._return(
                    target_path, fn, target_scope, bound, depth + 1, seen | {target.id}
                )
                return replace(flow, evidence=(*flow.evidence, self.span(path, node)))
            # Calls may transform/sanitize their arguments. Do not propagate them by name.
            return Flow(unknowns=(f"Unresolved transformation {name or 'dynamic call'}",))
        if isinstance(node, ast.BoolOp):
            branches = []
            for part in node.values:
                branches.append(self.expression(path, scope, part, values, depth, seen))
                if isinstance(part, ast.Constant) and (
                    (isinstance(node.op, ast.Or) and bool(part.value))
                    or (isinstance(node.op, ast.And) and not part.value)
                ):
                    break
            return combine(branches)
        if isinstance(node, ast.BinOp | ast.JoinedStr | ast.FormattedValue | ast.List | ast.Tuple):
            return combine(
                [
                    self.expression(path, scope, c, values, depth, seen)
                    for c in ast.iter_child_nodes(node)
                    if not isinstance(c, ast.operator | ast.boolop | ast.expr_context)
                ]
            )
        return Flow(unknowns=("Unsupported expression provenance",))

    def _return(
        self,
        path: str,
        fn: ast.FunctionDef | ast.AsyncFunctionDef,
        scope: Scope,
        values: dict[str, Flow],
        depth: int,
        seen: frozenset[str],
    ) -> Flow:
        for statement in fn.body[:MAX_STEPS]:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                value = self.expression(path, scope, statement.value, values, depth, seen)
                values[statement.targets[0].id] = replace(
                    value, evidence=(*value.evidence, self.span(path, statement))
                )
            elif isinstance(statement, ast.Return) and statement.value is not None:
                flow = self.expression(path, scope, statement.value, values, depth, seen)
                return replace(flow, evidence=(*flow.evidence, self.span(path, statement)))
            elif (
                isinstance(statement, ast.If)
                and not statement.orelse
                and statement.body
                and all(isinstance(s, ast.Raise) for s in statement.body)
                and not any(isinstance(n, ast.Call) for n in ast.walk(statement.test))
            ):
                continue
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                continue  # a docstring supplies no flow
            else:
                return Flow(unknowns=("Helper has unsupported control flow or effects",))
        return Flow(unknowns=("Helper return unavailable within the bounded body",))

    def flow(self, path: str, start: int, focus: int) -> Flow:
        matches = [
            item
            for item in self.functions.values()
            if item[0] == path
            and min([item[1].lineno, *[d.lineno for d in item[1].decorator_list]]) == start
        ]
        if len(matches) != 1:
            return Flow(unknowns=("Sink function identity is ambiguous",))
        _, fn, scope = matches[0]
        values = self.parameters(path, fn, scope)
        for statement in fn.body[:MAX_STEPS]:
            calls = [
                n for n in ast.walk(statement) if isinstance(n, ast.Call) and n.lineno == focus
            ]
            for call in calls:
                if not call.args:
                    continue
                name = dotted(call.func) or ""
                if (
                    name.endswith(".execute")
                    or name.endswith(".run")
                    or name.endswith(".check_output")
                    or name.endswith(".Popen")
                    or name.endswith("FileResponse")
                ):
                    argument = call.args[0]
                    if (
                        name.endswith(".execute")
                        and isinstance(argument, ast.Call)
                        and argument.args
                    ):
                        argument = argument.args[0]
                    return self.expression(path, scope, argument, values)
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                raw = self.expression(path, scope, statement.value, values)
                values[statement.targets[0].id] = replace(
                    raw, evidence=(*raw.evidence, self.span(path, statement))
                )
            elif isinstance(statement, ast.Return | ast.Raise):
                break
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                # An ignored effect may mutate an object argument or receiver. Keep
                # independent siblings, but do not retain the object's earlier flow.
                call = statement.value
                nodes = [*call.args, *[k.value for k in call.keywords]]
                if isinstance(call.func, ast.Attribute):
                    nodes.append(call.func.value)
                heads = {(dotted(n) or "").split(".")[0] for n in nodes}
                affected = [values[n] for n in heads if n in values]
                for name, value in list(values.items()):
                    if any(
                        value == v
                        or (v.resource is not None and value.resource == v.resource)
                        or (bool(v.inputs) and value.inputs == v.inputs)
                        for v in affected
                    ):
                        values[name] = Flow(unknowns=("Unresolved effect on sink source",))
        return Flow(unknowns=("Sink argument unavailable within the bounded body",))

    def _relationship(self, resource: str, field: str, child: str) -> SourceSpan | None:
        parent = self.rows[resource]
        scope = self.files[parent.path].scope
        for statement in self.classes[resource].body:
            if (
                not isinstance(statement, ast.AnnAssign)
                or not isinstance(statement.target, ast.Name)
                or statement.target.id != field
            ):
                continue
            call = statement.value
            if not isinstance(call, ast.Call) or not self.external(
                scope, call.func, "sqlalchemy.orm.relationship"
            ):
                return None
            if any(
                k.arg is None
                or (
                    k.arg == "viewonly"
                    and not (isinstance(k.value, ast.Constant) and k.value.value is False)
                )
                for k in call.keywords
            ):
                return None
            cascade = next(
                (k.value for k in call.keywords if k.arg == "cascade"),
                ast.Constant("save-update, merge"),
            )
            if (
                not isinstance(cascade, ast.Constant)
                or not isinstance(cascade.value, str)
                or not {"all", "save-update"}.intersection(
                    s.strip() for s in cascade.value.split(",")
                )
            ):
                return None
            annotation = statement.annotation
            # Only Mapped[list[ExactClass]] (including the quoted forward reference).
            if not isinstance(annotation, ast.Subscript) or not self.external(
                scope, annotation.value, "sqlalchemy.orm.Mapped"
            ):
                return None
            inner = annotation.slice
            if (
                not isinstance(inner, ast.Subscript)
                or dotted(inner.value) != "list"
                or not builtin(scope, "list")
            ):
                return None
            target = inner.slice
            if (
                isinstance(target, ast.Constant)
                and isinstance(target.value, str)
                and target.value.isidentifier()
            ):
                target = ast.Name(target.value)
            row = self.binding(scope, target)
            if row is not None and row.id == child:
                return self.span(parent.path, statement)
        return None

    def _writer(self, identity: str) -> None:
        path, fn, scope = self.functions[identity]
        if len(fn.body) > MAX_STEPS:
            return
        values = self.parameters(path, fn, scope)
        pending: list[tuple[str, str, Flow, str, str | None]] = []
        admitted: dict[str, tuple[str, SourceSpan]] = {}
        committed: dict[str, SourceSpan] = {}

        def constructor(call: ast.Call, owner: str, parent: str | None = None) -> None:
            site = self.calls.get((path, call.lineno, call.col_offset))
            row = self.resolver.resolve(site) if site is not None else None
            if not self.orm(row) or row is None or any(k.arg is None for k in call.keywords):
                return
            values[owner] = Flow(resource=row.id)
            for kw in call.keywords:
                raw = self.expression(path, scope, kw.value, values)
                if (
                    kw.arg is not None
                    and raw.inputs
                    and not raw.unknowns
                    and (field := self._field(row.id, kw.arg))
                ):
                    pending.append(
                        (
                            row.id,
                            kw.arg,
                            replace(raw, evidence=(*raw.evidence, self.span(path, call), field)),
                            owner,
                            parent,
                        )
                    )

        def statements(body: list[ast.stmt], loop: bool = False) -> bool:
            if len(body) > MAX_STEPS:
                return False
            for statement in body[:MAX_STEPS]:
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                ):
                    name = statement.targets[0].id
                    pending[:] = [
                        (r, f, v, o, p) for r, f, v, o, p in pending if o != name and p != name
                    ]
                    values[name] = self.expression(path, scope, statement.value, values)
                    admitted.pop(name, None)
                    if isinstance(statement.value, ast.Call):
                        constructor(statement.value, name)
                elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    call = statement.value
                    if not isinstance(call.func, ast.Attribute):
                        return False
                    receiver = self.expression(path, scope, call.func.value, values)
                    if (
                        call.func.attr == "add"
                        and receiver.session
                        and len(call.args) == 1
                        and not call.keywords
                        and isinstance(call.args[0], ast.Name)
                    ):
                        admitted[call.args[0].id] = (receiver.session, self.span(path, call))
                    elif (
                        call.func.attr == "commit"
                        and receiver.session
                        and not call.args
                        and not call.keywords
                        and not loop
                    ):
                        committed[receiver.session] = self.span(path, call)
                    elif (
                        call.func.attr == "append"
                        and len(call.args) == 1
                        and not call.keywords
                        and isinstance(call.args[0], ast.Call)
                        and isinstance(call.func.value, ast.Attribute)
                    ):
                        parent_name = dotted(call.func.value.value)
                        parent = values.get(parent_name or "", Flow())
                        site = self.calls.get((path, call.args[0].lineno, call.args[0].col_offset))
                        child = self.resolver.resolve(site) if site is not None else None
                        if (
                            parent.resource
                            and child
                            and (
                                relation := self._relationship(
                                    parent.resource, call.func.value.attr, child.id
                                )
                            )
                        ):
                            key = f"child:{call.lineno}"
                            constructor(call.args[0], key, parent_name)
                            pending[:] = [
                                (r, f, replace(v, evidence=(*v.evidence, relation)), o, p)
                                if o == key
                                else (r, f, v, o, p)
                                for r, f, v, o, p in pending
                            ]
                        else:
                            return False
                    else:
                        return False
                elif (
                    isinstance(statement, ast.For)
                    and not loop
                    and not statement.orelse
                    and isinstance(statement.target, ast.Name)
                ):
                    raw = self.expression(path, scope, statement.iter, values)
                    if not raw.inputs or raw.unknowns:
                        return False
                    values[statement.target.id] = replace(
                        raw, evidence=(*raw.evidence, self.span(path, statement.iter))
                    )
                    if not statements(statement.body, True):
                        return False
                    values.pop(statement.target.id, None)
                elif (
                    isinstance(statement, ast.If)
                    and not statement.orelse
                    and statement.body
                    and all(isinstance(s, ast.Raise) for s in statement.body)
                    and not any(isinstance(n, ast.Call) for n in ast.walk(statement.test))
                ):
                    continue
                elif isinstance(statement, ast.AugAssign) and loop:
                    # A separate scalar total cannot mutate the constructed child's field.
                    target = statement.target
                    if not isinstance(target, ast.Attribute) or (
                        dotted(target.value),
                        target.attr,
                    ) in {(o, f) for _, f, _, o, _ in pending}:
                        return False
                elif isinstance(statement, ast.Return):
                    break
                else:
                    return False
            return True

        if not statements(fn.body):
            return
        for resource, field, raw, owner, parent in pending:
            admission = admitted.get(parent or owner)
            if admission is None:
                continue
            session, added = admission
            if (
                session not in committed
                or added.start_line >= committed[session].start_line
                or any(
                    s.path == path and s.end_line >= committed[session].start_line
                    for s in raw.evidence
                )
                or values.get(parent or owner, Flow()).resource is None
            ):
                continue
            evidence = (*raw.evidence, added, committed[session])
            proof = replace(raw, evidence=evidence)
            previous = self.writes.get((resource, field))
            self.writes[(resource, field)] = combine([previous, proof]) if previous else proof

    def _field(self, resource: str, name: str) -> SourceSpan | None:
        row = self.rows[resource]
        scope = self.files[row.path].scope
        for statement in self.classes[resource].body:
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == name
                and isinstance(statement.annotation, ast.Subscript)
                and self.external(scope, statement.annotation.value, "sqlalchemy.orm.Mapped")
            ):
                value = statement.annotation.slice
                string = isinstance(value, ast.Name) and value.id == "str"
                optional = (
                    isinstance(value, ast.BinOp)
                    and isinstance(value.op, ast.BitOr)
                    and isinstance(value.left, ast.Name)
                    and value.left.id == "str"
                    and isinstance(value.right, ast.Constant)
                    and value.right.value is None
                )
                if (string or optional) and builtin(scope, "str"):
                    return self.span(row.path, statement)
        return None
