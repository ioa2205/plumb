"""Exercise serialization boundaries with synthetic credentials, never model weights."""

import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from agent.evidence import Cut, EvidencePacket, visible
from agent.llm import (
    ModelAdapter,
    ModelError,
    ModelRequest,
    RequestRejected,
    ask_json,
)
from agent.questions import guard_summary
from agent.tests.fake_llama import FakeLlama, Reply, answer, error
from agent.tests.test_llm import preflight, request, spend
from agent.validator import Rule, Validator
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from backend.app import create_app
from backend.contracts.code import Guard, SourceSpan
from backend.contracts.common import Language
from backend.contracts.runs import EventKind
from backend.jobs import Engine, Step
from backend.llama_server import LlamaServer, ServerConfig, ServerError
from backend.redaction import TOKEN, Redactor, capture_log
from backend.run_store import Draft, RunStore
from backend.security import COOKIE
from backend.settings import Settings
from backend.tests.support import PORT, signed_in, visitor
from backend.tests.test_jobs import RUN, T0, Stage, queued

LITERAL = "fixture literal that has no credential shape"
SHAPES = (
    "ghp_" + "a" * 36,
    "AKIA" + "A" * 16,
    "sk-" + "b" * 30,
    "eyJheader.payload.signature",
    'password="assignment-fixture"',
    "https://alice:url-fixture@localhost/path",
    "-----BEGIN PRIVATE KEY-----\nkey-fixture\n-----END PRIVATE KEY-----",
)


def configured(monkeypatch: pytest.MonkeyPatch, *values: str) -> Redactor:
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", json.dumps(values))
    return Redactor.configured()


