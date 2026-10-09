"""Entry-to-query access paths with conservative input provenance (M2.7)."""

import hashlib
import re
import sys
from pathlib import Path

from pydantic import Field

from analysis.access_facts import AccessFact, FunctionFacts, sql_access
from analysis.access_python import python_access_facts
from analysis.fastapi import Dependency, FastAPIMap, extract_fastapi
from analysis.index import Index, index_path
from analysis.nextjs import NextJSMap, extract_nextjs
from analysis.python_resolution import resolve_python
from analysis.resolution import CallGraph, LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from analysis.typescript_resolution import (
    NodeLimits,
    resolve_typescript,
    run_helper,
    snapshot_payload,
)
from backend.contracts.code import (
    AccessSite,
    DataLayer,
    EntryPoint,
    EntryPointKind,
    ProjectSnapshot,
    SourceSpan,
)
from backend.contracts.common import Contract, Framework, InputOrigin
from backend.settings import Settings

REQUEST_ORIGINS = {InputOrigin.PATH, InputOrigin.QUERY, InputOrigin.BODY, InputOrigin.HEADER}
_PRIORITY = [
    InputOrigin.PATH,
    InputOrigin.QUERY,
    InputOrigin.BODY,
    InputOrigin.HEADER,
    InputOrigin.UNKNOWN,
    InputOrigin.SESSION,
    InputOrigin.CONSTANT,
]


class AccessPath(Contract):
    site: AccessSite
    owner_symbol_id: str
    key_expression: str
    possible_origins: list[InputOrigin]
    via_symbol_ids: list[str]
    status: LinkStatus
    reason: str


class AccessMap(Contract):
    snapshot_id: str
    accesses: list[AccessPath]
    issues: list[str] = Field(default_factory=list)


