"""Terminal entry for authorized website tests (ADR-0028).

    plumb website                       saved website tests and their status
    plumb website fixture               the owned fixture, end to end (no external site)
    plumb website setup                 describe an external scope; nothing is visited
    plumb website run <journey-id>      run or resume an approved test
    plumb website show <journey-id>     what ran, what is waiting
    plumb website report <journey-id>   the private report
    plumb website stop <journey-id>     withdraw the approval
    plumb website qualify               check the network boundary on this computer

A test never starts from a message or a flag alone: the plan is printed and the
terminal asks for an explicit yes.
"""

import argparse
import getpass
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from backend.chat import Chats
from backend.contracts.assessment import ScopeAuthority
from backend.contracts.chat import ChatCreate, ChatView
from backend.contracts.web import (
    ActionClass,
    LoginConfig,
    OwnerRule,
    SignupConfig,
    WebAccount,
    WebBudget,
    WebObject,
    WebsiteScope,
    WebTarget,
)
from backend.contracts.web_journey import JourneyApprove, JourneyView, UserQuestion
from backend.settings import Settings
from backend.web_journey import new_journey
from backend.web_plan import approve, revoke
from backend.web_run import run_journey
from backend.web_store import JourneyStore
from backend.web_urls import UrlRefused, parse_url
from verification.web_fixture import Fixture
from verification.web_secrets import SecretStore, env_name

Read = Callable[[str], str]
Write = Callable[[str], None]


def add_website_arguments(commands: argparse._SubParsersAction) -> None:
    website = commands.add_parser(
        "website", help="Test an authorized website inside limits you approve first"
    )
    website.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "fixture", "setup", "run", "show", "report", "stop", "qualify"],
    )
    website.add_argument("journey_id", nargs="?")
    website.add_argument("--variant", choices=["open", "defended"], default="open")
    website.add_argument("--no-model", action="store_true", help="Decide by code and by you only")
    website.add_argument("--profile", default="auto")
    website.add_argument("--yes", action="store_true", help="Approve the printed plan")


def plan_text(view: JourneyView) -> str:
    plan, scope = view.plan, view.scope
    lines = [
        f"Plan for {scope.name}",
        f"  Website: {', '.join(target.origin for target in scope.targets)}",
        f"  Approved paths: {', '.join(path for target in scope.targets for path in target.paths)}",
        f"  Purpose: {scope.purpose}",
        f"  Authorized by: {scope.authority.granted_by} ({scope.authority.reference})",
        f"  Valid until: {scope.expires_at.astimezone().strftime('%d %B %Y %H:%M')}",
        f"  Limits: {plan.budget.max_requests} requests, {plan.budget.max_seconds} seconds, "
        f"{plan.budget.max_bytes // (1024 * 1024)} MiB, {plan.budget.max_model_questions} "
        "model questions",
        "",
        "  Steps:",
    ]
    for number, step in enumerate(plan.steps, start=1):
        mark = "  (changes something on the website)" if step.state_changing else ""
        lines.append(f"   {number}. {step.summary}{mark}")
    seconds = plan.expected_model_seconds
    wait = (
        f"up to about {seconds / 60:.0f} minute(s)" if seconds >= 90 else f"about {seconds:.0f} s"
    )
    lines.append("")
    lines.append(
        f"  The local model may be asked up to {plan.model_questions} closed question(s): {wait}."
    )
    if plan.unmeasured_question_types:
        lines.append(
            "  That wait is an upper limit, not a measurement, for: "
            + ", ".join(plan.unmeasured_question_types)
            + "."
        )
    for line in plan.not_covered:
        lines.append(f"  Not in this plan: {line}")
    return "\n".join(lines)


def activity_text(view: JourneyView) -> str:
    done = sum(step.state == "completed" for step in view.steps)
    lines = [
        f"{view.journey_id}: {view.status} — {view.activity}",
        f"  Steps: {done} of {len(view.steps)} completed. Pages seen: {len(view.pages)}. "
        f"Comparisons: {len(view.checks)}. Findings or leads: {len(view.findings)}.",
        f"  Used: {view.spent.requests} requests, {view.spent.seconds:.0f} s, "
        f"{view.spent.model_questions} model questions.",
    ]
    for account in view.accounts:
        lines.append(f"  Account {account.account_id}: {account.state.replace('_', ' ')}")
    for step in view.steps:
        if step.state != "completed":
            lines.append(f"  {step.step_id}: {step.state} — {step.note or 'not reached'}")
    for question in view.waiting:
        lines.append(f"  Waiting for your answer: {question.text}")
    if view.blocked:
        lines.append(f"  Blocked requests: {sum(row.count for row in view.blocked)}")
    if view.report_path:
        lines.append(f"  Report: {view.report_path}")
    return "\n".join(lines)


