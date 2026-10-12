"""The private website report, and the validator its claims must pass (ADR-0028).

This validator is for web observations only. It is separate from the source
validator and never accepts a web observation as source proof. A report is
written even when nothing was found: it then says what ran, what could not run
and what was seen, and that "no supported finding" is not "the website is secure".
"""

from pathlib import Path

from backend.contracts.web import EvidenceRef, digest
from backend.contracts.web_journey import JourneyView
from backend.redaction import Redactor
from backend.settings import Settings
from backend.web_store import JourneyStore, replace_atomically

NOT_SECURE = (
    "No supported finding does not mean this website is secure. Only the approved checks "
    "below ran, on designated synthetic accounts and objects."
)


class ReportRefused(ValueError):
    """A claim does not rest on exactly the saved evidence. Nothing is written."""


def validate(view: JourneyView) -> None:
    """Every citation resolves to an exact saved value; every conclusion has its basis."""
    evidence = {item.evidence_id: item for item in view.evidence}
    if len(evidence) != len(view.evidence):
        raise ReportRefused("Evidence identifiers must be unique.")
    checks = {check.check_id: check for check in view.checks}

    def resolve(reference: EvidenceRef) -> None:
        item = evidence.get(reference.evidence_id)
        value = item.fields.get(reference.field) if item is not None else None
        if value is None or digest(value) != reference.sha256:
            raise ReportRefused("A citation does not match the saved evidence exactly.")

    for check in view.checks:
        for reference in check.citations:
            resolve(reference)
        if check.comparison == "candidate":
            item = next(
                (item for item in view.scope.objects if item.object_id == check.object_id), None
            )
            if item is None or item.marker is None:
                raise ReportRefused("An object comparison needs an explicit identity marker.")
            if (
                check.owner_account_id != item.owner_account_id
                or check.other_account_id == item.owner_account_id
                or check.other_account_id
                not in {account.account_id for account in view.scope.accounts}
                or check.path != item.path
            ):
                raise ReportRefused(
                    "An object comparison must bind the designated owner and object."
                )
            cited = {(reference.evidence_id, reference.field) for reference in check.citations}
            required = {
                "request.account",
                "request.path",
                "response.status",
                "response.marker_present",
                "response.marker_excerpt",
                "response.capture_complete",
            }
            for account in (check.owner_account_id, check.other_account_id, None):
                responses = [
                    saved
                    for saved in evidence.values()
                    if saved.kind == "response"
                    and saved.account_id == account
                    and saved.object_id == check.object_id
                    and all((saved.evidence_id, field) in cited for field in required)
                ]
                if len(responses) != 1:
                    raise ReportRefused(
                        "An object comparison must cite each exact response control."
                    )
                response = responses[0]
                fields = response.fields
                if (
                    fields["response.capture_complete"] != "yes"
                    or fields["request.path"] != item.path
                    or fields["request.account"] != (account or "signed out")
                ):
                    raise ReportRefused(
                        "An object comparison has incomplete or mismatched controls."
                    )
                if account is not None and (
                    len(fields["response.status"]) != 3
                    or not fields["response.status"].isascii()
                    or not fields["response.status"].isdigit()
                    or not 200 <= int(fields["response.status"]) < 300
                    or fields["response.marker_present"] != "yes"
                    or item.marker not in fields["response.marker_excerpt"]
                ):
                    raise ReportRefused(
                        "A response does not prove receipt of the designated object."
                    )
            if (
                check.facts.get("owner received the object") != "yes"
                or check.facts.get("other account received the object") != "yes"
                or check.facts.get("object identity basis") != "explicit synthetic marker"
                or check.facts.get("response captures complete") != "yes"
            ):
                raise ReportRefused(
                    "An object comparison's facts lack its proven identity controls."
                )
    for finding in view.findings:
        check = checks.get(finding.check_id)
        if check is None or check.comparison != "candidate":
            raise ReportRefused("A finding must rest on a completed comparison that code computed.")
        for reference in finding.evidence:
            resolve(reference)
        if {(r.evidence_id, r.field) for r in finding.evidence} != {
            (r.evidence_id, r.field) for r in check.citations
        }:
            raise ReportRefused("A finding cites exactly the fields its comparison rests on.")
        if finding.conclusion == "supported":
            attempts = (check.judgment or {}).get("attempts")
            agreed = (
                check.judged == "supported"
                and isinstance(attempts, list)
                and len(attempts) == 3
                and all(
                    isinstance(a, dict)
                    and a.get("outcome") == "answered"
                    and a.get("value") == "forbidden"
                    for a in attempts
                )
            )
            if not agreed:
                raise ReportRefused(
                    "A supported finding needs three agreeing independent readings of the rule."
                )


