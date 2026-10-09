"""Readable offline report. Only trusted CSS gets a CSP hash; no scripts or network."""

from __future__ import annotations

import base64
import hashlib
import html
from collections import Counter
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

from backend.contracts.investigation import Conclusion, Finding, RuntimeVerification
from backend.contracts.verification import Access, ProbeOutcome, ProbeRun, StepRole

if TYPE_CHECKING:
    from backend.reports import ReportBundle

CSS = Path(__file__).with_name("html.css")
GLYPHS = {"supported": "●", "rejected": "⊘", "inconclusive": "◐", "candidate": "○"}
CONCLUSIONS = {
    "supported": "Source evidence supports this finding. Review the cited path.",
    "rejected": "A cited protection disproves this finding on the inspected path.",
    "inconclusive": "The evidence does not settle whether this path is protected.",
    "candidate": "This is a lead that still needs investigation.",
}
RUNTIME = {
    "not_attempted": ("Not tested", "No runtime check was attempted for this finding."),
    "unavailable": ("Unavailable", "A runtime check could not run. See the recorded limits."),
    "inconclusive": ("Inconclusive", "The runtime observations do not settle this finding."),
    "reproduced": (
        "Reproduced",
        "The attack exposed the victim marker and the owner control succeeded.",
    ),
    "not_reproduced": (
        "Not reproduced under tested conditions",
        "The attack was denied and the owner control succeeded in the recorded check.",
    ),
}


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def badge(conclusion: Conclusion) -> str:
    return (
        f'<span class="badge"><span aria-hidden="true">{GLYPHS[conclusion.value]}</span>'
        f"{escape(conclusion.value.capitalize())}</span>"
    )


def citation(finding: Finding, tag: str) -> str:
    # Display IDs and exhibit tags have contract-enforced alphabets; no target URLs.
    return f'<a class="tag" href="#{finding.display_id}-{tag}">{finding.display_id}/{tag}</a>'


def probe_html(probe: ProbeRun) -> str:
    steps = []
    for index, step in enumerate(probe.steps, 1):
        risk = step.role is StepRole.ATTACK and step.observed is Access.ALLOWED
        uncertain = (step.role is StepRole.ATTACK and step.observed is None) or (
            step.role is StepRole.CONTROL and step.observed is not Access.ALLOWED
        )
        tone = " risk" if risk else " attention" if uncertain else ""
        role = {"setup": "Setup", "attack": "Cross-user check", "control": "Owner control"}[
            step.role.value
        ]
        marker = {
            True: "Victim marker present",
            False: "Victim marker absent",
            None: "Marker unknown",
        }[step.marker_present]
        status = f"HTTP {step.status}" if step.status is not None else "No response"
        steps.append(
            f'<li class="probe-step{tone}"><p class="step-role">{index}. {role}</p>'
            f'<p class="step-person">As {escape(step.principal)}</p>'
            f'<p class="step-result">{status}</p><p class="step-detail">{marker}</p>'
            f'<p class="step-detail mono">{escape(step.method)} {escape(step.path)}</p>'
            f'<p class="step-detail muted">Expected if safe: {step.expected_if_safe.value}</p>'
            + (f'<p class="step-detail">{escape(step.error)}</p>' if step.error else "")
            + "</li>"
        )
    return (
        '<div class="probe"><h4>Recorded runtime check</h4>'
        f'<p class="meta">{escape(probe.runner.value.replace("_", " "))} · '
        f"{'Original' if probe.snapshot_role.value == 'vulnerable' else 'Patched'} snapshot · "
        f"{escape(probe.outcome.value.replace('_', ' '))}</p>"
        '<p class="step-detail">The victim marker is a unique value used to track '
        "the owner's test data. Its presence in another user's response shows exposure.</p>"
        f'<ol class="probe-flow">{"".join(steps)}</ol>'
        "<details><summary>Probe record and hashes</summary>"
        f"<pre>{escape(probe.model_dump_json(indent=2))}</pre></details></div>"
    )


