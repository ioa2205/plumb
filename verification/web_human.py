"""Trusted human tools for one live, contained authentication context.

Only the protected UI sends pointer coordinates or private text. No model can
call this surface. Pointer events never receive a write grant; the separate
submit tool uses the runner's existing exact observed-form grant.
"""

import base64
from typing import TYPE_CHECKING
from uuid import uuid4

from agent.web_questions import field_by_code
from backend.contracts.web import ObservedField, ObservedForm, PlanStep, WebAccount
from backend.contracts.web_journey import HumanAuthInput, HumanAuthView
from verification.web_pages import PrivacyStop, personal_data

if TYPE_CHECKING:
    from verification.web_browser import BrowserRunner

# This script only finds the observed field a person clicked. It accepts no
# selector, code or page-generated instruction from the caller.
HIT_FIELD_JS = """([x, y]) => {
 const hit = document.elementFromPoint(x, y);
 const forms = Array.from(document.querySelectorAll('form')).slice(0, 12);
 for (let f = 0; f < forms.length; f++) {
   const fields = Array.from(forms[f].querySelectorAll('input, select, textarea')).filter(
     e => !['submit', 'button', 'image', 'reset'].includes(
       (e.getAttribute('type') || '').toLowerCase())
   ).slice(0, 40);
   const i = fields.indexOf(hit);
   if (i >= 0) return [f, i];
 }
 return null;
}"""