def terminal_asker(read: Read, write: Write) -> Callable[[UserQuestion], str | None]:
    def ask(question: UserQuestion) -> str | None:
        write("\n" + question.text)
        for number, choice in enumerate(question.choices, start=1):
            write(f"  {number}. {choice.meaning}")
        try:
            answer = read("Your answer (number, or Enter to leave it open) > ")
            answer = answer.strip().lstrip("\ufeff")
        except (EOFError, OSError):
            return None  # nobody is at the terminal: the question stays open
        if answer.isdigit() and 1 <= int(answer) <= len(question.choices):
            return question.choices[int(answer) - 1].label
        return None

    return ask


def confirm_and_approve(
    view: JourneyView, settings: Settings, read: Read, write: Write, yes: bool
) -> JourneyView | None:
    write(plan_text(view))
    if not yes and read("\nApprove exactly this plan? [y/N] > ").strip().lower() not in {
        "y",
        "yes",
    }:
        write("Not approved. Nothing was visited.")
        return None
    reviewer = (
        "terminal user" if yes else (read("Your name for the record > ").strip() or "terminal user")
    )
    view = approve(
        view,
        JourneyApprove(
            plan_sha256=view.plan.sha256, approved_by=reviewer[:300], reviewed_plan=True
        ),
    )
    JourneyStore(settings).save(view)
    return view


def ask_secrets(view: JourneyView, store: SecretStore, write: Write) -> None:
    """Passwords for provisioned accounts: from the environment, or typed without echo."""
    refs = [
        a.secret_ref for a in view.scope.accounts if a.provisioned and not store.has(a.secret_ref)
    ]
    for ref in store.load_environment(refs):
        account = next(a for a in view.scope.accounts if a.secret_ref == ref)
        try:
            value = getpass.getpass(
                f"Password for the test account {account.label} "
                f"(or set {env_name(ref)}; Enter to skip) > "
            )
        except (EOFError, OSError):
            value = ""
        if value:
            store.put(ref, value)
        else:
            write(f"No password for {account.label}; that account will not be used.")


def lines(read: Read, prompt: str) -> list[str]:
    return [part.strip() for part in read(prompt).split(",") if part.strip()]


