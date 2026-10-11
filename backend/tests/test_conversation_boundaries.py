"""Independent negative audit of private storage and model admission; no inference."""

import os
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent.llm import JsonAnswer
from backend import conversation
from backend.contracts.code import SourceSpan
from backend.contracts.conversation import ConversationAsk, ConversationEvidence, ConversationView
from backend.preflight import PreflightResult
from backend.redaction import Redactor
from backend.settings import Settings

IDENTIFIER = "conversation-" + "a" * 32
SNAPSHOT = "b" * 64


def evidence() -> list[ConversationEvidence]:
    return [
        ConversationEvidence(
            reference_id="R001",
            label="app.py:1",
            quote="return value",
            source=SourceSpan(
                snapshot_id=SNAPSHOT,
                path="app.py",
                start_line=1,
                end_line=1,
                content_sha256="c" * 64,
            ),
        )
    ]


def view() -> ConversationView:
    return ConversationView(
        target_kind="review",
        target_id="review-" + "d" * 32,
        conversation_id=IDENTIFIER,
        state="running",
    )


class FakeServer:
    startup_timeout = 300.0

    def __init__(self, *, admitted: bool = True) -> None:
        self.admitted = admitted
        self.starts = 0
        self.stops = 0

    def preflight(self) -> PreflightResult:
        return PreflightResult(self.admitted, "test", 8192, 0, None, "Software fixture gate")

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class FakeAdapter:
    def __init__(self, server: FakeServer, **kwargs: object) -> None:
        self.server = server

    def __enter__(self) -> "FakeAdapter":
        self.server.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.stop()

    def ask(self, *args: object) -> JsonAnswer:
        return JsonAnswer(
            {"answer": "The return reads value.", "references": ["R001"], "unknowns": []},
            "software fixture",
            10,
            10,
            0.01,
        )


@pytest.fixture
def worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[conversation.Conversations, list[ConversationView], list[dict[str, Any]], FakeServer]:
    instance = conversation.Conversations(Settings(data_dir=tmp_path / "data"))
    saved: list[ConversationView] = []
    manifests: list[dict[str, Any]] = []
    server = FakeServer()
    monkeypatch.setattr(instance, "save", lambda value: saved.append(value))
    monkeypatch.setattr(instance, "path", lambda _: tmp_path / "private.json")
    monkeypatch.setattr(conversation, "write_json", lambda _, value: manifests.append(value))
    monkeypatch.setattr(conversation, "WorkerLock", lambda _: nullcontext())
    monkeypatch.setattr(
        conversation, "evidence_for", lambda *args: (evidence(), ["Unrun"], SNAPSHOT)
    )
    monkeypatch.setattr(conversation, "select", lambda *args: SimpleNamespace(identity=lambda: {}))
    monkeypatch.setattr(conversation, "first_use_pending", lambda *args: False)
    monkeypatch.setattr(conversation, "create", lambda *args: server)
    monkeypatch.setattr(conversation, "ModelAdapter", FakeAdapter)
    monkeypatch.setattr("eval.bench.machine.machine_state", lambda: {"software_fixture": True})
    return instance, saved, manifests, server


def test_private_storage_roundtrip_checks_real_files_without_attribute_error(
    tmp_path: Path,
) -> None:
    instance = conversation.Conversations(Settings(data_dir=tmp_path / "data"))
    original = view().model_copy(update={"state": "idle"})
    instance.save(original)
    assert instance.read(IDENTIFIER) == original
    for invalid in ("../escape", "conversation-" + "a" * 32 + "/file", "conversation-A"):
        with pytest.raises(ValueError, match="Invalid conversation"):
            instance.path(invalid)


def test_hardlinked_private_conversation_is_refused(tmp_path: Path) -> None:
    instance = conversation.Conversations(Settings(data_dir=tmp_path / "data"))
    instance.directory.mkdir(parents=True)
    outside = tmp_path / "unrelated.json"
    outside.write_text(view().model_dump_json(), encoding="utf-8")
    try:
        os.link(outside, instance.directory / (IDENTIFIER + ".json"))
    except PermissionError:
        pytest.skip("Sandbox refuses creating actual Windows hardlinks")
    with pytest.raises(ValueError, match=r"[Ll]ink"):
        instance.read(IDENTIFIER)


def test_hardlink_count_is_independently_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = conversation.Conversations(Settings(data_dir=tmp_path / "data"))
    instance.directory.mkdir(parents=True)
    target = instance.directory / (IDENTIFIER + ".json")
    target.write_text(view().model_dump_json(), encoding="utf-8")
    original = Path.stat

    def stat(path: Path, **kwargs: Any) -> os.stat_result:  # noqa: ANN401 - Path.stat passthrough
        result = original(path, **kwargs)
        if path == target and kwargs.get("follow_symlinks", True):
            fields = list(result)
            fields[3] = 2
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(ValueError, match="Hardlinked"):
        instance.path(IDENTIFIER)


