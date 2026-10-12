"""Which closed question types the installed local model can answer (ADR-0028, item 6).

A question type is relied on only after it was measured here. Each case is one
labelled decision point from owned synthetic material; some have "cannot tell"
as their right answer. The expected answer is for the evaluator only and never
enters a request.

    uv run --locked python -m eval.capability_map prepare --output <new-file>
    uv run --locked python -m eval.capability_map check <preparation.json>
    uv run --locked python -m eval.capability_map run <preparation.json> --output <new-file>
    uv run --locked python -m eval.capability_map account <preparation.json> <execution.json> \\
        --output <new-file>

``prepare`` and ``check`` load nothing. ``run`` loads the already installed
model once under the unchanged memory and first-use gates, asks every prepared
request once, and stops at its declared request or time budget or at the first
resource stop. A saved execution is replay, never fresh evidence.
"""

import argparse
import hashlib
import json
import statistics
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.asking import EvaluationAsker, explain
from agent.closed import (
    CANNOT_TELL,
    ClosedQuestion,
    Fact,
    MenuItem,
    attempt,
)
from agent.intent import intent_question, named
from agent.llm import (
    BudgetStop,
    ModelError,
    ModelTimeout,
    ModelUnavailable,
    PreflightRefused,
    RequestRejected,
)
from agent.web_questions import (
    field_question,
    form_question,
    page_question,
    rule_question,
    step_question,
)
from backend.contracts.web import ObservedField, ObservedForm, ObservedLink, PageObservation
from backend.jobs import WorkerLock
from backend.local_model import ModelNotReady, local_model
from backend.model_qualification import layer_identity, publish
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins

ROOT = Path(__file__).resolve().parents[1]
HYPOTHESIS = (
    "Asked one closed question at a time, with facts as short labelled lines and a single "
    "answer slot limited to the allowed values, the installed 2B model answers most decision "
    "points of each question type correctly within seconds, and abstains with the fixed "
    "label where the right answer is that it cannot tell."
)
MAX_REQUESTS = 70
MAX_SECONDS = 2700
QUESTION_SECONDS = 120.0
STOP = (
    "Stop at the first resource stop (budget, timeout, server unavailable, refused request or "
    "memory gate), at the request budget or at the time budget. No request is repeated."
)
KEEP = (
    "A type is kept when at least 80% of its cases are correct and none is a wrong accepted "
    "answer on a 'cannot tell' case."
)
_RESOURCE = (BudgetStop, ModelTimeout, ModelUnavailable, PreflightRefused, RequestRejected)
_AT = datetime(2026, 10, 12, tzinfo=UTC)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def identity() -> dict[str, str]:
    """The request layer, the question types and this driver, pinned by hash."""
    return {
        **layer_identity(),
        "eval/capability_map.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


# --- labelled decision points -------------------------------------------------------------------


def _field(label: str, name: str, kind: str = "text") -> ObservedField:
    return ObservedField(ref="o00000000-f0-i0", name=name, label=label, input_type=kind)


def _form(
    heading: str, button: str, fields: list[tuple[str, str, str]], method: str = "POST"
) -> ObservedForm:
    return ObservedForm(
        ref="o00000000-f0",
        method=method,  # ty: ignore[invalid-argument-type]
        action_path="/act",
        in_scope=True,
        heading=heading,
        submit_label=button,
        fields=[
            ObservedField(ref=f"o00000000-f0-i{index}", name=name, label=label, input_type=kind)
            for index, (label, name, kind) in enumerate(fields)
        ],
    )


def _page(
    title: str,
    text: str,
    *,
    headings: list[str] | None = None,
    forms: list[ObservedForm] | None = None,
    links: int = 4,
    account: str | None = None,
    status: int = 200,
) -> PageObservation:
    return PageObservation(
        observation_id="o00000000",
        via="browser",
        account_id=account,
        origin="http://127.0.0.1:8711",
        path="/page",
        status=status,
        title=title,
        headings=headings or [],
        text=text,
        links=[
            ObservedLink(ref=f"o00000000-l{index}", text=f"Link {index}", path="/x", in_scope=True)
            for index in range(links)
        ],
        forms=forms or [],
        collected_at=_AT,
    )


def _intent(message: str, selected: str | None = None) -> ClosedQuestion:
    return intent_question(message, named(message), selected=selected, previous=None)


def _field_case(label: str, name: str, heading: str, button: str) -> ClosedQuestion:
    form = _form(heading, button, [(label, name, "text"), ("Other field", "other", "text")])
    return field_question(form.fields[0], form, _page(heading, heading))


def _rule(
    statement: str,
    kind: str,
    owner: str,
    account: str,
    *,
    allowed: bool,
    outcome: str = "status 200; the object was returned",
    gaps: frozenset[str] = frozenset(),
) -> ClosedQuestion:
    return rule_question(
        statement=statement,
        object_kind=kind,
        owner=owner,
        account=account,
        account_is_owner=owner == account,
        declared_allowed=allowed,
        request=f"GET /api/items/31 as {account}",
        outcome=outcome,
        control="status 200; the object was returned",
        gaps=gaps,
    )


def _steps(purpose: str, items: list[tuple[str, str]]) -> ClosedQuestion:
    return step_question(purpose, [MenuItem(key, text) for key, text in items])


_SIGN_IN = [("Email or phone", "ident", "text"), ("Password", "pw", "password")]
_JOIN = [("Your name", "n", "text"), ("Pick a login", "l", "text"), ("Password", "pw", "password")]


def cases() -> list[tuple[str, ClosedQuestion, str]]:
    """``(case id, question, expected answer)``. Expected answers never enter a request."""
    review = "Review 1a2b3c4d"
    rows: list[tuple[str, ClosedQuestion, str]] = [
        # What a message asks for.
        ("intent-general", _intent("What is SQL injection?"), "general_question"),
        ("intent-general-uzbek", _intent("SQL inyeksiya nima?"), "general_question"),
        ("intent-creative", _intent("Write a short poem about autumn"), "creative_writing"),
        ("intent-explain", _intent("Explain that result", review), "explain_result"),
        (
            "intent-mixed",
            _intent("What is broken access control, and does my review show it?", review),
            "general_and_result",
        ),
        ("intent-folder", _intent("Review my folder"), "review_folder"),
        ("intent-website", _intent("Test this approved website"), "test_website"),
        ("intent-about", _intent("What can you do?"), "about_plumb"),
        ("intent-unclear", _intent("hmm"), f"{CANNOT_TELL}:unclear_request"),
        (
            "intent-several",
            _intent("Review my folder, write me a poem and then test my website"),
            f"{CANNOT_TELL}:several_requests",
        ),
        # What a form field means, where type and standard attributes do not say.
        (
            "field-name",
            _field_case("Your name", "name", "Create account", "Create account"),
            "display_name",
        ),
        (
            "field-username",
            _field_case("Choose a login", "handle", "Create account", "Join"),
            "username",
        ),
        ("field-email", _field_case("Work email", "contact1", "Create account", "Join"), "email"),
        ("field-phone", _field_case("Mobile number", "msisdn", "Your details", "Save"), "phone"),
        (
            "field-code",
            _field_case(
                "Code from your authenticator app", "token2", "Confirm it is you", "Verify"
            ),
            "one_time_code",
        ),
        ("field-search", _field_case("Find a parcel", "term", "Parcels", "Find"), "search_text"),
        ("field-other", _field_case("Delivery notes", "notes", "Delivery", "Save"), "other"),
        ("field-unclear", _field_case("", "f1", "", "OK"), f"{CANNOT_TELL}:label_unclear"),
        # What submitting a form does.
        (
            "form-sign-in",
            form_question(
                _form("Welcome back", "Continue", _SIGN_IN), _page("Welcome back", "Welcome back")
            ),
            "sign_in",
        ),
        (
            "form-sign-up",
            form_question(_form("Create account", "Create account", _JOIN), _page("Join", "Join")),
            "sign_up",
        ),
        (
            "form-create",
            form_question(
                _form(
                    "Add a parcel", "Save", [("Locker", "locker", "text"), ("Size", "size", "text")]
                ),
                _page("Add a parcel", "Add a parcel"),
            ),
            "create",
        ),
        (
            "form-update",
            form_question(
                _form("Edit delivery address", "Update", [("Street", "street", "text")]),
                _page("Edit address", "Edit delivery address"),
            ),
            "update",
        ),
        (
            "form-delete",
            form_question(
                _form("Cancel this pickup", "Yes, cancel it", [("Reason", "reason", "text")]),
                _page("Cancel pickup", "Cancel this pickup"),
            ),
            "delete",
        ),
        (
            "form-message",
            form_question(
                _form("Contact the locker team", "Send", [("Message", "body", "textarea")]),
                _page("Contact", "Contact the locker team"),
            ),
            "send_message",
        ),
        (
            "form-unclear",
            form_question(_form("", "OK", [("", "f1", "text")]), _page("", "")),
            f"{CANNOT_TELL}:purpose_unclear",
        ),
        # What kind of page this is.
        (
            "page-listing",
            page_question(
                _page(
                    "My parcels",
                    "My parcels Parcel 4117 at Chorsu A-12 (ready) Parcel 4118 at Chorsu B-02 "
                    "(ready) Parcel 4119 at Chorsu C-07 (in transit)",
                    headings=["My parcels"],
                    links=7,
                    account="dilnoza",
                )
            ),
            "listing",
        ),
        (
            "page-detail",
            page_question(
                _page(
                    "Parcel 4117",
                    "Parcel 4117 Locker: Chorsu A-12 Pickup label: shown below Status: ready",
                    headings=["Parcel 4117"],
                    account="dilnoza",
                )
            ),
            "detail",
        ),
        (
            "page-information",
            page_question(
                _page(
                    "Help",
                    "Help Lockers are open from 08:00 to 22:00. Find a locker on the partner map.",
                    headings=["Help"],
                )
            ),
            "information",
        ),
        (
            "page-error-with-200",
            page_question(
                _page("Oops", "Page not found. The page you asked for does not exist.", links=1)
            ),
            "error",
        ),
        (
            "page-sign-in",
            page_question(
                _page(
                    "Welcome back",
                    "Welcome back Email or phone Password Continue",
                    forms=[_form("Welcome back", "Continue", _SIGN_IN)],
                )
            ),
            "sign_in",
        ),
        (
            "page-sign-up",
            page_question(
                _page(
                    "Join",
                    "Create account Your name Pick a login Password Create account",
                    forms=[_form("Create account", "Create account", _JOIN)],
                )
            ),
            "sign_up",
        ),
        (
            "page-empty",
            page_question(_page("", "Loading", links=0)),
            f"{CANNOT_TELL}:too_little_shown",
        ),
        # Which of several equally valid steps serves the purpose best (a finite planning choice).
        (
            "step-label",
            _steps(
                "Check who can read a parcel's pickup label.",
                [
                    ("list", "List the signed-in account's own parcels"),
                    ("label", "Read the pickup label of parcel 4117 as another account"),
                    ("help", "Open the help page signed out"),
                ],
            ),
            "label",
        ),
        (
            "step-invoice",
            _steps(
                "Check whether one customer can read another customer's invoice.",
                [
                    ("profile", "Read the profile page as its own account"),
                    ("help", "Open the help page signed out"),
                    ("invoice", "Read invoice 12 as an account that does not own it"),
                ],
            ),
            "invoice",
        ),
        (
            "step-address",
            _steps(
                "Check who can see a delivery address.",
                [
                    ("address", "Read the delivery address of order 31 as another account"),
                    ("label", "Read the pickup label of parcel 4117 as another account"),
                    ("list", "List the signed-in account's own parcels"),
                ],
            ),
            "address",
        ),
        (
            "step-none",
            _steps(
                "Check that prices are shown in the right currency.",
                [
                    ("label", "Read the pickup label of parcel 4117 as another account"),
                    ("parcel", "Read parcel 4117 as another account"),
                ],
            ),
            f"{CANNOT_TELL}:no_item_fits",
        ),
        # Whether the owner's written rule covers this request and account.
        (
            "rule-forbidden",
            _rule(
                "Only the customer a parcel belongs to may read its pickup label.",
                "pickup label of parcel 4117",
                "dilnoza",
                "rustam",
                allowed=False,
            ),
            "forbidden",
        ),
        (
            "rule-forbidden-other-names",
            _rule(
                "Receipts are visible only to the customer who placed the order.",
                "receipt of order 31",
                "malika",
                "timur",
                allowed=False,
            ),
            "forbidden",
        ),
        (
            "rule-allowed-owner",
            _rule(
                "Only the customer a parcel belongs to may read its pickup label.",
                "pickup label of parcel 4117",
                "dilnoza",
                "dilnoza",
                allowed=True,
            ),
            "allowed",
        ),
        (
            "rule-allowed-everyone",
            _rule(
                "Any signed-in customer may read the public list of lockers.",
                "public list of lockers",
                "the service",
                "rustam",
                allowed=True,
            ),
            "allowed",
        ),
        (
            "rule-other-subject",
            _rule(
                "Only the customer a parcel belongs to may read its pickup label.",
                "opening hours of locker Chorsu A-12",
                "the service",
                "rustam",
                allowed=True,
            ),
            "not_about_this",
        ),
        (
            "rule-unclear",
            _rule(
                "Customers should be treated fairly.",
                "pickup label of parcel 4117",
                "dilnoza",
                "rustam",
                allowed=False,
            ),
            f"{CANNOT_TELL}:rule_unclear",
        ),
        (
            "rule-evidence-missing",
            _rule(
                "Only the customer a parcel belongs to may read its pickup label.",
                "pickup label of parcel 4117",
                "dilnoza",
                "rustam",
                allowed=False,
                outcome="not observed: the request was never sent",
                gaps=frozenset({"evidence_missing"}),
            ),
            f"{CANNOT_TELL}:evidence_missing",
        ),
    ]
    return rows


EXPLANATIONS = [
    (
        "explain-label",
        "rustam received an object that the owner's rule reserves for dilnoza.",
        (
            Fact(
                "owner's rule", "Only the customer a parcel belongs to may read its pickup label."
            ),
            Fact("object", "pickup label of parcel 4117"),
            Fact("object belongs to", "dilnoza"),
            Fact("requesting account", "rustam"),
            Fact("address", "/api/parcels/4117/label"),
            Fact("status for the requesting account", "200"),
            Fact("status for the owner", "200"),
        ),
        "The account rustam asked for /api/parcels/4117/label and received the pickup label "
        "of parcel 4117, which belongs to dilnoza.",
        ["dilnoza", "rustam", "newcomer"],
    ),
    (
        "explain-receipt",
        "timur received an object that the owner's rule reserves for malika.",
        (
            Fact("owner's rule", "Receipts are visible only to the customer who placed the order."),
            Fact("object", "receipt of order 31"),
            Fact("object belongs to", "malika"),
            Fact("requesting account", "timur"),
            Fact("address", "/api/orders/31/receipt"),
            Fact("status for the requesting account", "200"),
            Fact("status for the owner", "200"),
        ),
        "The account timur asked for /api/orders/31/receipt and received the receipt of order "
        "31, which belongs to malika.",
        ["malika", "timur"],
    ),
]
TEXTS = [
    ("chat-ordinary", "general_answer", "What is SQL injection?"),
    ("chat-creative", "creative_answer", "Write a short poem about autumn."),
]


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _pins(settings: Settings, profile: str) -> dict[str, Any]:
    from backend.profiles import REGISTRY, doctor

    chosen = profile if profile != "auto" else doctor(settings)["selected_profile"]
    if chosen not in REGISTRY:
        raise ValueError("No profile is available on this computer; run plumb doctor")
    selected = REGISTRY[chosen]
    return {
        "profile": selected.identity(),
        "model": load_model_pins().get(selected.model_id).model_dump(mode="json"),
        "llama_cpp": {
            key: value
            for key, value in load_llama_cpp_pin().model_dump(mode="json").items()
            if key != "variants"
        },
    }


def prepare(
    settings: Settings,
    output: Path,
    *,
    profile: str = "auto",
    question_types: tuple[str, ...] | None = None,
    max_requests: int = MAX_REQUESTS,
    max_seconds: int = MAX_SECONDS,
) -> dict[str, Any]:
    """Freeze the requests, pins, budgets and stop rule. Loads nothing."""
    all_cases = cases()
    known = {question.kind.name for _, question, _ in all_cases}
    selected = set(question_types) if question_types is not None else known
    if not selected or not selected <= known:
        raise ValueError("Choose existing question types; a type's complete case set is required")
    if not 1 <= max_requests <= MAX_REQUESTS or not 1 <= max_seconds <= MAX_SECONDS:
        raise ValueError("Request/time budgets must be positive and within the declared ceilings")
    chosen_cases = [row for row in all_cases if row[1].kind.name in selected]
    prepared = []
    for case_id, question, _ in chosen_cases:
        request = question.request(0)
        prepared.append(
            {
                "case_id": case_id,
                "question_type": question.kind.name,
                "system": request.system,
                "user": request.user,
                "allowed": question.allowed(0),
                "seed": request.seed,
                "request_sha256": _hash([request.system, request.user, request.schema]),
            }
        )
    expected = {case_id: answer for case_id, _, answer in chosen_cases}
    value = {
        "kind": "capability_map_preparation",
        "created": datetime.now(UTC).isoformat(),
        "hypothesis": HYPOTHESIS,
        "keep_rule": KEEP,
        "stop_condition": STOP,
        "max_requests": max_requests,
        "max_seconds": max_seconds,
        "question_seconds": QUESTION_SECONDS,
        "pins": _pins(settings, profile),
        "implementation": identity(),
        "closed_cases": prepared,
        "explanations": [row[0] for row in EXPLANATIONS] if question_types is None else [],
        "texts": [row[0] for row in TEXTS] if question_types is None else [],
        # Kept apart from the requests: for scoring only.
        "evaluator_only_expected_sha256": _hash(expected),
        "evaluator_only_expected": expected,
        "model_loaded": False,
    }
    _write_new(output, value)
    return value


def check(settings: Settings, preparation: Path) -> dict[str, Any]:
    """The saved preparation still matches this code and these pins. Loads nothing."""
    value = json.loads(preparation.read_bytes())
    if value.get("kind") != "capability_map_preparation":
        raise ValueError("Not a capability map preparation")
    if value["implementation"] != identity():
        raise ValueError("The request layer changed after this preparation; prepare again")
    current = {case_id: (question, expected) for case_id, question, expected in cases()}
    selected = {row["question_type"] for row in value["closed_cases"]}
    wanted = {
        case_id for case_id, (question, _) in current.items() if question.kind.name in selected
    }
    saved = [row["case_id"] for row in value["closed_cases"]]
    if not saved or len(saved) != len(set(saved)) or set(saved) != wanted:
        raise ValueError("Each selected type must retain its complete, distinct case set")
    if (
        not 1 <= value["max_requests"] <= MAX_REQUESTS
        or not 1 <= value["max_seconds"] <= MAX_SECONDS
    ):
        raise ValueError("Prepared request/time budgets exceed the declared ceilings")
    if value["question_seconds"] != QUESTION_SECONDS or value["keep_rule"] != KEEP:
        raise ValueError("The question budget or keep rule changed")
    for row in value["closed_cases"]:
        question, _ = current[row["case_id"]]
        if row["question_type"] != question.kind.name:
            raise ValueError("A prepared case has the wrong question type")
        request = question.request(0)
        if row["request_sha256"] != _hash([request.system, request.user, request.schema]):
            raise ValueError(f"Case {row['case_id']} differs from its prepared request")
        if "expected" in row:
            raise ValueError("An evaluator label is stored with a request")
    if value["evaluator_only_expected_sha256"] != _hash(value["evaluator_only_expected"]) or value[
        "evaluator_only_expected"
    ] != {case_id: current[case_id][1] for case_id in saved}:
        raise ValueError("The evaluator labels changed")
    if value["pins"] != _pins(settings, value["pins"]["profile"]["id"]):
        raise ValueError("Model, runtime or profile pins changed; prepare again")
    return value


def run(settings: Settings, preparation: Path, output: Path) -> dict[str, Any]:
    """One bounded real-model session over the prepared requests. No request is repeated."""
    from eval.bench.machine import machine_state

    prepared = check(settings, preparation)
    accounting_path = output.with_name(output.stem + ".accounting.json")
    if output.exists() or accounting_path.exists():
        raise ValueError("The output file already exists")
    questions = {case_id: question for case_id, question, _ in cases()}
    cancel = threading.Event()
    manifest: dict[str, Any] = {}
    started = time.perf_counter()
    deadline = started + prepared["max_seconds"]
    rows: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    stop: str | None = None
    loaded = None
    result: dict[str, Any] = {
        "kind": "capability_map_execution",
        "preparation_sha256": hashlib.sha256(preparation.read_bytes()).hexdigest(),
        "started": datetime.now(UTC).isoformat(),
        "machine_start": machine_state(),
        "model_loaded": False,
    }
    try:
        with (
            WorkerLock(settings.cache_dir / "review.lock"),
            local_model(
                settings,
                "capability-map",
                prepared["pins"]["profile"]["id"],
                cancel=cancel,
                deadline=lambda: deadline,
                manifest=manifest,
            ) as loaded,
        ):
            result["model_loaded"] = True
            asker = EvaluationAsker(
                loaded.adapter,
                profile=loaded.profile.id,
                seconds_per_question=prepared["question_seconds"],
            )
            for row in prepared["closed_cases"]:
                if len(rows) + len(texts) >= prepared["max_requests"]:
                    stop = "request budget"
                    break
                if time.perf_counter() >= deadline:
                    stop = "time budget"
                    break
                made = attempt(questions[row["case_id"]], asker, 0)
                rows.append(
                    {
                        "case_id": row["case_id"],
                        "question_type": row["question_type"],
                        **asdict(made),
                        "outcome": made.outcome,
                    }
                )
                print(f"  {row['case_id']}: {made.outcome} in {made.seconds:.1f} s", flush=True)
                if made.error in {kind.__name__ for kind in _RESOURCE}:
                    stop = "resource stop: " + made.error
                    break
            if stop is None:
                from agent.llm import TextRequest
                from backend.chat import CREATIVE_SYSTEM, GENERAL_MAX_TOKENS, GENERAL_SYSTEM

                for case_id, decision, facts, fallback, universe in EXPLANATIONS:
                    if case_id not in prepared["explanations"]:
                        continue
                    if (
                        len(rows) + len(texts) >= prepared["max_requests"]
                        or time.perf_counter() >= deadline
                    ):
                        stop = (
                            "request budget"
                            if len(rows) + len(texts) >= prepared["max_requests"]
                            else "time budget"
                        )
                        break
                    wording = explain(decision, facts, fallback, asker, universe=universe)
                    texts.append(
                        {"case_id": case_id, "question_type": "explanation", **asdict(wording)}
                    )
                    print(f"  {case_id}: wording by {wording.source}", flush=True)
                for case_id, name, prompt in TEXTS:
                    if stop is not None:
                        break
                    if case_id not in prepared["texts"]:
                        continue
                    if (
                        len(rows) + len(texts) >= prepared["max_requests"]
                        or time.perf_counter() >= deadline
                    ):
                        stop = (
                            "request budget"
                            if len(rows) + len(texts) >= prepared["max_requests"]
                            else "time budget"
                        )
                        break
                    request = TextRequest(
                        name=name,
                        system=CREATIVE_SYSTEM if name == "creative_answer" else GENERAL_SYSTEM,
                        user=prompt,
                        max_tokens=GENERAL_MAX_TOKENS,
                    )
                    try:
                        answer = asker.text(name, request, max_prompt_tokens=1500)
                        texts.append(
                            {
                                "case_id": case_id,
                                "question_type": name,
                                "prompt": prompt,
                                **asdict(answer),
                            }
                        )
                        print(
                            f"  {case_id}: {answer.completion_tokens} tokens "
                            f"in {answer.seconds:.1f} s",
                            flush=True,
                        )
                    except ModelError as error:
                        texts.append(
                            {
                                "case_id": case_id,
                                "question_type": name,
                                "error": type(error).__name__,
                            }
                        )
                        stop = "resource stop: " + type(error).__name__
                        break
    except (ModelNotReady, OSError, RuntimeError, ValueError) as error:
        stop = f"not started: {error}"
    result.update(
        {
            "finished": datetime.now(UTC).isoformat(),
            "seconds": round(time.perf_counter() - started, 3),
            "stop": stop,
            "closed": rows,
            "texts": texts,
            "manifest": manifest,
            "machine_end": machine_state(),
            "unrun_cases": [
                row["case_id"]
                for row in prepared["closed_cases"]
                if row["case_id"] not in {item["case_id"] for item in rows}
            ],
        }
    )
    _write_new(output, result)
    # The replay command only scores. Promotion belongs to this live invocation,
    # after the owned runtime has stopped, and still requires its runtime witness.
    accounting = account(preparation, output, accounting_path)
    qualification = publish(
        settings,
        loaded,
        prepared,
        result,
        accounting,
        {question.kind.name: question.kind for question in questions.values()},
    )
    result["qualification"] = str(qualification) if qualification else None
    result["accounting"] = str(accounting_path)
    return result


def account(preparation: Path, execution: Path, output: Path) -> dict[str, Any]:
    """Score a saved execution per question type. Launches nothing."""
    prepared = json.loads(preparation.read_bytes())
    executed = json.loads(execution.read_bytes())
    if executed["preparation_sha256"] != hashlib.sha256(preparation.read_bytes()).hexdigest():
        raise ValueError("This execution belongs to another preparation")
    expected = prepared["evaluator_only_expected"]
    types: dict[str, dict[str, Any]] = {}
    for row in executed["closed"]:
        kind = types.setdefault(
            row["question_type"],
            {"asked": 0, "answered": 0, "correct": 0, "abstained": 0, "refused": 0, "failed": 0,
             "wrong_on_cannot_tell": 0, "seconds": [], "prompt_ms": [], "predicted_ms": [],
             "prompt_tokens": [], "completion_tokens": [], "wrong": []},
        )  # fmt: skip
        want = expected[row["case_id"]]
        got = (
            row["value"]
            if row["value"] is not None
            else (f"{CANNOT_TELL}:{row['abstained']}" if row["abstained"] else None)
        )
        # A menu case is scored by the chosen item's key; the others by the label.
        kind["asked"] += 1
        kind[row["outcome"]] += 1
        if got == want:
            kind["correct"] += 1
        else:
            kind["wrong"].append({"case_id": row["case_id"], "expected": want, "got": got})
            if want.startswith(CANNOT_TELL) and row["outcome"] == "answered":
                kind["wrong_on_cannot_tell"] += 1
        if row["error"] is None:
            kind["seconds"].append(row["seconds"])
            kind["prompt_tokens"].append(row["prompt_tokens"])
            kind["completion_tokens"].append(row["completion_tokens"])
            for key in ("prompt_ms", "predicted_ms"):
                if row[key] is not None:
                    kind[key].append(row[key])
    summary = {}
    for name, kind in types.items():
        total = len([row for row in prepared["closed_cases"] if row["question_type"] == name])
        kept = (
            kind["asked"] == total
            and kind["correct"] >= 0.8 * total
            and kind["wrong_on_cannot_tell"] == 0
        )
        summary[name] = {
            "cases": total,
            "asked": kind["asked"],
            "answered": kind["answered"],
            "correct": kind["correct"],
            "abstained": kind["abstained"],
            "refused": kind["refused"],
            "failed": kind["failed"],
            "wrong_accepted_on_cannot_tell_cases": kind["wrong_on_cannot_tell"],
            "median_seconds": round(statistics.median(kind["seconds"]), 2)
            if kind["seconds"]
            else None,
            "median_prompt_ms": round(statistics.median(kind["prompt_ms"]), 1)
            if kind["prompt_ms"]
            else None,
            "median_generation_ms": round(statistics.median(kind["predicted_ms"]), 1)
            if kind["predicted_ms"]
            else None,
            "max_prompt_tokens": max(kind["prompt_tokens"], default=None),
            "max_completion_tokens": max(kind["completion_tokens"], default=None),
            "suggested_prompt_limit": (
                int(max(kind["prompt_tokens"]) * 1.25) + 16 if kind["prompt_tokens"] else None
            ),
            "kept": kept,
            "wrong": kind["wrong"],
        }
    value = {
        "kind": "capability_map_accounting",
        "preparation": preparation.name,
        "execution": execution.name,
        "fresh": False,
        "note": "Scored from the saved execution. Replay of saved answers, not a new run.",
        "session_seconds": executed["seconds"],
        "stop": executed["stop"],
        "unrun_cases": executed["unrun_cases"],
        "types": summary,
        "texts": [
            {
                key: row.get(key)
                for key in (
                    "case_id",
                    "question_type",
                    "source",
                    "reason",
                    "complete",
                    "prompt_tokens",
                    "completion_tokens",
                    "seconds",
                    "error",
                )
            }
            for row in executed["texts"]
        ],
    }
    _write_new(output, value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("prepare")
    one.add_argument("--output", type=Path, required=True)
    one.add_argument("--profile", default="auto")
    one.add_argument("--question-type", action="append", dest="question_types")
    one.add_argument("--max-requests", type=int, default=MAX_REQUESTS)
    one.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    two = commands.add_parser("check")
    two.add_argument("preparation", type=Path)
    three = commands.add_parser("run")
    three.add_argument("preparation", type=Path)
    three.add_argument("--output", type=Path, required=True)
    four = commands.add_parser("account")
    four.add_argument("preparation", type=Path)
    four.add_argument("execution", type=Path)
    four.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    try:
        if args.command == "prepare":
            value = prepare(
                settings,
                args.output,
                profile=args.profile,
                question_types=tuple(args.question_types) if args.question_types else None,
                max_requests=args.max_requests,
                max_seconds=args.max_seconds,
            )
            print(f"Prepared {len(value['closed_cases'])} closed cases; nothing was loaded.")
        elif args.command == "check":
            value = check(settings, args.preparation)
            print(f"{len(value['closed_cases'])} prepared cases match this code and these pins.")
        elif args.command == "run":
            value = run(settings, args.preparation, args.output)
            print(
                f"Asked {len(value['closed'])} closed and {len(value['texts'])} text requests in "
                f"{value['seconds']:.0f} s. Stop: {value['stop'] or 'completed'}."
            )
            return 0 if value["stop"] is None else 2
        else:
            value = account(args.preparation, args.execution, args.output)
            for name, row in value["types"].items():
                print(
                    f"{name}: asked {row['asked']}/{row['cases']}, correct {row['correct']}, "
                    f"abstained {row['abstained']}, refused {row['refused']}, "
                    f"median {row['median_seconds']} s, kept: {row['kept']}"
                )
    except (OSError, ValueError, KeyError) as error:
        print(f"Capability map stopped: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