def wizard(read: Read, write: Write, address: str | None = None) -> WebsiteScope | None:
    """Ask for the scope in plain words. Nothing is visited and nothing is assumed."""
    write(
        "\nSetting up a website test. I will ask what is approved; I assume nothing, and "
        "linked sites, CDNs and sign-in providers are not included unless you list them."
    )
    address = address or read("Website address (https://...) > ").strip()
    try:
        origin = parse_url(address if "://" in address else "https://" + address).origin
    except UrlRefused as refused:
        write(f"That address cannot be used: {refused}.")
        return None
    if not origin.startswith("https://"):
        write(
            "Only https websites can be tested. For Plumb's own practice site run: "
            "plumb website fixture"
        )
        return None
    paths = lines(read, "Approved paths, comma separated [/] > ") or ["/"]
    start = read("Page to start from [/] > ").strip() or "/"
    purpose = read("What is this test for? > ").strip()
    granted_by = read("Who authorized this test (name and role)? > ").strip()
    reference = read("Reference for that authorization (ticket, email, date) > ").strip()
    if not purpose or not granted_by or not reference:
        write("A purpose and an authorization are required. Nothing was saved.")
        return None
    accounts: list[WebAccount] = []
    while len(accounts) < 6:
        name = read(
            f"Test account {len(accounts) + 1}: a short id (Enter when there are no more) > "
        ).strip()
        if not name:
            break
        exists = read("  Does this account already exist? [Y/n] > ").strip().lower() not in {
            "n",
            "no",
        }
        accounts.append(
            WebAccount(
                account_id=name,
                role=read("  Its role (for example customer) > ").strip() or "user",
                label=read("  A label for reports > ").strip() or name,
                username=read("  Its username or sign-in email > ").strip() or name,
                secret_ref="acct-" + name,
                provisioned=exists,
                contact_email=read("  Synthetic email for sign-up (Enter for none) > ").strip()
                or None,
            )
        )
    login = signup = None
    if any(account.provisioned for account in accounts):
        login = LoginConfig(
            path=read("Sign-in page path [/login] > ").strip() or "/login",
            success_path=read(
                "Path that only a signed-in account can open (Enter for none) > "
            ).strip()
            or None,
            success_text=read("Text shown only after signing in (Enter for none) > ").strip()
            or None,
        )
    if any(not account.provisioned for account in accounts):
        signup = SignupConfig(
            path=read("Sign-up page path [/signup] > ").strip() or "/signup",
            approved_side_effects=lines(
                read, "What creating an account does besides that, as approved > "
            )
            or ["Creates one synthetic account."],
            sends_messages=read("Does sign-up send an email or SMS? [y/N] > ").strip().lower()
            in {"y", "yes"},
            success_text=read("Text shown only after the account exists > ").strip() or None,
            success_path=None,
        )
    objects: list[WebObject] = []
    rules: list[OwnerRule] = []
    while accounts and len(objects) < 10:
        path = read(
            f"Known synthetic object {len(objects) + 1}: its exact path "
            "(Enter when there are no more) > "
        ).strip()
        if not path:
            break
        identifier = f"object-{len(objects) + 1}"
        owner = (
            read(f"  Which test account owns it? [{accounts[0].account_id}] > ").strip()
            or accounts[0].account_id
        )
        kind = read("  What is it (for example invoice 12)? > ").strip() or "object"
        marker = read("  A value only the owner's view shows (Enter for none) > ").strip() or None
        statement = read("  The owner's rule in one sentence > ").strip() or (
            f"Only {owner} may read {kind}."
        )
        objects.append(
            WebObject(
                object_id=identifier, owner_account_id=owner, kind=kind, path=path, marker=marker
            )
        )
        rules.append(
            OwnerRule(
                rule_id=f"rule-{len(rules) + 1}",
                statement=statement,
                object_id=identifier,
                allowed_account_ids=[owner],
                declared_by=granted_by,
                basis=reference,
            )
        )
    actions: list[ActionClass] = ["read", "report"]
    if login is not None:
        actions.append("sign_in")
    if signup is not None:
        actions.append("sign_up")
    if rules and len(accounts) >= 2:
        actions.append("compare")
    hours = read("Valid for how many hours? [4] > ").strip()
    requests = read("Most requests in total [200] > ").strip()
    now = datetime.now(UTC)
    write("\nThe exact targets are: " + origin + " with paths " + ", ".join(paths) + ".")
    if read(
        "Is this list complete and authorized, with nothing else included? [y/N] > "
    ).strip().lower() not in {"y", "yes"}:
        write("Not confirmed. Nothing was saved.")
        return None
    return WebsiteScope(
        scope_id="scope-" + uuid4().hex[:12],
        website_id="website-" + uuid4().hex[:12],
        name=read("A name for this website in reports > ").strip() or origin,
        mode="external",
        targets=[WebTarget(origin=origin, paths=paths)],
        start_path=start,
        purpose=purpose,
        authority=ScopeAuthority(granted_by=granted_by, reference=reference, granted_at=now),
        accounts=accounts,
        objects=objects,
        rules=rules,
        allowed_actions=actions,
        login=login,
        signup=signup,
        expires_at=now
        + timedelta(hours=float(hours) if hours.replace(".", "", 1).isdigit() else 4),
        budget=WebBudget(max_requests=int(requests) if requests.isdigit() else 200),
        stop_conditions=[
            "Unexpected personal data appears.",
            "A request would leave the approved origin or paths.",
            "The site shows signs of harm to real users or data.",
        ],
        public_values=lines(
            read, "Contact details the site shows to everyone (comma separated) > "
        ),
        confirmed_targets=True,
    )


def run_and_show(
    settings: Settings,
    view: JourneyView,
    store: SecretStore,
    read: Read,
    write: Write,
    *,
    fixture: Fixture | None = None,
    use_model: bool,
    profile: str,
) -> JourneyView:
    cancel = threading.Event()
    shown = [""]

    def progress(current: JourneyView) -> None:
        if current.activity != shown[0]:
            shown[0] = current.activity
            write("  … " + current.activity)

    try:
        view, notes = run_journey(
            settings,
            view.journey_id,
            secrets=store,
            cancel=cancel,
            fixture=fixture,
            use_model=use_model,
            profile=profile,
            ask_user=terminal_asker(read, write),
            on_update=progress,
        )
    except KeyboardInterrupt:
        cancel.set()
        write("Stopping. Completed work is kept; run it again to continue.")
        return JourneyStore(settings).load(view.journey_id)
    for note in notes:
        write("  Note: " + note)
    write("\n" + activity_text(view))
    return view


