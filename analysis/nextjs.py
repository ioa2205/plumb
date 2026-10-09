"""Next.js App Router conventions from snapshot syntax, without loading the app."""

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from analysis.index import Index, SymbolRow, index_path
from analysis.resolution import LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from analysis.typescript_resolution import NodeLimits, run_helper, snapshot_payload
from backend.contracts.code import (
    EntryPoint,
    EntryPointKind,
    Guard,
    GuardKind,
    GuardMechanism,
    ProjectSnapshot,
    SourceSpan,
    SymbolKind,
)
from backend.contracts.common import Contract, Framework, RelPath
from backend.settings import Settings

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_FUNCTIONS = {SymbolKind.FUNCTION, SymbolKind.COMPONENT}


class ExportFact(Contract):
    name: str
    target_id: str | None


class ImportFact(Contract):
    module: str
    path: str | None
    type_only: bool


class FlowLocation(Contract):
    path: RelPath
    start_line: int
    end_line: int


class RenderFact(Contract):
    targets: list[str]
    tag: str
    props: dict[str, str]
    start_line: int
    end_line: int
    boundary_evidence: list[FlowLocation] = Field(default_factory=list)
    boundary_unknowns: list[str] = Field(default_factory=list)


class FlowOrigin(FlowLocation):
    symbol_id: str
    resource: str | None = None
    query_resource: str | None = None


class FieldFact(Contract):
    origin: FlowOrigin
    field: str
    output: str
    evidence: list[FlowLocation]


class SerializationFact(FlowLocation):
    owner_symbol_id: str
    kind: Literal["props", "return"]
    targets: list[str]
    fields: list[FieldFact]
    unknowns: list[str]
    boundary_evidence: list[FlowLocation] = Field(default_factory=list)


class SerializedField(Contract):
    source_owner_symbol_id: str
    source: SourceSpan
    field: str
    output: str
    evidence: list[SourceSpan]
    source_resource: str | None = None
    query_resource: str | None = None


class Serialization(Contract):
    owner_symbol_id: str
    kind: Literal["props", "return"]
    targets: list[str]
    span: SourceSpan
    fields: list[SerializedField]
    unknowns: list[str]
    boundary_evidence: list[SourceSpan] = Field(default_factory=list)


class ModuleFact(Contract):
    path: RelPath
    exports: list[ExportFact]
    imports: list[ImportFact]
    matcher: list[str] | None
    matcher_reason: str
    renders: list[RenderFact]
    issues: list[str]
    serializations: list[SerializationFact] = Field(default_factory=list)


class Component(Contract):
    symbol_id: str
    boundary: Literal["client", "server", "shared"]
    reason: str
    span: SourceSpan


class ClientProps(Contract):
    component_symbol_id: str
    props: dict[str, str]  # code expressions, not evaluated data or a safety verdict
    span: SourceSpan
    status: LinkStatus = LinkStatus.RESOLVED
    boundary_evidence: list[SourceSpan] = Field(default_factory=list)


class DataModule(Contract):
    path: RelPath
    export_symbol_ids: list[str]
    span: SourceSpan  # actual server-only import; filename is not evidence
    status: LinkStatus = LinkStatus.INFERRED
    reason: str = "server-only module; exported routines are DAL candidates, not confirmed guards"


class Proxy(Contract):
    id: str
    project: str
    symbol_id: str | None
    convention: Literal["proxy", "middleware"]
    matcher: list[str] | None
    reason: str
    guard: Guard
    optimistic: Literal[True] = True


class ProxyCoverage(Contract):
    proxy_id: str
    status: LinkStatus
    reason: str
    optimistic: Literal[True] = True


class NextEntry(Contract):
    entry: EntryPoint
    project: str
    status: LinkStatus
    proxies: list[ProxyCoverage]


class NextJSMap(Contract):
    snapshot_id: str
    entries: list[NextEntry]
    components: list[Component]
    client_props: list[ClientProps]
    data_modules: list[DataModule]
    proxies: list[Proxy]
    issues: list[str]
    serializations: list[Serialization] = Field(default_factory=list)


def _id(*parts: str) -> str:
    return "next:" + hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]


def _under(path: str, root: str) -> bool:
    return not root or path.startswith(root + "/")


def _join(root: str, path: str) -> str:
    return f"{root}/{path}" if root else path


def _route(path: str, app: str) -> str | None:
    parts = path[len(app) + 1 :].split("/")[:-1]
    if any(p.startswith("_") for p in parts):
        return None
    if any(p.startswith("(.)") or p.startswith("(..)") or p.startswith("(...)") for p in parts):
        return None  # intercepting routes need navigation context
    return "/" + "/".join(
        p.replace("%5F", "_").replace("%5f", "_")
        for p in parts
        if not p.startswith("@") and not (p.startswith("(") and p.endswith(")"))
    )


