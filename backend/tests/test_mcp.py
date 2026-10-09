"""Actual SDK requests exercise saved-read boundaries without inference."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.server._otel import OpenTelemetryMiddleware
from mcp.types import CallToolResult

from backend import mcp as integration
from backend.contracts.investigation import ExhibitRole
from backend.reports import ReportBundle, render
from backend.settings import Settings
from backend.tests.test_saved_reports import RUN_ID
from backend.tests.test_saved_reports import saved as saved


def call(server: MCPServer, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async def request() -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(request())


def files(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_read_only_tools_keep_identity_coverage_and_cited_code(
    saved: tuple[Settings, ReportBundle, Path],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    settings, bundle, _ = saved
    before = files(settings.data_dir)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("MCP started analysis, inference, writes or browser dispatch")

    for target in (
        "backend.llama_server.LlamaServer.start",
        "backend.review.Review.__init__",
        "backend.run_store.RunStore.create",
        "backend.saved_reports.launch",
        "analysis.snapshot.SnapshotStore.save",
        "analysis.snapshot.BlobStore.put",
    ):
        monkeypatch.setattr(target, forbidden)
    server = integration.create_server(settings)
    assert not any(isinstance(m, OpenTelemetryMiddleware) for m in server.middleware)

    async def request() -> None:
        async with Client(server, mode=mode) as client:
            tools = (await client.list_tools()).tools
            assert {t.name for t in tools} == {
                "get_run",
                "list_findings",
                "get_finding",
                "get_evidence",
            }
            assert all(t.annotations and t.annotations.read_only_hint for t in tools)
            assert all(t.annotations and not t.annotations.open_world_hint for t in tools)
            run = await client.call_tool("get_run", {"run_id": RUN_ID})
            assert not run.is_error and run.structured_content is not None
            assert run.structured_content["coverage"] == bundle.run.coverage.model_dump(mode="json")
            assert run.structured_content["run_type"] == "saved"
            assert "Static support does not establish runtime reproduction" in json.dumps(
                run.structured_content
            )
            page = await client.call_tool("list_findings", {"run_id": RUN_ID, "limit": 1})
            assert not page.is_error and page.structured_content is not None
            assert page.structured_content["findings"][0]["id"] == bundle.findings[0].id
            arguments = {"run_id": RUN_ID, "finding_id": bundle.findings[0].id}
            finding = await client.call_tool("get_finding", arguments)
            assert not finding.is_error and finding.structured_content is not None
            assert finding.structured_content["finding"] == bundle.findings[0].model_dump(
                mode="json"
            )
            evidence = await client.call_tool(
                "get_evidence", {**arguments, "exhibit_tag": "E01", "lines": 2}
            )
            assert not evidence.is_error and evidence.structured_content is not None
            result = evidence.structured_content
            span = bundle.findings[0].exhibits[0].span
            assert result["returned_span"]["start_line"] == span.start_line
            assert result["returned_span"]["end_line"] == span.start_line + 1
            assert result["text_is_code_only_and_redacted"]
            assert result["line_numbers_refer_to_original_snapshot"]
            assert result["next_offset"] == 2

    asyncio.run(request())
    assert files(settings.data_dir) == before


@pytest.mark.parametrize(
    "arguments",
    [
        {"run_id": "../outside"},
        {"run_id": "file:///private"},
        {"run_id": "review-" + "a" * 33},
        {"run_id": "private-input" * 1000},
        {"run_id": "private-input" * 2000},
        {"run_id": RUN_ID, "limit": 51},
        {"run_id": RUN_ID, "limit": 0},
        {"run_id": RUN_ID, "offset": -1},
        {"run_id": RUN_ID, "offset": 1_000_001},
        {"run_id": RUN_ID, "limit": True},
    ],
)
def test_invalid_or_oversized_arguments_are_refused_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        integration, "load", lambda *args: pytest.fail("Invalid tool arguments reached storage")
    )
    server = integration.create_server(Settings(data_dir=tmp_path / "absent"))
    result = call(server, "list_findings", arguments)
    assert result.is_error
    assert "private-input" not in result.model_dump_json()
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("name", ["review", "resume", "execute", "delete", "list_runs"])
def test_no_execution_mutation_or_implicit_run_enumeration_tools(tmp_path: Path, name: str) -> None:
    server = integration.create_server(Settings(data_dir=tmp_path / "absent"))
    assert call(server, name, {}).is_error
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        {"finding_id": "finding:outside", "exhibit_tag": "E01"},
        {"finding_id": "finding:1", "exhibit_tag": "E99"},
        {"finding_id": "finding:1", "exhibit_tag": "../outside"},
        {"finding_id": "finding:1", "exhibit_tag": "E01", "offset": 100},
        {"finding_id": "finding:1", "exhibit_tag": "E01", "lines": 81},
    ],
)
def test_only_cited_evidence_and_bounded_line_ranges_are_read(
    saved: tuple[Settings, ReportBundle, Path], arguments: dict[str, Any]
) -> None:
    server = integration.create_server(saved[0])
    result = call(server, "get_evidence", {"run_id": RUN_ID, **arguments})
    assert result.is_error


def test_corrupt_or_modified_reports_do_not_leak_their_text(
    saved: tuple[Settings, ReportBundle, Path],
) -> None:
    settings, _, directory = saved
    (directory / "report.json").write_text("private-input invalid JSON")
    result = call(integration.create_server(settings), "get_run", {"run_id": RUN_ID})
    assert result.is_error and "private-input" not in result.model_dump_json()


def test_source_redaction_preserves_original_span_identity(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from analysis.snapshot import SnapshotStore

    settings, bundle, directory = saved
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '["order_id"]')
    store = SnapshotStore(settings.cache_dir / "snapshots")
    for name, kind in (("report.json", "json"), ("report.html", "html")):
        (directory / name).write_text(render(bundle, store, kind), encoding="utf-8", newline="\n")
    result = call(
        integration.create_server(settings),
        "get_evidence",
        {"run_id": RUN_ID, "finding_id": bundle.findings[0].id, "exhibit_tag": "E01"},
    )
    assert not result.is_error and result.structured_content is not None
    data = result.structured_content
    assert "order_id" not in data["text"] and "[REDACTED]" in data["text"]
    assert (
        data["returned_span"]["content_sha256"]
        == bundle.findings[0].exhibits[0].span.content_sha256
    )


def test_developer_notes_are_not_returned_as_security_evidence(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, bundle, _ = saved
    bundle.findings[0].exhibits[0] = (
        bundle.findings[0].exhibits[0].model_copy(update={"role": ExhibitRole.DEVELOPER_NOTE})
    )
    monkeypatch.setattr(integration, "load", lambda *args: (bundle, Path("unused")))
    result = call(
        integration.create_server(settings),
        "get_evidence",
        {"run_id": RUN_ID, "finding_id": bundle.findings[0].id, "exhibit_tag": "E01"},
    )
    assert result.is_error


def test_large_output_is_refused_instead_of_truncated(
    saved: tuple[Settings, ReportBundle, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(integration, "MAX_OUTPUT_BYTES", 20)
    result = call(integration.create_server(saved[0]), "get_run", {"run_id": RUN_ID})
    assert result.is_error and result.structured_content is None