def fixture_command(settings: Settings, args: argparse.Namespace, read: Read, write: Write) -> int:
    from verification.web_fixture import FixtureUnavailable, launch

    write(
        f"Starting Plumb's own practice website (variant: {args.variant}) on this computer. "
        "No external site is contacted."
    )
    try:
        with launch(args.variant, settings) as fixture:
            view = new_journey(settings, fixture.scope(), args.profile)
            approved = confirm_and_approve(view, settings, read, write, args.yes)
            if approved is None:
                return 1
            view = run_and_show(
                settings,
                approved,
                fixture.secrets,
                read,
                write,
                fixture=fixture,
                use_model=not args.no_model,
                profile=args.profile,
            )
    except FixtureUnavailable as error:
        write(f"The practice website could not start: {error}")
        return 1
    return 0 if view.status == "done" else 2


def execute_website(
    settings: Settings, args: argparse.Namespace, read: Read | None = None, write: Write = print
) -> int:
    read = read or input
    store = JourneyStore(settings)
    try:
        if args.action == "list":
            journeys = store.list()
            if not journeys:
                write("No website test is saved. Try: plumb website fixture")
            for view in journeys:
                write(f"{view.journey_id}  {view.status:8}  {view.scope.name}")
            return 0
        if args.action == "qualify":
            from backend.web_boundary import qualify

            write("Checking the network boundary with the pinned browser. About a minute.")
            record = qualify(settings)
            for check in record["checks"]:
                write(f"  {'ok  ' if check['passed'] else 'FAIL'} {check['check']}")
            if record["error"]:
                write("  Error: " + record["error"])
            write(
                "Qualified: external websites may be tested under an approved scope."
                if record["passed"]
                else "Not qualified: external websites stay disabled."
            )
            return 0 if record["passed"] else 1
        if args.action == "fixture":
            return fixture_command(settings, args, read, write)
        if args.action == "setup":
            scope = wizard(read, write)
            if scope is None:
                return 1
            view = new_journey(settings, scope, args.profile)
            write(f"\nSaved as {view.journey_id}. Nothing has been visited.")
            if confirm_and_approve(view, settings, read, write, False) is not None:
                write(f"Approved. Start it with: plumb website run {view.journey_id}")
            return 0
        if not args.journey_id:
            write("Name the website test: plumb website (lists them)")
            return 2
        view = store.load(args.journey_id)
        if args.action == "show":
            write(activity_text(view))
            return 0
        if args.action == "report":
            if not view.report_path or not Path(view.report_path).is_file():
                write("This website test has no report yet.")
                return 1
            write(Path(view.report_path).read_text(encoding="utf-8"))
            return 0
        if args.action == "stop":
            store.save(revoke(view))
            write("Approval withdrawn. Nothing more will run; completed work is kept.")
            return 0
        if view.scope.mode == "owned_fixture":
            write("A practice-site test runs with its fixture: plumb website fixture")
            return 2
        if (
            view.status == "planned"
            and confirm_and_approve(view, settings, read, write, args.yes) is None
        ):
            return 1
        view = store.load(args.journey_id)
        if view.status not in {"approved", "paused", "handoff"}:
            write(f"This website test is {view.status}; there is nothing to run.")
            return 2
        secrets = SecretStore()
        ask_secrets(view, secrets, write)
        view = run_and_show(
            settings, view, secrets, read, write, use_model=not args.no_model, profile=args.profile
        )
        return 0 if view.status == "done" else 2
    except (OSError, ValueError) as error:
        write(f"Website command stopped: {error}")
        return 1


def setup_from_chat(
    worker: Chats, view: ChatView, url: str | None, read: Read, write: Write
) -> ChatView:
    """The chat's website proposal, continued by an explicit yes: scope, plan, approval."""
    settings = worker.settings
    scope = wizard(read, write, url)
    if scope is None:
        return view
    journey = new_journey(settings, scope)
    write(f"\nSaved as {journey.journey_id}. Nothing has been visited.")
    approved = confirm_and_approve(journey, settings, read, write, False)
    if approved is not None and read("Run it now? [y/N] > ").strip().lower() in {"y", "yes"}:
        secrets = SecretStore()
        ask_secrets(approved, secrets, write)
        run_and_show(settings, approved, secrets, read, write, use_model=True, profile="auto")
    try:
        view = worker.select(
            view.chat_id, ChatCreate(target_kind="website", target_id=journey.journey_id)
        )
        write("This website test is now selected: ask about it in your own words.")
    except (OSError, ValueError):
        write(f"Saved. Continue with: plumb website show {journey.journey_id}")
    return view
