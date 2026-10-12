"""The closed questions a website journey may ask, each with its code rung (ADR-0028).

For every type the first function is the code rung: what the observation itself
decides. Only what is left goes to the model, as one closed question whose
answer is then checked against the same observation.

Nothing here reads a model answer for a status, an account, an object, a marker
or a citation: those are computed and attached by code.
"""

import re

from agent.closed import (
    ClosedQuestion,
    Decision,
    Fact,
    MenuItem,
    QuestionType,
    Reason,
    by_code,
    one_line,
)
from backend.contracts.web import ObservedField, ObservedForm, PageObservation

_PASSWORD = "password"  # noqa: S105 - the name of an input type

# --- what an observed field means -------------------------------------------------------------

FIELD_MEANING = QuestionType(
    name="field_meaning",
    adds="What a form field asks for when its type and standard attributes do not say.",
    ask="What does this form field ask the user to enter?",
    labels=(
        ("username", "the account's user name or login name"),
        ("email", "an email address"),
        ("password", "the account's password"),
        ("password_confirm", "the same password typed a second time"),
        ("display_name", "the person's own name as shown to others"),
        ("phone", "a phone number"),
        ("one_time_code", "a code sent by message or made by an authenticator app"),
        ("search_text", "words to search for"),
        ("other", "something else"),
    ),
    reasons=(Reason("label_unclear", "the label and name do not say what is wanted"),),
)
_HINTS = {
    "username": "username",
    "email": "email",
    "current-password": "password",
    "new-password": "password",
    "name": "display_name",
    "given-name": "display_name",
    "nickname": "display_name",
    "tel": "phone",
    "one-time-code": "one_time_code",
}
_NAMES = {
    "username": "username",
    "user": "username",
    "login": "username",
    "email": "email",
    "e-mail": "email",
    "mail": "email",
    "phone": "phone",
    "tel": "phone",
    "telephone": "phone",
    "otp": "one_time_code",
    "totp": "one_time_code",
    "q": "search_text",
    "search": "search_text",
    "query": "search_text",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", value.lower())


def field_by_code(field: ObservedField, form: ObservedForm) -> Decision | None:
    """Type, autocomplete and an exact conventional name decide; a free label does not."""
    passwords = [item for item in form.fields if item.input_type == _PASSWORD]
    if field.input_type == _PASSWORD:
        first = passwords[0].ref == field.ref
        return by_code(
            FIELD_MEANING,
            "password" if first else "password_confirm",
            "The field is a password input"
            + (", the first of the form." if first else ", after another one in the same form."),
        )
    if field.hint in _HINTS:
        return by_code(FIELD_MEANING, _HINTS[field.hint], "Its autocomplete attribute says so.")
    if field.input_type == "email":
        return by_code(FIELD_MEANING, "email", "The field is an email input.")
    if field.input_type == "tel":
        return by_code(FIELD_MEANING, "phone", "The field is a telephone input.")
    if field.input_type == "search":
        return by_code(FIELD_MEANING, "search_text", "The field is a search input.")
    if _norm(field.name) in _NAMES:
        return by_code(FIELD_MEANING, _NAMES[_norm(field.name)], "Its name is a conventional one.")
    return None


def field_question(
    field: ObservedField, form: ObservedForm, page: PageObservation
) -> ClosedQuestion:
    position = next(
        index for index, item in enumerate(form.fields, start=1) if item.ref == field.ref
    )

    def verify(label: str) -> str | None:
        if label in {"password", "password_confirm"}:
            return "A password field is a password input, and this one is not."
        if label == "email" and field.input_type not in {"text", "email"}:
            return "This input cannot hold an email address."
        return None

    return ClosedQuestion(
        kind=FIELD_MEANING,
        facts=(
            Fact("field label", one_line(field.label) or "(none)"),
            Fact("field name", one_line(field.name) or "(none)"),
            Fact("input type", field.input_type or "text"),
            Fact("position in form", f"{position} of {len(form.fields)}"),
            Fact("form heading", one_line(form.heading) or "(none)"),
            Fact("form button", one_line(form.submit_label) or "(none)"),
            Fact("page title", one_line(page.title) or "(none)"),
        ),
        verify=verify,
        user_question=f"What should be entered in the field “{field.label or field.name}”?",
    )


# --- what a form is for -----------------------------------------------------------------------

FORM_PURPOSE = QuestionType(
    name="form_purpose",
    adds="What submitting a form does, when its fields alone do not settle it.",
    ask="What does submitting this form do?",
    labels=(
        ("sign_in", "signs in to an existing account"),
        ("sign_up", "creates a new account"),
        ("search", "searches or filters and changes nothing"),
        ("create", "creates a new item"),
        ("update", "changes an existing item or setting"),
        ("delete", "deletes or cancels something"),
        ("send_message", "sends a message to someone"),
        ("other", "something else"),
    ),
    reasons=(Reason("purpose_unclear", "the form's wording does not say what it does"),),
)


def form_by_code(form: ObservedForm) -> Decision | None:
    hints = {item.hint for item in form.fields if item.input_type == _PASSWORD}
    passwords = sum(item.input_type == _PASSWORD for item in form.fields)
    if passwords >= 2:
        return by_code(FORM_PURPOSE, "sign_up", "The form asks for a password twice.")
    if passwords == 1 and hints == {"new-password"}:
        return by_code(FORM_PURPOSE, "sign_up", "Its password field is marked as a new password.")
    if passwords == 1 and hints == {"current-password"}:
        return by_code(
            FORM_PURPOSE, "sign_in", "Its password field is marked as the current password."
        )
    if form.method == "GET" and not passwords:
        return by_code(FORM_PURPOSE, "search", "The form only reads: it is sent with GET.")
    return None


def form_question(form: ObservedForm, page: PageObservation) -> ClosedQuestion:
    passwords = sum(item.input_type == _PASSWORD for item in form.fields)

    def verify(label: str) -> str | None:
        if label in {"sign_in", "sign_up"} and passwords == 0:
            return "A sign-in or sign-up form has a password field, and this one has none."
        if label == "search" and form.method == "POST" and passwords:
            return "A search form does not ask for a password."
        return None

    fields = ", ".join(
        f"{item.label or item.name or 'unnamed'} ({item.input_type})"
        for item in form.fields
        if item.input_type != "hidden"
    )
    return ClosedQuestion(
        kind=FORM_PURPOSE,
        facts=(
            Fact("form heading", one_line(form.heading) or "(none)"),
            Fact("form button", one_line(form.submit_label) or "(none)"),
            Fact("fields", one_line(fields) or "(none)"),
            Fact("password fields", str(passwords)),
            Fact("sent with", form.method),
            Fact("sent to", one_line(form.action_path) or "(same page)"),
            Fact("page title", one_line(page.title) or "(none)"),
        ),
        verify=verify,
        user_question=f"What does the form “{form.heading or form.submit_label}” do?",
    )


# --- what kind of page this is ----------------------------------------------------------------

PAGE_KIND = QuestionType(
    name="page_kind",
    adds="What a page is for, read from its wording, when its structure does not settle it.",
    ask="What kind of page is this?",
    labels=(
        ("sign_in", "asks the visitor to sign in"),
        ("sign_up", "asks the visitor to create an account"),
        ("account_area", "shows a signed-in person their own things"),
        ("listing", "lists several items of the same kind"),
        ("detail", "shows one item in detail"),
        ("information", "general information, help or a landing page"),
        ("error", "says that something went wrong or was not found"),
    ),
    reasons=(Reason("too_little_shown", "the page shows too little to tell"),),
)


def page_by_code(page: PageObservation) -> Decision | None:
    if page.status is not None and page.status >= 400:
        return by_code(PAGE_KIND, "error", f"The page answered with status {page.status}.")
    purposes = {decision.value for form in page.forms if (decision := form_by_code(form))}
    if "sign_up" in purposes and "sign_in" not in purposes:
        return by_code(PAGE_KIND, "sign_up", "Its only account form asks for a password twice.")
    if purposes == {"sign_in"} and len(page.forms) == 1:
        return by_code(PAGE_KIND, "sign_in", "Its only form is a sign-in form.")
    return None


def page_question(page: PageObservation) -> ClosedQuestion:
    passwords = sum(item.input_type == _PASSWORD for form in page.forms for item in form.fields)

    def verify(label: str) -> str | None:
        if label in {"sign_in", "sign_up"} and passwords == 0:
            return "A sign-in or sign-up page has a password field, and this page has none."
        return None

    return ClosedQuestion(
        kind=PAGE_KIND,
        facts=(
            Fact("page title", one_line(page.title) or "(none)"),
            Fact("headings", one_line("; ".join(page.headings[:4])) or "(none)"),
            Fact("visible text", one_line(page.text) or "(none)"),
            Fact("forms", str(len(page.forms))),
            Fact("password fields", str(passwords)),
            Fact("links", str(len(page.links))),
            Fact("signed in as", page.account_id or "nobody"),
        ),
        gaps=frozenset(),
        verify=verify,
        user_question=f"What kind of page is “{page.title or page.path}”?",
    )


# --- which of several equally valid steps comes first -------------------------------------------

NEXT_STEP = QuestionType(
    name="next_step",
    adds="Which of several equally valid checks serves the stated purpose best.",
    ask="Which step serves the stated purpose best?",
    labels=(),
    reasons=(Reason("no_item_fits", "none of the steps serves the stated purpose"),),
    menu=True,
)


def step_by_code(items: list[MenuItem], room: int) -> Decision | None:
    """One ready step, or room for all of them: there is nothing to choose."""
    ready = [item for item in items if item.ready]
    if not ready:
        return by_code(NEXT_STEP, "", "No step's prerequisites hold.")
    if len(ready) == 1:
        return by_code(NEXT_STEP, ready[0].key, "Only one step is ready.")
    if room >= len(ready):
        return by_code(
            NEXT_STEP, ready[0].key, "The budget covers every ready step; they run in plan order."
        )
    return None


def step_question(purpose: str, items: list[MenuItem]) -> ClosedQuestion:
    # No question for the user here: when the model cannot choose, the approved plan's own
    # order is the deterministic next step, and nothing waits.
    return ClosedQuestion(
        kind=NEXT_STEP,
        facts=(Fact("purpose of the test", one_line(purpose)),),
        menu=tuple(items[:6]),
    )


# --- whether the owner's written rule covers this request ----------------------------------------

RULE_COVERS = QuestionType(
    name="rule_covers",
    adds="Whether the owner's rule, read as a sentence, forbids this account this object.",
    ask="By the owner's written rule, may this account receive this object?",
    labels=(
        ("forbidden", "the rule says this account must not receive it"),
        ("allowed", "the rule says this account may receive it"),
        ("not_about_this", "the rule is about something else"),
    ),
    reasons=(
        Reason("rule_unclear", "the rule's wording does not settle it"),
        Reason("evidence_missing", "a fact needed to apply the rule is absent", checkable=True),
    ),
)


def rule_question(
    *,
    statement: str,
    object_kind: str,
    owner: str,
    account: str,
    account_is_owner: bool,
    declared_allowed: bool,
    request: str,
    outcome: str,
    control: str,
    gaps: frozenset[str] = frozenset(),
) -> ClosedQuestion:
    """One reading of the rule. Code already holds every observed fact and attaches them."""

    def verify(label: str) -> str | None:
        # The reviewer's own structured declaration is the reference a reading is held to.
        if label == "forbidden" and declared_allowed:
            return "The owner's declaration lists this account as allowed."
        if label == "allowed" and not declared_allowed:
            return "The owner's declaration does not list this account as allowed."
        return None

    return ClosedQuestion(
        kind=RULE_COVERS,
        facts=(
            Fact("owner's rule", one_line(statement)),
            Fact("object", one_line(object_kind)),
            Fact("object belongs to", owner),
            Fact("requesting account", account),
            Fact("requesting account owns the object", "yes" if account_is_owner else "no"),
            Fact("request", one_line(request)),
            Fact("what came back", one_line(outcome)),
            Fact("owner's own request", one_line(control)),
        ),
        gaps=gaps,
        verify=verify,
    )


ALL_TYPES = (FIELD_MEANING, FORM_PURPOSE, PAGE_KIND, NEXT_STEP, RULE_COVERS)
