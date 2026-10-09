"""A cited project overview and cross-file review units; no inference (M2.9)."""

from collections import Counter, defaultdict, deque
from typing import Literal

from agent.validator import Validator
from analysis.access import AccessMap
from analysis.snapshot import SnapshotStore
from backend.capabilities import table
from backend.contracts.application_map import ApplicationMap, MapLink
from backend.contracts.capabilities import CapabilityTable
from backend.contracts.code import EntryPoint, ProjectSnapshot, SnapshotFile, Symbol, SymbolKind
from backend.contracts.common import Contract, LinkStatus


class ReviewUnit(Contract):
    entry: EntryPoint
    access_ids: list[str]
    node_ids: list[str]
    link_ids: list[str]
    peer_entry_ids: list[str]
    unresolved_link_ids: list[str]
    optimistic_link_ids: list[str]


class ProjectOverview(Contract):
    capabilities: CapabilityTable | None = None
    schema_version: Literal[1] = 1
    snapshot: ProjectSnapshot
    languages: dict[str, int]
    frameworks: dict[str, int]
    modules: list[Symbol]
    empty_modules: list[SnapshotFile]
    resources: dict[str, int]
    graph: ApplicationMap
    units: list[ReviewUnit]
    limitations: list[str]


def overview(
    snapshot: ProjectSnapshot, graph: ApplicationMap, access: AccessMap, store: SnapshotStore
) -> ProjectOverview:
    """Derive navigation from existing facts, preserving unknowns and shared helpers.

    A unit is possible source reachability, not runtime reachability or protection.
    Resource names group navigation only; they never establish policy or sensitivity.
    """
    if graph.snapshot_id != snapshot.id or access.snapshot_id != snapshot.id:
        raise ValueError("overview inputs must use the same snapshot")
    if store.load(snapshot.id) != snapshot:
        raise ValueError("overview snapshot metadata differs from its stored manifest")
    graph = ApplicationMap.model_validate(graph.model_dump())
    # The index represents an empty package initializer as a synthetic line-1
    # module. It has no citable code. Keep its file/hash as inventory instead.
    files = {file.path: file for file in snapshot.files}
    empty = [
        symbol
        for symbol in graph.symbols
        if symbol.kind is SymbolKind.MODULE and files[symbol.span.path].size == 0
    ]
    empty_ids = {symbol.id for symbol in empty}
    if any(link.source in empty_ids or link.target in empty_ids for link in graph.links):
        raise ValueError("empty module has linked synthetic citations; overview unavailable")
    graph = graph.model_copy(
        update={"symbols": [s for s in graph.symbols if s.id not in empty_ids]}
    )
    sites = {a.id: a for a in graph.access_sites}
    if (
        {path.site.id for path in access.accesses} != set(sites)
        or len(access.accesses) != len(sites)
        or any(sites.get(a.site.id) != a.site for a in access.accesses)
    ):
        raise ValueError("overview access paths must match the application map")
    validator = Validator(snapshot, store)
    nodes = [
        *graph.entries,
        *graph.symbols,
        *graph.guards,
        *graph.unknown_targets,
        *graph.access_sites,
    ]
    for item in [*nodes, *graph.links]:
        if validator.span(item.span):
            raise ValueError("overview contains an invalid source citation")
    symbol_ids = {s.id for s in graph.symbols}
    if any(s not in symbol_ids for path in access.accesses for s in path.via_symbol_ids):
        raise ValueError("overview path references an unknown symbol")
    outgoing: dict[str, list[MapLink]] = defaultdict(list)
    by_entry: dict[str, list[str]] = defaultdict(list)
    peers: dict[str, set[str]] = defaultdict(set)
    for link in graph.links:
        outgoing[link.source].append(link)
    for site in graph.access_sites:
        by_entry[site.entry_point_id].append(site.id)
        peers[site.resource].add(site.entry_point_id)
    units = []
    for entry in sorted(graph.entries, key=lambda e: (e.span.path, e.span.start_line, e.id)):
        access_ids = set(by_entry[entry.id])
        visited: set[str] = set()
        selected: dict[str, MapLink] = {}
        # Preserve the input-bound access path as well as forward call/dependency
        # links. Never inherit a different route's access through a shared helper.
        pending = deque([entry.id, entry.handler_symbol_id])
        pending.extend(
            s
            for path in access.accesses
            if path.site.entry_point_id == entry.id
            for s in path.via_symbol_ids
        )
        while pending:
            node = pending.popleft()
            if node in visited:
                continue
            visited.add(node)
            for link in outgoing[node]:
                if link.target in sites and link.target not in access_ids:
                    continue
                selected[link.id] = link
                pending.append(link.target)
        resources = {sites[s].resource for s in access_ids}
        units.append(
            ReviewUnit(
                entry=entry,
                access_ids=sorted(access_ids),
                node_ids=sorted(visited),
                link_ids=sorted(selected),
                peer_entry_ids=sorted(set().union(*(peers[r] for r in resources)) - {entry.id}),
                unresolved_link_ids=sorted(
                    link.id for link in selected.values() if link.status is LinkStatus.UNRESOLVED
                ),
                optimistic_link_ids=sorted(
                    link.id for link in selected.values() if link.optimistic
                ),
            )
        )
    limitations = [
        *graph.limitations,
        "Project overview only; no model judgments or security verdicts were run.",
        "Review units are possible static flows, not runtime traces; "
        "dependencies and guard candidates do not prove protection.",
        "Resource labels and peer links aid navigation, not business policy or data sensitivity.",
        "Language counts include snapshot source files; framework counts include "
        "discovered entries, not every installed dependency.",
        "No supported entry points were discovered; this is not a claim that the project is safe."
        if not graph.entries
        else "Included files without discovered entries may contain unsupported security flows; "
        "exclusions remain in the snapshot.",
    ]
    modules: list[Symbol] = [symbol for symbol in graph.symbols if symbol.kind is SymbolKind.MODULE]
    modules.sort(key=lambda symbol: symbol.span.path)
    return ProjectOverview(
        capabilities=table(snapshot, graph, store),
        snapshot=snapshot,
        languages=dict(
            sorted(Counter(f.language.value for f in snapshot.files if f.language).items())
        ),
        frameworks=dict(sorted(Counter(e.framework.value for e in graph.entries).items())),
        modules=modules,
        empty_modules=[files[symbol.span.path] for symbol in empty],
        resources=dict(sorted(Counter(s.resource for s in graph.access_sites).items())),
        graph=graph,
        units=units,
        limitations=list(dict.fromkeys(limitations)),
    )