def observed_summary(probe: ProbeRun) -> str:
    attack = next((s for s in probe.steps if s.role is StepRole.ATTACK), None)
    control = next((s for s in probe.steps if s.role is StepRole.CONTROL), None)
    if attack is None or control is None:
        return "Recorded check is inconclusive."
    if probe.outcome is ProbeOutcome.REPRODUCED:
        return (
            f"{attack.principal} received the owner's test marker. "
            f"Owner access as {control.principal} also succeeded."
        )
    if probe.outcome is ProbeOutcome.NOT_REPRODUCED:
        return (
            f"Access as {attack.principal} was denied. "
            f"Owner access as {control.principal} succeeded under these conditions."
        )
    return f"Recorded check: {probe.outcome.value.replace('_', ' ')}."


def case_html(finding: Finding, bundle: ReportBundle) -> str:
    runtime_title, runtime_text = RUNTIME[finding.runtime_verification.value]
    runtime_tone = "risk" if finding.runtime_verification is RuntimeVerification.REPRODUCED else ""
    if finding.runtime_verification in {
        RuntimeVerification.UNAVAILABLE,
        RuntimeVerification.INCONCLUSIVE,
    }:
        runtime_tone = "attention"
    source_tone = "attention" if finding.conclusion is Conclusion.INCONCLUSIVE else ""
    probes = [p for p in bundle.probe_runs if p.finding_id == finding.id]
    route = next((s for p in probes for s in p.steps if s.role is StepRole.ATTACK), None)
    route_html = (
        f'<p class="route mono">{escape(route.method)} {escape(route.path)}</p>' if route else ""
    )
    checks = []
    for check in finding.checks:
        link = citation(finding, check.exhibit_tag) if check.exhibit_tag else ""
        checks.append(
            '<li class="check"><span aria-hidden="true">'
            f"{'●' if check.found else '○'}</span><div>{escape(check.item)} {link}"
            f'<p class="muted">{"Found" if check.found else "Not found"}; '
            f"searched {escape(check.searched)}</p></div></li>"
        )
    flow = ""
    if finding.flow:
        flow = (
            '<section class="part"><h3>Source to sink</h3><ol class="flow-list">'
            + "".join(
                f"<li>{escape(step.label)} {citation(finding, step.exhibit_tag)}</li>"
                for step in finding.flow
            )
            + "</ol></section>"
        )
    exhibits = []
    for exhibit in finding.exhibits:
        span = exhibit.span
        exhibits.append(
            f'<details class="exhibit" id="{finding.display_id}-{exhibit.tag}"><summary>'
            f'<span class="tag">{finding.display_id}/{exhibit.tag}</span> '
            f"{escape(exhibit.role.value.replace('_', ' '))}"
            f'<span class="location mono">{escape(span.path)}:'
            f"{span.start_line}-{span.end_line}</span>"
            f"</summary><p>{escape(exhibit.gloss)}</p>"
            '<dl class="records"><dt>Content SHA256</dt>'
            f'<dd class="mono">{span.content_sha256}</dd><dt>Snapshot</dt>'
            f'<dd class="mono">{span.snapshot_id}</dd></dl></details>'
        )
    unknowns = [*finding.gaps, *finding.unknowns]
    unknown_html = (
        '<section class="part"><h3>Still unknown and limited</h3><ul class="limits">'
        + "".join(f"<li>{escape(item)}</li>" for item in unknowns)
        + "</ul></section>"
        if unknowns
        else ""
    )
    change = next(
        (c for c in bundle.suggested_changes if c.id == finding.suggested_change_id), None
    )
    change_html = (
        '<section class="part"><h3>Suggested change</h3>'
        f'<p class="badge proposed">{escape(change.status.value.replace("_", " "))}</p>'
        f"<p>{escape(change.intent)}</p><pre>{escape(change.diff)}</pre></section>"
        if change
        else ""
    )
    return (
        f'<article class="sheet case" id="{finding.display_id}"><header>'
        f'<p class="meta mono">{finding.display_id} · '
        f"{escape(finding.family.value.replace('_', ' '))} · "
        + ", ".join(f"CWE-{cwe}" for cwe in finding.cwe)
        + f"</p><h2>{escape(finding.title)}</h2>{route_html}"
        + f'<p class="lede">{escape(finding.lede)}</p></header>'
        + (
            f'<p class="condition {runtime_tone}"><strong>Test result:</strong> '
            f"{escape(observed_summary(probes[0]))}</p>"
            if probes
            else ""
        )
        + f'<p class="meta">Severity: {finding.severity.value} · '
        + f"Evidence: {finding.strength.value} · Disposition: {finding.disposition.value}</p>"
        + '<dl class="states">'
        + f'<div class="state {source_tone}"><dt>Source conclusion</dt>'
        + f"<dd>{badge(finding.conclusion)}"
        + f"<p>{CONCLUSIONS[finding.conclusion.value]}</p></dd></div>"
        + f'<div class="state {runtime_tone}"><dt>Runtime verification</dt><dd><strong>'
        + f"{runtime_title}</strong><p>{runtime_text}</p></dd></div></dl>"
        + '<div class="case-grid"><div>'
        + flow
        + '<section class="part"><h3>What Plumb looked for</h3>'
        + (
            f'<ul class="checks">{"".join(checks)}</ul>'
            if checks
            else "<p>No challenge checklist recorded.</p>"
        )
        + '</section><section class="part"><h3>Proof</h3>'
        + (
            "".join(probe_html(probe) for probe in probes)
            if probes
            else f'<p class="condition attention">{runtime_title}. {runtime_text}</p>'
        )
        + "</section>"
        + change_html
        + (
            '<section class="part"><h3>Fix proposal and regression specification</h3>'
            + "<p>Saved proposal only. No target edit or regression execution.</p>"
            + "".join(
                "<pre>" + escape(p.model_dump_json(indent=2)) + "</pre>"
                for p in bundle.proposals
                if p.finding_id == finding.id
            )
            + "</section>"
            if any(p.finding_id == finding.id for p in bundle.proposals)
            else ""
        )
        + unknown_html
        + (
            '<section class="part"><h3>Reviewer decisions</h3>'
            + "<p>Current reviewer view. Original reports and runtime proof are preserved.</p>"
            + "".join(
                "<pre>" + escape(d.model_dump_json(indent=2)) + "</pre>"
                for d in bundle.disposition_history
                if d.finding_id == finding.id
            )
            + "</section>"
            if any(d.finding_id == finding.id for d in bundle.disposition_history)
            else ""
        )
        + '</div><section><h3>Evidence locations</h3><p class="meta">Open an exhibit for its '
        + "explanation and exact hashes. Source text is omitted from exports.</p>"
        + "".join(exhibits)
        + "<details><summary>Finding record and assessment</summary>"
        + f"<p>Severity: <strong>{finding.severity.value}</strong>. "
        + f"{escape(finding.severity_rationale)}</p>"
        + f"<p>Evidence strength: {finding.strength.value}. "
        + f"Disposition: {finding.disposition.value}.</p>"
        + f"<pre>{escape(finding.model_dump_json(indent=2))}</pre></details></section></div>"
        + '<a class="back" href="#findings">Back to findings ↑</a></article>'
    )


