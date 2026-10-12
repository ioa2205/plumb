"""The website journey: a durable observe-act-observe loop that code drives (ADR-0028).

    scope -> discover -> authenticate -> map -> select check -> execute -> observe
          -> challenge -> record -> report

Code owns permissions, prerequisites, budgets, progress, dispatch and stopping.
The model is consulted only at real choices, through closed questions, and
never while the browser runs: browser work and model work alternate, with a
saved checkpoint between them. A journey finishes and reports with no model at
all; then every decision is code's, the user's, or recorded as undecided.

A step that changes something on the website is checkpointed as attempted
before it is sent. If the run dies there, the step is uncertain and is never
sent again.
"""

import hashlib
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent.asking import TimingLog, explain
from agent.closed import Asker, ClosedQuestion, Decision, Fact, MenuItem, decide, judge_three
from agent.web_questions import (
    field_by_code,
    field_question,
    form_by_code,
    form_question,
    page_by_code,
    rule_question,
    step_by_code,
    step_question,
)
from backend.contracts.assessment import EvidenceCitation
from backend.contracts.chat import ChatPart
from backend.contracts.conversation import ConversationEvidence
from backend.contracts.web import (
    BlockedRequest,
    EvidenceRef,
    LoginConfig,
    ObservedForm,
    PageObservation,
    PlanStep,
    SignupConfig,
    WebAccount,
    WebEvidence,
    WebsiteScope,
    digest,
)
from backend.contracts.web_journey import (
    AccountRecord,
    CheckRecord,
    DecisionRecord,
    Finding,
    Incident,
    JourneyView,
    PageRecord,
    Spent,
    Stage,
    StepRecord,
    UserChoice,
    UserQuestion,
)
from backend.redaction import Redactor
from backend.settings import Settings
from backend.web_human import HumanChannel
from backend.web_plan import MAP_PAGES, approval_in_force, make_plan
from backend.web_store import JourneyStore
from backend.web_urls import WebUrl, parse_url, path_within
from verification.egress import (
    ActionPermission,
    Egress,
    EgressBudget,
    EgressPolicy,
    EgressRefused,
    EgressStopped,
)
from verification.web_fixture import Fixture
from verification.web_http import HttpAdapter, HttpSession, UncertainWrite
from verification.web_human import HumanBrowser
from verification.web_pages import Bound, PrivacyStop, personal_data
from verification.web_secrets import MissingSecret, SecretStore

_PASSWORD = "password"  # noqa: S105 - the name of an input type
# Links that may end a session or remove something are not followed while mapping.
_RISKY_LINK = re.compile(
    r"log[-_ ]?out|sign[-_ ]?out|delete|remove|destroy|cancel|unsubscribe|deactivate", re.IGNORECASE
)
_DENIED = frozenset({401, 403, 404})
_HEADERS = {
    "content-security-policy": "a content security policy",
    "x-content-type-options": "the X-Content-Type-Options header",
    "x-frame-options": "the X-Frame-Options header",
}


class Halt(Exception):
    """The journey must stop now. Completed work is already saved."""

    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


ModelFactory = Callable[[], AbstractContextManager[Asker | None]]
BrowserFactory = Callable[
    [Egress, SecretStore, Redactor, frozenset[str]], AbstractContextManager[Any]
]


def new_journey(settings: Settings, scope: WebsiteScope, profile: str = "auto") -> JourneyView:
    """Freeze the scope and make its plan. Nothing is visited and no model is asked."""
    scope = WebsiteScope.model_validate(scope.model_dump())
    now = datetime.now(UTC)
    if now >= scope.expires_at:
        raise ValueError("The scope has already expired")
    timings = TimingLog(settings.cache_dir / "closed-questions" / "timings.jsonl")
    plan = make_plan(scope, timings, profile)
    view = JourneyView(
        journey_id="journey-" + uuid4().hex,
        scope=scope,
        plan=plan,
        plan_sha256=plan.sha256,
        steps=[StepRecord(step_id=step.step_id, action=step.action) for step in plan.steps],
        accounts=[AccountRecord(account_id=account.account_id) for account in scope.accounts],
        created_at=now,
        updated_at=now,
    )
    JourneyStore(settings).save(view)
    return view


