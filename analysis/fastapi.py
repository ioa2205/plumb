"""Static FastAPI routes and dependency chains; never imports the reviewed app."""

import ast
import hashlib
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from analysis.index import Index, SymbolRow, index_path
from analysis.python_syntax import PythonFile, collect, import_module
from analysis.resolution import LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from backend.contracts.code import EntryPoint, EntryPointKind, ProjectSnapshot, SourceSpan
from backend.contracts.common import Contract, Framework, Language

_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
_CONSTRUCTORS = {
    "fastapi.FastAPI",
    "fastapi.applications.FastAPI",
    "fastapi.APIRouter",
    "fastapi.routing.APIRouter",
}
_DEPENDS = {
    "fastapi.Depends",
    "fastapi.Security",
    "fastapi.params.Depends",
    "fastapi.params.Security",
}


class AuthSignal(Contract):
    kind: Literal["http_401_raise", "http_403_raise"]
    span: SourceSpan
    # Syntax only. No guard is confirmed here, and reachability is not proven.


class Dependency(Contract):
    expression: str
    parameter: str | None
    target_symbol_id: str | None
    factory_symbol_id: str | None = None
    factory_arguments: list[str] = Field(default_factory=list)
    status: LinkStatus
    reason: str
    span: SourceSpan
    auth_signals: list[AuthSignal] = Field(default_factory=list)
    children: list["Dependency"] = Field(default_factory=list)


class FastAPIRoute(Contract):
    entry: EntryPoint
    router_id: str
    mount_status: LinkStatus  # static declaration, not runtime reachability
    dependencies: list[Dependency]


class RouterFact(Contract):
    id: str
    kind: Literal["app", "router"]
    prefix: str | None
    span: SourceSpan


class FastAPIMap(Contract):
    snapshot_id: str
    routes: list[FastAPIRoute]
    routers: list[RouterFact]
    issues: list[str]


@dataclass(frozen=True)
class Ref:
    name: str


@dataclass(frozen=True)
class Bound:
    target: Ref
    factory_id: str
    arguments: tuple[str, ...]


@dataclass
class Router:
    fact: RouterFact
    specs: list["Spec"]


type Value = Ref | Bound | Router | None
type Env = dict[str, Value]
type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass
class Function:
    file: PythonFile
    node: FunctionNode
    row: SymbolRow
    env: Env
    body_env: Env | None = None


@dataclass(frozen=True)
class Spec:
    file: PythonFile
    node: ast.expr
    env: Env
    parameter: str | None = None
    implicit: ast.expr | None = None


@dataclass
class Declaration:
    function: Function
    decorator: ast.Call
    env: Env


