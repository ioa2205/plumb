"""Bounded Python sink facts and executable safety checks; never executes source."""

import ast
from dataclasses import dataclass

# Closures are consumed synchronously inside their function iteration.
# ruff: noqa: B023
from analysis.syntax import code_only
from backend.contracts.code import SourceSpan
from backend.contracts.common import Language


@dataclass(frozen=True)
class Value:
    inputs: frozenset[str] = frozenset()
    dynamic: bool = False
    allowlist: str | None = None
    resolved: bool = False
    uncertain: bool = False


@dataclass(frozen=True)
class SinkFact:
    kind: str
    function: str
    start: int
    end: int
    focus: int
    inputs: tuple[str, ...]
    mechanism: str
    risky: bool
    issues: tuple[str, ...] = ()
    provenance: tuple[SourceSpan, ...] = ()
    flow_notes: tuple[str, ...] = ()


def dotted(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def sinks(source: bytes) -> list[SinkFact]:
    """Only sequential top-level statements and canonical local forms are supported.

    Unsupported flow is retained as an issue; it cannot establish absence or acquit.
    Import names are resolved and local rebinding invalidates recognized sink identities.
    """
    try:
        tree = ast.parse(code_only(Language.PYTHON, source))
    except (SyntaxError, UnicodeError):
        return []
    imports: dict[str, str] = {}
    literals: dict[str, ast.Dict] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update({a.asname or a.name: a.name for a in node.names})
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.update({a.asname or a.name: f"{node.module}.{a.name}" for a in node.names})
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = node.targets[0].id
            if (
                isinstance(node.value, ast.Dict)
                and node.value.keys
                and all(
                    isinstance(n, ast.Constant) and isinstance(n.value, str)
                    for n in [*node.value.keys, *node.value.values]
                )
            ):
                literals[name] = node.value
    # Mutation/rebinding makes a module map unsuitable as a closed allowlist.
    for name in list(literals):
        writes = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store)
        ]
        mutation = any(
            isinstance(n, ast.Call)
            and dotted(n.func).startswith(name + ".")
            and not dotted(n.func).endswith(".get")
            for n in ast.walk(tree)
        )
        escaped = any(
            isinstance(n, ast.Name)
            and n.id == name
            and isinstance(n.ctx, ast.Load)
            and not any(
                isinstance(p, ast.Attribute) and p.value is n and p.attr == "get"
                for p in ast.walk(tree)
            )
            for n in ast.walk(tree)
        )
        if (
            len(writes) != 1
            or mutation
            or escaped
            or any(
                isinstance(n, ast.Subscript)
                and dotted(n.value) == name
                and isinstance(n.ctx, ast.Store)
                for n in ast.walk(tree)
            )
        ):
            literals.pop(name)
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            imports.pop(dotted(node).split(".")[0], None)
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    imports.pop(target.id, None)
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        params = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
        defaults = (
            {
                a.arg: d
                for a, d in zip(
                    fn.args.args[-len(fn.args.defaults) :], fn.args.defaults, strict=False
                )
            }
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
        dependency_params = {
            name
            for name, default in defaults.items()
            if isinstance(default, ast.Call) and dotted(default.func).endswith("Depends")
        }
        values = {
            a.arg: Value(frozenset({a.arg}), True)
            for a in params
            if a.arg not in dependency_params
            and dotted(a.annotation) not in {"Request", "Session", "User"}
        }
        local = {
            n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        } | {a.arg for a in params}
        local.update(
            a.asname or a.name.split(".")[0]
            for n in ast.walk(fn)
            if isinstance(n, ast.Import | ast.ImportFrom)
            for a in n.names
        )
        safe_maps = {n: m for n, m in literals.items() if n not in local}
        denied: set[str] = set()
        contained: set[str] = set()
        resolved_roots: set[str] = set()

        def value(node: ast.AST) -> Value:
            if isinstance(node, ast.Constant):
                return Value()
            if isinstance(node, ast.Name):
                return values.get(node.id, Value(dynamic=node.id not in safe_maps))
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                if name.endswith(".get") and name.rsplit(".", 1)[0] in safe_maps and node.args:
                    if len(node.args) != 1 or node.keywords:
                        return Value(uncertain=True, dynamic=True)
                    raw = value(node.args[0])
                    return Value(raw.inputs, True, name.rsplit(".", 1)[0], uncertain=raw.uncertain)
                if isinstance(node.func, ast.Attribute) and node.func.attr == "resolve":
                    raw = value(node.func.value)
                    if node.args or node.keywords:
                        return Value(uncertain=True, dynamic=True)
                    return Value(raw.inputs, raw.dynamic, raw.allowlist, True, raw.uncertain)
            children = [value(c) for c in ast.iter_child_nodes(node)]
            return Value(
                frozenset().union(*(c.inputs for c in children)),
                any(c.dynamic for c in children) or isinstance(node, ast.Attribute),
                uncertain=any(c.uncertain for c in children) or isinstance(node, ast.Call),
            )

        def actual(node: ast.expr) -> str:
            name = dotted(node)
            root, _, suffix = name.partition(".")
            return "" if root in local else imports.get(root, "") + ("." + suffix if suffix else "")

        issues = tuple(
            ["Unsupported control flow; absence and safety are not established"]
            if any(
                isinstance(
                    n,
                    ast.Try
                    | ast.For
                    | ast.While
                    | ast.With
                    | ast.Match
                    | ast.AugAssign
                    | ast.AnnAssign
                    | ast.Delete
                    | ast.FunctionDef
                    | ast.AsyncFunctionDef,
                )
                or (
                    isinstance(n, ast.If)
                    and (
                        n.orelse or not n.body or not all(isinstance(b, ast.Raise) for b in n.body)
                    )
                )
                or any(isinstance(c, ast.NamedExpr) for c in ast.walk(n))
                or (
                    isinstance(n, ast.Assign)
                    and (len(n.targets) != 1 or not isinstance(n.targets[0], ast.Name))
                )
                for n in fn.body
            )
            else []
        )
        for statement in fn.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                name = statement.targets[0].id
                if name in resolved_roots:
                    contained.clear()
                values[name] = value(statement.value)
                denied.discard(name)
                contained.discard(name)
                resolved_roots.discard(name)
                base = (
                    statement.value.func.value
                    if isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    else None
                )
                fixed_config = dotted(base).startswith("request.app.state.settings.")
                if values[name].resolved and not values[name].inputs and fixed_config:
                    resolved_roots.add(name)
            if (
                isinstance(statement, ast.If)
                and statement.body
                and all(isinstance(n, ast.Raise) for n in statement.body)
            ):
                condition = statement.test
                atoms = (
                    condition.values
                    if isinstance(condition, ast.BoolOp) and isinstance(condition.op, ast.Or)
                    else [condition]
                )
                for atom in atoms:
                    if (
                        isinstance(atom, ast.Compare)
                        and len(atom.ops) == 1
                        and isinstance(atom.ops[0], ast.Is)
                        and isinstance(atom.comparators[0], ast.Constant)
                        and atom.comparators[0].value is None
                    ):
                        denied.add(dotted(atom.left))
                    if (
                        isinstance(atom, ast.UnaryOp)
                        and isinstance(atom.op, ast.Not)
                        and isinstance(atom.operand, ast.Call)
                    ):
                        call = atom.operand
                        if dotted(call.func).endswith(".is_relative_to") and len(call.args) == 1:
                            path = (
                                dotted(call.func.value)
                                if isinstance(call.func, ast.Attribute)
                                else ""
                            )
                            root = dotted(call.args[0])
                            if values.get(path, Value()).resolved and root in resolved_roots:
                                contained.add(path)
            # Calls inside straight-line expressions are included.
            candidates = (
                [statement.value]
                if isinstance(statement, ast.Return) and statement.value
                else [statement]
            )
            for candidate in candidates:
                for call in ast.walk(candidate):
                    if not isinstance(call, ast.Call) or not call.args:
                        continue
                    target = actual(call.func)
                    kind = (
                        "command"
                        if target
                        in {"subprocess.run", "subprocess.check_output", "subprocess.Popen"}
                        else "path"
                        if target == "fastapi.responses.FileResponse"
                        else "sql"
                        if dotted(call.func).endswith(".execute")
                        else None
                    )
                    if kind is None:
                        continue
                    argument = call.args[0]
                    if kind == "sql":
                        if (
                            not isinstance(argument, ast.Call)
                            or actual(argument.func) != "sqlalchemy.text"
                            or not argument.args
                        ):
                            continue
                        argument = argument.args[0]
                    raw = value(argument)
                    mechanism, risky = "none_found", False
                    if kind == "sql":
                        dynamic_names = {
                            n.id for n in ast.walk(argument) if isinstance(n, ast.Name)
                        }
                        allowed = bool(dynamic_names) and all(
                            values.get(n, Value()).allowlist and n in denied for n in dynamic_names
                        )
                        if allowed:
                            mechanism = "allowlisted"
                        elif not raw.dynamic:
                            mechanism = "parameterized"
                        else:
                            risky = bool(raw.inputs)
                    elif kind == "command":
                        shell = next(
                            (k.value for k in call.keywords if k.arg == "shell"),
                            ast.Constant(False),
                        )
                        if (
                            isinstance(argument, ast.List)
                            and argument.elts
                            and isinstance(argument.elts[0], ast.Constant)
                            and isinstance(argument.elts[0].value, str)
                            and isinstance(shell, ast.Constant)
                            and shell.value is False
                            and not any(
                                k.arg is None or k.arg == "executable" for k in call.keywords
                            )
                        ):
                            mechanism = "parameterized"
                        elif isinstance(shell, ast.Constant) and shell.value is True:
                            risky = bool(raw.inputs)
                    elif dotted(argument) in contained:
                        mechanism = "contained"
                    else:
                        risky = bool(raw.inputs)
                    results.append(
                        SinkFact(
                            kind,
                            fn.name,
                            min([fn.lineno, *[d.lineno for d in fn.decorator_list]]),
                            fn.end_lineno or fn.lineno,
                            call.lineno,
                            tuple(sorted(raw.inputs)),
                            mechanism,
                            risky,
                            (
                                *issues,
                                *(
                                    ["Unresolved call or stored-value provenance"]
                                    if raw.uncertain and mechanism == "none_found"
                                    else []
                                ),
                            ),
                        )
                    )
            if isinstance(statement, ast.Return | ast.Raise):
                break
    return results
