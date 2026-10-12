"""One bounded plan from a frozen scope, and its one-use approval (ADR-0028).

The plan is made by code from the scope alone: no page has been visited and no
model is asked. It says in plain words what would be done, under which account,
how many requests each step may use, which steps change something on the
website, how many model questions may be asked and how long those may take.
"""

from datetime import UTC, datetime
from uuid import uuid4

from agent.asking import TimingLog, expected_wait
from backend.contracts.web import STATE_CHANGING, PlanApproval, PlanStep, WebsitePlan, WebsiteScope
from backend.contracts.web_journey import JourneyApprove, JourneyView

MAP_PAGES = 8
QUESTION_SECONDS = 120.0  # the limit of one closed question, used where nothing is measured


def make_plan(scope: WebsiteScope, timings: TimingLog | None, profile: str) -> WebsitePlan:
    allowed = set(scope.allowed_actions)
    steps: list[PlanStep] = []

    def add(
        step_id: str, stage: str, action: str, summary: str, requests: int, **more: str
    ) -> None:
        steps.append(
            PlanStep(
                step_id=step_id,
                stage=stage,  # ty: ignore[invalid-argument-type]
                action=action,  # ty: ignore[invalid-argument-type]
                summary=summary,
                state_changing=action in STATE_CHANGING,
                max_requests=requests,
                **more,
            )
        )

    not_covered: list[str] = []
    if "read" in allowed:
        add(
            "discover",
            "discover",
            "read",
            f"Open {scope.origin}{scope.start_path} without signing in and note its links "
            "and forms.",
            12,
        )
    signed_in: list[str] = []
    for account in scope.accounts:
        if account.provisioned and "sign_in" in allowed and scope.login is not None:
            add(
                f"signin-{account.account_id}",
                "authenticate",
                "sign_in",
                f"Sign in once as {account.label} on {scope.login.path} with its stored password.",
                12,
                account_id=account.account_id,
            )
            signed_in.append(account.account_id)
        elif not account.provisioned and "sign_up" in allowed and scope.signup is not None:
            effects = " ".join(scope.signup.approved_side_effects)
            add(
                f"signup-{account.account_id}",
                "authenticate",
                "sign_up",
                f"Create the synthetic account {account.label} once on {scope.signup.path}. "
                f"{effects}"[:300],
                12,
                account_id=account.account_id,
            )
            signed_in.append(account.account_id)
        else:
            not_covered.append(
                f"The account {account.label} is not used: no approved way to sign in."
            )
    if "read" in allowed:
        add(
            "map-visitor",
            "map",
            "read",
            f"Visit up to {MAP_PAGES} approved pages linked from the start page, signed out.",
            MAP_PAGES * 5,
        )
        for account_id in signed_in:
            add(
                f"map-{account_id}",
                "map",
                "read",
                f"Visit up to {MAP_PAGES} approved pages as {account_id}.",
                MAP_PAGES * 5,
                account_id=account_id,
            )
    checks = 0
    if "compare" in allowed:
        objects = {item.object_id: item for item in scope.objects}
        for rule in scope.rules:
            item = objects[rule.object_id]
            for account in scope.accounts:
                if account.account_id in rule.allowed_account_ids:
                    continue
                if account.account_id not in signed_in or item.owner_account_id not in signed_in:
                    continue
                checks += 1
                add(
                    f"check-{rule.rule_id}-{account.account_id}",
                    "check",
                    "compare",
                    f"Read {item.kind} at {item.path} as its owner {item.owner_account_id} and as "
                    f"{account.account_id}, and compare what each receives.",
                    4,
                    account_id=account.account_id,
                    object_id=item.object_id,
                )
    else:
        not_covered.append("No cross-account comparison: that action class is not approved.")
    if "report" in allowed:
        add(
            "report",
            "report",
            "report",
            "Write the private report of what ran and what was seen.",
            0,
        )
    if "submit_form" not in allowed:
        not_covered.append("No other form is submitted; forms are only described.")
    needed = sum(step.max_requests for step in steps)
    if needed > scope.budget.max_requests:
        not_covered.append(
            f"The steps may need up to {needed} requests and the budget is "
            f"{scope.budget.max_requests}: later steps stop when it is used up."
        )
    forms = len({step.action for step in steps if step.stage == "authenticate"})
    # The most the journey may ask: field and form questions where code cannot decide,
    # one ordering question, three readings of the rule and one wording per comparison.
    planned = [
        ("field_meaning", 2 * forms),
        ("form_purpose", forms),
        ("next_step", 1 if checks > 1 else 0),
        ("rule_covers", 3 * checks),
        ("explanation", checks),
    ]
    total = sum(count for _, count in planned)
    cap = scope.budget.max_model_questions
    if total > cap:
        not_covered.append(
            f"Up to {total} model questions could arise and {cap} are budgeted; "
            "the rest are decided by code, asked of you, or recorded as undecided."
        )
        scale = cap / total if total else 0
        planned = [(name, int(count * scale)) for name, count in planned]
    wait = expected_wait(timings, profile, planned, QUESTION_SECONDS)
    now = datetime.now(UTC)
    return WebsitePlan(
        plan_id="plan-" + uuid4().hex[:12],
        website_id=scope.website_id,
        scope_sha256=scope.sha256,
        steps=steps,
        budget=scope.budget,
        model_questions=min(cap, wait["questions"]),
        expected_model_seconds=wait["expected_seconds"],
        unmeasured_question_types=wait["unmeasured_types"],
        not_covered=[line[:300] for line in not_covered],
        created_at=now,
        expires_at=scope.expires_at,
    )


