"""Offline integration of matched execution; no scanner/model/target is started."""

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, Never, cast

import httpx
import pytest

from backend.preflight import PreflightResult
from backend.redaction import Redactor
from backend.settings import Settings
from eval.baselines import development as base
from eval.baselines import execution as run
from eval.candidate import write_new
from eval.mutation import development as corpus
from eval.mutation.corpus import build


@pytest.fixture(scope="module")
def prepared() -> base.Preparation:
    template = next(t for t in corpus.development_templates() if t.name == "order_receipt")
    cases = [
        corpus.Case(
            id=v.id,
            template=v.template,
            operator=v.operator,
            family=v.family,
            label=v.label,
            cwe=v.cwe,
            entry=v.handler,
            sources={"api/input.py": v.source},
            control_id=f"{v.template}/original",
        )
        for v in build([template])
    ]
    return base.prepare(
        cases, hypothesis="Offline executor boundary fixtures", max_attempts=10, max_seconds=60
    )


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "machine_state", lambda: {"scope": "software_fixture"})
    monkeypatch.setattr(run, "binary", lambda *_: Path("verified-fixture.exe"))


class FakeServer:
    startup_timeout = 120.0
    load_seconds = 0.0
    sampler = None

    def __init__(
        self,
        *,
        ok: bool = True,
        raw: str = '{"findings":[]}',
        status: int = 200,
        start_error: bool = False,
        stop_error: bool = False,
    ) -> None:
        self.ok, self.raw, self.status = ok, raw, status
        self.start_error, self.stop_error = start_error, stop_error
        self.starts = self.stops = self.preflights = 0
        self.chats: list[dict[str, Any]] = []
        self.redactor = Redactor(secrets=())
        self.client = httpx.Client(
            base_url="http://127.0.0.1", transport=httpx.MockTransport(self.reply)
        )

    def reply(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1] * 20})
        self.chats.append(json.loads(request.content))
        return httpx.Response(
            self.status,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": self.raw}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    def preflight(self) -> PreflightResult:
        self.preflights += 1
        return PreflightResult(self.ok, "fixture", 8192, 0, None, "fixture gate")

    def start(self) -> None:
        self.starts += 1
        if self.start_error:
            raise RuntimeError("fixture start failed")

    def stop(self) -> None:
        self.stops += 1
        self.client.close()
        if self.stop_error:
            raise RuntimeError("fixture stop failed")


def execute(
    prepared: base.Preparation,
    tmp_path: Path,
    method: base.Method = "one_shot",
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> run.Execution:
    return run.execute(
        prepared,
        method,
        tmp_path / "execution.json",
        Settings(data_dir=tmp_path / "data"),
        evidence_kind="software_fixture",
        clock=clock,
    )


def test_actual_adapter_fake_transport_uses_exact_public_packets_and_closes(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeServer()
    monkeypatch.setattr(run.profiles, "create", lambda *_: fake)
    result = execute(prepared, tmp_path)
    assert result.state == "completed" and (fake.starts, fake.stops, fake.preflights) == (1, 1, 1)
    assert len(fake.chats) == len(prepared.cases)
    for body, packet in zip(fake.chats, base.check(prepared), strict=True):
        assert body["messages"][1]["content"] == base.request(packet)["user"]
        assert body["cache_prompt"] is False and body["max_tokens"] == 600
        assert body["temperature"] == 0 and body["seed"] == 42
        assert body["response_format"]["type"] == "json_schema"
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert sum(r.prompt_tokens for r in result.records) == 100
    assert run.Execution.model_validate_json((tmp_path / "execution.json").read_bytes()) == result
    assert run.accounting(prepared, result)["evidence_kind"] == "software_fixture"


@pytest.mark.parametrize("option", ["preflight", "start", "stop", "invalid", "unavailable"])
def test_model_failures_keep_every_case_and_stop_owned_server(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
) -> None:
    fake = FakeServer(
        ok=option != "preflight",
        start_error=option == "start",
        stop_error=option == "stop",
        raw="{" if option == "invalid" else '{"findings":[]}',
        status=503 if option == "unavailable" else 200,
    )
    monkeypatch.setattr(run.profiles, "create", lambda *_: fake)
    result = execute(prepared, tmp_path)
    assert result.state == "failed" and fake.stops == 1 and len(result.records) == 5
    if option == "preflight":
        assert fake.starts == 0 and not fake.chats
        assert all(r.state == "unrun" for r in result.records)
    if option == "invalid":
        assert all(r.state == "failed" for r in result.records)
        assert set(result.raw_transport.values()) == {"{"}
        assert sum(r.prompt_tokens for r in result.records) == 100
    if option == "unavailable":
        assert len(fake.chats) == 5  # One request per case, no hidden transient retry.
    assert run.accounting(prepared, result)["state"] == "failed"


def test_attempt_budget_retains_unrun_cases_without_launching_more(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeServer()
    monkeypatch.setattr(run.profiles, "create", lambda *_: fake)
    result = execute(prepared.model_copy(update={"max_attempts": 1}), tmp_path)
    assert len(fake.chats) == 1 and result.state == "failed"
    assert [r.state for r in result.records] == ["completed"] + ["unrun"] * 4


def test_elapsed_budget_blocks_launch_and_retains_failed_batch(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([0, 61, 62])
    monkeypatch.setattr(run.profiles, "create", lambda *_: pytest.fail("must not create server"))
    result = execute(prepared, tmp_path, clock=lambda: next(ticks))
    assert result.state == "failed" and all(r.state == "unrun" for r in result.records)


def test_initial_identity_or_output_refusal_starts_nothing(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run.profiles, "create", lambda *_: pytest.fail("must not create server"))
    output = tmp_path / "execution.json"
    output.write_text("owned by user")
    with pytest.raises(FileExistsError):
        execute(prepared, tmp_path)
    assert output.read_text() == "owned by user"
    with pytest.raises(ValueError, match="drift"):
        execute(prepared.model_copy(update={"configuration": {}}), tmp_path)


def native(packet: base.Packet, path: str) -> dict[str, Any]:
    return {
        "results": [
            {
                "check_id": "plumb.authz.load-by-id-without-owner-comparison",
                "path": path,
                "start": {"line": packet.focus.start_line},
                "end": {"line": packet.focus.end_line},
                "extra": {"metadata": {"family": "authorization"}},
            }
        ],
        "errors": [],
        "paths": {"skipped": []},
        "version": "fixture",
    }


@pytest.mark.parametrize(
    "path", ["../outside.py", "api/input.py:stream", "elsewhere.py", "README.md"]
)
def test_scanner_normalization_refuses_unowned_citations(
    prepared: base.Preparation,
    tmp_path: Path,
    path: str,
) -> None:
    packet = base.check(prepared)[0]
    with pytest.raises(ValueError):
        run.normalize_scanner(json.dumps(native(packet, path)), tmp_path, packet)
    with pytest.raises(ValueError):
        run.normalize_scanner(
            json.dumps(native(packet, str(tmp_path.parent / "outside.py"))), tmp_path, packet
        )


def test_scanner_normalization_binds_rule_family_and_actual_file(
    prepared: base.Preparation,
    tmp_path: Path,
) -> None:
    packet = base.check(prepared)[0]
    data = native(packet, str(tmp_path / packet.focus.path))
    result = json.loads(run.normalize_scanner(json.dumps(data), tmp_path, packet))
    assert result["results"][0]["path"] == packet.focus.path
    for change in ("rule", "family", "errors", "skipped", "lines"):
        value = json.loads(json.dumps(data))
        if change == "rule":
            value["results"][0]["check_id"] = "unknown-rule"
        if change == "family":
            value["results"][0]["extra"]["metadata"]["family"] = "injection"
        if change == "errors":
            value["errors"] = [{"message": "partial"}]
        if change == "skipped":
            value["paths"]["skipped"] = ["input.py"]
        if change == "lines":
            value["results"][0]["start"]["line"] = True
        with pytest.raises(ValueError):
            run.normalize_scanner(json.dumps(value), tmp_path, packet)


@pytest.mark.parametrize("failure", [None, "timeout", "exit", "malformed"])
def test_fake_pinned_scanner_materializes_only_frozen_data_and_cleans(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    roots = []
    monkeypatch.setenv("SEMGREP_APP_TOKEN", "fixture-only")

    def process(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        root = Path(argv[-1])
        roots.append(root)
        assert argv[0] == "verified-fixture.exe" and "--no-rewrite-rule-ids" in argv
        assert argv[argv.index("--jobs") + 1] == "1"
        timeout = cast(float, kwargs["timeout"])
        assert 0 < timeout <= 60 and kwargs["stdin"] == subprocess.DEVNULL
        assert "SEMGREP_APP_TOKEN" not in cast(dict[str, str], kwargs["env"])
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) == [
            "api/input.py"
        ]
        assert (root / "api/input.py").read_bytes() in [
            c.sources["api/input.py"].encode() for c in prepared.cases
        ]
        if failure == "timeout":
            cast(BinaryIO, kwargs["stdout"]).write(b'{"partial":')
            raise subprocess.TimeoutExpired(argv, timeout)
        cast(BinaryIO, kwargs["stdout"]).write(
            b"{" if failure == "malformed" else b'{"results":[],"errors":[]}'
        )
        return subprocess.CompletedProcess(argv, 2 if failure == "exit" else 0)

    monkeypatch.setattr(run.subprocess, "run", process)
    result = execute(prepared, tmp_path, "opengrep")
    assert result.state == ("completed" if failure is None else "failed")
    assert len(roots) == 5 and all(not p.parent.exists() for p in roots)
    if failure in {"exit", "malformed", "timeout"}:
        assert len(result.raw_transport) == 5
    if failure == "timeout":
        assert set(result.raw_transport.values()) == {'{"partial":'}
        assert all(r.error == "Scanner timed out" for r in result.records)
    assert not any(p.name.startswith(".baseline-") for p in tmp_path.iterdir())


def test_interrupt_saves_partial_denominators_and_teardown(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*_: object) -> Never:
        raise KeyboardInterrupt

    monkeypatch.setattr(run, "scan", interrupt)
    result = execute(prepared, tmp_path, "opengrep")
    assert result.state == "failed" and "KeyboardInterrupt" in str(result.error)
    assert len(result.records) == 5 and all(r.state == "unrun" for r in result.records)


def test_accounting_cli_has_no_launch_and_refuses_execution_drift(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeServer()
    monkeypatch.setattr(run.profiles, "create", lambda *_: fake)
    result = execute(prepared, tmp_path)
    write_new(tmp_path / "preparation.json", prepared)
    monkeypatch.setattr(run, "execute", lambda *_: pytest.fail("must not launch"))
    assert (
        run.main(
            [
                "account",
                str(tmp_path / "preparation.json"),
                str(tmp_path / "execution.json"),
                "--output",
                str(tmp_path / "account.json"),
            ]
        )
        == 0
    )
    assert (
        json.loads((tmp_path / "account.json").read_bytes())["release_acceptance"] == "unassessed"
    )
    with pytest.raises(ValueError, match="drift"):
        run.accounting(prepared, result.model_copy(update={"execution_pins": {}}))
    with pytest.raises(SystemExit):
        run.main(
            ["run", str(tmp_path / "preparation.json"), "--method", "full_plumb", "--output", "x"]
        )


def test_persistence_failure_stops_model_and_preserves_initial_denominators(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeServer()
    monkeypatch.setattr(run.profiles, "create", lambda *_: fake)

    def refuse(*_: object) -> None:
        raise OSError("fixture denied write")

    monkeypatch.setattr(run, "checkpoint", refuse)
    with pytest.raises(OSError):
        execute(prepared, tmp_path)
    assert fake.stops == 1
    saved = run.Execution.model_validate_json((tmp_path / "execution.json").read_bytes())
    assert len(saved.records) == 5 and all(r.state == "unrun" for r in saved.records)


def test_aggregate_output_overrun_is_failed_and_no_further_cases_start(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeServer()
    monkeypatch.setattr(run.profiles, "create", lambda *_: fake)
    monkeypatch.setattr(base, "MAX_BYTES", 200_001)
    result = execute(prepared, tmp_path)
    assert result.state == "failed" and "Aggregate" in str(result.error)
    assert len(fake.chats) < 5 and fake.stops == 1
    assert result.records[-1].state == "unrun"


def test_invalid_model_citations_retain_raw_and_fail_before_publishing(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeServer(
        raw=json.dumps(
            {
                "findings": [
                    {
                        "path": "../outside.py",
                        "family": "authorization",
                        "start_line": 1,
                        "end_line": 1,
                        "explanation": "fixture",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(run.profiles, "create", lambda *_: fake)
    result = execute(prepared, tmp_path)
    assert result.state == "failed" and all(r.state == "failed" for r in result.records)
    assert len(result.raw_transport) == 5
    assert run.accounting(prepared, result)["state"] == "failed"


def test_repeated_preparation_preserves_separate_owned_model_logs(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names: list[str] = []

    def create(_: Settings, name: str, _profile: object) -> FakeServer:
        names.append(name)
        return FakeServer(ok=False)

    monkeypatch.setattr(run.profiles, "create", create)
    for name in ("first", "second"):
        folder = tmp_path / name
        folder.mkdir()
        result = execute(prepared, folder)
        assert result.state == "failed" and result.observations["log_id"] == names[-1]
    assert len(set(names)) == 2