@dataclass
class Mount:
    file: PythonFile
    call: ast.Call
    env: Env


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _literal(node: ast.expr | None, default: str = "") -> str | None:
    if node is None:
        return default
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _walk_body(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """This function's executable syntax, excluding nested function/class bodies."""
    for statement in body:
        yield statement
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from _walk_nodes(statement)


def _walk_nodes(node: ast.AST) -> Iterator[ast.AST]:
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _walk_nodes(child)


class Adapter:
    def __init__(self, snapshot: ProjectSnapshot, store: SnapshotStore, index: Index) -> None:
        if index.meta("snapshot_id") != snapshot.id:
            raise ValueError("adapter and index must use the same snapshot")
        self.snapshot, self.index = snapshot, index
        self.files: dict[str, PythonFile] = {}
        self.modules: dict[str, list[PythonFile]] = {}
        self.envs: dict[str, Env] = {}
        self.functions: dict[str, Function] = {}
        self.routers: dict[str, Router] = {}
        self.declarations: list[Declaration] = []
        self.mounts: list[Mount] = []
        self.issues: list[str] = []
        for file in snapshot.files:
            if file.language is not Language.PYTHON:
                continue
            try:
                parsed = collect(file.path, store.read(snapshot, file.path), index)
            except (SyntaxError, UnicodeError, ValueError):
                self.issues.append(f"{file.path}: Python syntax unavailable")
                continue
            self.files[file.path] = parsed
            self.modules.setdefault(parsed.module.qualified_name, []).append(parsed)
            self.envs[file.path] = {}
        for file in self.files.values():
            self._seed(file, file.tree.body, self.envs[file.path])
        for file in self.files.values():
            self._scan(file, file.tree.body, self.envs[file.path])

    def span(self, file: PythonFile, node: ast.AST) -> SourceSpan:
        start, end = getattr(node, "lineno", 1), getattr(node, "end_lineno", 1)
        return SourceSpan(
            snapshot_id=self.snapshot.id,
            path=file.path,
            start_line=start,
            end_line=end,
            content_sha256=span_sha256(file.source, start, end),
        )

    def _row(self, file: PythonFile, node: FunctionNode) -> SymbolRow | None:
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        return next(
            (
                s
                for s in self.index.symbols(path=file.path)
                if s.name == node.name and s.start_line == start
            ),
            None,
        )

    def _seed(self, file: PythonFile, body: list[ast.stmt], env: Env) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    env[alias.asname or alias.name.split(".")[0]] = Ref(
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
            elif isinstance(node, ast.ImportFrom):
                module = import_module(file, node)
                for alias in node.names:
                    if alias.name == "*":
                        for name in env:
                            env[name] = None
                        self.issues.append(
                            f"{file.path}:{node.lineno}: wildcard import bindings are unresolved"
                        )
                    if alias.name != "*" and module:
                        env[alias.asname or alias.name] = Ref(f"{module}.{alias.name}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                row = self._row(file, node)
                if row:
                    env[node.name] = Ref(row.qualified_name)
                    self.functions[row.qualified_name] = Function(file, node, row, env)
                    nested = dict(env)
                    self._seed(file, node.body, nested)
            elif isinstance(node, ast.ClassDef):
                env[node.name] = None  # class/callable-object dependencies stay unknown for now

    def dereference(self, value: Value, seen: frozenset[str] = frozenset()) -> Value:
        if isinstance(value, Ref) and any(
            len(files) > 1 and (value.name == module or value.name.startswith(module + "."))
            for module, files in self.modules.items()
        ):
            return None
        if not isinstance(value, Ref) or value.name in self.functions:
            return value
        if value.name in seen or len(seen) >= 32:
            return None
        for module in sorted(self.modules, key=len, reverse=True):
            if value.name == module:
                return value if len(self.modules[module]) == 1 else None
            if not value.name.startswith(module + "."):
                continue
            files = self.modules[module]
            if len(files) != 1:
                return None
            tail = value.name[len(module) + 1 :]
            head, dot, suffix = tail.partition(".")
            env = self.envs[files[0].path]
            if head not in env:
                continue
            target = env[head]
            if dot:
                target = Ref(f"{target.name}.{suffix}") if isinstance(target, Ref) else None
            if target == value:
                return target
            return self.dereference(target, seen | {value.name})
        return value

    def value(self, node: ast.expr | None, env: Env) -> Value:
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Attribute):
            parent = self.value(node.value, env)
            return Ref(f"{parent.name}.{node.attr}") if isinstance(parent, Ref) else None
        if isinstance(node, ast.Call):
            fn = self.dereference(self.value(node.func, env))
            if isinstance(fn, Ref) and fn.name in self.functions:
                factory = self.functions[fn.name]
                returns = [n for n in _walk_body(factory.node.body) if isinstance(n, ast.Return)]
                if (
                    len(returns) == 1
                    and returns[0] is factory.node.body[-1]
                    and isinstance(returns[0].value, ast.Name)
                ):
                    child_name = f"{fn.name}.{returns[0].value.id}"
                    rebound = any(
                        isinstance(n, ast.Name)
                        and isinstance(n.ctx, (ast.Store, ast.Del))
                        and n.id == returns[0].value.id
                        for n in _walk_body(factory.node.body)
                    )
                    if child_name in self.functions and not rebound:
                        arguments = tuple(ast.unparse(arg) for arg in node.args)
                        arguments += tuple(
                            f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords
                        )
                        return Bound(Ref(child_name), factory.row.id, arguments)
        return None

    def name(self, node: ast.expr | None, env: Env) -> str | None:
        value = self.dereference(self.value(node, env))
        if not isinstance(value, Ref):
            return None
        # A project module named fastapi/typing is not the external framework.
        if any(
            value.name == module or value.name.startswith(module + ".") for module in self.modules
        ):
            return None
        return value.name

    def registrations_in(self, node: ast.AST, env: Env) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and self.name(child.func, env) in _CONSTRUCTORS:
                return True
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                receiver = self.dereference(self.value(child.func.value, env))
                if isinstance(receiver, Router) and child.func.attr in _METHODS | {
                    "include_router",
                    "api_route",
                }:
                    return True
        return False

    def specs(self, file: PythonFile, call: ast.Call, env: Env) -> list[Spec]:
        dependencies = _keyword(call, "dependencies")
        if dependencies is None:
            return []
        nodes = (
            dependencies.elts if isinstance(dependencies, (ast.List, ast.Tuple)) else [dependencies]
        )
        return [Spec(file, node, dict(env)) for node in nodes]

    def _scan(self, file: PythonFile, body: list[ast.stmt], env: Env) -> None:
        for node in body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                rhs = node.value
                value = self.value(rhs, env)
                if isinstance(rhs, ast.Call) and self.name(rhs.func, env) in _CONSTRUCTORS:
                    name = self.name(rhs.func, env) or ""
                    kind = "app" if name.endswith(".FastAPI") else "router"
                    digest = hashlib.sha256(f"{file.path}:{node.lineno}".encode()).hexdigest()
                    identity = f"router:{digest[:24]}"
                    fact = RouterFact(
                        id=identity,
                        kind=kind,
                        prefix=_literal(_keyword(rhs, "prefix")),
                        span=self.span(file, rhs),
                    )
                    value = Router(fact, self.specs(file, rhs, env))
                    self.routers[identity] = value
                for target in targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = value
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                row = self._row(file, node)
                if not row:
                    continue
                function = Function(file, node, row, dict(env))
                self.functions[row.qualified_name] = function
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(
                        decorator.func, ast.Attribute
                    ):
                        self.declarations.append(Declaration(function, decorator, dict(env)))
                nested = dict(env)
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                    nested[arg.arg] = None
                for arg in (node.args.vararg, node.args.kwarg):
                    if arg:
                        nested[arg.arg] = None
                self._seed(file, node.body, nested)
                self._scan(file, node.body, nested)
                function.body_env = nested
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == "include_router":
                    self.mounts.append(Mount(file, call, dict(env)))
                elif (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"add_api_route", "mount", "add_route"}
                    and isinstance(self.dereference(self.value(call.func.value, env)), Router)
                ):
                    self.issues.append(
                        f"{file.path}:{call.lineno}: {call.func.attr} registration is unresolved"
                    )
            elif isinstance(node, ast.For):
                if (
                    isinstance(node.target, ast.Name)
                    and isinstance(node.iter, (ast.Tuple, ast.List))
                    and len(node.iter.elts) <= 128
                ):
                    for item in node.iter.elts:
                        nested = {**env, node.target.id: self.value(item, env)}
                        self._scan(file, node.body, nested)
                elif self.registrations_in(node, env):
                    self.issues.append(f"{file.path}:{node.lineno}: dynamic loop not expanded")
            elif isinstance(
                node, (ast.If, ast.Try, ast.TryStar, ast.While, ast.With, ast.AsyncWith)
            ):
                # No branch execution or reachability guesses. Report possible
                # registrations in unsupported control flow instead of dropping silently.
                if self.registrations_in(node, env):
                    self.issues.append(
                        f"{file.path}:{node.lineno}: conditional registration is unresolved"
                    )

    def signature(self, function: Function) -> list[Spec]:
        args, file, env = function.node.args, function.file, function.env
        positional = [*args.posonlyargs, *args.args]
        defaults: dict[str, ast.expr | None] = dict(
            zip(
                (a.arg for a in positional[len(positional) - len(args.defaults) :]),
                args.defaults,
                strict=True,
            )
        )
        defaults.update(
            {a.arg: default for a, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)}
        )
        specs: list[Spec] = []
        for arg in [*positional, *args.kwonlyargs]:
            annotation = arg.annotation
            candidates = [defaults.get(arg.arg)]
            implicit = annotation
            if (
                isinstance(annotation, ast.Subscript)
                and self.name(annotation.value, env)
                in {"typing.Annotated", "typing_extensions.Annotated"}
                and isinstance(annotation.slice, ast.Tuple)
            ):
                implicit = annotation.slice.elts[0]
                candidates.extend(annotation.slice.elts[1:])
            for candidate in candidates:
                if isinstance(candidate, ast.Call) and self.name(candidate.func, env) in _DEPENDS:
                    specs.append(Spec(file, candidate, env, arg.arg, implicit))
        return specs

    def signals(self, function: Function) -> list[AuthSignal]:
        out: list[AuthSignal] = []
        for node in _walk_body(function.node.body):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            call = node.exc
            if self.name(call.func, function.body_env or function.env) not in {
                "fastapi.HTTPException",
                "fastapi.exceptions.HTTPException",
            }:
                continue
            code = _keyword(call, "status_code") or (call.args[0] if call.args else None)
            if isinstance(code, ast.Constant) and code.value in (401, 403):
                kind = "http_401_raise" if code.value == 401 else "http_403_raise"
                out.append(AuthSignal(kind=kind, span=self.span(function.file, node)))
        return out

    def dependency(self, spec: Spec, seen: frozenset[str] = frozenset()) -> Dependency:
        node = spec.node
        expression = ast.unparse(node)
        span = self.span(spec.file, node)
        target: Value = None
        if isinstance(node, ast.Call) and self.name(node.func, spec.env) in _DEPENDS:
            argument = node.args[0] if node.args else _keyword(node, "dependency") or spec.implicit
            target = self.dereference(self.value(argument, spec.env))
        bound = target if isinstance(target, Bound) else None
        ref = bound.target if bound else target
        function = self.functions.get(ref.name) if isinstance(ref, Ref) else None
        children: list[Dependency] = []
        reason = "Unknown dependency expression or external callable"
        if function:
            if function.row.id in seen or len(seen) >= 32:
                reason = "Dependency cycle or depth limit; chain is incomplete"
                self.issues.append(f"{spec.file.path}:{node.lineno}: {reason}")
                function = None
            else:
                reason = (
                    "Static imported callable"
                    if not bound
                    else "Factory returns this nested callable; arguments retained"
                )
                children = [
                    self.dependency(child, seen | {function.row.id})
                    for child in self.signature(function)
                ]
        return Dependency(
            expression=expression,
            parameter=spec.parameter,
            target_symbol_id=function.row.id if function else None,
            factory_symbol_id=bound.factory_id if bound else None,
            factory_arguments=list(bound.arguments) if bound else [],
            status=LinkStatus.INFERRED if function else LinkStatus.UNRESOLVED,
            reason=reason,
            span=span,
            auth_signals=self.signals(function) if function else [],
            children=children,
        )

    def build(self) -> FastAPIMap:
        mounted: dict[str, list[tuple[Router, str | None, list[Spec]]]] = {}
        for mount in self.mounts:
            call = mount.call
            assert isinstance(call.func, ast.Attribute)  # noqa: S101 - internal AST invariant
            parent = self.dereference(self.value(call.func.value, mount.env))
            argument = call.args[0] if call.args else _keyword(call, "router")
            child = self.dereference(self.value(argument, mount.env))
            if isinstance(parent, Router) and isinstance(child, Router):
                mounted.setdefault(parent.fact.id, []).append(
                    (
                        child,
                        _literal(_keyword(call, "prefix")),
                        self.specs(mount.file, call, mount.env),
                    )
                )
            elif isinstance(parent, Router):
                self.issues.append(
                    f"{mount.file.path}:{call.lineno}: included router is unresolved"
                )
        declared: dict[str, list[Declaration]] = {}
        for declaration in self.declarations:
            func = declaration.decorator.func
            assert isinstance(func, ast.Attribute)  # noqa: S101
            router = self.dereference(self.value(func.value, declaration.env))
            if isinstance(router, Router) and func.attr in _METHODS | {"api_route"}:
                declared.setdefault(router.fact.id, []).append(declaration)
        routes: list[FastAPIRoute] = []
        visited: set[str] = set()

        def traverse(
            router: Router,
            prefix: str | None,
            inherited: list[Spec],
            chain: tuple[str, ...],
            attached: bool,
        ) -> None:
            if router.fact.id in chain or len(chain) >= 32:
                self.issues.append(f"{router.fact.span.path}: router cycle or depth limit")
                return
            visited.add(router.fact.id)
            chain = (*chain, router.fact.id)
            full_prefix = (
                prefix + router.fact.prefix
                if prefix is not None and router.fact.prefix is not None
                else None
            )
            dependencies = [*inherited, *router.specs]
            for declaration in declared.get(router.fact.id, []):
                call, function = declaration.decorator, declaration.function
                assert isinstance(call.func, ast.Attribute)  # noqa: S101
                route_path = _literal(call.args[0] if call.args else _keyword(call, "path"))
                route = (
                    full_prefix + route_path
                    if full_prefix is not None and route_path is not None
                    else None
                )
                methods: list[str | None] = [call.func.attr.upper()]
                if call.func.attr == "api_route":
                    value = _keyword(call, "methods")
                    methods = ["GET"] if value is None else [None]
                    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                        literals = [_literal(item) for item in value.elts]
                        methods = [m.upper() if m else None for m in literals]
                specs = [
                    *dependencies,
                    *self.specs(function.file, call, declaration.env),
                    *self.signature(function),
                ]
                for method in methods:
                    key = f"{function.row.id}:{chain}:{route}:{method}:{len(routes)}"
                    entry = EntryPoint(
                        id="entry:" + hashlib.sha256(key.encode()).hexdigest()[:24],
                        snapshot_id=self.snapshot.id,
                        kind=EntryPointKind.HTTP_ROUTE,
                        framework=Framework.FASTAPI,
                        method=method,
                        route=route,
                        handler_symbol_id=function.row.id,
                        span=self.index.to_contract(function.row, self.snapshot.id).span,
                    )
                    status = (
                        LinkStatus.INFERRED
                        if attached and route is not None and method
                        else LinkStatus.UNRESOLVED
                    )
                    routes.append(
                        FastAPIRoute(
                            entry=entry,
                            router_id=router.fact.id,
                            mount_status=status,
                            dependencies=[self.dependency(spec) for spec in specs],
                        )
                    )
            for child, extra, specs in mounted.get(router.fact.id, []):
                child_prefix = (
                    full_prefix + extra if full_prefix is not None and extra is not None else None
                )
                traverse(child, child_prefix, [*dependencies, *specs], chain, attached)

        for router in self.routers.values():
            if router.fact.kind == "app":
                traverse(router, "", [], (), True)
        for router in self.routers.values():
            if router.fact.id not in visited:
                self.issues.append(
                    f"{router.fact.span.path}:{router.fact.span.start_line}: "
                    "router has no known app mount"
                )
                traverse(router, "", [], (), False)
        return FastAPIMap(
            snapshot_id=self.snapshot.id,
            routes=routes,
            routers=[r.fact for r in self.routers.values()],
            issues=sorted(set(self.issues)),
        )


def extract_fastapi(snapshot: ProjectSnapshot, store: SnapshotStore, index: Index) -> FastAPIMap:
    return Adapter(snapshot, store, index).build()


def main(argv: list[str] | None = None) -> int:
    import argparse

    from backend.settings import Settings
    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(
        description="Extract FastAPI routes and dependencies from a snapshot"
    )
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    cache = Settings().cache_dir
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        result = extract_fastapi(snapshot, store, index)
        output = cache / "adapters" / f"{snapshot.id}.fastapi.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"{len(result.routes)} routes, {len(result.routers)} routers/apps; {output}")
        for route in result.routes:
            print(f"  {route.entry.method} {route.entry.route} [{route.mount_status}]")
        for issue in result.issues:
            print(f"limitation: {issue}")
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
