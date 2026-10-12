"""Regenerate the Ask and Website view fixtures from the real backend.

    uv run --extra browser python frontend/scripts/fixtures/make_ask_website_fixtures.py

The website views come from one real journey on Plumb's own practice website
with the pinned browser and no model (its one open question is answered as the
user would). The chat view is built from the backend's own contracts. Everything
is synthetic; nothing external is contacted and no model is loaded.
"""

import hashlib
import json
import tempfile
from pathlib import Path

from backend.contracts.assessment import EvidenceCitation
from backend.contracts.chat import ChatChoice, ChatPart, ChatTask, ChatTurn, ChatView
from backend.contracts.conversation import ConversationEvidence
from backend.contracts.web_journey import JourneyApprove, JourneyView
from backend.settings import Settings
from backend.web_journey import new_journey
from backend.web_plan import approve
from backend.web_run import run_journey
from backend.web_store import JourneyStore
from verification.web_fixture import launch

HERE = Path(__file__).resolve().parent
LIMITS = (
    "Each answer stops at 320 tokens (roughly 240 words) and 300 seconds. "
    "One model on this computer answers one message at a time."
)


def chat() -> dict[str, object]:
    quote = "200"
    evidence = ConversationEvidence(
        reference_id="R001",
        label="E014 · response.status · rustam",
        quote=quote,
        observation=EvidenceCitation(
            artifact_id="E014",
            field="response.status",
            sha256=hashlib.sha256(quote.encode()).hexdigest(),
        ),
    )
    turns = [
        ChatTurn(
            prompt="What is SQL injection?",
            intent="general_question",
            intent_rung="model",
            interpretation="I read this as a general question.",
            parts=[
                ChatPart(
                    kind="general",
                    text="SQL injection is a way of changing a database query by putting query "
                    "text into a value the application did not expect to be code. It works when "
                    "the application builds the query by joining strings.",
                    basis="General answer from the local model. No website, code or saved "
                    "result was looked at, and this is not a finding.",
                )
            ],
            limits=LIMITS,
            model_requests=2,
            model_seconds=41.5,
        ),
        ChatTurn(
            prompt="Test https://shop.example.com",
            intent="test_website",
            intent_rung="model",
            interpretation="I read this as a request to test a website.",
            parts=[
                ChatPart(
                    kind="notice",
                    text="Set up a bounded test of https://shop.example.com. Nothing is visited "
                    "until you approve its plan.",
                    basis="A proposal only. A message cannot start, approve or widen a test.",
                )
            ],
            task=ChatTask(
                kind="website_setup",
                summary="Set up a bounded test of https://shop.example.com. Nothing is visited "
                "until you approve its plan.",
                ready=False,
                missing=[
                    "The exact addresses and paths that are approved.",
                    "Who authorized the test and why it is being done.",
                ],
                steps=["You confirm the exact scope and accounts.", "I show one bounded plan."],
                url="https://shop.example.com",
            ),
            limits=LIMITS,
            model_requests=1,
            model_seconds=12.0,
        ),
        ChatTurn(
            prompt="What is broken access control, and what does this test show about it?",
            intent="general_and_result",
            intent_rung="model_reordered",
            interpretation="I read this as a general question plus a question about the "
            "selected result.",
            parts=[
                ChatPart(
                    kind="general",
                    text="Broken access control means an application lets someone do or see "
                    "something its own rules reserve for someone else.",
                    basis="General answer from the local model. No website, code or saved "
                    "result was looked at, and this is not a finding.",
                ),
                ChatPart(
                    kind="cited",
                    text="This website test is done. Lead (not confirmed): the account rustam "
                    "asked for /api/parcels/4117/label and received it. [R001]",
                    basis="Read from the saved journey record by code; each reference is an "
                    "exact saved value.",
                    evidence=[evidence],
                ),
            ],
            limits=LIMITS,
            model_requests=3,
            model_seconds=58.0,
        ),
        ChatTurn(
            prompt="hmm",
            intent="unclear",
            intent_rung="user",
            interpretation="I could not tell what this message asks for.",
            parts=[
                ChatPart(
                    kind="notice",
                    text="I could not tell what this message asks for. Please pick one, or say "
                    "it another way.",
                    basis="No answer was written and nothing was run.",
                )
            ],
            choices=[
                ChatChoice(intent="general_question", label="Answer a general question"),
                ChatChoice(intent="test_website", label="Test an approved website"),
            ],
            limits=LIMITS,
            model_requests=2,
            model_seconds=20.0,
        ),
    ]
    view = ChatView(
        chat_id="chat-" + "c" * 32,
        state="completed",
        target_kind="website",
        target_id="journey-" + "a" * 32,
        target_label="Website test of Chorsu Parcel Lockers (http://127.0.0.1:8711)",
        turns=turns,
        message="Answered. Nothing was run or approved by this message.",
        limits=LIMITS,
    )
    return view.model_dump(mode="json")


def websites() -> dict[str, object]:
    from backend.settings import Settings as Real

    real = Real()
    settings = Settings(data_dir=Path(tempfile.mkdtemp(prefix="plumb-fixtures-")))
    import backend.setup.browser as browser

    browser.directory = lambda _: real.data_dir / "browsers"  # ty: ignore[invalid-assignment]
    with launch("open", settings) as fixture:
        planned = new_journey(settings, fixture.scope())
        approved = approve(
            planned,
            JourneyApprove(
                plan_sha256=planned.plan_sha256, approved_by="Fixture reviewer", reviewed_plan=True
            ),
        )
        JourneyStore(settings).save(approved)
        waiting, _ = run_journey(
            settings, approved.journey_id, secrets=fixture.secrets, fixture=fixture, use_model=False
        )
        done, _ = run_journey(
            settings,
            approved.journey_id,
            secrets=fixture.secrets,
            fixture=fixture,
            use_model=False,
            answers={question.subject: "display_name" for question in waiting.waiting},
        )
    if (planned.status, waiting.status, done.status) != ("planned", "paused", "done"):
        raise RuntimeError(f"unexpected statuses: {planned.status}/{waiting.status}/{done.status}")

    def portable(view: JourneyView) -> dict[str, object]:
        value = json.loads(view.model_dump_json())
        value["report_path"] = None if value["report_path"] is None else "report.md"
        return value

    return {
        "provenance": "One real journey on the owned practice website with the pinned browser "
        "and no model; synthetic accounts and data only.",
        "planned": portable(planned),
        "waiting": portable(waiting),
        "done": portable(done),
    }


def main() -> None:
    (HERE / "chat-views.json").write_text(
        json.dumps({"view": chat()}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (HERE / "website-views.json").write_text(
        json.dumps(websites(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print("wrote chat-views.json and website-views.json")


if __name__ == "__main__":
    main()