def summary(result: ProjectOverview, *, max_units: int = 12) -> str:
    """Bound terminal navigation; full scope and citations live in the JSON record."""
    if max_units < 0:
        raise ValueError("max_units must be nonnegative")
    graph = result.graph
    unresolved = sum(link.status is LinkStatus.UNRESOLVED for link in graph.links)
    rows = [
        f"Project: {result.snapshot.root_name} | snapshot {result.snapshot.id[:12]}",
        f"Included files: {len(result.snapshot.files)}; excluded: {len(result.snapshot.excluded)}",
        "Source files: "
        + (", ".join(f"{k} {v}" for k, v in result.languages.items()) or "none supported"),
        "Discovered entries: "
        + (", ".join(f"{k} {v}" for k, v in result.frameworks.items()) or "none supported"),
        f"Modules with source: {len(result.modules)}; empty modules: {len(result.empty_modules)}; "
        f"access paths: {len(graph.access_sites)}; "
        f"unresolved links: {unresolved}",
        f"Guard candidates: {len(graph.guards)} (unverified); "
        f"extraction issues: {len(graph.issues)}",
        f"Showing {min(max_units, len(result.units))} of {len(result.units)} entry flows:",
    ]
    for unit in result.units[:max_units]:
        entry = unit.entry
        rows.append(
            f"  {entry.method or entry.kind.value} {entry.route or entry.id} | "
            f"{entry.span.path}:{entry.span.start_line} | "
            f"{len(unit.access_ids)} access paths, {len(unit.unresolved_link_ids)} unresolved links"
        )
    rows += [
        "Overview only; no security verdict. Full citations, unknowns and exclusions "
        "are saved in overview.json."
    ]
    if not result.units:
        rows.append(
            "No supported entries were discovered. Do not interpret this as a safe project."
        )
    if result.capabilities:
        rows.extend(
            [
                "Capability: Parsed/Indexed are source observations; Investigated is unverified "
                "for the current engine, and general Runtime-testable is unavailable.",
                result.capabilities.quality_note,
                result.capabilities.runtime_note,
            ]
        )
    return "\n".join(rows)
