"""Join snapshot facts into the graph served by the workbench API (M2.8)."""

import hashlib
import sys
from collections import Counter
from pathlib import Path

from analysis.access import AccessMap, extract_accesses
from analysis.fastapi import Dependency, FastAPIMap, extract_fastapi
from analysis.index import Index, index_path
from analysis.nextjs import NextJSMap, extract_nextjs
from analysis.python_resolution import resolve_python
from analysis.resolution import CallGraph, LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.typescript_resolution import resolve_typescript
from backend.contracts.application_map import ApplicationMap, LinkKind, MapLink, UnknownTarget
from backend.contracts.code import (
    Guard,
    GuardKind,
    GuardMechanism,
    ProjectSnapshot,
    SourceSpan,
    SymbolKind,
)
from backend.map_store import MapStore
from backend.settings import Settings


def _id(kind: str, *parts: str) -> str:
    return kind + ":" + hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]


def assemble_map(
    snapshot: ProjectSnapshot,
    index: Index,
    fastapi: FastAPIMap,
    nextjs: NextJSMap,
    access: AccessMap,
    graphs: list[CallGraph],
) -> ApplicationMap:
    if index.meta("snapshot_id") != snapshot.id or any(
        f.snapshot_id != snapshot.id for f in [fastapi, nextjs, access, *graphs]
    ):
        raise ValueError("application map inputs must use the same snapshot")
    symbols = [index.to_contract(row, snapshot.id) for row in index.symbols()]
    symbol_ids = {s.id for s in symbols}
    entries = [r.entry for r in fastapi.routes] + [r.entry for r in nextjs.entries]
    guards: dict[str, Guard] = {}
    unknown: dict[str, UnknownTarget] = {}
    links: dict[str, MapLink] = {}
    issues = [
        *fastapi.issues,
        *nextjs.issues,
        *access.issues,
        *(issue for graph in graphs for issue in graph.issues),
    ]

    def link(
        source: str,
        target: str,
        kind: LinkKind,
        status: LinkStatus,
        span: SourceSpan,
        reason: str,
        *,
        optimistic: bool = False,
    ) -> None:
        key = _id(
            "link",
            source,
            target,
            kind,
            span.path,
            str(span.start_line),
            str(span.end_line),
            reason,
        )
        links[key] = MapLink(
            id=key,
            source=source,
            target=target,
            kind=kind,
            status=status,
            reason=reason,
            span=span,
            optimistic=optimistic,
        )

    def unknown_target(label: str, reason: str, span: SourceSpan) -> str:
        key = _id("unknown", label, span.path, str(span.start_line), reason)
        unknown[key] = UnknownTarget(id=key, label=label, reason=reason, span=span)
        return key

    for graph in graphs:
        for edge in graph.edges:
            target = edge.target_id or unknown_target(edge.callee, edge.reason, edge.span)
            link(edge.caller_id, target, edge.kind, edge.status, edge.span, edge.reason)

    def dependency(parent: str, dep: Dependency, route_guards: set[str]) -> None:
        target = dep.target_symbol_id or unknown_target(dep.expression, dep.reason, dep.span)
        link(parent, target, "dependency", dep.status, dep.span, dep.reason)
        for signal in dep.auth_signals:
            guard_id = _id("guard", signal.kind, signal.span.path, str(signal.span.start_line))
            guards[guard_id] = Guard(
                id=guard_id,
                snapshot_id=snapshot.id,
                kind=GuardKind.UNKNOWN,
                canonical=f"{signal.kind}: executable rejection syntax; protection not established",
                mechanism=GuardMechanism.DEPENDENCY,
                span=signal.span,
                via_symbol_id=dep.target_symbol_id,
            )
            route_guards.add(guard_id)
            link(
                target,
                guard_id,
                "guard_candidate",
                LinkStatus.INFERRED,
                signal.span,
                "Dependency contains HTTP rejection syntax; "
                "condition and dominance need investigation",
            )
        for child in dep.children:
            dependency(target, child, route_guards)

    for route in fastapi.routes:
        entry = route.entry
        link(
            entry.id,
            entry.handler_symbol_id,
            "handler",
            route.mount_status,
            entry.span,
            "Static FastAPI declaration and router mount",
        )
        route_guards: set[str] = set()
        for dep in route.dependencies:
            dependency(entry.id, dep, route_guards)
        for item in access.accesses:
            if item.site.entry_point_id == entry.id:
                for guard_id in sorted(route_guards):
                    link(
                        guard_id,
                        item.site.id,
                        "may_check",
                        LinkStatus.UNRESOLVED,
                        guards[guard_id].span,
                        "Candidate dependency check; "
                        "protected object, condition and dominance are unverified",
                    )
    proxies = {p.id: p for p in nextjs.proxies}
    for proxy in nextjs.proxies:
        guards[proxy.guard.id] = proxy.guard
    for route in nextjs.entries:
        entry = route.entry
        link(
            entry.id,
            entry.handler_symbol_id,
            "handler",
            route.status,
            entry.span,
            "Static Next.js convention; no layout authorization inherited",
        )
        for coverage in route.proxies:
            proxy = proxies[coverage.proxy_id]
            link(
                entry.id,
                proxy.guard.id,
                "proxy",
                coverage.status,
                proxy.guard.span,
                coverage.reason,
                optimistic=True,
            )
            for item in access.accesses:
                if item.site.entry_point_id == entry.id:
                    link(
                        proxy.guard.id,
                        item.site.id,
                        "may_check",
                        LinkStatus.UNRESOLVED,
                        proxy.guard.span,
                        "Optimistic routing layer; not an authorization boundary",
                        optimistic=True,
                    )
    for item in access.accesses:
        if item.owner_symbol_id not in symbol_ids:
            raise ValueError("access owner is not an indexed symbol")
        link(item.owner_symbol_id, item.site.id, "access", item.status, item.site.span, item.reason)
        # A direct entry-to-site path keeps the route context even when the loader is shared.
        link(
            item.site.entry_point_id,
            item.site.id,
            "access",
            item.status,
            item.site.span,
            "Possible input provenance along " + " -> ".join(item.via_symbol_ids),
        )
    for transfer in nextjs.client_props:
        candidates = [
            s
            for s in symbols
            if s.span.path == transfer.span.path
            and s.span.start_line <= transfer.span.start_line
            and s.span.end_line >= transfer.span.end_line
        ]
        if not candidates:
            # No link without a source node; the gap stays visible instead of stopping the map.
            issues.append(
                f"{transfer.span.path}:{transfer.span.start_line}: "
                "client props are rendered outside any indexed symbol"
            )
            continue
        functions = [s for s in candidates if s.kind in {SymbolKind.FUNCTION, SymbolKind.COMPONENT}]
        smallest = min(functions or candidates, key=lambda s: s.span.end_line - s.span.start_line)
        link(
            smallest.id,
            transfer.component_symbol_id,
            "client_props",
            transfer.status,
            transfer.span,
            "Props cross an explicit client boundary; field sensitivity needs investigation",
        )
    return ApplicationMap(
        snapshot_id=snapshot.id,
        entries=entries,
        symbols=symbols,
        guards=list(guards.values()),
        access_sites=[a.site for a in access.accesses],
        unknown_targets=list(unknown.values()),
        links=list(links.values()),
        issues=sorted(set(issues)),
        limitations=[
            "Static source map, not a runtime trace or a vulnerability verdict.",
            "Guard candidates are unconfirmed; may_check links do not establish authorization.",
            "Proxy and middleware coverage is optimistic, never a security boundary.",
            "Dynamic/external calls and uncertain input origins remain unresolved.",
            "Framework-generated routes, custom configuration and unsupported query forms "
            "may be absent.",
        ],
    )


