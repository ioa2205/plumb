"""Bounded TypeScript 6 compiler-API helper over in-memory snapshot sources (M2.4)."""

import json
import subprocess
import sys
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

import psutil

from analysis.index import Index, index_path
from analysis.platform_calls import platform_identity
from analysis.resolution import CallEdge, CallGraph, graph_path
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from analysis.ty_client import isolated_environment
from backend.contracts.code import ProjectSnapshot, SourceSpan
from backend.contracts.common import Language
from backend.settings import Settings

TS_VERSION = "6.0.3"
HELPER = Path(__file__).parent / "typescript" / "resolver.mts"
LANGUAGES = {Language.TYPESCRIPT, Language.TSX, Language.JAVASCRIPT}


class TypeScriptUnavailable(RuntimeError):
    """Resolution did not complete. Never report an empty graph as complete coverage."""


@dataclass(frozen=True)
class NodeLimits:
    timeout_seconds: float = 60
    heap_mib: int = 192
    rss_bytes: int = 384 * 1024 * 1024
    input_bytes: int = 32 * 1024 * 1024
    output_bytes: int = 16 * 1024 * 1024


def run_helper(
    payload: dict[str, Any],
    cache: Path,
    node: Path,
    limits: NodeLimits,
) -> dict[str, Any]:
    if not node.is_absolute() or not node.is_file():
        raise TypeScriptUnavailable("Set PLUMB_NODE_BINARY to an absolute Node.js 24+ executable")
    if not (HELPER.parent / "node_modules" / "typescript" / "lib" / "typescript.js").is_file():
        raise TypeScriptUnavailable(
            "Run pnpm --dir analysis/typescript install --frozen-lockfile --ignore-scripts"
        )
    raw = json.dumps(payload, ensure_ascii=True).encode()
    if len(raw) > limits.input_bytes:
        raise TypeScriptUnavailable("TypeScript input budget exceeded")
    cache.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="ts-", dir=cache) as directory:
        root = Path(directory).resolve()
        stdout_path, stderr_path = root / "stdout", root / "stderr"
        stop = threading.Event()
        failures: list[str] = []
        peak = 0
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(  # noqa: S603 - trusted executable and fixed helper
                [
                    str(node),
                    f"--max-old-space-size={limits.heap_mib}",
                    "--permission",
                    f"--allow-fs-read={HELPER.parent.resolve()}",
                    str(HELPER.resolve()),
                ],
                cwd=root,
                env=isolated_environment(root),
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            def monitor() -> None:
                nonlocal peak
                try:
                    child = psutil.Process(process.pid)
                    while not stop.wait(0.05):
                        peak = max(peak, child.memory_info().rss)
                        if peak > limits.rss_bytes:
                            failures.append("TypeScript RSS budget exceeded")
                        if (
                            stdout_path.stat().st_size > limits.output_bytes
                            or stderr_path.stat().st_size > 65536
                        ):
                            failures.append("TypeScript output budget exceeded")
                        if failures:
                            process.kill()
                            return
                except psutil.NoSuchProcess:
                    return
                except (OSError, psutil.AccessDenied):
                    failures.append("TypeScript helper could not be monitored")
                    process.kill()

            watcher = threading.Thread(target=monitor, daemon=True)
            watcher.start()
            try:
                process.communicate(raw, timeout=limits.timeout_seconds)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.communicate()
                raise TypeScriptUnavailable("TypeScript time budget exceeded") from error
            finally:
                stop.set()
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                watcher.join(timeout=1)
        if failures:
            raise TypeScriptUnavailable(failures[0])
        if stdout_path.stat().st_size > limits.output_bytes:
            raise TypeScriptUnavailable("TypeScript output budget exceeded")
        if process.returncode:
            with stderr_path.open("rb") as log:
                message = log.read(2000).decode("utf-8", errors="replace")
            raise TypeScriptUnavailable(
                f"TypeScript helper failed ({process.returncode}): {message}"
            )
        try:
            output = json.loads(stdout_path.read_bytes())
        except (ValueError, UnicodeError) as error:
            raise TypeScriptUnavailable("TypeScript helper returned invalid JSON") from error
        if not isinstance(output, dict) or output.get("version") != TS_VERSION:
            raise TypeScriptUnavailable("TypeScript helper returned an unexpected version")
        output["peak_rss_bytes"] = max(peak, output.get("peak_rss_bytes", 0))
        return output


def snapshot_payload(
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    index: Index,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Shared source-only input for call resolution and framework extraction."""
    if index.meta("snapshot_id") != snapshot.id:
        raise ValueError("resolver and index must use the same snapshot")
    sources = {
        f.path: store.read(snapshot, f.path) for f in snapshot.files if f.language in LANGUAGES
    }
    rows = [row for row in index.symbols() if row.path in sources]
    payload = {
        "files": [
            {"path": path, "text": source.decode("utf-8")} for path, source in sources.items()
        ],
        "configs": [
            {"path": file.path, "text": store.read(snapshot, file.path).decode("utf-8")}
            for file in snapshot.files
            if PurePosixPath(file.path).name in {"tsconfig.json", "jsconfig.json"}
        ],
        "symbols": [
            {
                "id": row.id,
                "path": row.path,
                "name": row.name,
                "kind": row.kind.value,
                "start_line": row.start_line,
                "end_line": row.end_line,
                "local_name": row.local_name,
            }
            for row in rows
        ],
    }
    return sources, payload


def resolve_typescript(
    snapshot: ProjectSnapshot,
    store: SnapshotStore,
    index: Index,
    cache: Path,
    *,
    node: Path | None = None,
    limits: NodeLimits | None = None,
) -> CallGraph:
    sources, payload = snapshot_payload(snapshot, store, index)
    if not sources:
        return CallGraph(
            snapshot_id=snapshot.id, language="typescript", resolver_version=TS_VERSION, edges=[]
        )
    output = run_helper(
        payload, cache / "typescript", node or Settings().node_binary, limits or NodeLimits()
    )
    if output.get("platform_sha256") != platform_identity():
        raise TypeScriptUnavailable("TypeScript returned unpinned platform declarations")
    ids = {row.id for row in index.symbols() if row.path in sources}
    edges: list[CallEdge] = []
    for raw in output["edges"]:
        if (
            raw["path"] not in sources
            or raw["caller_id"] not in ids
            or (raw["target_id"] is not None and raw["target_id"] not in ids)
        ):
            raise TypeScriptUnavailable(
                "TypeScript returned a location outside the indexed snapshot"
            )
        path, start, end = raw["path"], raw["start_line"], raw["end_line"]
        if not 1 <= start <= end <= len(sources[path].decode("utf-8").splitlines()):
            raise TypeScriptUnavailable("TypeScript returned an invalid source span")
        edges.append(
            CallEdge(
                caller_id=raw["caller_id"],
                target_id=raw["target_id"],
                callee=raw["callee"],
                span=SourceSpan(
                    snapshot_id=snapshot.id,
                    path=path,
                    start_line=start,
                    end_line=end,
                    content_sha256=span_sha256(sources[path], start, end),
                ),
                reference_line=raw["reference_line"],
                column=raw["column"],
                kind=raw["kind"],
                status=raw["status"],
                via="typescript",
                reason=raw["reason"],
                platform_operation=raw.get("platform_operation"),
            )
        )
    return CallGraph(
        snapshot_id=snapshot.id,
        language="typescript",
        resolver_version=f"typescript-2; TS {TS_VERSION}",
        platform_sha256=output["platform_sha256"],
        edges=edges,
        issues=output["issues"],
        peak_rss_bytes=output["peak_rss_bytes"],
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from eval.splits import sealed_paths

    parser = argparse.ArgumentParser(
        description="Resolve TypeScript snapshot calls without running target code"
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--caller")
    args = parser.parse_args(argv)
    cache = Settings().cache_dir
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(args.root, store, sealed=sealed_paths())
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        graph = resolve_typescript(snapshot, store, index, cache)
        graph.save(graph_path(cache, snapshot.id, "typescript"))
        print(
            f"snapshot {snapshot.id}, edges: {dict(Counter(e.status.value for e in graph.edges))}"
        )
        print(f"Node peak RSS: {graph.peak_rss_bytes} bytes")
        for issue in graph.issues:
            print(f"limitation: {issue}")
        if args.caller:
            row = index.symbol(args.caller)
            names = {s.id: s.qualified_name for s in index.symbols()}
            for edge in graph.calls(row.id) if row else []:
                print(
                    f"  {edge.span.path}:{edge.span.start_line} {edge.callee} -> "
                    f"{names.get(edge.target_id, '?')} [{edge.status}, {edge.kind}]"
                )
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