def test_settings_load_literals_without_serializing_them(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = configured(monkeypatch, LITERAL)
    assert policy.text(LITERAL) == TOKEN
    assert LITERAL not in repr(policy) + repr(Settings()) + Settings().model_dump_json()
    assert "redaction_secrets" not in Settings().model_dump()
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", '[""]')
    with pytest.raises(ValidationError, match="cannot be empty"):
        Settings()


@pytest.mark.parametrize("value", (*SHAPES, LITERAL))
def test_only_redacted_context_reaches_tokenizer_and_chat(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    configured(monkeypatch, LITERAL)
    fake = FakeLlama(answer({"kind": "owner"}, prompt_tokens=None))
    original = request(f"L1 | {value}\nL2 | if order.customer_id != user.id: raise Denied")
    original = replace(original, system=f"Answer narrowly. {value}")
    try:
        with ModelAdapter(fake, preflight=preflight) as adapter:
            used = spend()
            result = adapter.ask(original, used)
        wire = json.dumps(fake.requests)
        assert value not in wire
        for fragment in ("assignment-fixture", "url-fixture", "key-fixture", LITERAL):
            assert fragment not in wire
        counted = fake.requests[0][1]["content"]
        sent = "\n".join(message["content"] for message in fake.chats[0]["messages"])
        assert counted == sent
        assert result.prompt_tokens == used.prompt_tokens == len(sent.split())
        assert original.user.startswith(f"L1 | {value}")
    finally:
        fake.shutdown()


def test_credential_in_schema_identity_refuses_before_loading() -> None:
    fake = FakeLlama()
    try:
        with pytest.raises(RequestRejected):
            ModelAdapter(fake, preflight=preflight, redactor=Redactor(("L1",))).ask(
                ModelRequest("guard_summary", "system", "user", {"enum": ["L1"]}), spend()
            )
        assert fake.starts == 0 and fake.requests == []
        packet = EvidencePacket.build(
            Cut.whole("handler", f"api/{SHAPES[0]}.py", Language.PYTHON, b"x = 1\n")
        )
        with pytest.raises(ValueError, match="evidence path"):
            packet.render()
    finally:
        fake.shutdown()


@pytest.mark.parametrize("value", (LITERAL, "hidden\u202evalue", "a" * 200))
def test_packet_redacts_before_escaping_and_trimming_notes(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    policy = configured(monkeypatch, value)
    source = f'x = "{value}"\n# {value}\nif order.customer_id != user.id: raise Denied\n'.encode()
    packet = EvidencePacket.build(Cut.whole("handler", "api/orders.py", Language.PYTHON, source))
    original_lines = packet.line_ids.copy()
    locations = [packet.location(line_id) for line_id in original_lines]
    prompt = guard_summary(packet)
    rendered = packet.render(redactor=policy)
    assert visible(value) not in rendered + prompt.user
    if len(value) > 120:
        assert value[:119] not in rendered
    assert TOKEN in rendered
    assert packet.line("L1").text == visible(f'x = "{value}"')
    assert packet.line_ids == original_lines
    assert [packet.location(line_id) for line_id in original_lines] == locations
    assert [
        line.split(" | ")[0] for line in rendered.splitlines() if " | " in line
    ] == original_lines


def test_multiline_keys_keep_each_citation_line() -> None:
    source = (
        b'x = """-----BEGIN PRIVATE KEY-----\nkey-fixture\n-----END PRIVATE KEY-----"""\ny = 2\n'
    )
    packet = EvidencePacket.build(Cut.whole("handler", "api/orders.py", Language.PYTHON, source))
    rendered = packet.render()
    assert "key-fixture" not in rendered
    assert [
        line.split(" | ")[0] for line in rendered.splitlines() if " | " in line
    ] == packet.line_ids
    assert packet.location("L4") == ("api/orders.py", 4)
    assert "key-fixture" in packet.line("L2").text


def test_redaction_leaves_original_hashes_and_guard_validation_intact(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = (
        b'x = "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
        b"if order.customer_id != user.id:\n    raise Denied\n"
    )
    (root / "orders.py").write_bytes(source)
    store = SnapshotStore(tmp_path / "cache")
    snapshot = take_snapshot(root, store)
    validator = Validator(snapshot, store)
    span = SourceSpan(
        snapshot_id=snapshot.id,
        path="orders.py",
        start_line=1,
        end_line=3,
        content_sha256=span_sha256(source, 1, 3),
    )
    packet = EvidencePacket.build(Cut.whole("handler", "orders.py", Language.PYTHON, source))
    assert "ghp_" not in guard_summary(packet).request().body()["messages"][1]["content"]
    guard = Guard(
        id="g:1",
        snapshot_id=snapshot.id,
        kind="owner",
        canonical="OWNER",
        mechanism="comparison",
        span=span,
    )
    assert validator.confirm(guard, subject="user.id", object="order.customer_id").confirmed
    assert validator.span(span) == []
    bad = span.model_copy(update={"content_sha256": "0" * 64})
    assert validator.span(bad)[0].rule is Rule.BAD_SPAN
    assert (root / "orders.py").read_bytes() == source


@pytest.mark.parametrize(
    "reply",
    (
        error(400, LITERAL),
        error(503, LITERAL),
        answer(LITERAL),
        answer(LITERAL, finish_reason="length"),
        Reply(body={"error": LITERAL}),
        answer([LITERAL]),
    ),
)
def test_model_failures_do_not_echo_raw_completions(reply: Reply) -> None:
    fake = FakeLlama(reply)
    try:
        with (
            ModelAdapter(fake, preflight=preflight) as adapter,
            pytest.raises(ModelError) as failure,
        ):
            adapter.ask(request(), spend(max_retries=0))
        assert LITERAL not in str(failure.value)
    finally:
        fake.shutdown()


def test_unbudgeted_requests_and_direct_tokenization_use_same_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy = configured(monkeypatch, LITERAL)
    server = LlamaServer(ServerConfig(Path("unused"), Path("unused")), tmp_path / "log")
    requests: list[httpx.Request] = []

    def receive(sent: httpx.Request) -> httpx.Response:
        requests.append(sent)
        if sent.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(200, json=answer({"kind": "owner"}).body)

    server.client.close()
    server.client = httpx.Client(base_url=server.base_url, transport=httpx.MockTransport(receive))
    try:
        ask_json(server, LITERAL, SHAPES[0], request().schema, name="guard_summary")
        server.tokenize(LITERAL)
        assert all(
            LITERAL.encode() not in sent.content and b"ghp_" not in sent.content
            for sent in requests
        )
        assert policy.text(LITERAL) == TOKEN
    finally:
        server.stop()


def test_all_run_event_messages_are_redacted_before_sqlite_and_sse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured(monkeypatch, LITERAL)
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, "q1")
    run = store.run(RUN)
    assert run is not None
    original = f"{LITERAL} {SHAPES[0]}"
    drafts = [Draft(EventKind.QUESTION_ACTIVITY, "q1", Stage.FRAME, message=original)]
    saved = store.record(run, T0, events=drafts)
    assert LITERAL not in saved[0].model_dump_json()
    assert "ghp_" not in saved[0].model_dump_json()
    assert saved == store.events(RUN)
    assert saved[0].question_id == "q1" and saved[0].seq == 1
    assert drafts[0].message == original
    assert LITERAL.encode() not in store.path.read_bytes()


def test_worker_exception_records_are_sanitized_for_every_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    configured(monkeypatch, LITERAL)
    store = RunStore(tmp_path / "runs.sqlite")
    queued(store, "q1")

    def fail(*_: object) -> Step:
        try:
            raise ValueError(LITERAL)
        except ValueError as cause:
            raise RuntimeError(SHAPES[0]) from cause

    Engine(store, {Stage.FRAME: fail}).run(RUN)
    assert TOKEN in caplog.text and "RuntimeError" in caplog.text
    assert LITERAL not in caplog.text and "ghp_" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_api_logs_mask_current_and_consumed_launch_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    configured(monkeypatch, LITERAL)
    app = create_app(Settings(data_dir=tmp_path), port=PORT)
    bootstrap = app.state.gate.bootstrap_url.split("token=")[1]
    client = signed_in(app)
    session = client.cookies.get(COOKIE)
    assert session

    @app.get("/broken")
    def broken() -> None:
        raise RuntimeError(f"{bootstrap} {session} {LITERAL} {SHAPES[0]}")

    response = client.get("/broken")
    assert response.status_code == 500
    for value in (bootstrap, session, LITERAL, SHAPES[0]):
        assert value not in caplog.text + response.text
    assert TOKEN in caplog.text
    assert visitor(app).get("/broken").status_code == 401


@pytest.mark.parametrize("value", (*SHAPES, LITERAL, "-----BEGIN PRIVATE KEY-----\nunfinished"))
def test_child_pipe_redacts_across_arbitrary_chunk_boundaries(value: str) -> None:
    class SmallReads(io.BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            return super().read(min(size, 3) if size is not None else 3)

    output = io.StringIO()
    capture_log(SmallReads(f"ready {value}\n".encode()), output, Redactor((LITERAL,)))
    text = output.getvalue()
    assert "ready" in text and TOKEN in text
    for fragment in (value, "key-fixture", "assignment-fixture", "url-fixture", "unfinished"):
        assert fragment not in text


def test_log_overflow_drains_every_byte_and_omits_partial_values() -> None:
    data = io.BytesIO((LITERAL * 100).encode())
    output = io.StringIO()
    capture_log(data, output, Redactor((LITERAL,)), limit=20)
    assert data.tell() == len(data.getvalue())
    assert "size limit exceeded" in output.getvalue()
    assert LITERAL[:20] not in output.getvalue()


@pytest.mark.parametrize("mode", ("ready", "exit", "timeout"))
def test_real_child_logs_are_sanitized_and_flushed_on_all_shutdown_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    child = Path(__file__).with_name("redaction_child.py")
    ready = tmp_path / "ready"

    def argv(config: ServerConfig, port: int, api_key: str) -> list[str]:
        return [sys.executable, "-u", str(child), str(ready), api_key, LITERAL, mode]

    monkeypatch.setattr(ServerConfig, "argv", argv)
    server = LlamaServer(
        ServerConfig(Path("unused"), Path("unused")),
        tmp_path / "child.log",
        startup_timeout=3 if mode != "timeout" else 1,
        redactor=Redactor((LITERAL,)),
    )
    server.client.close()
    server.client = httpx.Client(
        base_url=server.base_url,
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200 if ready.exists() and mode == "ready" else 503)
        ),
    )
    if mode == "ready":
        server.start()
        assert server.log_path.read_bytes() == b""  # no raw data is ever spooled
        server.stop()
    else:
        with pytest.raises(ServerError, match=r"exited|not ready"):
            server.start()
    text = server.log_path.read_text(encoding="utf-8")
    assert "child ready" in text and TOKEN in text
    assert LITERAL not in text and server.api_key not in text and "ghp_" not in text
    assert server._log_thread is None and server._log is None
    server.stop()


def test_failed_child_launch_closes_log_and_hides_arguments(tmp_path: Path) -> None:
    server = LlamaServer(ServerConfig(tmp_path / LITERAL, Path("unused")), tmp_path / "log")
    with pytest.raises(ServerError, match="could not be started") as failure:
        server.start()
    assert LITERAL not in str(failure.value)
    assert server._log is None


@pytest.mark.parametrize("status,payload", [(403, LITERAL), (200, LITERAL), (200, "[]")])
def test_direct_server_error_messages_never_include_response_data(
    tmp_path: Path, status: int, payload: str
) -> None:
    server = LlamaServer(ServerConfig(Path("unused"), Path("unused")), tmp_path / "log")
    server.client.close()
    server.client = httpx.Client(
        base_url=server.base_url,
        transport=httpx.MockTransport(lambda req: httpx.Response(status, text=payload)),
    )
    try:
        with pytest.raises(ServerError) as failure:
            server.post("/v1/chat/completions", request().body())
        assert LITERAL not in str(failure.value)
    finally:
        server.stop()


def test_direct_model_schema_never_changes_identities(tmp_path: Path) -> None:
    server = LlamaServer(
        ServerConfig(Path("unused"), Path("unused")),
        tmp_path / "log",
        redactor=Redactor((LITERAL,)),
    )
    try:
        with pytest.raises(ServerError, match="schema"):
            server.post("/v1/chat/completions", {"response_format": {"enum": [LITERAL]}})
    finally:
        server.stop()