def matcher_covers(pattern: str, route: str | None) -> bool | None:
    """Only literal segments and named path parameters; never compile target regex."""
    if pattern in {"/:path*", "/:path(.*)"}:
        return True if route is not None else None
    if not pattern.startswith("/") or len(pattern) > 2048:
        return None
    pieces = pattern.strip("/").split("/") if pattern != "/" else []
    if any(not re.fullmatch(r"[A-Za-z0-9_.~-]+|:[A-Za-z][A-Za-z0-9_]*[?*+]?", p) for p in pieces):
        return None
    if route is None or "[" in route:
        return None
    actual = route.strip("/").split("/") if route != "/" else []
    i = 0
    for n, piece in enumerate(pieces):
        if piece.startswith(":"):
            suffix = piece[-1]
            if suffix in "*+?":
                if n != len(pieces) - 1:
                    return None
                remaining = len(actual) - i
                return remaining >= (1 if suffix == "+" else 0) and (
                    suffix != "?" or remaining <= 1
                )
            if i == len(actual):
                return False
        elif i == len(actual) or actual[i] != piece:
            return False
        i += 1
    return i == len(actual)


def extract_nextjs(
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    index: Index,
    cache: Path,
    *,
    node: Path | None = None,
    limits: NodeLimits | None = None,
) -> NextJSMap:
    sources, payload = snapshot_payload(snapshot, store, index)
    issues: list[str] = []
    # Package manifests are data only. No next.config, package script or import is run.
    projects: list[str] = []
    for file in snapshot.files:
        if PurePosixPath(file.path).name != "package.json":
            continue
        try:
            package = json.loads(store.read(snapshot, file.path))
            if isinstance(package, dict) and any(
                isinstance(package.get(key), dict) and "next" in package[key]
                for key in ("dependencies", "devDependencies")
            ):
                projects.append(file.path.removesuffix("package.json").rstrip("/"))
        except (ValueError, UnicodeError):
            issues.append(f"{file.path}: invalid package manifest")
    empty = NextJSMap(
        snapshot_id=snapshot.id,
        entries=[],
        components=[],
        client_props=[],
        data_modules=[],
        proxies=[],
        issues=issues,
    )
    if not projects or not sources:
        return empty
    payload["framework"] = True
    output = run_helper(
        payload, cache / "typescript", node or Settings().node_binary, limits or NodeLimits()
    )
    modules = {m.path: m for m in map(ModuleFact.model_validate, output["modules"])}
    if set(modules) != set(sources):
        raise ValueError("framework helper must return exactly the snapshot source modules")
    rows = {row.id: row for row in index.symbols() if row.path in sources}
    for module in modules.values():
        ids = [e.target_id for e in module.exports if e.target_id]
        ids.extend(t for r in module.renders for t in r.targets)
        if any(i not in rows for i in ids) or any(
            i.path is not None and i.path not in sources for i in module.imports
        ):
            raise ValueError("framework helper returned an unknown snapshot location")
    issues.extend(output["issues"])
    projects.sort(key=len, reverse=True)

    def project_for(path: str) -> str | None:
        return next((root for root in projects if _under(path, root)), None)

    def span(path: str, start: int, end: int) -> SourceSpan:
        if path not in sources or not 1 <= start <= end <= len(
            sources[path].decode("utf-8").splitlines()
        ):
            raise ValueError("invalid framework source span")
        return SourceSpan(
            snapshot_id=snapshot.id,
            path=path,
            start_line=start,
            end_line=end,
            content_sha256=span_sha256(sources[path], start, end),
        )

    def row_span(row: SymbolRow) -> SourceSpan:
        return span(row.path, row.start_line, row.end_line)

    def module_span(path: str) -> SourceSpan:
        return row_span(
            next(r for r in rows.values() if r.path == path and r.kind is SymbolKind.MODULE)
        )

    entries: list[NextEntry] = []
    page_ids: set[str] = set()
    proxies: list[Proxy] = []
    data_modules: list[DataModule] = []
    directives = {path: index.file_directive(path) for path in sources}
    server_roots: set[str] = set()

    def add(
        path: str,
        root: str,
        target: str | None,
        kind: EntryPointKind,
        route: str | None,
        method: str | None,
        name: str,
    ) -> None:
        if target is None:
            issues.append(f"{path}: {name} entry point has no unique indexed handler")
            return
        row = rows[target]
        location = row_span(row) if row.path == path else module_span(path)
        entries.append(
            NextEntry(
                entry=EntryPoint(
                    id=_id(path, kind.value, name, target),
                    snapshot_id=snapshot.id,
                    kind=kind,
                    framework=Framework.NEXTJS,
                    method=method,
                    route=route,
                    handler_symbol_id=target,
                    span=location,
                ),
                project=root,
                status=LinkStatus.INFERRED,
                proxies=[],
            )
        )
        if kind is EntryPointKind.PAGE:
            page_ids.add(target)
        if directives[path] != "use client":
            server_roots.add(path)

    for path, module in modules.items():
        root = project_for(path)
        if root is None:
            continue
        issues.extend(f"{path}: {issue}" for issue in module.issues)
        if "/pages/" in "/" + path:
            issues.append(f"{path}: Pages Router is outside this App Router adapter")
        app = _join(root, "app")
        if not any(p.startswith(app + "/") for p in sources):
            app = _join(root, "src/app")
        stem = PurePosixPath(path).stem
        exports = {e.name: e.target_id for e in module.exports}
        if path.startswith(app + "/") and stem in {"page", "route"}:
            route = _route(path, app)
            if route is None:
                if not any(p.startswith("_") for p in path[len(app) + 1 :].split("/")):
                    issues.append(f"{path}: intercepting route needs navigation context")
            elif stem == "page":
                add(
                    path, root, exports.get("default"), EntryPointKind.PAGE, route, "GET", "default"
                )
            else:
                for name in sorted(_METHODS & exports.keys()):
                    add(path, root, exports[name], EntryPointKind.ROUTE_HANDLER, route, name, name)
        if path.startswith(app + "/") and stem == "layout" and directives[path] != "use client":
            server_roots.add(path)
        # Every action is a separate public POST; no layout/proxy authorization is inherited.
        action_ids = {r.id for r in rows.values() if r.path == path and r.directive == "use server"}
        if directives[path] == "use server":
            action_ids.update(target for target in exports.values() if target is not None)
            for name, target in exports.items():
                if target is None and any(
                    r.path == path and r.name == name and r.kind is not SymbolKind.TYPE
                    for r in rows.values()
                ):
                    issues.append(f"{path}: non-function or unresolved Server Action export {name}")
        for target in sorted(action_ids):
            row = rows[target]
            if row.kind not in _FUNCTIONS:
                continue
            if not row.is_async:
                issues.append(f"{path}: Server Action {row.name} is not explicitly async")
            if directives[path] == "use client":
                issues.append(f"{path}: inline Server Action inside a client module")
            add(path, root, target, EntryPointKind.SERVER_ACTION, None, "POST", row.local_name)
        server_only = [
            i for i in index.imports(path) if i.module == "server-only" and i.kind == "side_effect"
        ]
        if server_only:
            data_modules.append(
                DataModule(
                    path=path,
                    export_symbol_ids=sorted({e.target_id for e in module.exports if e.target_id}),
                    span=span(path, server_only[0].line, server_only[0].line),
                )
            )
        if stem in {"proxy", "middleware"} and str(PurePosixPath(path).parent) in {
            root or ".",
            _join(root, "src"),
        }:
            target = exports.get(stem) or exports.get("default")
            if not target:
                issues.append(f"{path}: proxy handler unresolved")
            guard = Guard(
                id=_id(path, "proxy-guard"),
                snapshot_id=snapshot.id,
                kind=GuardKind.UNKNOWN,
                canonical="Optimistic routing check; authorization not established",
                mechanism=GuardMechanism.PROXY_MATCHER,
                span=row_span(rows[target]) if target else module_span(path),
                via_symbol_id=target,
            )
            proxies.append(
                Proxy(
                    id=_id(path, "proxy"),
                    project=root,
                    symbol_id=target,
                    convention="proxy" if stem == "proxy" else "middleware",
                    matcher=module.matcher,
                    reason=module.matcher_reason,
                    guard=guard,
                )
            )
            server_roots.add(path)
            if module.matcher is None:
                issues.append(f"{path}: {module.matcher_reason}")

    # Execution context follows static runtime imports. Type imports and Server Action
    # imports do not bring server implementation into a client bundle.
    def closure(seeds: set[str], client: bool) -> set[str]:
        seen: set[str] = set()
        pending = list(seeds)
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            if (client and directives[path] == "use server") or (
                not client and directives[path] == "use client"
            ):
                continue
            seen.add(path)
            pending.extend(
                i.path for i in modules[path].imports if not i.type_only and i.path is not None
            )
        return seen

    clients = closure(
        {p for p in sources if project_for(p) is not None and directives[p] == "use client"}, True
    )
    servers = closure(server_roots, False)
    for module in data_modules:
        if module.path in clients:
            issues.append(f"{module.path}: server-only module is reachable from a client import")
    components = [
        Component(
            symbol_id=r.id,
            boundary="shared"
            if r.path in clients and r.path in servers
            else "client"
            if r.path in clients
            else "server",
            reason="Static runtime import context; reachability is not proven",
            span=row_span(r),
        )
        for r in rows.values()
        if project_for(r.path) is not None and (r.kind is SymbolKind.COMPONENT or r.id in page_ids)
    ]
    component_ids = {c.symbol_id for c in components if directives[c.span.path] == "use client"}
    props: list[ClientProps] = []
    serializations: list[Serialization] = []
    for path in servers:
        for render in modules[path].renders:
            if (
                len(render.targets) == 1
                and render.targets[0] in component_ids
                and not render.boundary_unknowns
                and render.boundary_evidence
            ):
                props.append(
                    ClientProps(
                        component_symbol_id=render.targets[0],
                        props=render.props,
                        span=span(path, render.start_line, render.end_line),
                        boundary_evidence=[
                            span(s.path, s.start_line, s.end_line) for s in render.boundary_evidence
                        ],
                    )
                )
    for path, module in modules.items():
        for crossing in module.serializations:
            if (
                crossing.path != path
                or crossing.owner_symbol_id not in rows
                or any(t not in rows for t in crossing.targets)
            ):
                raise ValueError("serialization helper returned an unknown source identity")
            owner = rows[crossing.owner_symbol_id]
            if (
                owner.path != path
                or not owner.start_line
                <= crossing.start_line
                <= crossing.end_line
                <= owner.end_line
            ):
                raise ValueError("serialization crossing is outside its callable")
            if crossing.kind == "props" and (
                path not in servers
                or len(crossing.targets) != 1
                or crossing.targets[0] not in component_ids
            ):
                continue
            fields = []
            for field in crossing.fields:
                source = field.origin
                row = rows.get(source.symbol_id)
                if (
                    row is None
                    or row.path != source.path
                    or not row.start_line <= source.start_line <= source.end_line <= row.end_line
                ):
                    raise ValueError("serialization source is outside its indexed callable")
                fields.append(
                    SerializedField(
                        source_owner_symbol_id=source.symbol_id,
                        source=span(source.path, source.start_line, source.end_line),
                        field=field.field,
                        output=field.output,
                        source_resource=source.resource,
                        query_resource=source.query_resource,
                        evidence=list(
                            {
                                s.model_dump_json(): s
                                for s in [
                                    span(s.path, s.start_line, s.end_line) for s in field.evidence
                                ]
                            }.values()
                        ),
                    )
                )
            serializations.append(
                Serialization(
                    owner_symbol_id=owner.id,
                    kind=crossing.kind,
                    targets=crossing.targets,
                    span=span(path, crossing.start_line, crossing.end_line),
                    fields=fields,
                    unknowns=crossing.unknowns
                    + (
                        ["Client boundary source binding is unavailable"]
                        if crossing.kind == "props" and not crossing.boundary_evidence
                        else []
                    ),
                    boundary_evidence=[
                        span(s.path, s.start_line, s.end_line) for s in crossing.boundary_evidence
                    ],
                )
            )
    covered: list[NextEntry] = []
    for entry in entries:
        coverage: list[ProxyCoverage] = []
        for proxy in proxies:
            if proxy.project != entry.project:
                continue
            matches = (
                [matcher_covers(p, entry.entry.route) for p in proxy.matcher]
                if proxy.matcher is not None
                else [None]
            )
            if proxy.symbol_id is None:
                matches = [None]
            if True in matches or None in matches:
                coverage.append(
                    ProxyCoverage(
                        proxy_id=proxy.id,
                        status=LinkStatus.INFERRED if True in matches else LinkStatus.UNRESOLVED,
                        reason="Literal route matcher; optimistic only"
                        if True in matches
                        else "Matcher or entry URL unresolved; no authorization inherited",
                    )
                )
        covered.append(entry.model_copy(update={"proxies": coverage}))
    return NextJSMap(
        snapshot_id=snapshot.id,
        entries=covered,
        components=components,
        client_props=props,
        data_modules=data_modules,
        proxies=proxies,
        serializations=serializations,
        issues=sorted(set(issues)),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(
        description="Extract Next.js entries and boundaries from a snapshot"
    )
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    cache = Settings().cache_dir
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        result = extract_nextjs(snapshot, store, index, cache)
        output = cache / "adapters" / f"{snapshot.id}.nextjs.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(
            f"{len(result.entries)} entries, {len(result.components)} components, "
            f"{len(result.proxies)} optimistic proxies; {output}"
        )
        for item in result.entries:
            print(
                f"  {item.entry.kind}: {item.entry.method} "
                f"{item.entry.route or item.entry.handler_symbol_id}"
            )
        for issue in result.issues:
            print(f"limitation: {issue}")
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