def approve(view: JourneyView, request: JourneyApprove, now: datetime | None = None) -> JourneyView:
    """Record the reviewer's approval of this exact plan. Nothing runs here."""
    now = now or datetime.now(UTC)
    if view.status != "planned":
        raise ValueError("This plan was already decided; make a new plan to change it")
    if request.plan_sha256 != view.plan.sha256 or view.plan.scope_sha256 != view.scope.sha256:
        raise ValueError("The plan changed after it was shown; review the current plan")
    if now >= view.scope.expires_at:
        raise ValueError("The scope has expired")
    known = [step.step_id for step in view.plan.steps]
    chosen = known if request.step_ids is None else request.step_ids
    if len(set(chosen)) != len(chosen) or not set(chosen) <= set(known):
        raise ValueError("Approval may only name steps of this plan, each once")
    approval = PlanApproval(
        plan_sha256=view.plan.sha256,
        approved_step_ids=chosen,
        approved_by=request.approved_by,
        granted_at=now,
        expires_at=view.scope.expires_at,
        reviewed_plan=True,
    )
    return view.model_copy(
        update={
            "approval": approval,
            "status": "approved",
            "activity": "Approved. Nothing has been visited yet.",
            "updated_at": now,
        }
    )


def revoke(view: JourneyView, now: datetime | None = None) -> JourneyView:
    """Withdraw the approval. Completed work is kept; nothing more runs under it."""
    now = now or datetime.now(UTC)
    if view.approval is None or view.approval_revoked_at is not None:
        raise ValueError("There is no approval in force to withdraw")
    return view.model_copy(
        update={
            "approval_revoked_at": now,
            "status": "stopped" if view.status != "done" else "done",
            "stop_reason": view.stop_reason or "The approval was withdrawn by the reviewer.",
            "activity": "Approval withdrawn. Nothing more will run.",
            "updated_at": now,
        }
    )


def approval_in_force(view: JourneyView, now: datetime | None = None) -> str | None:
    """None when the journey may run now; otherwise the reason it may not."""
    now = now or datetime.now(UTC)
    approval = view.approval
    if approval is None:
        return "The plan has not been approved."
    if view.approval_revoked_at is not None:
        return "The approval was withdrawn."
    if approval.plan_sha256 != view.plan.sha256 or view.plan.scope_sha256 != view.scope.sha256:
        return "The scope or plan changed after approval."
    if now >= approval.expires_at or now >= view.scope.expires_at:
        return "The scope or its approval has expired."
    return None
