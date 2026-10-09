"""Python call graph: pinned ty find-references, then static import fallback (M2.3)."""

import ast
import os
import sys
from collections import Counter, defaultdict
from importlib.metadata import PackageNotFoundError
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from analysis.index import Index, SymbolRow, index_path
from analysis.python_syntax import (
    CallSite,
    ImportResolver,
    PythonFile,
    collect,
)
from analysis.resolution import CallEdge, CallGraph, LinkStatus, graph_path
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from analysis.ty_client import TY_VERSION, TyLimits, TyUnavailable, snapshot_server
from backend.contracts.code import ProjectSnapshot, SourceSpan
from backend.contracts.common import Language

RESOLVER_VERSION = "python-1"


def source_roots(files: dict[str, PythonFile]) -> list[str]:
    roots: set[str] = set()
    for file in files.values():
        parts = PurePosixPath(file.path).parts
        if PurePosixPath(file.path).stem == "__init__":
            parts = parts[:-1]
        count = len(file.module.qualified_name.split("."))
        roots.add(PurePosixPath(*parts[:-count]).as_posix())
    return sorted(roots)


def _uri_key(uri: str) -> str | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
        return None
    path = unquote(parsed.path)
    return path.casefold() if os.name == "nt" else path


def _location_key(
    location: dict[str, Any],
    allowed: dict[str | None, str],
) -> tuple[str, int, int] | None:
    uri = location.get("uri", location.get("targetUri"))
    span = location.get("range", location.get("targetSelectionRange", {}))
    if not isinstance(uri, str) or not isinstance(span, dict):
        raise TyUnavailable("ty returned a malformed source location")
    start = span.get("start", {})
    if not isinstance(start, dict):
        raise TyUnavailable("ty returned a malformed source position")
    line, column = start.get("line"), start.get("character")
    if type(line) is not int or type(column) is not int or line < 0 or column < 0:
        raise TyUnavailable("ty returned an invalid source position")
    try:
        path = allowed.get(_uri_key(uri))
    except ValueError as error:
        raise TyUnavailable("ty returned a malformed URI") from error
    return (path, line, column) if path else None


def ty_references(
    files: dict[str, PythonFile],
    sources: dict[str, bytes],
    cache: Path,
    limits: TyLimits | None,
) -> tuple[dict[tuple[str, int, int], set[str]], int]:
    refs: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    with snapshot_server(sources, source_roots(files), cache, limits) as client:
        # Accept references only to the exact staged source URI allowlist. Never
        # read a path returned by LSP, including external/stdlib/stub locations.
        allowed = {_uri_key((client.root / p).as_uri()): p for p in files}
        declarations = {
            (file.path, definition.line, definition.column): definition.symbol.id
            for file in files.values()
            for definition in file.definitions
        }
        for file in files.values():
            for definition in file.definitions:
                for reference in client.references(file.path, definition.line, definition.column):
                    key = _location_key(reference, allowed)
                    if key:
                        refs[key].add(definition.symbol.id)
        # ty 0.0.84 find-references misses some re-export aliases; definition
        # lookup follows them. Only accept exact indexed declaration positions.
        for file in files.values():
            for call in file.calls:
                key = (file.path, call.line, call.column)
                if key in refs or not isinstance(call.node.func, (ast.Name, ast.Attribute)):
                    continue
                locations = client.request(
                    "textDocument/definition",
                    {
                        "textDocument": {"uri": (client.root / file.path).as_uri()},
                        "position": {"line": call.line, "character": call.column},
                    },
                )
                if locations is None:
                    continue
                if isinstance(locations, dict):
                    locations = [locations]
                if not isinstance(locations, list):
                    raise TyUnavailable("ty returned malformed definitions")
                targets: set[str] = set()
                for location in locations:
                    if not isinstance(location, dict):
                        raise TyUnavailable("ty returned a malformed definition")
                    position = _location_key(location, allowed)
                    target = declarations.get(position) if position else None
                    if not target:
                        targets.clear()
                        break
                    targets.add(target)
                if targets:
                    refs[key] = targets
        peak = client.peak_rss_bytes
    return refs, peak


def _edge(
    snapshot: ProjectSnapshot,
    file: PythonFile,
    call: CallSite,
    target: SymbolRow | None,
    status: LinkStatus,
    via: str,
    reason: str,
) -> CallEdge:
    node = call.node.func
    end_line = node.end_lineno or node.lineno
    return CallEdge(
        caller_id=call.scope.owner.id,
        target_id=target.id if target else None,
        callee=call.callee,
        span=SourceSpan(
            snapshot_id=snapshot.id,
            path=file.path,
            start_line=node.lineno,
            end_line=end_line,
            content_sha256=span_sha256(file.source, node.lineno, end_line),
        ),
        column=call.column,
        reference_line=call.line + 1,
        status=status,
        via=via,
        reason=reason,
    )


