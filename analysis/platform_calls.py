"""Exact trusted platform provenance, separate from resolved target helpers or guards."""

import hashlib
import re
from pathlib import Path

from analysis.resolution import CallEdge, CallGraph
from analysis.snapshot import SnapshotStore
from analysis.syntax import span_sha256
from backend.contracts.code import ProjectSnapshot

PIN = Path(__file__).parent / "typescript" / "platform-pin.json"


def platform_identity() -> str:
    return hashlib.sha256(PIN.read_bytes()).hexdigest()


def non_authorizing(
    edge: CallEdge, graph: CallGraph, snapshot: ProjectSnapshot, store: SnapshotStore
) -> bool:
    """A fresh compiler-bound platform operation, still cited to the exact frozen call.

    The graph never treats this operation as a source-defined callable or a guard.
    Legacy/unattested graphs and corrupt source/positions cannot waive uncertainty.
    """
    if (
        graph.platform_sha256 != platform_identity()
        or graph.resolver_version != "typescript-2; TS 6.0.3"
        or graph.snapshot_id != snapshot.id
        or edge.span.snapshot_id != snapshot.id
        or edge not in graph.edges
        or edge.platform_operation is None
        or edge.via != "typescript"
        or edge.target_id is not None
        or edge.kind != "call"
    ):
        return False
    try:
        source = store.read(snapshot, edge.span.path)
        lines = source.decode("utf-8").splitlines()
        if not 1 <= edge.span.start_line <= edge.reference_line <= edge.span.end_line <= len(lines):
            return False
        if (
            span_sha256(source, edge.span.start_line, edge.span.end_line)
            != edge.span.content_sha256
        ):
            return False
        token = "Number" if edge.platform_operation == "number_conversion" else "get"
        if (edge.platform_operation == "number_conversion" and edge.callee != "Number") or (
            edge.platform_operation == "form_data_read"
            and re.fullmatch(r"[A-Za-z_$][\w$]*\.get", edge.callee) is None
        ):
            return False
        # Compiler columns are UTF-16 positions, not Python character offsets.
        line = lines[edge.reference_line - 1].encode("utf-16-le")
        return (
            re.match(rf"{token}(?![\w$])", line[edge.column * 2 :].decode("utf-16-le")) is not None
        )
    except (OSError, ValueError, UnicodeError):
        return False