class Journey:
    def __init__(
        self,
        settings: Settings,
        journey_id: str,
        *,
        secrets: SecretStore,
        cancel: threading.Event | None = None,
        fixture: Fixture | None = None,
        model: ModelFactory | None = None,
        browser: BrowserFactory | None = None,
        egress: Callable[[EgressPolicy, EgressBudget, Callable[[], bool]], Egress] | None = None,
        on_update: Callable[[JourneyView], None] | None = None,
        ask_user: Callable[[UserQuestion], str | None] | None = None,
        answers: dict[str, str] | None = None,
        human: HumanChannel | None = None,
    ) -> None:
        self.settings = settings
        self.store = JourneyStore(settings)
        self.view = self.store.load(journey_id)
        self.scope = self.view.scope
        self.secrets = secrets
        self.cancel = cancel or threading.Event()
        self.fixture = fixture
        self.model = model
        self.browser_factory = browser
        self.egress_factory = egress or (
            lambda policy, budget, canceled: Egress(policy, budget, cancel=canceled)
        )
        self.on_update = on_update or (lambda view: None)
        self.ask_user = ask_user
        self.user_answers = dict(answers or {})
        self.human = human
        self._resume_human: set[str] = set()
        self.accounts = {account.account_id: account for account in self.scope.accounts}
        self.objects = {item.object_id: item for item in self.scope.objects}
        self.rules = {rule.rule_id: rule for rule in self.scope.rules}
        self.plan = {step.step_id: step for step in self.view.plan.steps}
        self.sessions: dict[str, HttpSession] = {}
        self.pending: list[tuple[Stage, str, ClosedQuestion]] = []  # stage, subject, question
        self.answers: dict[str, str] = {
            record.subject: record.value
            for record in self.view.decisions
            if record.value is not None
        }
        self.expected = frozenset(
            value
            for value in (
                *self.scope.public_values,
                *[account.username for account in self.scope.accounts],
                *[account.contact_email or "" for account in self.scope.accounts],
                *[account.contact_phone or "" for account in self.scope.accounts],
            )
            if value
        )
        self._started = 0.0
        self._egress: Egress | None = None
        self._base = Spent()
        self._blocked_before: list[BlockedRequest] = []

    # --- record keeping ----------------------------------------------------------------------

    def redactor(self) -> Redactor:
        extra = [*self.secrets.values()]
        for session in self.sessions.values():
            extra.extend(session.values())
        return Redactor.configured(self.settings, extra=tuple(extra))

    def update(self, **changes: Any) -> None:  # noqa: ANN401 - fields of the journey record
        self.view = self.view.model_copy(update={**changes, "updated_at": datetime.now(UTC)})

    def save(self) -> None:
        if self._egress is not None:
            used = self._egress.budget
            base = self._base
            self.update(
                spent=self.view.spent.model_copy(
                    update={
                        "requests": base.requests + used.requests,
                        "bytes": base.bytes + used.bytes,
                        "seconds": round(base.seconds + (time.monotonic() - self._started), 3),
                    }
                ),
                blocked=[*self._blocked_before, *self._egress.blocked][:200],
            )
        self.store.save(self.view, secrets=self.redactor().secrets)
        self.on_update(self.view)

    def say(self, stage: Stage, activity: str) -> None:
        self.update(stage=stage, activity=activity[:300])
        self.save()

    def step(self, step_id: str) -> StepRecord:
        return next(step for step in self.view.steps if step.step_id == step_id)

    def set_step(
        self, step_id: str, state: str, note: str = "", evidence: list[str] | None = None
    ) -> None:
        steps = [
            step.model_copy(
                update={
                    "state": state,
                    "note": note[:600],
                    "evidence_ids": [*step.evidence_ids, *(evidence or [])][:60],
                }
            )
            if step.step_id == step_id
            else step
            for step in self.view.steps
        ]
        self.update(steps=steps)
        self.save()

    def set_account(self, account_id: str, state: str, note: str = "", kept: bool = False) -> None:
        self.update(
            accounts=[
                record.model_copy(update={"state": state, "note": note[:600], "session_kept": kept})
                if record.account_id == account_id
                else record
                for record in self.view.accounts
            ]
        )

    def account_state(self, account_id: str) -> str:
        return next(r.state for r in self.view.accounts if r.account_id == account_id)

    def runnable(self, step_id: str) -> PlanStep | None:
        """The plan step, if it is approved and still to do. Uncertain writes are never redone."""
        step = self.plan.get(step_id)
        if step is None:
            return None
        record = self.step(step_id)
        approved = (
            self.view.approval is not None and step_id in self.view.approval.approved_step_ids
        )
        if record.state in {"completed", "blocked", "skipped", "uncertain"}:
            return None
        if not approved:
            self.set_step(step_id, "skipped", "Not approved by the reviewer.")
            return None
        if record.state == "attempted":
            if step.state_changing or step.action == "sign_in":
                # It was started and never confirmed. Whether it happened is unknown.
                self.set_step(
                    step_id,
                    "uncertain",
                    "This step was interrupted after it began. It is not repeated automatically.",
                )
                if step.account_id:
                    self.set_account(step.account_id, "uncertain", "Interrupted during this step.")
                return None
            return step  # a read is safe to do again
        return step

    def evidence(
        self,
        kind: str,
        via: str,
        fields: dict[str, str],
        *,
        account_id: str | None = None,
        object_id: str | None = None,
        provenance: str,
    ) -> WebEvidence:
        redactor = self.redactor()
        clean = {key: redactor.text(str(value))[:8000] for key, value in fields.items()}
        identifier = f"E{len(self.view.evidence) + 1:03}"
        item = WebEvidence(
            evidence_id=identifier,
            website_id=self.scope.website_id,
            kind=kind,  # ty: ignore[invalid-argument-type]
            via=via,  # ty: ignore[invalid-argument-type]
            account_id=account_id,
            object_id=object_id,
            fields=clean,
            collected_at=datetime.now(UTC),
            provenance=provenance[:300],
            sha256=digest(
                {
                    "evidence_id": identifier,
                    "kind": kind,
                    "account_id": account_id,
                    "object_id": object_id,
                    "fields": clean,
                }
            ),
        )
        self.update(evidence=[*self.view.evidence, item])
        return item

    @staticmethod
    def cite(item: WebEvidence, field: str) -> EvidenceRef:
        return EvidenceRef(
            evidence_id=item.evidence_id, field=field, sha256=digest(item.fields[field])
        )

    def decided(self, stage: Stage, subject: str, decision: Decision) -> None:
        self.update(
            decisions=[
                *self.view.decisions,
                DecisionRecord(
                    at=datetime.now(UTC),
                    stage=stage,
                    question_type=decision.kind,
                    subject=subject[:200],
                    value=decision.value or None,
                    rung=decision.rung,
                    reason=(decision.reason or decision.user_question or "")[:600] or None,
                    attempts=decision.record()["attempts"],
                ),
            ][-200:]
        )
        if decision.value:
            self.answers[subject] = decision.value

    def choose(
        self, stage: Stage, subject: str, by_code: Decision | None, question: ClosedQuestion
    ) -> str | None:
        """Code decides now, or the question waits for the next model phase."""
        if subject in self.answers:
            return self.answers[subject]
        if by_code is not None:
            self.decided(stage, subject, by_code)
            return by_code.value or None
        if all(known != subject for _, known, _ in self.pending):
            self.pending.append((stage, subject, question))
        return None

    # --- network, browser and model resources ----------------------------------------------------

    def check_live(self) -> None:
        if self.cancel.is_set():
            raise Halt("paused", "Stopped by the user. Completed work is kept.")
        if (reason := approval_in_force(self.view)) is not None:
            raise Halt("stopped", reason)

    @contextmanager
    def network(self) -> Iterator[Egress]:
        spent, budget = self.view.spent, self.scope.budget
        left = budget.max_seconds - spent.seconds
        if spent.requests >= budget.max_requests or spent.bytes >= budget.max_bytes or left <= 0:
            raise Halt("stopped", "The approved request, data or time budget is used up.")
        if self.scope.mode == "owned_fixture":
            if self.fixture is None or self.fixture.origin != self.scope.origin:
                raise Halt(
                    "stopped", "An owned-fixture scope runs only against the fixture Plumb started."
                )
            port: int | None = self.fixture.port
        else:
            from backend.web_boundary import qualified

            if (reason := qualified(self.settings)) is not None:
                raise Halt("stopped", reason)
            port = None
        policy = EgressPolicy(
            mode=self.scope.mode,
            targets=tuple(self.scope.targets),
            expires_at=self.scope.expires_at,
            owned_port=port,
            approved_actions=tuple(
                ActionPermission(step.step_id, step.action, step.account_id)
                for step in self.view.plan.steps
                if self.view.approval is not None
                and step.step_id in self.view.approval.approved_step_ids
                and step.action in {"sign_in", "sign_up", "submit_form"}
                and step.action in self.scope.allowed_actions
            ),
        )
        self._base, self._blocked_before = spent, list(self.view.blocked)
        self._started = time.monotonic()
        egress = self.egress_factory(
            policy,
            EgressBudget(
                max_requests=budget.max_requests - spent.requests,
                max_bytes=budget.max_bytes - spent.bytes,
                deadline=time.monotonic() + left,
            ),
            self.cancel.is_set,
        )
        self._egress = egress
        try:
            yield egress
        finally:
            with suppress(OSError, ValueError):
                self.save()
            self._egress = None
            egress.close()

    @contextmanager
    def browser(self, egress: Egress) -> Iterator[Any]:
        """The contained browser, or None with the reason recorded when it cannot be used."""
        if self.browser_factory is None:
            self.update(browser="unavailable", browser_note="No browser runner was provided.")
            yield None
            return
        try:
            manager = self.browser_factory(egress, self.secrets, self.redactor(), self.expected)
            runner = manager.__enter__()
        except Exception as error:
            self.update(
                browser="unavailable",
                browser_note=Redactor.configured(self.settings).text(str(error))[:600]
                or type(error).__name__,
            )
            yield None
            return
        self.update(browser="used", browser_note="")
        try:
            yield runner
        finally:
            with suppress(Exception):
                manager.__exit__(None, None, None)

    def ask_pending(self) -> None:
        """One model phase: every waiting question goes down the ladder, within the budget."""
        waiting, self.pending = self.pending, []
        if not waiting:
            return
        self.say(
            waiting[0][0],
            f"Asking the local model {len(waiting)} closed question(s)."
            if self.model is not None
            else f"{len(waiting)} question(s) code could not decide go to you or stay open.",
        )
        factory = self.model if self.model is not None else (lambda: nullcontext(None))
        with factory() as asker:
            for stage, subject, question in waiting:
                self.check_live()
                room = self.scope.budget.max_model_questions - self.view.spent.model_questions
                decision = decide(question, asker if room >= 2 else None)
                self.count_model(decision.attempts)
                if decision.value is None and decision.rung == "user":
                    decision = self.to_user(subject, question, decision)
                self.decided(stage, subject, decision)
                self.save()

    def to_user(self, subject: str, question: ClosedQuestion, decision: Decision) -> Decision:
        """The last rung: ask now when someone is there, otherwise leave the question waiting."""
        ready = {item.key for item in question.menu if item.ready}
        asked = UserQuestion(
            subject=subject[:200],
            question_type=question.kind.name,
            text=(question.user_question or question.kind.ask)[:300],
            choices=[
                UserChoice(label=label, meaning=meaning)
                for label, meaning in (
                    question.kind.labels
                    or tuple((item.key, item.text) for item in question.menu if item.ready)
                )
            ],
        )
        answer = self.ask_user(asked) if self.ask_user is not None else None
        accepted = (
            answer in ready
            if question.menu
            else answer is not None and question.grade({"answer": answer})[0] == answer
        )
        if answer is not None and accepted:
            return Decision(
                kind=decision.kind,
                value=answer,
                rung="user",
                reason="Answered by the user.",
                attempts=decision.attempts,
            )
        waiting = [item for item in self.view.waiting if item.subject != asked.subject]
        self.update(waiting=[*waiting, asked][:20])
        return decision

    def take_answers(self) -> None:
        """Answers the user gave to waiting questions: recorded as theirs, then work resumes."""
        answered = []
        for asked in self.view.waiting:
            value = self.user_answers.get(asked.subject)
            if value is None or value not in {choice.label for choice in asked.choices}:
                continue
            answered.append(asked.subject)
            if asked.question_type == "human_auth":
                step_id = asked.subject.removeprefix("human:")
                step = self.plan.get(step_id)
                if (
                    step is None
                    or not step.account_id
                    or self.account_state(step.account_id) != "handoff"
                ):
                    continue
                if value == "resume":
                    self._resume_human.add(step_id)
                else:
                    self.set_account(step.account_id, "failed", "Human completion was declined.")
                    self.set_step(step_id, "blocked", "Human completion was declined.")
                self.decided(
                    "authenticate",
                    asked.subject,
                    Decision(
                        kind="human_auth", value=value, rung="user", reason="Answered by the user."
                    ),
                )
                continue
            self.decided(
                "authenticate",
                asked.subject,
                Decision(
                    kind=asked.question_type,
                    value=value,
                    rung="user",
                    reason="Answered by the user.",
                ),
            )
        if not answered:
            return
        waiting_note = "Needs your answer"
        reopened = {
            step.step_id
            for step in self.view.steps
            if step.note.startswith(waiting_note) and f"human:{step.step_id}" not in answered
        }
        accounts = {self.plan[name].account_id for name in reopened if name in self.plan}
        self.update(
            waiting=[item for item in self.view.waiting if item.subject not in answered],
            steps=[
                StepRecord(step_id=step.step_id, action=step.action)
                if step.step_id in reopened
                or (
                    step.state in {"skipped", "blocked"}
                    and self.plan[step.step_id].account_id in accounts
                )
                else step
                for step in self.view.steps
            ],
            accounts=[
                AccountRecord(account_id=record.account_id)
                if record.account_id in accounts
                else record
                for record in self.view.accounts
            ],
            checks=[c for c in self.view.checks if c.other_account_id not in accounts],
        )

    def count_model(self, attempts: tuple[Any, ...]) -> None:
        self.update(
            spent=self.view.spent.model_copy(
                update={
                    "model_questions": self.view.spent.model_questions
                    + sum(a.error != "UnqualifiedQuestion" for a in attempts),
                    "model_seconds": round(
                        self.view.spent.model_seconds + sum(a.seconds for a in attempts), 3
                    ),
                }
            )
        )

    # --- looking at pages -----------------------------------------------------------------------

    def url(self, path: str) -> WebUrl:
        return parse_url(self.scope.origin + path)

    def look(
        self,
        browser: Any,  # noqa: ANN401 - the browser tools, or None
        http: HttpAdapter,
        account_id: str | None,
        url: WebUrl,
        step_id: str,
        *,
        navigate: bool = True,
    ) -> Bound | None:
        """Open and describe one page. A privacy stop drops the page and records only its kind."""
        self.check_live()
        try:
            if browser is not None:
                status = browser.navigate(account_id, url) if navigate else None
                bound = browser.observe(account_id, status)
            else:
                session = self.sessions.get(account_id or "", HttpSession(account_id))
                bound, _ = http.observe(
                    session, url, redactor=self.redactor(), expected_personal=self.expected
                )
        except PrivacyStop as stop:
            self.incident(step_id, url.path, stop)
            self.record_page(url.path, account_id, None, note="Stopped: unexpected personal data.")
            return None
        except EgressStopped:
            raise
        except EgressRefused as refused:
            self.record_page(url.path, account_id, None, note=refused.reason)
            return None
        self.record_page(bound.observation.path, account_id, bound.observation)
        return bound

    def incident(self, step_id: str, path: str, stop: PrivacyStop) -> None:
        """A privacy stop: the content is gone, only its kind and place are recorded."""
        self.update(
            incidents=[
                *self.view.incidents,
                Incident(at=datetime.now(UTC), step_id=step_id, path=path, kinds=stop.kinds),
            ][:20]
        )

    def record_page(
        self, path: str, account_id: str | None, page: PageObservation | None, note: str = ""
    ) -> None:
        pages = [p for p in self.view.pages if (p.path, p.account_id) != (path, account_id)]
        if page is None:
            record = PageRecord(path=path, account_id=account_id, via="browser", note=note[:300])
        else:
            kind = page_by_code(page)
            forms = []
            for form in page.forms:
                purpose = form_by_code(form)
                forms.append((purpose.value if purpose else "") or form.heading or "form")
            item = self.evidence(
                "page",
                page.via,
                {
                    "page.path": page.path,
                    "page.status": str(page.status) if page.status is not None else "not reported",
                    "page.title": page.title or "(none)",
                    "page.text": page.text[:1500] or "(empty)",
                    "page.forms": "; ".join(forms) or "none",
                    "page.links": str(len(page.links)),
                },
                account_id=account_id,
                provenance=f"Observed by Plumb's {page.via} adapter",
            )
            record = PageRecord(
                path=page.path,
                account_id=account_id,
                via=page.via,
                status=page.status,
                title=page.title,
                kind=(kind.value or "") if kind else "",
                kind_rung=kind.rung if kind else None,
                links=len(page.links),
                forms=forms[:12],
                evidence_id=item.evidence_id,
                blocked=page.blocked,
                note=(
                    "A human step is needed here: " + page.challenge.replace("_", " ")
                    if page.challenge != "none"
                    else ""
                ),
            )
        self.update(pages=[*pages, record][:120])

    # --- forms: which one, and what each field means ------------------------------------------

    def account_form(
        self, page: PageObservation, purpose: str, declared: bool
    ) -> ObservedForm | None:
        """The page's sign-in or sign-up form, by code where the page or the reviewer decides."""
        candidates = [
            form
            for form in page.forms
            if form.in_scope and any(item.input_type == _PASSWORD for item in form.fields)
        ]
        matching = [form for form in candidates if (d := form_by_code(form)) and d.value == purpose]
        if len(matching) == 1:
            return matching[0]
        if len(candidates) == 1 and declared:
            # The reviewer named this page for this purpose and it has one account form.
            return candidates[0]
        for index, form in enumerate(candidates):
            subject = f"form:{page.path}:{index}"
            value = self.choose(
                "authenticate", subject, form_by_code(form), form_question(form, page)
            )
            if value == purpose:
                return form
        return None

    def meanings(self, page: PageObservation, form: ObservedForm) -> dict[str, str | None]:
        """Field reference -> meaning; None where code cannot tell and the model was not asked."""
        result: dict[str, str | None] = {}
        visible = [item for item in form.fields if item.input_type != "hidden"]
        others = [item for item in visible if item.input_type != _PASSWORD]
        for item in visible:
            subject = f"field:{page.path}:{item.name or item.label}"
            by_code = field_by_code(item, form)
            if by_code is None and len(others) == 1 and len(visible) == 2:
                # A sign-in form with one password field: the other field identifies the account.
                result[item.ref] = "username"
                continue
            result[item.ref] = self.choose(
                "authenticate", subject, by_code, field_question(item, form, page)
            )
        return result

    def fill_account_form(
        self,
        browser: Any,  # noqa: ANN401 - the browser tools
        account: WebAccount,
        form: ObservedForm,
        meanings: dict[str, str | None],
    ) -> str | None:
        """Fill every field code understands. Returns why the form cannot be completed, if so."""
        for item in form.fields:
            if item.input_type == "hidden":
                continue
            meaning = meanings.get(item.ref)
            value: str | None = None
            secret: str | None = None
            if meaning in {"password", "password_confirm"}:
                secret = account.secret_ref
            elif meaning == "username":
                value = account.username
            elif meaning == "email":
                value = account.contact_email or (
                    account.username if "@" in account.username else None
                )
            elif meaning == "display_name":
                value = account.label.split("(")[0].strip() or account.username
            elif meaning == "phone":
                value = account.contact_phone
            elif meaning == "one_time_code":
                return "The form asks for a one-time code; a person must complete this step."
            if value is None and secret is None:
                if item.required or meaning is None:
                    return (
                        f"The field “{item.label or item.name}” is not understood or has no value."
                    )
                continue
            browser.fill(account.account_id, item.ref, value=value, secret_ref=secret)
        return None

    def confirmed(
        self,
        browser: Any,  # noqa: ANN401 - the browser tools, or None
        http: HttpAdapter,
        account_id: str,
        config: LoginConfig | SignupConfig,
        step_id: str,
    ) -> str | None:
        """The reviewer's own post-sign-in check. None when it passes; otherwise what was seen."""
        bound = (
            self.look(browser, http, account_id, self.url(config.success_path), step_id)
            if config.success_path
            else self.look(
                browser,
                http,
                account_id,
                browser.location(account_id) or self.url("/"),
                step_id,
                navigate=False,
            )
        )
        if bound is None:
            return "The page for the check after signing in could not be read."
        page = bound.observation
        if page.challenge != "none":
            return "handoff:" + page.challenge
        if config.success_text and config.success_text not in page.text:
            return "The expected text after signing in was not shown."
        if config.success_path and not path_within(page.path, config.success_path):
            return "The site did not stay on the expected page after signing in."
        return None

    # --- the stages -----------------------------------------------------------------------------

    def run(self) -> JourneyView:
        if self.view.status not in {"approved", "paused", "handoff", "running"}:
            raise ValueError("This journey is not waiting to run")
        if (reason := approval_in_force(self.view)) is not None:
            raise ValueError(reason)
        if self.view.approval_used_at is None:
            # The approval is for this one journey. It is marked used before anything is sent.
            self.update(approval_used_at=datetime.now(UTC))
        self.update(status="running", stop_reason=None)
        self.take_answers()
        self.save()
        try:
            self.first_look()
            self.ask_pending()
            self.act()
            self.judge()
            if self.view.waiting:
                # Everything that could run did. The rest waits for the user's own answer.
                raise Halt(
                    "paused",
                    f"Waiting for your answer to {len(self.view.waiting)} question(s). "
                    "The report so far is ready.",
                )
            self.update(
                status="done", stage="report", activity="Finished. The private report is ready."
            )
            self.report()
        except Halt as halt:
            self.update(status=halt.status, stop_reason=halt.reason, activity=halt.reason[:300])
        except EgressStopped as stopped:
            status = "paused" if self.cancel.is_set() else "stopped"
            self.update(status=status, stop_reason=stopped.reason, activity=stopped.reason[:300])
        except (OSError, RuntimeError, ValueError) as error:
            self.update(
                status="failed",
                stop_reason=f"The journey stopped on an internal error ({type(error).__name__}). "
                "Completed work is kept.",
            )
        finally:
            if self.view.status in {"stopped", "failed", "paused"}:
                # What was done so far is still reported; the report step itself stays open.
                with suppress(OSError, ValueError, RuntimeError):
                    self.report(final=False)
            self.save()
            self.sessions.clear()
        return self.view

    def first_look(self) -> None:
        """Browser phase one: the start page, and the sign-in and sign-up pages signed out."""
        discover = "discover" in self.plan and self.step("discover").state in {
            "planned",
            "attempted",
        }
        accounts = [
            step
            for step in self.view.plan.steps
            if step.stage == "authenticate" and self.step(step.step_id).state == "planned"
        ]
        if not discover and not accounts:
            return
        self.say("discover", "Opening the start page.")
        with self.network() as egress, self.browser(egress) as browser:
            http = HttpAdapter(egress)
            if self.runnable("discover") is not None:
                self.set_step("discover", "attempted")
                seen = self.look(browser, http, None, self.url(self.scope.start_path), "discover")
                self.leads(http)
                self.set_step(
                    "discover",
                    "completed" if seen is not None else "blocked",
                    "" if seen is not None else "The start page could not be observed.",
                )
            # Read the account forms once, signed out, so that anything code cannot decide
            # about them is asked of the model before any form is filled.
            if browser is not None:
                for config, purpose in (
                    (self.scope.login, "sign_in"),
                    (self.scope.signup, "sign_up"),
                ):
                    if config is None or not any(s.action == purpose for s in accounts):
                        continue
                    seen = self.look(browser, http, None, self.url(config.path), "discover")
                    if seen is None or seen.observation.challenge != "none":
                        continue
                    form = self.account_form(seen.observation, purpose, declared=True)
                    if form is not None:
                        self.meanings(seen.observation, form)
            self.order_checks()

    def leads(self, http: HttpAdapter) -> None:
        """Low-impact observations of the start page's response. Leads, never findings."""
        try:
            result = http.request(HttpSession(None), "GET", self.url(self.scope.start_path))
        except (EgressRefused, UncertainWrite):
            return
        if result.status >= 400:
            return
        found = [
            f"The start page's response did not carry {name}. A lead to look at, not a finding."
            for header, name in _HEADERS.items()
            if header not in result.headers
        ]
        if result.url.scheme == "https" and "strict-transport-security" not in result.headers:
            found.append(
                "The start page's response did not carry Strict-Transport-Security. "
                "A lead to look at, not a finding."
            )
        self.update(leads=list(dict.fromkeys([*self.view.leads, *found]))[:40])

    def order_checks(self) -> None:
        """Which approved comparison runs first: code when all fit, otherwise one question."""
        checks = [
            s
            for s in self.view.plan.steps
            if s.stage == "check" and self.step(s.step_id).state == "planned"
        ]
        if len(checks) < 2 or "order:checks" in self.answers:
            return
        left = self.scope.budget.max_requests - self.view.spent.requests
        room = max(0, left - 60) // 4
        items = [MenuItem(step.step_id, step.summary[:200]) for step in checks]
        self.choose(
            "select",
            "order:checks",
            step_by_code(items, room),
            step_question(self.scope.purpose, items),
        )

    def act(self) -> None:
        """Browser phase two: sign in, sign up, map, and read the objects to compare."""
        self.check_live()
        todo = [
            step
            for step in self.view.plan.steps
            if step.stage in {"authenticate", "map", "check"}
            and self.step(step.step_id).state in {"planned", "attempted"}
        ]
        if not todo and not self._resume_human:
            return
        with self.network() as egress, self.browser(egress) as browser:
            http = HttpAdapter(egress)
            self.restore_sessions(browser, http)
            self.resume_handoffs(browser, http)
            # A completed handoff may have reopened dependent reads/comparisons.
            todo = [
                step
                for step in self.view.plan.steps
                if step.stage in {"authenticate", "map", "check"}
                and self.step(step.step_id).state in {"planned", "attempted"}
            ]
            for step in [s for s in todo if s.stage == "authenticate"]:
                self.authenticate(browser, http, step)
            for step in [s for s in todo if s.stage == "map"]:
                self.map(browser, http, step)
            first = self.answers.get("order:checks")
            checks = sorted(
                [s for s in todo if s.stage == "check"], key=lambda s: s.step_id != first
            )
            for step in checks:
                self.compare(http, step)

    def authenticate(self, browser: Any, http: HttpAdapter, step: PlanStep) -> None:  # noqa: ANN401
        account = self.accounts[str(step.account_id)]
        if self.runnable(step.step_id) is None:
            return
        config = self.scope.login if step.action == "sign_in" else self.scope.signup
        if config is None:
            return self.set_step(step.step_id, "skipped", "No page is configured for this.")
        self.say(
            "authenticate",
            ("Signing in" if step.action == "sign_in" else "Creating the account")
            + f": {account.label}.",
        )
        if browser is None:
            self.set_account(account.account_id, "failed", "The browser is unavailable.")
            return self.set_step(
                step.step_id, "blocked", "This form needs the browser, which is unavailable here."
            )
        try:
            if step.action == "sign_up":
                self.secrets.generate(account.secret_ref)
            self.secrets.get(account.secret_ref)
        except MissingSecret as missing:
            self.set_account(account.account_id, "failed", str(missing))
            return self.set_step(step.step_id, "blocked", str(missing))
        seen = self.look(browser, http, account.account_id, self.url(config.path), step.step_id)
        if seen is None:
            self.set_account(account.account_id, "failed", "The page could not be observed.")
            return self.set_step(step.step_id, "blocked", "The page could not be observed.")
        page = seen.observation
        if page.challenge != "none":
            return self.handoff(step, account, page.challenge, browser, http)
        form = self.account_form(page, step.action, declared=True)
        meanings = self.meanings(page, form) if form is not None else {}
        if self.pending:
            # Something is still undecided and the model phase for it has passed.
            waiting = "; ".join(q.user_question or subject for _, subject, q in self.pending)[:400]
            self.pending.clear()
            self.set_account(account.account_id, "failed", "A form field was not understood.")
            return self.set_step(step.step_id, "blocked", "Needs your answer: " + waiting)
        if form is None:
            self.set_account(account.account_id, "failed", "No matching form was found.")
            return self.set_step(step.step_id, "blocked", "No matching form was found on the page.")
        try:
            if self._egress is None:
                raise EgressRefused("other", "No approved website transport is active.")
            with self._egress.action(step.step_id, account.account_id):
                problem = self.fill_account_form(browser, account, form, meanings)
                if problem is not None:
                    if "one-time code" in problem:
                        return self.handoff(step, account, "one_time_code", browser, http)
                    self.set_account(account.account_id, "failed", problem)
                    return self.set_step(step.step_id, "blocked", problem)
                # Saved as attempted before the form is sent: an interruption here is uncertain.
                self.set_step(step.step_id, "attempted")
                browser.submit(account.account_id, form.ref)
        except UncertainWrite as uncertain:
            self.set_account(account.account_id, "uncertain", str(uncertain))
            return self.set_step(
                step.step_id, "uncertain", f"{uncertain} It is not repeated automatically."
            )
        except EgressStopped:
            raise
        except (EgressRefused, MissingSecret, ValueError, RuntimeError) as error:
            self.set_account(account.account_id, "failed", str(error)[:300])
            return self.set_step(step.step_id, "blocked", str(error)[:300] or type(error).__name__)
        problem = self.confirmed(browser, http, account.account_id, config, step.step_id)
        if problem is not None and problem.startswith("handoff:"):
            return self.handoff(step, account, problem.split(":", 1)[1], browser, http)
        if problem is not None:
            # One attempt per account. A failed sign-in is never tried again with anything else.
            self.set_account(account.account_id, "failed", problem)
            return self.set_step(step.step_id, "blocked", problem + " It was not tried again.")
        self.sessions[account.account_id] = browser.session(account.account_id)
        state = browser.state(account.account_id)
        kept_on_disk = bool(state) and self.store.keep_session(
            self.view.journey_id, account.account_id, state
        )
        self.set_account(
            account.account_id,
            "signed_in" if step.action == "sign_in" else "created",
            "The check after signing in passed.",
            kept=kept_on_disk,
        )
        self.set_step(step.step_id, "completed")

    def restore_sessions(self, browser: Any, http: HttpAdapter) -> None:  # noqa: ANN401
        """A resumed journey gets each signed-in account back from that account's own saved state.

        When that fails the account is marked as needing a new sign-in. Nothing is
        guessed and no other account's state is ever used in its place.
        """
        config = self.scope.login or self.scope.signup
        for record in self.view.accounts:
            name = record.account_id
            if record.state not in {"signed_in", "created"} or name in self.sessions:
                continue
            kept = self.store.session(self.view.journey_id, name)
            restored = False
            if kept is not None and browser is not None and config is not None:
                try:
                    browser.restore(name, kept)
                    restored = self.confirmed(browser, http, name, config, "restore") is None
                except EgressStopped:
                    raise
                except Exception:
                    restored = False
            if restored:
                self.sessions[name] = browser.session(name)
            else:
                self.set_account(
                    name,
                    "needs_sign_in",
                    "The saved session could not be restored. "
                    "Signing in again needs a new approval.",
                )
        self.save()

    def keep_handoff(
        self,
        browser: Any,  # noqa: ANN401 - the finite browser tools
        step: PlanStep,
        challenge: str,
        *,
        before_write: bool,
        submitted: bool = False,
    ) -> bool:
        state = browser.state(step.account_id)
        location = browser.location(step.account_id)
        if not state or location is None:
            return False
        # Metadata and challenge addresses can contain session material, so these
        # stay inside the protected state blob, never in the journey contract.
        return self.store.keep_session(
            self.view.journey_id,
            str(step.account_id),
            {
                **state,
                "plumb_handoff": {
                    "plan_sha256": self.view.plan_sha256,
                    "step_id": step.step_id,
                    "account_id": step.account_id,
                    "url": location.url,
                    "challenge": challenge,
                    "before_write": before_write,
                    "submitted": submitted,
                },
            },
        )

    def handoff(
        self,
        step: PlanStep,
        account: WebAccount,
        challenge: str,
        browser: Any,  # noqa: ANN401 - the finite browser tools
        http: HttpAdapter,
    ) -> None:
        words = challenge.replace("_", " ")
        line = (
            f"{account.label}: the site asks for a {words}. A person has to complete this step; "
            "Plumb does not try to get around it."
        )
        self.update(handoffs=list(dict.fromkeys([*self.view.handoffs, line[:300]]))[:12])
        before_write = self.step(step.step_id).state != "attempted"
        kept = self.keep_handoff(browser, step, challenge, before_write=before_write)
        self.set_account(account.account_id, "handoff", line, kept=kept)
        self.set_step(step.step_id, "blocked", line)
        self.wait_for_human(browser, http, step, account, challenge, before_write=before_write)

    def resume_handoffs(self, browser: Any, http: HttpAdapter) -> None:  # noqa: ANN401
        for step_id in tuple(self._resume_human):
            self.check_live()
            step = self.plan[step_id]
            name = str(step.account_id)
            if self.view.approval is None or step_id not in self.view.approval.approved_step_ids:
                raise Halt("stopped", "The human authentication step is not approved.")
            state = self.store.session(self.view.journey_id, name)
            metadata = state.get("plumb_handoff") if state else None
            if (
                browser is None
                or state is None
                or not isinstance(metadata, dict)
                or metadata.get("plan_sha256") != self.view.plan_sha256
                or metadata.get("step_id") != step_id
                or metadata.get("account_id") != name
            ):
                self.set_account(
                    name,
                    "needs_sign_in",
                    "The interim session is unavailable or mismatched. "
                    "Signing in again needs a new approval.",
                )
                self.set_step(
                    step_id,
                    "blocked",
                    "The interim session could not be restored; no sign-in was repeated.",
                )
                continue
            browser.restore(
                name, {key: value for key, value in state.items() if key != "plumb_handoff"}
            )
            browser.navigate(name, parse_url(str(metadata["url"])))
            self.wait_for_human(
                browser,
                http,
                step,
                self.accounts[name],
                str(metadata["challenge"]),
                before_write=metadata.get("before_write") is True,
                submitted=metadata.get("submitted") is True,
            )
        self._resume_human.clear()

    def wait_for_human(
        self,
        browser: Any,  # noqa: ANN401 - the finite browser tools
        http: HttpAdapter,
        step: PlanStep,
        account: WebAccount,
        challenge: str,
        *,
        before_write: bool,
        submitted: bool = False,
    ) -> None:
        asked = UserQuestion(
            subject=f"human:{step.step_id}",
            question_type="human_auth",
            text=f"Resume private human completion for {account.label}?",
            choices=[
                UserChoice(
                    label="resume", meaning="Open the same account's contained challenge view."
                ),
                UserChoice(
                    label="stop",
                    meaning="Leave this account blocked; do not repeat sign-in or signup.",
                ),
            ],
        )
        self.update(waiting=[q for q in self.view.waiting if q.subject != asked.subject] + [asked])
        if self.human is None:
            self.save()
            return
        control = HumanBrowser(browser, step, account, before_write=before_write)
        control.submitted = submitted
        deadline = time.monotonic() + 300
        completed = False
        private_stop = False
        self.update(
            status="handoff", activity=f"Complete the private challenge for {account.label}."
        )
        self.save()
        try:
            self.human.publish(control.snapshot(challenge))
            for _ in range(64):
                event = None
                while event is None:
                    self.check_live()
                    if self._egress is not None:
                        self._egress.live()
                    if time.monotonic() >= deadline:
                        raise Halt(
                            "paused",
                            "The human challenge timed out. Its protected interim state is kept.",
                        )
                    event = self.human.take()
                self.check_live()
                if event.kind == "pause":
                    raise Halt(
                        "paused", "Human completion paused. The protected interim session is kept."
                    )
                if event.kind == "completed":
                    config = self.scope.login if step.action == "sign_in" else self.scope.signup
                    problem = (
                        self.confirmed(browser, http, account.account_id, config, step.step_id)
                        if config
                        else "No sign-in check is configured."
                    )
                    if problem is None:
                        self.complete_handoff(browser, step, account, asked.subject)
                        completed = True
                        return
                    self.human.publish(
                        control.snapshot(challenge, "Sign-in is not confirmed. " + problem)
                    )
                    continue
                try:
                    if event.kind == "submit":
                        control.submission()  # refuse before recording an attempt
                        self.keep_handoff(
                            browser, step, challenge, before_write=before_write, submitted=True
                        )
                        self.set_step(
                            step.step_id,
                            "uncertain",
                            "Human challenge submission started; "
                            "it is never repeated automatically.",
                        )
                        if self._egress is None:
                            raise ValueError("No approved network action is active.")
                        with self._egress.action(step.step_id, account.account_id):
                            control.input(event)
                        self.set_step(
                            step.step_id,
                            "blocked",
                            "Human challenge submitted once. Explicit completion "
                            "and sign-in checks are still required.",
                        )
                    else:
                        control.input(event)
                    self.keep_handoff(
                        browser,
                        step,
                        challenge,
                        before_write=before_write,
                        submitted=control.submitted,
                    )
                    self.human.publish(control.snapshot(challenge))
                except UncertainWrite:
                    self.set_account(
                        account.account_id,
                        "uncertain",
                        "The human challenge submission is uncertain; it is not repeated.",
                    )
                    raise Halt(
                        "paused", "The human challenge submission is uncertain; it is not repeated."
                    ) from None
                except (ValueError, EgressRefused) as error:
                    self.human.publish(
                        control.snapshot(challenge, self.redactor().text(str(error))[:300])
                    )
            raise Halt("paused", "The human interaction limit was reached. Interim state is kept.")
        except PrivacyStop as stop:
            private_stop = True
            self.incident(
                step.step_id,
                self.scope.login.path if self.scope.login else self.scope.start_path,
                stop,
            )
            self.store.forget_session(self.view.journey_id, account.account_id)
            self.set_account(
                account.account_id, "failed", "Human completion stopped on unexpected private data."
            )
            self.set_step(
                step.step_id, "blocked", "Human completion stopped on unexpected private data."
            )
            self.update(waiting=[q for q in self.view.waiting if q.subject != asked.subject])
            raise Halt(
                "paused",
                "Human completion stopped on unexpected private data; the view was discarded.",
            ) from None
        finally:
            if not completed and not private_stop:
                self.keep_handoff(
                    browser, step, challenge, before_write=before_write, submitted=control.submitted
                )
            self.human.publish(None)

    def complete_handoff(
        self,
        browser: Any,  # noqa: ANN401 - the finite browser tools
        step: PlanStep,
        account: WebAccount,
        subject: str,
    ) -> None:
        self.sessions[account.account_id] = browser.session(account.account_id)
        state = browser.state(account.account_id)
        kept = bool(state) and self.store.keep_session(
            self.view.journey_id, account.account_id, state
        )
        self.set_account(
            account.account_id,
            "signed_in" if step.action == "sign_in" else "created",
            "Human completion was confirmed and the approved sign-in check passed.",
            kept=kept,
        )
        affected = {
            s.step_id
            for s in self.view.plan.steps
            if s.stage in {"map", "check"}
            and (
                s.account_id == account.account_id
                or (
                    s.object_id in self.objects
                    and self.objects[str(s.object_id)].owner_account_id == account.account_id
                )
            )
        }
        self.update(
            status="running",
            waiting=[q for q in self.view.waiting if q.subject != subject],
            steps=[
                StepRecord(step_id=s.step_id, action=s.action)
                if s.step_id in affected and s.state in {"blocked", "skipped"}
                else s
                for s in self.view.steps
            ],
            checks=[
                c
                for c in self.view.checks
                if not (c.check_id in affected and c.state != "completed")
            ],
            handoffs=[
                line for line in self.view.handoffs if not line.startswith(account.label + ":")
            ],
        )
        self.decided(
            "authenticate",
            subject,
            Decision(
                kind="human_auth",
                value="completed",
                rung="user",
                reason="The user explicitly confirmed completion; "
                "code revalidated the approved account.",
            ),
        )
        self.set_step(
            step.step_id, "completed", "Human completion and the approved sign-in check passed."
        )

    def map(self, browser: Any, http: HttpAdapter, step: PlanStep) -> None:  # noqa: ANN401
        if self.runnable(step.step_id) is None:
            return
        account_id = step.account_id
        if account_id is not None and self.account_state(account_id) not in {
            "signed_in",
            "created",
        }:
            return self.set_step(step.step_id, "skipped", "This account is not signed in.")
        self.say("map", f"Mapping pages as {account_id or 'a signed-out visitor'}.")
        self.set_step(step.step_id, "attempted")
        queue = [self.scope.start_path]
        login = self.scope.login
        if account_id is not None and login is not None and login.success_path:
            queue.insert(0, login.success_path)
        seen: set[str] = set()
        skipped = 0
        while queue and len(seen) < MAP_PAGES:
            path = queue.pop(0)
            if path in seen:
                continue
            seen.add(path)
            bound = self.look(browser, http, account_id, self.url(path), step.step_id)
            if bound is None:
                continue
            for link in bound.observation.links:
                target = bound.links.get(link.ref)
                if target is None or target.origin != self.scope.origin or target.query:
                    continue
                if _RISKY_LINK.search(link.text + " " + target.path):
                    skipped += 1
                    continue
                if target.path not in seen and target.path not in queue:
                    queue.append(target.path)
            self.save()
        note = f"{len(seen)} page(s) visited."
        if queue:
            note += f" {len(queue)} more linked page(s) were not visited (page limit)."
        if skipped:
            note += f" {skipped} link(s) that looked like sign-out or removal were not followed."
        self.set_step(step.step_id, "completed", note)

    def read_object(
        self, http: HttpAdapter, account_id: str | None, object_id: str
    ) -> tuple[WebEvidence, dict[str, str]]:
        item = self.objects[object_id]
        session = self.sessions.get(account_id or "", HttpSession(account_id))
        result = http.request(session, "GET", self.url(item.path))
        # Check the entire bounded response before retaining a preview. A prefix is
        # neither the complete privacy boundary nor evidence that two objects match.
        body = result.text()
        if kinds := personal_data(body, frozenset({*self.expected, item.marker or ""})):
            raise PrivacyStop(kinds)
        body = self.redactor().text(body)
        marker = "not declared" if item.marker is None else ("yes" if item.marker in body else "no")
        marker_at = body.find(item.marker) if item.marker is not None else -1
        marker_excerpt = (
            body[max(0, marker_at - 80) : marker_at + len(item.marker or "") + 80]
            if marker_at >= 0
            else "(none)"
        )
        fields = {
            "request.method": "GET",
            "request.path": item.path,
            "request.account": account_id or "signed out",
            "response.status": str(result.status),
            "response.content_type": result.headers.get("content-type", "not sent"),
            "response.marker_present": marker,
            "response.marker_excerpt": marker_excerpt,
            "response.capture_complete": "no" if result.truncated else "yes",
            "response.body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "response.body_bytes": str(len(result.body)),
            "response.preview_complete": "yes" if len(body) <= 2000 else "no",
            "response.body": body[:2000] or "(empty)",
        }
        evidence = self.evidence(
            "response",
            "http",
            fields,
            account_id=account_id,
            object_id=object_id,
            provenance="Read by Plumb's HTTP adapter with this account's own session",
        )
        return evidence, fields

    def compare(self, http: HttpAdapter, step: PlanStep) -> None:
        if self.runnable(step.step_id) is None:
            return
        rule_id = next(
            r.rule_id
            for r in self.scope.rules
            if step.step_id == f"check-{r.rule_id}-{step.account_id}"
        )
        item = self.objects[str(step.object_id)]
        owner, other = item.owner_account_id, str(step.account_id)
        check = CheckRecord(
            check_id=step.step_id,
            rule_id=rule_id,
            object_id=item.object_id,
            path=item.path,
            owner_account_id=owner,
            other_account_id=other,
        )
        missing = [name for name in (owner, other) if name not in self.sessions]
        if missing:
            note = "Not run: no signed-in session for " + ", ".join(missing) + "."
            self.update(
                checks=[
                    *self.view.checks,
                    check.model_copy(update={"state": "blocked", "note": note}),
                ]
            )
            return self.set_step(step.step_id, "blocked", note)
        self.say("execute", f"Comparing what {owner} and {other} receive at {item.path}.")
        self.set_step(step.step_id, "attempted")
        try:
            control, control_fields = self.read_object(http, owner, item.object_id)
            attempt, attempt_fields = self.read_object(http, other, item.object_id)
            visitor, visitor_fields = self.read_object(http, None, item.object_id)
        except PrivacyStop as stop:
            self.incident(step.step_id, item.path, stop)
            self.update(
                checks=[
                    *self.view.checks,
                    check.model_copy(
                        update={"state": "blocked", "note": "Stopped: unexpected personal data."}
                    ),
                ]
            )
            return self.set_step(step.step_id, "blocked", "Stopped: unexpected personal data.")
        except EgressStopped:
            raise
        except (EgressRefused, UncertainWrite) as refused:
            note = f"Not completed: {refused}"
            self.update(
                checks=[
                    *self.view.checks,
                    check.model_copy(update={"state": "blocked", "note": note[:600]}),
                ]
            )
            return self.set_step(step.step_id, "blocked", note)
        # Everything below is computed by code from the three saved responses.
        owner_status, other_status = (
            int(control_fields["response.status"]),
            int(attempt_fields["response.status"]),
        )
        marker = item.marker is not None
        complete = all(
            fields["response.capture_complete"] == "yes"
            for fields in (control_fields, attempt_fields, visitor_fields)
        )
        owner_ok = (
            marker
            and complete
            and 200 <= owner_status < 300
            and (control_fields["response.marker_present"] == "yes")
        )
        same_body = attempt_fields["response.body_sha256"] == control_fields["response.body_sha256"]
        disclosed = (
            marker
            and complete
            and attempt_fields["response.marker_present"] == "yes"
            and 200 <= other_status < 300
        )
        denied = other_status in _DENIED and attempt_fields["response.marker_present"] != "yes"
        gaps: list[str] = []
        if not marker:
            comparison = "inconclusive"
            gaps.append(
                "No explicit synthetic object marker was declared. A successful response or "
                "an identical application shell does not establish that the object was returned."
            )
        elif not complete:
            comparison = "inconclusive"
            gaps.append("A response capture was truncated; complete object controls are missing.")
        elif not owner_ok:
            comparison = "inconclusive"
            gaps.append(
                "The owner's own request did not return the object, so there is no control."
            )
        elif disclosed:
            comparison = "candidate"
        elif denied:
            comparison = "protected"
        else:
            comparison = "inconclusive"
            gaps.append("The other account's response was neither a clear denial nor the object.")
        facts = {
            "owner status": str(owner_status),
            "owner received the object": (
                "unknown" if not marker or not complete else "yes" if owner_ok else "no"
            ),
            "other account status": str(other_status),
            "other account received the object": (
                "unknown" if not marker or not complete else "yes" if disclosed else "no"
            ),
            "responses are identical": "unknown" if not complete else "yes" if same_body else "no",
            "marker declared": "yes" if marker else "no",
            "object identity basis": "explicit synthetic marker" if marker else "unknown",
            "response captures complete": "yes" if complete else "no",
            "signed-out status": visitor_fields["response.status"],
        }
        wanted = (
            "request.account",
            "request.path",
            "response.status",
            "response.marker_present",
            "response.marker_excerpt",
            "response.capture_complete",
        )
        citations = [self.cite(e, f) for e in (control, attempt, visitor) for f in wanted]
        citations += [self.cite(e, "response.body_sha256") for e in (control, attempt)]
        self.update(
            checks=[
                *[c for c in self.view.checks if c.check_id != check.check_id],
                check.model_copy(
                    update={
                        "state": "completed",
                        "comparison": comparison,
                        "facts": facts,
                        "gaps": gaps,
                        "citations": citations,
                    }
                ),
            ]
        )
        self.set_step(
            step.step_id,
            "completed",
            f"Compared: {comparison}.",
            [control.evidence_id, attempt.evidence_id, visitor.evidence_id],
        )

    # --- challenge and record: three readings of the rule, then findings ----------------------

    def judge(self) -> None:
        candidates = [
            c for c in self.view.checks if c.comparison == "candidate" and c.judged is None
        ]
        if not candidates:
            return
        self.say(
            "challenge",
            f"Asking the local model about {len(candidates)} comparison(s)."
            if self.model is not None
            else f"{len(candidates)} comparison(s) stay leads: no model reads the rule.",
        )
        factory = self.model if self.model is not None else (lambda: nullcontext(None))
        with factory() as asker:
            for check in candidates:
                self.check_live()
                rule, item = self.rules[check.rule_id], self.objects[check.object_id]
                question = rule_question(
                    statement=rule.statement,
                    object_kind=item.kind,
                    owner=check.owner_account_id,
                    account=check.other_account_id,
                    account_is_owner=check.other_account_id == item.owner_account_id,
                    declared_allowed=check.other_account_id in rule.allowed_account_ids,
                    request=f"GET {check.path} as {check.other_account_id}",
                    outcome="status "
                    + check.facts["other account status"]
                    + "; the object was returned",
                    control=f"status {check.facts['owner status']}; the object was returned",
                )
                room = self.scope.budget.max_model_questions - self.view.spent.model_questions
                judgment = judge_three(question, asker if room >= 3 else None)
                self.count_model(judgment.attempts)
                supported = judgment.value == "forbidden"
                self.decided(
                    "challenge",
                    f"rule:{check.check_id}",
                    Decision(
                        kind=judgment.kind,
                        value=judgment.value,
                        rung="model" if judgment.value else "stop",
                        reason=judgment.reason
                        or ("Three independent readings agreed." if judgment.value else None),
                        attempts=judgment.attempts,
                    ),
                )
                self.update(
                    checks=[
                        c.model_copy(
                            update={
                                "judged": "supported" if supported else "not_confirmed",
                                "judgment": judgment.record(),
                                "note": "Three independent readings of the owner's rule agreed."
                                if supported
                                else "The comparison is complete, but the readings of the owner's "
                                "rule did not all agree or were not available. It stays a lead.",
                            }
                        )
                        if c.check_id == check.check_id
                        else c
                        for c in self.view.checks
                    ]
                )
                self.record_finding(check.check_id, asker)
                self.save()

    def record_finding(self, check_id: str, asker: Any) -> None:  # noqa: ANN401 - asker or None
        check = next(c for c in self.view.checks if c.check_id == check_id)
        rule, item = self.rules[check.rule_id], self.objects[check.object_id]
        owner, other, path = check.owner_account_id, check.other_account_id, check.path
        supported = check.judged == "supported"
        fallback = (
            f"The account {other} asked for {path} and received {item.kind}, which belongs to "
            f"{owner}. The owner's rule says: {rule.statement}"
        )
        facts = (
            Fact("owner's rule", rule.statement[:200]),
            Fact("object", item.kind[:200]),
            Fact("object belongs to", owner),
            Fact("requesting account", other),
            Fact("address", path),
            Fact("status for the requesting account", check.facts["other account status"]),
            Fact("status for the owner", check.facts["owner status"]),
        )
        room = self.scope.budget.max_model_questions - self.view.spent.model_questions
        writer = asker if room >= 1 and hasattr(asker, "text") else None
        wording = explain(
            f"{other} received an object that the owner's rule reserves for {owner}.",
            facts,
            fallback,
            writer,
            universe=[*self.accounts, *self.objects],
        )
        if writer is not None:
            self.update(
                spent=self.view.spent.model_copy(
                    update={"model_questions": self.view.spent.model_questions + 1}
                )
            )
        model_line = (
            "Local model: three independent closed readings of the owner's rule agreed."
            if supported
            else "Local model: the readings of the owner's rule did not all agree or were "
            "unavailable, so this is a lead from the comparison alone."
        )
        finding = Finding(
            finding_id=f"W-{len(self.view.findings) + 1:02}",
            title=f"{other} can read {item.kind} that belongs to {owner}"[:300],
            conclusion="supported" if supported else "candidate",
            description=fallback[:1024],
            affected_application=self.scope.name,
            affected_endpoint=f"GET {self.scope.origin}{path}"[:300],
            safe_reproduction=[
                f"Sign in as the test account {owner} and request GET {path}: "
                "the object is returned.",
                f"Sign in as the test account {other} and request GET {path}.",
                "Compare the two responses. Use only the designated synthetic object.",
            ],
            potential_impact=(
                f"If the same holds for real accounts, one {self.accounts[other].role} could read "
                f"another's {item.kind.split(' of ')[0]}. "
                "This was observed on one synthetic object only."
            )[:1024],
            evidence=check.citations,
            mitigation=(
                "Have the server check, for this address, that the signed-in account is allowed to "
                "receive the object before returning it. Which code enforces this is not visible "
                "from outside and is not guessed here."
            ),
            methodology=[
                "Cross-account comparison of one known synthetic object under two approved "
                "test accounts.",
                "The owner's own request is the control; a signed-out request is a second control.",
                "Status, marker presence and response equality are computed by code.",
            ],
            tools_and_models=[
                "Plumb website journey: HTTP adapter and pinned browser behind one egress broker.",
                model_line,
            ],
            limits=[
                "Observed once by Plumb's runner; not repeated, and no proof about other objects.",
                "No source code was read. The cause inside the application is unknown.",
            ],
            explanation=wording.text[:1024],
            explanation_source=wording.source,
            check_id=check_id,
        )
        self.update(findings=[*[f for f in self.view.findings if f.check_id != check_id], finding])

    def report(self, final: bool = True) -> None:
        from backend.web_report import write_report

        # Render the same final state that will be saved, but only complete the
        # report step after its validated file has actually been written.
        complete = "report" in self.plan and final and self.runnable("report") is not None
        snapshot = self.view.model_copy(
            update={
                "steps": [
                    step.model_copy(update={"state": "completed"})
                    if complete and step.step_id == "report"
                    else step
                    for step in self.view.steps
                ]
            }
        )
        path = write_report(self.settings, snapshot)
        self.update(report_path=str(path), steps=snapshot.steps)