def resolve_python(
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    index: Index,
    cache: Path,
    *,
    use_ty: bool = True,
    limits: TyLimits | None = None,
) -> CallGraph:
    if index.meta("snapshot_id") != snapshot.id:
        raise ValueError("resolver and index must use the same snapshot")
    sources = {
        f.path: store.read(snapshot, f.path)
        for f in snapshot.files
        if f.language is Language.PYTHON
    }
    files: dict[str, PythonFile] = {}
    issues: list[str] = []
    for path, source in sources.items():
        try:
            files[path] = collect(path, source, index)
        except (SyntaxError, UnicodeError, ValueError) as error:
            issues.append(f"{path}: Python syntax unavailable ({type(error).__name__})")
    fallback = ImportResolver(files, index)
    symbols = {s.id: s for s in index.symbols()}
    refs: dict[tuple[str, int, int], set[str]] = {}
    peak = 0
    if use_ty and files:
        try:
            # Invalid encodings cannot be sent to the LSP; keep them in issues.
            valid_sources = {p: f.source for p, f in files.items()}
            refs, peak = ty_references(files, valid_sources, cache / "ty", limits)
        except (TyUnavailable, OSError, PackageNotFoundError) as error:
            # Partial reference sets may conceal ambiguous targets. Discard them.
            issues.append(f"ty unavailable; import fallback only: {error}")
    elif not use_ty:
        issues.append("ty disabled; import fallback only")
    ambiguous_paths = {
        f.path for group in fallback.modules.values() if len(group) > 1 for f in group
    }
    edges: list[CallEdge] = []
    for file in files.values():
        for call in file.calls:
            direct = isinstance(call.node.func, (ast.Name, ast.Attribute))
            targets = refs.get((file.path, call.line, call.column), set()) if direct else set()
            target = symbols[next(iter(targets))] if len(targets) == 1 else None
            if len(targets) > 1 or (target and target.path in ambiguous_paths):
                edges.append(
                    _edge(
                        snapshot,
                        file,
                        call,
                        None,
                        LinkStatus.UNRESOLVED,
                        "ty",
                        "Multiple possible definitions or ambiguous module roots",
                    )
                )
            elif target:
                edges.append(
                    _edge(
                        snapshot,
                        file,
                        call,
                        target,
                        LinkStatus.RESOLVED,
                        "ty",
                        "Unique snapshot definition from ty references/definition",
                    )
                )
            else:
                target = fallback.resolve(call)
                status = LinkStatus.INFERRED if target else LinkStatus.UNRESOLVED
                reason = (
                    "Static lexical/import binding; not confirmed by ty"
                    if target
                    else "External, dynamic, shadowed, or unknown callable"
                )
                edges.append(_edge(snapshot, file, call, target, status, "imports", reason))
    return CallGraph(
        snapshot_id=snapshot.id,
        language="python",
        resolver_version=f"{RESOLVER_VERSION}; ty {TY_VERSION}",
        edges=edges,
        issues=issues,
        peak_rss_bytes=peak,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from backend.settings import Settings
    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(description="Resolve Python calls without running target code")
    parser.add_argument("root", type=Path)
    parser.add_argument("--no-ty", action="store_true", help="use the conservative import fallback")
    parser.add_argument("--caller", help="show calls from this qualified symbol")
    args = parser.parse_args(argv)
    cache = Settings().cache_dir
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        graph = resolve_python(snapshot, store, index, cache, use_ty=not args.no_ty)
        path = graph_path(cache, snapshot.id, "python")
        graph.save(path)
        print(f"snapshot {snapshot.id}, calls: {dict(Counter(e.status for e in graph.edges))}")
        print(f"ty sampled peak RSS: {graph.peak_rss_bytes} bytes; graph: {path}")
        for issue in graph.issues:
            print(f"limitation: {issue}")
        if args.caller:
            caller = index.symbol(args.caller)
            symbols = {row.id: row for row in index.symbols()}
            for edge in graph.calls(caller.id) if caller else []:
                target = symbols[edge.target_id].qualified_name if edge.target_id else "?"
                print(
                    f"  {edge.span.path}:{edge.span.start_line} {edge.callee} -> "
                    f"{target} [{edge.status}, {edge.via}]"
                )
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
