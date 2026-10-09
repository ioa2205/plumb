"""SQLAlchemy and raw-SQL syntax summaries over Python snapshot ASTs."""

# Each closure is consumed in its loop iteration; none escape or run asynchronously.
# ruff: noqa: B023

import ast
from collections.abc import Iterator

from analysis.access_facts import AccessFact, CallFact, FunctionFacts, Parameter, sql_access
from analysis.index import Index
from analysis.python_syntax import CallSite, ImportResolver, PythonFile, Scope, collect, dotted
from analysis.snapshot import SnapshotStore
from backend.contracts.code import DataLayer, Operation, ProjectSnapshot, SymbolKind
from backend.contracts.common import Language


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _walk(child)


def _external(node: ast.expr | None, scope: Scope, package: str, member: str | None = None) -> bool:
    name = dotted(node) if node else None
    binding = scope.lookup(name.split(".")[0]) if name else None
    actual = (
        ".".join(p for p in (binding.member, name.partition(".")[2]) if p)
        if binding and name
        else ""
    )
    return bool(
        binding
        and binding.module
        and (binding.module == package or binding.module.startswith(package + "."))
        and (member is None or actual == member)
    )


def python_access_facts(
    snapshot: ProjectSnapshot, store: SnapshotStore, index: Index
) -> tuple[list[FunctionFacts], list[str]]:
    files: dict[str, PythonFile] = {}
    issues: list[str] = []
    for file in snapshot.files:
        if file.language is Language.PYTHON:
            try:
                files[file.path] = collect(file.path, store.read(snapshot, file.path), index)
            except (SyntaxError, UnicodeError):
                issues.append(f"{file.path}: Python access syntax unavailable")
    resolver = ImportResolver(files, index)
    shadowed = any(
        name == "sqlalchemy" or name.startswith("sqlalchemy.") for name in resolver.modules
    )
    facts: list[FunctionFacts] = []
    for file in files.values():
        rows = {r.id: r for r in index.symbols(file.path)}
        for fn in (
            n for n in ast.walk(file.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            start = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
            candidates = [
                r
                for r in rows.values()
                if r.name == fn.name
                and r.start_line == start
                and r.kind in {SymbolKind.FUNCTION, SymbolKind.METHOD}
            ]
            if len(candidates) != 1:
                continue
            row = candidates[0]
            calls = [c for c in file.calls if c.scope.owner.id == row.id]
            scope = calls[0].scope if calls else file.scope
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
                    a.arg: d
                    for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True)
                    if d is not None
                }
            )
            parameters: list[Parameter] = []
            for i, arg in enumerate(args):
                default = defaults.get(arg.arg)
                hint = None
                if isinstance(default, ast.Call):
                    for construct, origin in (
                        ("Query", "query"),
                        ("Path", "path"),
                        ("Body", "body"),
                        ("Form", "body"),
                        ("Header", "header"),
                        ("Cookie", "header"),
                    ):
                        if _external(default.func, scope, "fastapi", construct):
                            hint = origin
                elif isinstance(arg.annotation, ast.Name) and arg.annotation.id in {
                    "int",
                    "str",
                    "float",
                    "bool",
                }:
                    hint = "query"
                parameters.append(Parameter(name=arg.arg, index=i, request_hint=hint))
            env = {p.name: {f"p{p.index}"} for p in parameters}
            sessions = {
                a.arg
                for a in args
                if not shadowed and _external(a.annotation, scope, "sqlalchemy", "Session")
            }
            constants: dict[str, ast.expr] = {}
            for stmt in file.tree.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    constants[stmt.targets[0].id] = stmt.value

            def inputs(expr: ast.AST | None) -> set[str]:
                if expr is None or isinstance(expr, ast.Constant):
                    return set()
                if isinstance(expr, ast.Name):
                    return env.get(expr.id, {"?"})
                if isinstance(expr, ast.Call):
                    result = set().union(
                        *(inputs(a) for a in expr.args), *(inputs(k.value) for k in expr.keywords)
                    )
                    if isinstance(expr.func, ast.Attribute):
                        result |= inputs(expr.func.value)
                    return result or {"?"}
                return set().union(*(inputs(c) for c in ast.iter_child_nodes(expr)))

            def string(expr: ast.expr, seen: frozenset[str] = frozenset()) -> str | None:
                if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                    return expr.value
                if isinstance(expr, ast.Name) and expr.id in constants and expr.id not in seen:
                    return string(constants[expr.id], seen | {expr.id})
                if isinstance(expr, ast.JoinedStr):
                    return "".join(
                        v.value
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                        else "__dynamic__"
                        for v in expr.values
                    )
                if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                    left, right = string(expr.left, seen), string(expr.right, seen)
                    return left + right if left is not None and right is not None else None
                if (
                    isinstance(expr, ast.Call)
                    and expr.args
                    and _external(expr.func, scope, "sqlalchemy")
                ):
                    return string(expr.args[0], seen)
                return None

            def resource(expr: ast.expr, call: CallSite) -> str | None:
                name = dotted(expr)
                if not name:
                    return None
                head, _, tail = name.partition(".")
                resolved = resolver.binding(call.scope.lookup(head), tail)
                return resolved.name if resolved and resolved.kind is SymbolKind.CLASS else None

            def access(call: CallSite) -> AccessFact | None:
                node = call.node
                if not isinstance(node.func, ast.Attribute) or not isinstance(
                    node.func.value, ast.Name
                ):
                    return None
                if node.func.value.id not in sessions:
                    return None
                method = node.func.attr
                found_resource: str | None = None
                key: ast.expr | None = None
                layer, operation = DataLayer.SQLALCHEMY, Operation.READ
                key_values: set[str] = set()
                expression = ""
                if method == "get" and len(node.args) >= 2:
                    found_resource, key = resource(node.args[0], call), node.args[1]
                elif method in {"scalar", "scalars", "execute"} and node.args:
                    query = node.args[0]
                    select = next(
                        (
                            n
                            for n in ast.walk(query)
                            if isinstance(n, ast.Call)
                            and n.args
                            and _external(n.func, call.scope, "sqlalchemy", "select")
                        ),
                        None,
                    )
                    if select:
                        found_resource = resource(select.args[0], call)
                        comparisons = [
                            n
                            for n in ast.walk(query)
                            if isinstance(n, ast.Compare)
                            and len(n.ops) == 1
                            and isinstance(n.ops[0], ast.Eq)
                            and isinstance(n.left, ast.Attribute)
                            and (n.left.attr == "id" or n.left.attr.endswith("_id"))
                        ]
                        primary = [
                            c
                            for c in comparisons
                            if isinstance(c.left, ast.Attribute) and c.left.attr == "id"
                        ]
                        for comparison in primary or comparisons:
                            key_values |= inputs(comparison.comparators[0])
                        expression = ", ".join(ast.unparse(c) for c in primary or comparisons)
                        keyed = [
                            k
                            for n in ast.walk(query)
                            if isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "filter_by"
                            for k in n.keywords
                            if k.arg == "id" or (k.arg is not None and k.arg.endswith("_id"))
                        ]
                        keyed_primary = [k for k in keyed if k.arg == "id"]
                        if not comparisons and keyed:
                            for keyword in keyed_primary or keyed:
                                key_values |= inputs(keyword.value)
                            expression = ", ".join(
                                f"{k.arg}={ast.unparse(k.value)}" for k in keyed_primary or keyed
                            )
                        if not comparisons and not keyed:
                            return None
                    else:
                        sql = string(query)
                        parsed = sql_access(sql) if sql else None
                        if not parsed:
                            return None
                        found_resource, operation, keys = parsed
                        layer = DataLayer.RAW_SQL
                        values = node.args[1] if len(node.args) > 1 else None
                        for bind in keys:
                            value: ast.expr | None = None
                            if isinstance(bind, str) and isinstance(values, ast.Dict):
                                value = next(
                                    (
                                        v
                                        for k, v in zip(values.keys, values.values, strict=True)
                                        if isinstance(k, ast.Constant) and k.value == bind
                                    ),
                                    None,
                                )
                            elif (
                                isinstance(bind, int)
                                and isinstance(values, (ast.Tuple, ast.List))
                                and bind < len(values.elts)
                            ):
                                value = values.elts[bind]
                            key_values |= inputs(value) if value else {"?"}
                        expression = ast.unparse(values) if values else "unknown bindings"
                if key is not None:
                    key_values, expression = inputs(key), ast.unparse(key)
                if not found_resource:
                    return None
                return AccessFact(
                    resource=found_resource,
                    operation=operation,
                    data_layer=layer,
                    key_inputs=sorted(key_values),
                    key_expression=expression,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    reason=(
                        "SQLAlchemy-annotated receiver and static query syntax; "
                        "possible input influence"
                    ),
                )

            call_by_node = {id(c.node): c for c in calls}
            summaries: list[CallFact] = []
            accesses: list[AccessFact] = []
            # Flow-insensitive union avoids losing an input at a branch or reassignment;
            # it is possible influence, never a reachability or guard proof.
            nodes = [n for stmt in fn.body for n in _walk(stmt)]
            for _ in range(min(len(nodes) + 1, 16)):
                changed = False
                for n in nodes:
                    if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        for target in targets:
                            if isinstance(target, ast.Name):
                                prior = env.get(target.id, set())
                                value = prior | inputs(n.value)
                                if value != prior:
                                    env[target.id], changed = value, True
                if not changed:
                    break
            for n in nodes:
                if isinstance(n, ast.Call) and (call := call_by_node.get(id(n))) is not None:
                    summaries.append(
                        CallFact(
                            line=call.line + 1,
                            column=call.column,
                            arguments=[sorted(inputs(a)) for a in n.args],
                            keywords={k.arg: sorted(inputs(k.value)) for k in n.keywords if k.arg},
                        )
                    )
                    candidate = access(call)
                    if candidate:
                        accesses.append(candidate)
            facts.append(
                FunctionFacts(
                    symbol_id=row.id, parameters=parameters, calls=summaries, accesses=accesses
                )
            )
    return facts, issues