def extract_accesses(
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    index: Index,
    cache: Path,
    *,
    fastapi: FastAPIMap | None = None,
    nextjs: NextJSMap | None = None,
    python_graph: CallGraph | None = None,
    typescript_graph: CallGraph | None = None,
) -> AccessMap:
    if index.meta("snapshot_id") != snapshot.id:
        raise ValueError("access extraction and index must use the same snapshot")
    fastapi = fastapi if fastapi is not None else extract_fastapi(snapshot, store, index)
    nextjs = nextjs if nextjs is not None else extract_nextjs(snapshot, store, index, cache)
    python_graph = (
        python_graph
        if python_graph is not None
        else resolve_python(snapshot, store, index, cache, use_ty=False)
    )
    typescript_graph = (
        typescript_graph
        if typescript_graph is not None
        else resolve_typescript(snapshot, store, index, cache)
    )
    if any(m.snapshot_id != snapshot.id for m in (fastapi, nextjs, python_graph, typescript_graph)):
        raise ValueError("all access inputs must refer to the same snapshot")
    summaries, issues = python_access_facts(snapshot, store, index)
    sources, payload = snapshot_payload(snapshot, store, index)
    if sources:
        payload["access"] = True
        output = run_helper(payload, cache / "typescript", Settings().node_binary, NodeLimits())
        ts_facts = [FunctionFacts.model_validate(f) for f in output["functions"]]
        for fact in ts_facts:
            query_facts = list(fact.accesses)
            for sql in fact.sql_calls:
                parsed = sql_access(sql.sql, include_unkeyed=True)
                if parsed is None:
                    if "__dynamic__" in sql.sql:
                        issues.append(
                            f"{fact.symbol_id}:{sql.start_line}: dynamic SQL access is unresolved"
                        )
                    continue
                resource, operation, binds = parsed
                inputs: set[str] = set()
                for bind in binds:
                    inputs.update(
                        sql.bindings[bind]
                        if isinstance(bind, int) and 0 <= bind < len(sql.bindings)
                        else ["?"]
                    )
                query_facts.append(
                    AccessFact(
                        resource=resource,
                        operation=operation,
                        data_layer=DataLayer.RAW_SQL,
                        key_inputs=sorted(inputs),
                        key_expression=sql.sql,
                        start_line=sql.start_line,
                        end_line=sql.end_line,
                        reason=(
                            "SQL literal/key binding through a driver or source-inspected "
                            "wrapper; possible input influence"
                        ),
                    )
                )
            summaries.append(fact.model_copy(update={"accesses": query_facts}))
        issues.extend(output["issues"])
    functions = {f.symbol_id: f for f in summaries}
    rows = {r.id: r for r in index.symbols()}
    if any(key not in rows for key in functions):
        raise ValueError("access helper returned an unknown symbol")
    graph = [*python_graph.edges, *typescript_graph.edges]
    edges = {(e.caller_id, e.reference_line, e.column): e for e in graph if e.kind == "call"}
    entries = [r.entry for r in fastapi.routes] + [r.entry for r in nextjs.entries]
    accesses: dict[tuple[str, str, int, str], AccessPath] = {}

    def root_bindings(entry: EntryPoint, function: FunctionFacts) -> dict[str, set[InputOrigin]]:
        bindings: dict[str, set[InputOrigin]] = {}
        for param in function.parameters:
            key = f"p{param.index}" + (f".{param.field}" if param.field else "")
            origin = InputOrigin.UNKNOWN
            if entry.framework is Framework.FASTAPI:
                if re.search(r"\{" + re.escape(param.name) + r"(?::[^}]+)?\}", entry.route or ""):
                    origin = InputOrigin.PATH
                elif param.request_hint:
                    origin = InputOrigin(param.request_hint)
                # Other FastAPI bindings need type/default/dependency interpretation;
                # never infer a session or request source from the parameter's name.
            elif entry.kind is EntryPointKind.SERVER_ACTION:
                origin = InputOrigin.BODY
            elif entry.kind is EntryPointKind.PAGE:
                if param.field == "params":
                    origin = InputOrigin.PATH
                elif param.field == "searchParams":
                    origin = InputOrigin.QUERY
                bindings[f"p{param.index}.params"] = {InputOrigin.PATH}
                bindings[f"p{param.index}.searchParams"] = {InputOrigin.QUERY}
            elif entry.kind is EntryPointKind.ROUTE_HANDLER:
                if param.index == 1:
                    origin = InputOrigin.PATH
                else:
                    bindings[f"p{param.index}.nextUrl.searchParams"] = {InputOrigin.QUERY}
                    bindings[f"p{param.index}.url"] = {InputOrigin.QUERY}
                    bindings[f"p{param.index}.headers"] = {InputOrigin.HEADER}
            bindings[key] = {origin}
        return bindings

    def evaluate(tokens: list[str], bindings: dict[str, set[InputOrigin]]) -> set[InputOrigin]:
        origins: set[InputOrigin] = set()
        for token in tokens:
            keys = [k for k in bindings if token == k or token.startswith(k + ".")]
            origins.update(bindings[max(keys, key=len)] if keys else {InputOrigin.UNKNOWN})
        return origins or {InputOrigin.CONSTANT}

    def walk(
        entry: EntryPoint,
        symbol_id: str,
        bindings: dict[str, set[InputOrigin]],
        chain: list[str],
        seen: set[tuple[str, str]],
        depth: int = 0,
    ) -> None:
        signature = (symbol_id, repr(sorted((k, sorted(v)) for k, v in bindings.items())))
        if signature in seen:
            return
        if depth >= 16 or len(seen) >= 2048:
            issues.append(f"{entry.id}: access traversal budget reached; coverage incomplete")
            return
        seen.add(signature)
        function = functions.get(symbol_id)
        if function is None:
            return
        row = rows[symbol_id]
        chain = [*chain, symbol_id]
        for candidate in function.accesses:
            origins = evaluate(candidate.key_inputs, bindings)
            if origins == {InputOrigin.CONSTANT} and entry.framework is not Framework.NEXTJS:
                continue
            source = store.read(snapshot, row.path)
            if (
                not 1
                <= candidate.start_line
                <= candidate.end_line
                <= len(source.decode("utf-8").splitlines())
            ):
                raise ValueError("access helper returned an invalid span")
            span = SourceSpan(
                snapshot_id=snapshot.id,
                path=row.path,
                start_line=candidate.start_line,
                end_line=candidate.end_line,
                content_sha256=span_sha256(source, candidate.start_line, candidate.end_line),
            )
            key = (entry.id, symbol_id, candidate.start_line, candidate.resource)
            previous = accesses.get(key)
            if previous:
                origins.update(previous.possible_origins)
            known = bool(origins & REQUEST_ORIGINS) or origins == {InputOrigin.CONSTANT}
            accesses[key] = AccessPath(
                site=AccessSite(
                    id="access:"
                    + hashlib.sha256("\0".join(map(str, key)).encode()).hexdigest()[:24],
                    snapshot_id=snapshot.id,
                    entry_point_id=entry.id,
                    resource=candidate.resource,
                    operation=candidate.operation,
                    key_origin=next(o for o in _PRIORITY if o in origins),
                    data_layer=candidate.data_layer,
                    span=span,
                ),
                owner_symbol_id=symbol_id,
                key_expression=candidate.key_expression,
                possible_origins=sorted(origins),
                via_symbol_ids=chain,
                status=LinkStatus.INFERRED if known else LinkStatus.UNRESOLVED,
                reason=candidate.reason
                + ("; request-derived key" if known else "; key input origin unresolved"),
            )
        for call in function.calls:
            edge = edges.get((symbol_id, call.line, call.column))
            target = functions.get(edge.target_id) if edge and edge.target_id else None
            if target is None:
                continue
            target_bindings: dict[str, set[InputOrigin]] = {}
            for param in target.parameters:
                values = call.keywords.get(param.name)
                if values is None:
                    values = (
                        call.arguments[param.index] if param.index < len(call.arguments) else ["?"]
                    )
                token = f"p{param.index}" + (f".{param.field}" if param.field else "")
                target_bindings[token] = evaluate(values, bindings)
            walk(entry, target.symbol_id, target_bindings, chain, seen, depth + 1)

    def dependency(
        entry: EntryPoint, dep: Dependency, chain: list[str], seen: set[tuple[str, str]]
    ) -> None:
        if dep.target_symbol_id and dep.target_symbol_id in functions:
            target = functions[dep.target_symbol_id]
            walk(entry, target.symbol_id, root_bindings(entry, target), chain, seen)
            chain = [*chain, target.symbol_id]
        for child in dep.children:
            dependency(entry, child, chain, seen)

    for entry in entries:
        target = functions.get(entry.handler_symbol_id)
        if target is None:
            issues.append(f"{entry.id}: entry handler access summary unavailable")
            continue
        seen: set[tuple[str, str]] = set()
        walk(entry, target.symbol_id, root_bindings(entry, target), [], seen)
        route = next((r for r in fastapi.routes if r.entry.id == entry.id), None)
        if route:
            for dep in route.dependencies:
                dependency(entry, dep, [target.symbol_id], seen)
    ordered = sorted(accesses.values(), key=lambda item: item.site.id)
    return AccessMap(
        snapshot_id=snapshot.id,
        accesses=ordered,
        issues=sorted(set(issues)),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(description="Find static entry-to-data access paths")
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    cache = Settings().cache_dir
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        result = extract_accesses(snapshot, store, index, cache)
        output = cache / "adapters" / f"{snapshot.id}.access.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"{len(result.accesses)} access paths; {output}")
        for item in result.accesses:
            print(
                f"  {item.site.resource}: {item.site.span.path}:{item.site.span.start_line} "
                f"[{item.site.key_origin}, {item.status}]"
            )
        for issue in result.issues:
            print(f"limitation: {issue}")
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
