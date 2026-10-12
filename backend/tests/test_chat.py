"""Target-free chat: general answers, cited answers, proposals and their boundaries.

Software only. The model is a scripted stand-in, so these tests establish routing
and checks, never answer quality.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from agent.asking import EvaluationAsker
from agent.llm import JsonAnswer, ModelRequest, ModelTimeout, Spend, TextAnswer, TextRequest
from backend import chat
from backend.chat import (
    ABOUT,
    CITED_BASIS,
    GENERAL_BASIS,
    GENERAL_MAX_TOKENS,
    GENERAL_SYSTEM,
    HISTORY_CHARS,
    HISTORY_TURNS,
    Chats,
    card_for,
    general_history,
    named_in,
    trim_to_sentence,
)
from backend.contracts.chat import ChatAsk, ChatCreate, ChatPart, ChatTurn, ChatView, Intent
from backend.contracts.code import SourceSpan
from backend.contracts.conversation import ConversationEvidence
from backend.local_model import Loaded, ModelNotReady
from backend.redaction import Redactor
from backend.settings import Settings

SNAPSHOT = "b" * 64
REVIEW = "review-" + "d" * 32


class Model:
    """Scripted adapter: intents, plain texts and cited answers are played in order."""

    def __init__(self) -> None:
        self.intents: list[str] = []
        self.texts: list[Any] = []  # TextAnswer or an exception to raise
        self.cited: list[dict[str, Any]] = []
        self.closed: list[ModelRequest] = []
        self.written: list[TextRequest] = []
        self.loads = 0
        self.ready: str | None = None  # a refusal message when the model may not start
        self.gate: threading.Event | None = None

    def count_tokens(self, text: str, spend: Spend) -> int:
        return 4

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.closed.append(request)
        if request.name == "closed_message_intent":
            data: dict[str, Any] = {"answer": self.intents.pop(0)}
        else:
            data = self.cited.pop(0)
        return JsonAnswer(data, json.dumps(data), 50, 5, 0.25, prompt_ms=200.0, predicted_ms=50.0)

    def ask_text(self, request: TextRequest, spend: Spend) -> TextAnswer:
        self.written.append(request)
        if self.gate is not None:
            self.gate.wait(5)
        reply = self.texts.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def evidence() -> list[ConversationEvidence]:
    return [
        ConversationEvidence(
            reference_id="R001",
            label="tandir/routers/orders.py:41",
            quote="    order = db.get(Order, order_id)",
            source=SourceSpan(
                snapshot_id=SNAPSHOT,
                path="tandir/routers/orders.py",
                start_line=41,
                end_line=41,
                content_sha256="c" * 64,
            ),
        )
    ]


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Model:
    fake = Model()

    @contextmanager
    def loaded(*args: object, manifest: dict[str, Any], **kwargs: object) -> Iterator[Loaded]:
        if fake.ready is not None:
            raise ModelNotReady(fake.ready)
        fake.loads += 1
        manifest.update(model_created=True, model_stopped=False)
        try:
            yield Loaded(fake, SimpleNamespace(id="test-profile"))  # ty: ignore[invalid-argument-type]
        finally:
            manifest["model_stopped"] = True

    monkeypatch.setattr(chat, "local_model", loaded)
    # This is the explicit scripted software seam. A fixture cannot publish a
    # qualification; production ModelAsker remains closed by default.
    monkeypatch.setattr(chat, "ModelAsker", EvaluationAsker)
    monkeypatch.setattr(chat, "intent_reason", lambda *_: None)
    monkeypatch.setattr(chat, "WorkerLock", lambda _: nullcontext())
    monkeypatch.setattr(
        chat, "evidence_for", lambda *args: (evidence(), ["Static only."], SNAPSHOT)
    )
    return fake


@pytest.fixture
def chats(tmp_path: Path, model: Model) -> Iterator[Chats]:
    worker = Chats(
        Settings(data_dir=tmp_path / "data", redaction_secrets=(SecretStr("hunter2-private"),))
    )
    yield worker
    worker.close()


def say(worker: Chats, view: ChatView, prompt: str, choice: Intent | None = None) -> ChatView:
    worker.start(view.chat_id, ChatAsk(prompt=prompt, choice=choice))
    return worker.wait(view.chat_id, 10)


def text(reply: str, complete: bool = True) -> TextAnswer:
    return TextAnswer(reply, complete, 40, 60, 1.5)


# --- general and creative answers ----------------------------------------------------------


def test_an_unqualified_intent_goes_to_the_user_without_loading_or_misrouting(
    chats: Chats, model: Model, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.model_qualification import intent_reason

    monkeypatch.setattr(chat, "intent_reason", intent_reason)
    model.intents = ["review_folder"]  # the recorded wrong reading must never be sent
    turn = say(chats, chats.new(), "Explain that result").turns[-1]
    assert (turn.intent, turn.intent_rung, turn.model_requests) == ("unclear", "user", 0)
    assert model.loads == 0 and model.closed == [] and turn.task is None
    assert "passing local capability measurement" in turn.parts[0].text
    assert {item.intent for item in turn.choices} >= {"general_question", "review_folder"}


def test_an_ordinary_question_needs_no_target_and_is_answered_as_general(
    chats: Chats, model: Model
) -> None:
    model.intents, model.texts = ["general_question"], [text("It is an injection of SQL text.")]
    view = say(chats, chats.new(), "What is SQL injection?")
    assert (view.state, view.target_kind, view.target_id) == ("completed", None, None)
    (turn,) = view.turns
    assert (turn.intent, turn.intent_rung) == ("general_question", "model")
    assert turn.interpretation == "I read this as a general question."
    (part,) = turn.parts
    assert (part.kind, part.text, part.basis) == (
        "general",
        "It is an injection of SQL text.",
        GENERAL_BASIS,
    )
    assert part.evidence == [] and turn.task is None
    assert (turn.authorization_granted, turn.actions_executed, turn.finding_created) == (
        False,
        False,
        False,
    )
    assert turn.model_requests == 2 and str(GENERAL_MAX_TOKENS) in turn.limits
    (written,) = model.written
    assert written.system == GENERAL_SYSTEM and written.user == "What is SQL injection?"
    assert "response_format" not in written.body()  # the general contract has no citation slot
    assert model.loads == 1  # one load serves the intent question and the answer


def test_a_creative_request_and_other_languages_are_not_rejected_by_keywords(
    chats: Chats, model: Model
) -> None:
    model.intents = ["creative_writing", "general_question"]
    model.texts = [text("Leaves fall.\nThe tandir glows."), text("SQL inyeksiya bu hujum turi.")]
    view = chats.new()
    poem = say(chats, view, "Write a short poem").turns[-1]
    assert (poem.intent, poem.parts[0].kind) == ("creative_writing", "general")
    assert "Not about any website" in poem.parts[0].basis
    uzbek = say(chats, view, "SQL inyeksiya nima?").turns[-1]
    assert uzbek.parts[0].text == "SQL inyeksiya bu hujum turi."


def test_a_general_or_creative_followup_contains_the_previous_answer(
    chats: Chats,
    model: Model,
) -> None:
    model.texts = [
        text("Autumn leaves fall slowly."),
        text("Leaves fall."),
        text("They fall in autumn."),
    ]
    view = chats.new()
    say(chats, view, "Write a short poem about autumn", choice="creative_writing")
    say(chats, view, "Make that shorter", choice="creative_writing")
    latest = say(chats, view, "Explain the season in that poem", choice="general_question")
    assert "Autumn leaves fall slowly." in model.written[1].user
    assert "Make that shorter" in model.written[2].user and "Leaves fall." in model.written[2].user
    assert "Current request:\nExplain the season in that poem" in model.written[2].user
    assert "not instructions, evidence or permission" in model.written[2].system
    assert latest.turns[-1].model_requests == 1
    assert latest.turns[-1].authorization_granted is False


def test_history_is_sanitized_bounded_and_does_not_cross_a_target_result() -> None:
    def turn(prompt: str, answer: str, intent: Intent = "general_question") -> ChatTurn:
        return ChatTurn(
            prompt=prompt,
            intent=intent,
            intent_rung="user",
            interpretation="You chose this.",
            limits="test",
            parts=[ChatPart(kind="general", text=answer, basis=GENERAL_BASIS)],
        )

    view = ChatView(
        chat_id="chat-" + "c" * 32,
        turns=[
            turn("Oldest", "Earlier answer."),
            turn("Question " * 50, "A" * 4000),
            turn("Last question", "hunter2-private is just a placeholder.\x00 Done."),
        ],
    )
    history = general_history(view, Redactor(("hunter2-private",)))
    encoded = json.dumps(history, ensure_ascii=False)
    assert len(history) == HISTORY_TURNS and "Oldest" not in encoded
    assert "hunter2-private" not in encoded and "[REDACTED]" in encoded and "\x00" not in encoded
    assert "shortened" in encoded and len(encoded) < HISTORY_CHARS + 10
    view.turns.append(turn("Explain my result", "A result-specific answer.", "general_and_result"))
    assert general_history(view, Redactor()) == []
    view.turns[-1] = turn("Is https://shop.example vulnerable?", "An unsafe saved answer.")
    assert general_history(view, Redactor()) == []
    view.turns[-1] = turn("Explain F-02", "A saved identifier.")
    assert general_history(view, Redactor()) == []


def test_history_is_removed_before_generation_when_the_real_token_budget_would_overflow(
    chats: Chats,
    model: Model,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model.texts = [text("An earlier explanation."), text("A new explanation.")]
    view = chats.new()
    say(chats, view, "Explain seasons", choice="general_question")
    counted: list[str] = []

    def count(candidate: str, spend: Spend) -> int:
        counted.append(candidate)
        return 1501 if "Previous general chat" in candidate else 4

    monkeypatch.setattr(model, "count_tokens", count)
    say(chats, view, "Make that shorter", choice="general_question")
    assert counted and "An earlier explanation." in counted[0]
    assert model.written[-1].user == "Make that shorter"
    assert len(model.written) == 2  # context selection did not retry the generation


def test_a_cut_off_answer_is_shown_to_its_last_sentence_and_says_so(
    chats: Chats, model: Model
) -> None:
    model.intents = ["general_question", "general_question"]
    model.texts = [
        text("First point. Second point. A third that never", False),
        text("no end", False),
    ]
    view = chats.new()
    part = say(chats, view, "Explain cookies").turns[-1].parts[0]
    assert part.text == "First point. Second point. (This answer reached its length limit.)"
    assert part.complete is False
    nothing = say(chats, view, "Explain sessions").turns[-1].parts[0]
    assert (nothing.kind, nothing.complete) == ("notice", False)
    assert trim_to_sentence("One. Two") == "One." and trim_to_sentence("no end") == ""


def test_a_matching_reviewed_card_grounds_the_answer_and_is_named(
    chats: Chats, model: Model
) -> None:
    model.intents, model.texts = ["general_question"], [text("Compare two accounts on one object.")]
    part = say(chats, chats.new(), "What is IDOR and how is it tested?").turns[-1].parts[0]
    assert (part.kind, part.guidance_card) == ("guidance", "GUIDE-object-authorization")
    assert "Cross-account object authorization" in part.basis and "not a finding" in part.basis
    assert model.written[0].user.startswith("Reviewed guidance:\n- Topic: Cross-account")
    assert card_for("Write a short poem about autumn") is None
    assert card_for("What is SQL injection?") is None
    assert card_for("How do role and admin privilege checks work?") is not None


# --- unknown targets and invented target facts ---------------------------------------------


def test_a_question_about_an_unknown_website_gets_a_plan_and_no_model_wording(
    chats: Chats, model: Model
) -> None:
    model.intents = ["general_question"]
    turn = say(chats, chats.new(), "Is https://shop.example vulnerable to SQL injection?").turns[-1]
    (part,) = turn.parts
    assert part.kind == "notice" and "I have not visited https://shop.example" in part.text
    assert turn.task is not None and (turn.task.kind, turn.task.ready, turn.task.url) == (
        "website_setup",
        False,
        "https://shop.example",
    )
    assert turn.task.authorization_granted is False and turn.task.started is False
    assert model.written == []  # nothing was written about a site nobody looked at


@pytest.mark.parametrize(
    "address",
    [
        "shop.xyz",
        "shop.biz?item=1",
        "xn--e1afmkfd.xn--p1ai",
        "пример.рф",
        "192.0.2.1:8080/login",
        "[2001:db8::1]:8443",
        "localhost:8701",
    ],
)
def test_unobserved_bare_domains_and_ips_never_get_an_uncited_target_answer(
    chats: Chats,
    model: Model,
    address: str,
) -> None:
    turn = say(chats, chats.new(), f"Is {address} vulnerable?", choice="general_question").turns[-1]
    assert turn.parts[0].kind == "notice" and "have no observations" in turn.parts[0].text
    assert turn.task is not None and turn.task.kind == "website_setup"
    assert model.loads == 0 and model.written == []


@pytest.mark.parametrize(
    "invented",
    [
        "shop.xyz exposes customer receipts.",
        "192.0.2.1 leaks every invoice.",
        "пример.рф has no authentication.",
    ],
)
def test_a_general_answer_cannot_introduce_an_unobserved_target_claim(
    chats: Chats,
    model: Model,
    invented: str,
) -> None:
    model.texts = [text(invented)]
    turn = say(chats, chats.new(), "What is SQL injection?", choice="general_question").turns[-1]
    assert turn.parts[0].kind == "notice" and "did not show it" in turn.parts[0].text
    assert turn.finding_created is False and turn.actions_executed is False


def test_a_general_answer_that_names_the_selected_result_is_withheld(
    chats: Chats, model: Model
) -> None:
    view = chats.new(ChatCreate(target_kind="review", target_id=REVIEW))
    assert view.target_label == "Review " + "d" * 8
    model.intents = ["general_question", "general_question"]
    model.texts = [
        text(f"Your {REVIEW} proves the receipt route is broken."),
        text("Finding F-02 in your code is real."),
    ]
    for prompt in ("What is IDOR in general terms, briefly?", "And broken access control?"):
        (part,) = say(chats, view, prompt).turns[-1].parts
        assert part.kind == "notice" and "did not show it" in part.text
    assert named_in("See R003 and F-12", ()) == ["R003", "F-12"]


def test_a_secret_shaped_answer_is_withheld(chats: Chats, model: Model) -> None:
    model.intents, model.texts = ["general_question"], [text("Use password = hunter2-private")]
    (part,) = say(chats, chats.new(), "Give an example config").turns[-1].parts
    assert part.kind == "notice" and "something private" in part.text


# --- questions about a selected result --------------------------------------------------------


def test_a_mixed_follow_up_is_general_where_general_and_cited_where_about_the_result(
    chats: Chats, model: Model
) -> None:
    view = chats.new(ChatCreate(target_kind="review", target_id=REVIEW))
    model.intents = ["general_and_result"]
    model.texts = [text("IDOR is reading another user's object by changing its identifier.")]
    model.cited = [
        {
            "answer": "The receipt handler loads the order by ID only.",
            "references": ["R001"],
            "unknowns": [],
        }
    ]
    turn = say(chats, view, "What is broken access control, and does my review show it?").turns[-1]
    general, cited = turn.parts
    assert (general.kind, general.evidence) == ("general", [])
    assert "Answer only the general part" in model.written[0].system
    assert (cited.kind, cited.basis) == ("cited", CITED_BASIS)
    assert (
        cited.text == "Local model interpretation: The receipt handler loads the order by ID only."
    )
    assert [item.reference_id for item in cited.evidence] == ["R001"]
    assert cited.evidence[0].source is not None and cited.evidence[0].source.snapshot_id == SNAPSHOT
    assert turn.finding_created is False
    # The selection is kept for the next message.
    assert chats.read(view.chat_id).target_id == REVIEW


@pytest.mark.parametrize(
    "answer",
    [
        {"answer": "Yes, the review proves an IDOR.", "references": [], "unknowns": []},
        {"answer": "Yes, see R009.", "references": ["R009"], "unknowns": []},
        {"answer": "Yes, see R001 and R002.", "references": ["R001"], "unknowns": []},
        {"answer": "Yes.", "references": ["R001", "R001"], "unknowns": []},
        {"answer": "Yes.", "references": ["R001"]},
    ],
)
def test_an_uncited_or_wrongly_cited_claim_about_the_result_does_not_pass(
    chats: Chats, model: Model, answer: dict[str, Any]
) -> None:
    view = chats.new(ChatCreate(target_kind="review", target_id=REVIEW))
    model.intents, model.cited = ["explain_result"], [answer]
    (part,) = say(chats, view, "Explain that result").turns[-1].parts
    assert part.kind == "notice" and part.evidence == []
    assert "does not settle this question" in part.text
    assert "proves" not in part.text and "Yes" not in part.text


def test_explaining_a_result_with_nothing_selected_asks_which_and_guesses_nothing(
    chats: Chats, model: Model
) -> None:
    model.intents = ["explain_result"]
    turn = say(chats, chats.new(), "Explain that result").turns[-1]
    assert turn.task is not None and turn.task.kind == "choose_result"
    assert "will not guess" in turn.parts[0].text and model.written == []
    assert len(model.closed) == 1  # only the intent question


# --- proposals never start work -------------------------------------------------------------


def test_review_and_website_requests_become_proposals(
    chats: Chats, model: Model, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    model.intents = ["review_folder", "review_folder", "test_website"]
    view = chats.new()
    ready = say(chats, view, f"Review my folder {project}").turns[-1]
    assert ready.task is not None and (ready.task.kind, ready.task.ready, ready.task.folder) == (
        "inspect_folder",
        True,
        str(project),
    )
    assert "Nothing has been read yet" in ready.parts[0].text
    missing = say(chats, view, "Review my folder").turns[-1]
    assert missing.task is not None and missing.task.ready is False
    assert missing.task.missing == ["The folder's full path on this computer."]
    website = say(chats, view, "Test this approved website").turns[-1]
    assert website.task is not None and website.task.missing[0] == "The website's address."
    assert "cannot start, approve or widen" in website.parts[0].basis
    assert not (tmp_path / "data" / "cache" / "snapshots").exists()  # nothing was inspected
    assert model.written == []


def test_a_bare_address_is_routed_by_code_without_loading_the_model(
    chats: Chats, model: Model
) -> None:
    turn = say(chats, chats.new(), "https://shop.example/").turns[-1]
    assert (turn.intent, turn.intent_rung, turn.model_requests) == ("test_website", "code", 0)
    assert model.loads == 0


# --- when the model cannot be used ------------------------------------------------------------


def test_without_a_model_the_chat_asks_a_plain_question_instead_of_rejecting(
    chats: Chats, model: Model
) -> None:
    model.ready = "Only 0.7 GB of memory is free; the model needs 1.4 GB."
    view = chats.new()
    turn = say(chats, view, "Tell me something interesting").turns[-1]
    assert (turn.intent, turn.intent_rung) == ("unclear", "user")
    assert "0.7 GB" in turn.parts[0].text and "Please pick one" in turn.parts[0].text
    assert [choice.intent for choice in turn.choices][:2] == [
        "general_question",
        "creative_writing",
    ]
    picked = say(chats, view, "Tell me something interesting", choice="about_plumb").turns[-1]
    assert (picked.intent, picked.intent_rung, picked.parts[0].text) == (
        "about_plumb",
        "user",
        ABOUT,
    )
    general = say(chats, view, "Tell me something interesting", choice="general_question")
    assert "cannot write this answer now" in general.turns[-1].parts[0].text
    assert general.state == "completed" and len(general.turns) == 3


def test_a_slow_answer_keeps_earlier_turns_and_shows_nothing_half_written(
    chats: Chats, model: Model
) -> None:
    model.intents = ["general_question", "general_question"]
    model.texts = [text("A full answer."), ModelTimeout("slow")]
    view = chats.new()
    say(chats, view, "First question")
    second = say(chats, view, "Second question")
    assert second.state == "completed" and len(second.turns) == 2
    assert second.turns[0].parts[0].text == "A full answer."
    assert "did not finish" in second.turns[1].parts[0].text


def test_stop_cancels_the_running_answer_and_keeps_saved_turns(chats: Chats, model: Model) -> None:
    model.intents = ["general_question", "general_question"]
    model.texts = [text("Kept."), text("Never shown.")]
    view = chats.new()
    say(chats, view, "First")
    model.gate = threading.Event()
    running = chats.start(view.chat_id, ChatAsk(prompt="Second"))
    assert running.state == "running"
    with pytest.raises(ValueError, match="still being written"):
        chats.start(view.chat_id, ChatAsk(prompt="Third"))
    chats.cancel(view.chat_id)
    model.gate.set()
    stopped = chats.wait(view.chat_id, 10)
    assert stopped.state == "canceled" and [turn.prompt for turn in stopped.turns] == ["First"]
    model.gate = None
    model.intents, model.texts = ["general_question"], [text("Resumed.")]
    assert say(chats, view, "Again").turns[-1].parts[0].text == "Resumed."


def test_an_interactive_session_keeps_one_loaded_model_between_messages(
    tmp_path: Path, model: Model
) -> None:
    worker = Chats(Settings(data_dir=tmp_path / "data"), hold_model=True)
    try:
        model.intents = ["general_question", "creative_writing"]
        model.texts = [text("One."), text("Two.")]
        view = worker.new()
        say(worker, view, "First")
        say(worker, view, "Second")
        assert model.loads == 1
        worker.release_model()  # for example before browser work
        model.intents, model.texts = ["general_question"], [text("Three.")]
        say(worker, view, "Third")
        assert model.loads == 2
    finally:
        worker.close()


# --- storage and input boundaries ---------------------------------------------------------------


def test_secrets_in_a_message_are_refused_before_any_model_or_storage(
    chats: Chats, model: Model
) -> None:
    view = chats.new()
    with pytest.raises(ValueError, match="Remove passwords"):
        chats.start(view.chat_id, ChatAsk(prompt="my token is hunter2-private, is it safe?"))
    assert chats.read(view.chat_id).turns == [] and model.loads == 0


def test_private_storage_bounds(tmp_path: Path, model: Model) -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        Chats(Settings(data_dir=Path(chat.__file__).resolve().parents[1] / "tmp" / "x"))
    worker = Chats(Settings(data_dir=tmp_path / "data"))
    for bad in ("chat-xyz", "../chat-" + "a" * 32, "conversation-" + "a" * 32):
        with pytest.raises(ValueError, match="Invalid chat ID"):
            worker.read(bad)
    view = worker.new()
    model.intents, model.texts = ["general_question"], [text("Fine.")]
    say(worker, view, "Hello")
    files = sorted(path.name for path in (tmp_path / "data" / "cache" / "chats").iterdir())
    assert len(files) == 2
    assert sum(name.endswith(".chat-invocation.json") for name in files) == 1
    manifest = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "data" / "cache" / "chats").iterdir()
        if path.name.endswith(".chat-invocation.json")
    )
    assert manifest["intent"]["rung"] == "model" and manifest["model_stopped"] is True
    assert manifest["requests"][0]["answer"]["text"] == "Fine."
    worker.close()


def test_a_chat_has_a_finite_number_of_turns(
    chats: Chats, model: Model, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat, "MAX_TURNS", 1)
    view = chats.new()
    say(chats, view, "https://shop.example/")
    with pytest.raises(ValueError, match="start a new one"):
        chats.start(view.chat_id, ChatAsk(prompt="https://shop.example/"))


def test_part_contract_keeps_general_and_cited_apart() -> None:
    with pytest.raises(ValueError, match="only a cited part carries evidence"):
        ChatPart(kind="general", text="x", basis="y", evidence=evidence())
    with pytest.raises(ValueError, match="exact evidence"):
        ChatPart(kind="cited", text="x", basis="y")
    with pytest.raises(ValueError, match="reviewed card"):
        ChatPart(kind="guidance", text="x", basis="y")
    with pytest.raises(ValueError, match="both its kind"):
        ChatCreate(target_kind="review")