# --- what the chat says about a journey: built by code from the saved record ----------------------


def journey_label(settings: Settings, journey_id: str) -> str:
    view = JourneyStore(settings).load(journey_id)
    return f"Website test of {view.scope.name} ({view.scope.origin})"[:256]


def journey_answer(settings: Settings, journey_id: str, prompt: str) -> ChatPart:
    """A cited summary of the saved journey. No model writes it and nothing is added to it."""
    view = JourneyStore(settings).load(journey_id)
    index = {item.evidence_id: item for item in view.evidence}
    cited: list[ConversationEvidence] = []
    lines = [
        f"This website test is {view.status}. {len(view.pages)} page observation(s), "
        f"{len(view.checks)} comparison(s), {len(view.findings)} finding(s) or lead(s)."
    ]
    for finding in view.findings[:4]:
        refs = []
        for ref in finding.evidence:
            item = index.get(ref.evidence_id)
            if (
                item is None
                or digest(item.fields.get(ref.field, "")) != ref.sha256
                or len(cited) >= 8
            ):
                continue
            number = f"R{len(cited) + 1:03}"
            cited.append(
                ConversationEvidence(
                    reference_id=number,
                    label=f"{item.evidence_id} · {ref.field}"
                    + (f" · {item.account_id}" if item.account_id else ""),
                    quote=item.fields[ref.field],
                    observation=EvidenceCitation(
                        artifact_id=item.evidence_id, field=ref.field, sha256=ref.sha256
                    ),
                )
            )
            refs.append(number)
        label = "Supported" if finding.conclusion == "supported" else "Lead (not confirmed)"
        lines.append(
            f"{label}: {finding.explanation} [{', '.join(refs)}]"
            if refs
            else f"{label}: {finding.explanation}"
        )
    if not view.findings:
        lines.append(
            "No supported finding. That does not mean the website is secure: only the approved "
            "checks ran."
        )
    text = " ".join(lines)[:8000]
    if not cited:
        return ChatPart(
            kind="notice",
            text=text,
            basis="Read from the saved journey record by code. No model wrote this.",
        )
    return ChatPart(
        kind="cited",
        text=text,
        basis="Read from the saved journey record by code; each reference is an exact saved value.",
        evidence=cited,
    )