def test_first_use_refusal_never_creates_or_starts_a_model(
    worker: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, saved, manifests, server = worker
    monkeypatch.setattr(conversation, "first_use_pending", lambda *args: True)

    def forbidden(*args: object) -> None:
        pytest.fail("First-use refusal reached model creation")

    monkeypatch.setattr(conversation, "create", forbidden)
    instance._run(view(), ConversationAsk(prompt="Explain this return"), threading.Event())
    assert saved[-1].state == "failed" and not saved[-1].turns and server.starts == 0
    assert manifests[-1]["model_created"] is False
    assert manifests[-1]["model_stopped"] is None


def test_cancel_during_retrieval_never_reaches_model_admission(
    worker: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, saved, _, server = worker
    cancel = threading.Event()

    def retrieved(*args: object) -> tuple:
        cancel.set()
        return evidence(), [], SNAPSHOT

    monkeypatch.setattr(conversation, "evidence_for", retrieved)

    def forbidden(*args: object) -> None:
        pytest.fail("Canceled retrieval reached model creation")

    monkeypatch.setattr(conversation, "create", forbidden)
    instance._run(view(), ConversationAsk(prompt="Explain this return"), cancel)
    assert saved[-1].state == "canceled" and not saved[-1].turns and server.starts == 0


def test_expired_retrieval_budget_never_reaches_model_admission(
    worker: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, saved, _, server = worker
    now = [0.0]
    monkeypatch.setattr(conversation.time, "perf_counter", lambda: now[0])

    def retrieved(*args: object) -> tuple:
        now[0] = 2.0
        return evidence(), [], SNAPSHOT

    monkeypatch.setattr(conversation, "evidence_for", retrieved)

    def forbidden(*args: object) -> None:
        pytest.fail("Expired retrieval reached model creation")

    monkeypatch.setattr(conversation, "create", forbidden)
    instance._run(
        view(), ConversationAsk(prompt="Explain this return", max_seconds=1), threading.Event()
    )
    assert saved[-1].state == "failed" and not saved[-1].turns and server.starts == 0


def test_memory_refusal_uses_real_adapter_admission_without_loading(
    worker: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent.llm import ModelAdapter

    instance, saved, _, server = worker
    server.admitted = False
    monkeypatch.setattr(conversation, "ModelAdapter", ModelAdapter)
    instance._run(view(), ConversationAsk(prompt="Explain this return"), threading.Event())
    assert saved[-1].state == "failed" and not saved[-1].turns and server.starts == 0
    assert server.stops > 0


def test_changed_evidence_discards_answer_but_stops_owned_model(
    worker: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, saved, _, server = worker
    identities = iter([SNAPSHOT, "e" * 64])
    monkeypatch.setattr(
        conversation, "evidence_for", lambda *args: (evidence(), [], next(identities))
    )
    instance._run(view(), ConversationAsk(prompt="Explain this return"), threading.Event())
    assert saved[-1].state == "failed" and not saved[-1].turns
    assert server.starts == 1 and server.stops > 0


def test_failed_model_cleanup_is_recorded_without_claiming_it_stopped(
    worker: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, saved, manifests, server = worker

    def failed_stop() -> None:
        server.stops += 1
        raise RuntimeError("Software fixture cleanup failure")

    monkeypatch.setattr(server, "stop", failed_stop)
    instance._run(view(), ConversationAsk(prompt="Explain this return"), threading.Event())
    assert saved[-1].state == "failed"
    assert server.starts == 1 and server.stops >= 2
    assert manifests[-1]["model_created"] is True
    assert manifests[-1]["model_stopped"] is False
    assert manifests[-1]["cleanup_error"] == "RuntimeError"


def test_canceled_inference_monitor_stops_model_and_discards_a_returned_answer(
    worker: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, saved, manifests, server = worker
    cancel, stopped = threading.Event(), threading.Event()

    def stop() -> None:
        server.stops += 1
        stopped.set()

    class CanceledAdapter(FakeAdapter):
        def ask(self, *args: object) -> JsonAnswer:
            cancel.set()
            assert stopped.wait(2), "Cancel monitor did not stop the software fixture"
            return super().ask(*args)

    monkeypatch.setattr(server, "stop", stop)
    monkeypatch.setattr(conversation, "ModelAdapter", CanceledAdapter)
    instance._run(view(), ConversationAsk(prompt="Explain this return"), cancel)
    assert saved[-1].state == "canceled" and not saved[-1].turns
    assert server.starts == 1 and server.stops >= 2
    assert manifests[-1]["model_created"] is True
    assert manifests[-1]["model_stopped"] is True


@pytest.mark.parametrize(
    "changed",
    [
        {"references": ["R999"]},
        {"references": ["R001", "R001"]},
        {"actions_executed": True},
        {"authorization_granted": True},
    ],
)
def test_model_output_cannot_add_refs_or_grant_actions(changed: dict[str, object]) -> None:
    answer: dict[str, object] = {
        "answer": "The line returns value.",
        "references": ["R001"],
        "unknowns": [],
    }
    with pytest.raises(ValueError, match="invalid"):
        conversation.validate_answer({**answer, **changed}, "Explain", evidence(), [], SNAPSHOT)


def test_uncited_output_remains_unknown_and_preserves_recorded_gaps() -> None:
    answer: dict[str, object] = {"answer": "Everything is safe", "references": [], "unknowns": []}
    result = conversation.validate_answer(
        answer, "Explain", evidence(), ["No protected control"], SNAPSHOT
    )
    assert result.generated_by == "unresolved" and not result.evidence
    assert "safe" not in result.answer and result.unknowns == ["No protected control"]
    assert (
        not result.actions_executed
        and not result.authorization_granted
        and not result.verdict_changed
    )


def test_prose_cannot_mention_an_unselected_reference_or_configured_private_value() -> None:
    answer: dict[str, object] = {
        "answer": "R999 establishes this.",
        "references": ["R001"],
        "unknowns": [],
    }
    with pytest.raises(ValueError, match="unselected"):
        conversation.validate_answer(answer, "Explain", evidence(), [], SNAPSHOT)
    answer["answer"] = "The private value is local-private-value."
    with pytest.raises(ValueError, match="Private"):
        conversation.validate_answer(
            answer, "Explain", evidence(), [], SNAPSHOT, Redactor(("local-private-value",))
        )