def _rung(rung: str) -> str:
    return {
        "code": "code",
        "model": "local model",
        "model_reordered": "local model, second independent try",
        "user": "asked of the user",
        "stop": "not decided",
    }[rung]


def markdown(view: JourneyView) -> str:
    validate(view)
    scope, spent = view.scope, view.spent
    where = "owned fixture" if scope.mode == "owned_fixture" else "external, by approved scope"
    done = [s for s in view.steps if s.state == "completed"]
    not_done = [s for s in view.steps if s.state != "completed"]
    summary = {step.step_id: step.summary for step in view.plan.steps}
    supported = [f for f in view.findings if f.conclusion == "supported"]
    leads = [f for f in view.findings if f.conclusion == "candidate"]
    out = [
        f"# Private website test report: {scope.name}",
        "",
        "Private and local. Review it before sharing any part of it.",
        "",
        f"- Website: {scope.origin} ({where})",
        f"- Purpose: {scope.purpose}",
        f"- Authorized by: {scope.authority.granted_by} ({scope.authority.reference})",
        f"- Journey: {view.journey_id}, status **{view.status}**"
        + (f" ({view.stop_reason})" if view.stop_reason else ""),
        f"- Used: {spent.requests} of {scope.budget.max_requests} requests, "
        f"{spent.bytes} of {scope.budget.max_bytes} bytes, {spent.seconds:.0f} of "
        f"{scope.budget.max_seconds} seconds, {spent.model_questions} of "
        f"{scope.budget.max_model_questions} model questions ({spent.model_seconds:.0f} s)",
        "",
        "## Result",
        "",
        f"{len(supported)} supported finding(s), {len(leads)} lead(s) not confirmed, "
        f"{sum(c.comparison == 'protected' for c in view.checks)} comparison(s) where the other "
        "account was denied.",
        "",
        NOT_SECURE,
        "",
        "## What ran",
        "",
    ]
    out += [
        f"- {summary.get(s.step_id, s.step_id)}" + (f" {s.note}" if s.note else "") for s in done
    ]
    out += ["" if done else "- Nothing completed.", "", "## What could not run", ""]
    out += [
        f"- {summary.get(s.step_id, s.step_id)} — **{s.state}**: {s.note or 'not reached'}"
        for s in not_done
    ] or ["- Every planned step completed."]
    out += [f"- Not in this plan: {line}" for line in view.plan.not_covered]
    if view.browser == "unavailable":
        out.append(f"- The browser was unavailable: {view.browser_note}")
    out += ["", "## Accounts", ""]
    out += [f"- {a.account_id}: {a.state.replace('_', ' ')}. {a.note}" for a in view.accounts] or [
        "- No account was used."
    ]
    for line in view.handoffs:
        out.append(f"- Needs a person: {line}")
    out += ["", "## Pages seen", ""]
    for page in view.pages:
        who = page.account_id or "signed out"
        kind = (
            f", {page.kind.replace('_', ' ')} (by {_rung(page.kind_rung)})"
            if page.kind and page.kind_rung
            else ""
        )
        forms = f", forms: {', '.join(page.forms)}" if page.forms else ""
        ref = f" [{page.evidence_id}]" if page.evidence_id else ""
        out.append(
            f"- `{page.path}` as {who}: status {page.status or 'not reported'}{kind}, "
            f"{page.links} link(s){forms}{ref}" + (f" — {page.note}" if page.note else "")
        )
    if not view.pages:
        out.append("- No page was observed.")
    out += ["", "## Comparisons", ""]
    for check in view.checks:
        refs = ", ".join(sorted({r.evidence_id for r in check.citations}))
        out.append(
            f"- `{check.path}`: owner {check.owner_account_id}, other account "
            f"{check.other_account_id} — **{check.comparison.replace('_', ' ')}**"
            + (f" [{refs}]" if refs else "")
        )
        out += [f"  - {name}: {value}" for name, value in check.facts.items()]
        out += [f"  - Gap: {gap}" for gap in check.gaps]
        if check.note:
            out.append(f"  - {check.note}")
    if not view.checks:
        out.append("- No comparison ran.")
    for finding in view.findings:
        label = "Supported finding" if finding.conclusion == "supported" else "Lead, not confirmed"
        out += [
            "",
            f"## {finding.finding_id} · {label}: {finding.title}",
            "",
            f"{finding.explanation}",
            "",
            "*Wording by: "
            + (
                "the local model, checked against its facts"
                if finding.explanation_source == "model"
                else "code, from the same facts"
            )
            + ".*",
            "",
            f"- Description: {finding.description}",
            f"- Affected application: {finding.affected_application}",
            f"- Affected endpoint: `{finding.affected_endpoint}`",
            "- Safe reproduction:",
            *[
                f"  {number}. {step}"
                for number, step in enumerate(finding.safe_reproduction, start=1)
            ],
            f"- Potential impact: {finding.potential_impact}",
            "- Evidence (sanitized, exact saved values): "
            + ", ".join(f"{r.evidence_id} `{r.field}`" for r in finding.evidence),
            f"- Mitigation: {finding.mitigation}",
            "- Methodology: " + " ".join(finding.methodology),
            "- Tools and model: " + " ".join(finding.tools_and_models),
            "- Runtime: observed once by Plumb's own runner; not a repeated or "
            "source-verified proof.",
            "- Limits: " + " ".join(finding.limits),
        ]
    out += ["", "## Other observations (leads, not findings)", ""]
    out += [f"- {line}" for line in view.leads] or ["- None recorded."]
    out += ["", "## Blocked requests", ""]
    out += [
        f"- {row.kind.replace('_', ' ')}: {row.host or '(no host)'}, "
        f"{row.count} time(s) — {row.reason}"
        for row in view.blocked
    ] or ["- Nothing was blocked."]
    if view.incidents:
        out += ["", "## Privacy stops", ""]
        out += [
            f"- At `{i.path}` ({i.step_id}): unexpected {', '.join(i.kinds)}. The page content "
            "was discarded; only this note was kept. Tell the website's owner privately."
            for i in view.incidents
        ]
    out += ["", "## Decisions and who made them", ""]
    for record in view.decisions:
        # An arrow, not a colon: "password: ..." would read as a credential to the redactor.
        out.append(
            f"- {record.question_type} · `{record.subject}` → "
            f"**{record.value or 'undecided'}** ({_rung(record.rung)})"
            + (f" — {record.reason}" if record.reason else "")
        )
    for question in view.waiting:
        out.append(f"- Waiting for your answer: {question.text}")
    if not view.decisions:
        out.append("- No decision needed a question; code decided everything.")
    out += ["", "## Evidence", ""]
    for item in view.evidence:
        who = item.account_id or "signed out"
        out.append(f"### {item.evidence_id} · {item.kind} · {who} · {item.provenance}")
        out += [f"- `{name}`: {value[:600]}" for name, value in item.fields.items()]
        out.append("")
    out += [
        "## Uncertainties and coverage",
        "",
        "- Only the pages, accounts and objects listed above were looked at.",
        "- A response difference or a missing header is a lead, not a vulnerability by itself.",
        "- Nothing here was verified in source code, and no internal cause is claimed.",
        f"- {NOT_SECURE}",
        "",
    ]
    return "\n".join(out)


def write_report(settings: Settings, view: JourneyView) -> Path:
    text = markdown(view)
    if Redactor.configured(settings).text(text) != text:
        raise ReportRefused("The report would contain a credential; it was not written.")
    path = JourneyStore(settings).folder(view.journey_id) / "report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    replace_atomically(temporary, path)
    return path