def build_map(
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    index: Index,
    cache: Path,
    *,
    use_ty: bool = True,
) -> ApplicationMap:
    # Sequential helpers respect the machine's memory budget.
    python = resolve_python(snapshot, store, index, cache, use_ty=use_ty)
    typescript = resolve_typescript(snapshot, store, index, cache)
    fastapi = extract_fastapi(snapshot, store, index)
    nextjs = extract_nextjs(snapshot, store, index, cache)
    access = extract_accesses(
        snapshot,
        store,
        index,
        cache,
        fastapi=fastapi,
        nextjs=nextjs,
        python_graph=python,
        typescript_graph=typescript,
    )
    return assemble_map(snapshot, index, fastapi, nextjs, access, [python, typescript])


def main(argv: list[str] | None = None) -> int:
    import argparse

    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(description="Build and persist a static application map")
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--without-ty", action="store_true", help="use the labeled Python import fallback"
    )
    args = parser.parse_args(argv)
    cache = Settings().cache_dir
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        result = build_map(snapshot, store, index, cache, use_ty=not args.without_ty)
        database = MapStore(cache / "application_maps.sqlite")
        database.save(result)
        statuses = Counter(link.status for link in result.links)
        print(
            f"snapshot {snapshot.id}: {len(result.entries)} entries, "
            f"{len(result.guards)} guard candidates, {len(result.access_sites)} access sites, "
            f"{len(result.unknown_targets)} unknown targets; {database.path}"
        )
        print(
            f"{len(result.links)} links: "
            + ", ".join(f"{statuses[status]} {status}" for status in LinkStatus)
        )
        for issue in result.issues:
            print(f"limitation: {issue}")
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