class HumanBrowser:
    def __init__(
        self, runner: "BrowserRunner", step: PlanStep, account: WebAccount, *, before_write: bool
    ) -> None:
        self.runner, self.step, self.account = runner, step, account
        self.before_write = before_write
        self.focused: tuple[int, int] | None = None
        self.focused_signature: tuple[str, str, str, str] | None = None
        self.typed: dict[tuple[str, str, str, str], str] = {}
        self.submitted = False

    @staticmethod
    def signature(form: ObservedForm, field: ObservedField) -> tuple[str, str, str, str]:
        return form.method, form.action_path, field.name, field.input_type

    @staticmethod
    def meaning(form: ObservedForm, field: ObservedField) -> str | None:
        decision = field_by_code(field, form)
        if decision is not None:
            return decision.value
        if field.name.lower() in {"code", "verification_code"}:
            return "one_time_code"
        if field.name.lower() in {"captcha", "captcha_answer", "captcha_text"}:
            return "captcha"
        return None

    def expected(self, form: ObservedForm, field: ObservedField) -> str:
        meaning = self.meaning(form, field)
        account = self.account
        fixed = {
            "username": account.username,
            "email": account.contact_email
            or (account.username if "@" in account.username else None),
            "display_name": account.label.split("(")[0].strip(),
            "phone": account.contact_phone,
        }
        if meaning in fixed and fixed[meaning] is not None:
            return str(fixed[meaning])
        if meaning in {"password", "password_confirm"}:
            return self.runner.secrets.get(account.secret_ref)
        if meaning in {"one_time_code", "captcha"}:
            value = self.typed.get(self.signature(form, field))
            if value is not None:
                return value
        raise ValueError("This field has no approved account value or human challenge input.")

    def submission(self) -> str:
        if self.submitted:
            raise ValueError("A challenge submission is never repeated automatically.")
        current = self.runner._current.get(self.account.account_id)
        if current is None:
            raise ValueError("Refresh this account's challenge first.")
        forms = [
            form
            for form in current.bound.observation.forms
            if form.ref in current.bound.forms
            and (
                self.before_write
                or any(
                    (decision := field_by_code(field, form)) is not None
                    and decision.value == "one_time_code"
                    for field in form.fields
                )
            )
        ]
        if len(forms) != 1:
            raise ValueError(
                "There is no single approved challenge form to submit. "
                "The original sign-in or signup is not repeated."
            )
        form = forms[0]
        page, form_index, _ = self.runner._bound_form(self.account.account_id, form.ref)
        from verification.web_browser import FORM_VALUES_JS

        values = page.evaluate(FORM_VALUES_JS, form_index)
        if not isinstance(values, list):
            raise ValueError("The challenge form changed; refresh it.")
        for raw in values:
            index = raw.get("index")
            if not isinstance(index, int) or not 0 <= index < len(form.fields):
                continue  # a submit button is not an editable identity field
            field = form.fields[index]
            if raw.get("disabled") or (
                field.input_type == "hidden" and self.meaning(form, field) is None
            ):
                continue
            if raw.get("value") != self.expected(form, field):
                raise ValueError(
                    "A challenge field differs from the approved account or human input."
                )
        return form.ref

    def snapshot(self, challenge: str, note: str = "") -> HumanAuthView:
        runner, name = self.runner, self.account.account_id
        runner._own_thread()
        runner.observe(name)  # scope, privacy and fresh observed references
        page = runner._page(name)
        text = page.locator("body").inner_text(timeout=runner._timeout())
        if len(text) > 200_000:
            raise ValueError("The challenge page exceeds the private view limit.")
        if kinds := personal_data(text, runner.expected_personal):
            raise PrivacyStop(kinds)
        if any(
            secret and secret in text
            for secret in (
                *runner.secrets.values(),
                *runner.session(name).values(),
                *runner.redactor.secrets,
            )
        ):
            raise PrivacyStop(["credential echo"])
        image = page.screenshot(
            type="png",
            full_page=False,
            animations="disabled",
            mask=[page.locator("input, textarea, [contenteditable]")],
            timeout=runner._timeout(),
        )
        if len(image) > 3 * 1024 * 1024:
            raise ValueError("The challenge image exceeds the private view limit.")
        return HumanAuthView(
            view_id=uuid4().hex,
            step_id=self.step.step_id,
            account_id=name,
            label=self.account.label,
            challenge=challenge,  # ty: ignore[invalid-argument-type]
            question=(
                note
                or "Complete this account's challenge. Input values are hidden. "
                "Then explicitly ask Plumb to check sign-in."
            )[:300],
            screenshot_png=base64.b64encode(image).decode("ascii"),
        )

    def input(self, event: HumanAuthInput) -> None:
        runner, name = self.runner, self.account.account_id
        runner._own_thread()
        current = runner._current.get(name)
        location = runner.location(name)
        if current is None or location is None:
            raise ValueError("Refresh this account's challenge first.")
        if not runner.egress.in_scope(location):
            raise runner.egress.refuse(
                "off_scope", location.host, "The human view left its approved scope."
            )
        if current.url != location.url:
            raise ValueError("The challenge page moved; refresh it before acting.")
        page = runner._page(name)
        if event.kind == "pointer":
            hit = page.evaluate(HIT_FIELD_JS, [event.x, event.y])
            self.focused = tuple(hit) if isinstance(hit, list) and len(hit) == 2 else None
            self.focused_signature = None
            if self.focused is not None:
                f, i = self.focused
                if 0 <= f < len(current.bound.observation.forms):
                    form = current.bound.observation.forms[f]
                    if 0 <= i < len(form.fields):
                        self.focused_signature = self.signature(form, form.fields[i])
            page.mouse.click(event.x, event.y)
            runner._settle(page)
        elif event.kind == "text":
            if self.focused is None:
                raise ValueError("Select a text field in the private view before entering text.")
            form_index, field_index = self.focused
            try:
                form = current.bound.observation.forms[form_index]
                field = form.fields[field_index]
            except IndexError:
                raise ValueError("The selected field changed; select it again.") from None
            if self.focused_signature != self.signature(form, field):
                raise ValueError("The selected field changed; select it again.")
            meaning = self.meaning(form, field)
            if meaning not in {
                "one_time_code",
                "captcha",
                "password",
                "password_confirm",
            } and event.text != self.expected(form, field):
                raise ValueError("Account identity must match the designated test account.")
            reference = (
                self.account.secret_ref
                if meaning in {"password", "password_confirm"}
                else "human-" + uuid4().hex
            )
            runner.secrets.put(reference, str(event.text))
            runner.fill(name, field.ref, secret_ref=reference)
            self.typed[self.signature(form, field)] = str(event.text)
        elif event.kind == "submit":
            reference = self.submission()
            self.submitted = True
            runner.submit(name, reference)