def render_html(bundle: ReportBundle) -> str:
    """Input must already have passed the shared evidence validator and redactor."""
    coverage = bundle.run.coverage
    order = {"supported": 0, "inconclusive": 1, "candidate": 2, "rejected": 3}
    findings = sorted(bundle.findings, key=lambda f: order[f.conclusion.value])
    categories = ("completed", "pending", "excluded", "unsupported")
    # Integers from the validated coverage contract; never repository text in CSS.
    rules = "\n".join(
        f"#coverage-{name} {{ flex-grow: {getattr(coverage, name)}; flex-basis: 0; }}"
        for name in categories
    )
    css = CSS.read_text(encoding="utf-8") + "\n" + rules
    digest = base64.b64encode(hashlib.sha256(css.encode()).digest()).decode("ascii")
    counts = Counter(f.conclusion.value for f in bundle.findings)
    overview = (
        " · ".join(
            f"{counts[name]} {name}"
            for name in ("supported", "rejected", "inconclusive", "candidate")
            if counts[name]
        )
        or "No findings recorded"
    )
    navigation = []
    for finding in findings:
        probe = next((p for p in bundle.probe_runs if p.finding_id == finding.id), None)
        attack = (
            next((s for s in probe.steps if s.role is StepRole.ATTACK), None) if probe else None
        )
        location = (
            f"{attack.method} {attack.path}"
            if attack
            else f"{finding.exhibits[0].span.path}:{finding.exhibits[0].span.start_line}"
            if finding.exhibits
            else "No evidence location recorded"
        )
        tone = "risk" if finding.runtime_verification is RuntimeVerification.REPRODUCED else ""
        navigation.append(
            f'<li><a class="{tone}" href="#{finding.display_id}"><span class="mono">'
            f"{finding.display_id}</span><span>{escape(finding.title)}"
            f'<span class="route mono">{escape(location)}</span>'
            + (f'<span class="meta">{escape(observed_summary(probe))}</span>' if probe else "")
            + f"</span>{badge(finding.conclusion)}</a></li>"
        )
    segments = "".join(
        f'<span id="coverage-{name}" class="segment-{name}"></span>'
        for name in categories
        if getattr(coverage, name)
    )
    count_items = "".join(
        f'<li><span class="dot segment-{name}" aria-hidden="true"></span>'
        f"<strong>{getattr(coverage, name)}</strong> {name}</li>"
        for name in categories
    )
    limits = "".join(f"<li>{escape(item)}</li>" for item in bundle.limitations)
    supplementary = ""
    if bundle.supplementary:
        observed = bundle.supplementary
        items = "".join(
            "<li><strong>"
            + escape(s.category + ": " + s.status)
            + "</strong> · "
            + escape(s.summary)
            + '<p class="mono">'
            + escape(
                f"{s.source.path}:{s.source.start_line}-{s.source.end_line}; "
                f"{s.rule_id}; {s.rule_version}"
            )
            + "</p><details><summary>Observation and limitations</summary><pre>"
            + escape(s.model_dump_json(indent=2))
            + "</pre></details></li>"
            for s in observed.signals
        )
        supplementary = (
            '<section class="sheet" id="signals"><h2>Supplementary security signals</h2>'
            + f"<p>{len(observed.signals)} observations · {escape(observed.status)}. "
            + "Separate from findings and coverage. Exposure is not exploitability.</p>"
            + f'<p class="meta">Advisory date {escape(str(observed.pack_date))}; '
            + f"source {escape(str(observed.pack_source))}; "
            + f"pack SHA256 {escape(str(observed.pack_sha256))}</p><ul>{items}</ul></section>"
        )
    report = (
        '<a class="skip" href="#findings">Skip to findings</a><main><div class="topbar">'
        '<div class="wordmark"><svg viewBox="0 0 16 28" aria-hidden="true">'
        '<path d="M7 0h2v15l5 5-6 8-6-8 5-5z"/></svg>plumb</div>'
        '<fieldset class="theme"><legend>Appearance</legend>'
        '<label><input type="radio" name="theme" id="theme-system" checked>System</label>'
        '<label><input type="radio" name="theme" id="theme-day">Day</label>'
        '<label><input type="radio" name="theme" id="theme-night">Night</label></fieldset></div>'
        '<header class="sheet intro"><p class="meta">Saved report · '
        f"{escape(bundle.run.created_at.astimezone(UTC).strftime('%d %b %Y, %H:%M UTC'))} · "
        f"Source run: {escape(bundle.run.run_type.value)}</p>"
        f"<h1>{escape(bundle.snapshot.root_name)} security review</h1>"
        '<p class="lede">Start with the findings below. Source conclusions and runtime '
        "checks answer different questions; each case shows both.</p>"
        f'<p class="overview">{overview}</p><p class="meta">Run {bundle.run.lifecycle.value} · '
        f"Snapshot <code>{bundle.snapshot.id[:12]}</code></p>"
        '<div class="legend"><span>● Supported: evidence for a finding</span>'
        "<span>⊘ Rejected: protection cited</span>"
        "<span>◐ Inconclusive: still unknown</span></div></header>"
        '<section class="sheet" id="findings"><div class="section-head"><h2>Findings</h2>'
        '<a href="#scope">See reviewed scope and limits ↓</a></div>'
        + (
            f'<ol class="finding-nav">{"".join(navigation)}</ol>'
            if navigation
            else "<p>No findings recorded. This is not a claim that the application is safe.</p>"
        )
        + '</section><section class="sheet" id="scope"><div class="section-head">'
        + "<h2>Reviewed scope</h2>"
        + f'<p class="mono">{coverage.completed} / {coverage.total} completed</p></div>'
        + "<p>Counts describe the recorded review queue. They do not measure the percentage "
        + "of vulnerabilities found.</p>"
        + '<div class="coverage-bar" role="img" aria-label="Coverage: '
        + f"{coverage.completed} completed, {coverage.pending} pending, "
        + f"{coverage.excluded} excluded, {coverage.unsupported} unsupported, "
        + f'{coverage.total} total">{segments}</div><ul class="coverage-counts">{count_items}</ul>'
        + "<details><summary>All limitations and exclusions "
        + f'({len(bundle.limitations)})</summary><ul class="limits">{limits}</ul>'
        + "</details></section>"
        + supplementary
        + (
            '<section class="sheet"><h2>Capability accounting</h2>'
            + f"<p>{escape(bundle.capabilities.quality_note)}</p><ul>"
            + "".join(
                f"<li><strong>{escape(r.name)} ({escape(r.category)})</strong>: "
                f"Parsed {escape(r.parsed)}"
                + (f" ({r.parsed_units}/{r.units})" if r.units is not None else "")
                + f"; Indexed {escape(r.indexed)}"
                + (f" ({r.indexed_units}/{r.units})" if r.units is not None else "")
                + "; Investigated unverified; Runtime-testable unavailable."
                + f"<p>{escape(r.reason)}</p></li>"
                for r in bundle.capabilities.rows
            )
            + f"</ul><p>{escape(bundle.capabilities.runtime_note)}</p>"
            + "<details><summary>Historical evidence identities</summary><ul>"
            + "".join(
                f"<li><code>{escape(e.record)}</code><p>{escape(e.scope)}</p>"
                f"<code>SHA256 {e.sha256}</code></li>"
                for e in bundle.capabilities.evidence
            )
            + "</ul></details></section>"
            if bundle.capabilities
            else ""
        )
        + "".join(case_html(finding, bundle) for finding in findings)
        + '<section class="sheet"><h2>Reproducibility</h2><p class="muted">Exact run, model, '
        + "toolchain and snapshot metadata from this saved report.</p>"
        + "<details><summary>Run and snapshot records</summary>"
        + f"<pre>{escape(bundle.run.model_dump_json(indent=2))}</pre>"
        + f"<pre>{escape(bundle.snapshot.model_dump_json(indent=2))}</pre></details></section>"
        + '<p class="footer meta">Saved evidence only. Opening this file runs no review, '
        + "model or target application. Colors always have text labels.</p></main>"
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        f"style-src &#39;sha256-{digest}&#39;; base-uri &#39;none&#39;; "
        'form-action &#39;none&#39;">'
        f"<title>Plumb review · {escape(bundle.snapshot.root_name)}</title><style>{css}</style>"
        f"</head><body>{report}</body></html>\n"
    )
