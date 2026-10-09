"""Validated Markdown, HTML, JSON and SARIF exports (M3.11, PROJECT_PLAN §6).

Every format is derived from the same redacted bundle. Rendering reads only the
content-addressed snapshot and never executes target code or starts inference.
"""

import html
import json
import re
from collections.abc import Sequence
from importlib.metadata import version
from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, JsonValue, model_validator

from agent.validator import Validator
from analysis.snapshot import SnapshotStore
from backend.contracts.capabilities import CapabilityTable
from backend.contracts.code import Guard, ProjectSnapshot
from backend.contracts.common import Contract
from backend.contracts.investigation import Conclusion, DispositionDecision, ExhibitRole, Finding
from backend.contracts.peers import PeerComparison
from backend.contracts.policies import BoundPolicy
from backend.contracts.runs import ReviewRun, RunLifecycle
from backend.contracts.signals import SignalSet
from backend.contracts.verification import FixProposal, ProbeRun, SuggestedChange
from backend.redaction import TOKEN, Redactor, redact

Format = Literal["markdown", "html", "json", "sarif"]
SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json"
BASE_LIMITATIONS = (
    "Static support does not establish runtime reproduction.",
    "Only included snapshot files were reviewed; excluded and unsupported scope "
    "remains outside the review.",
    "Valid citations establish grounding, not the correctness of a security judgment.",
    "Exports omit source text. Redaction covers known credential shapes and supplied "
    "secret values, not arbitrary secrets.",
)


class ReportBundle(Contract):
    """Local report interchange, including records required to validate claims.

    This composite is not a new persisted entity or API contract. Its schema
    lives beside the report schemas, separately from the core entity registry.
    """

    capabilities: CapabilityTable | None = None
    format_version: Literal["1.0"] = "1.0"
    run: ReviewRun
    snapshot: ProjectSnapshot
    findings: list[Finding] = Field(default_factory=list)
    guards: list[Guard] = Field(default_factory=list)
    probe_runs: list[ProbeRun] = Field(default_factory=list)
    suggested_changes: list[SuggestedChange] = Field(default_factory=list)
    peer_comparisons: list[PeerComparison] = Field(default_factory=list, max_length=2000)
    limitations: list[str] = Field(default_factory=list)
    policies: list[BoundPolicy] = Field(default=[], max_length=100)
    supplementary: SignalSet | None = None
    proposals: list[FixProposal] = Field(default=[], max_length=2000)
    disposition_history: list[DispositionDecision] = Field(default=[], max_length=2000)

    @model_validator(mode="after")
    def _same_review(self) -> Self:
        if self.capabilities and self.capabilities.snapshot_id != self.snapshot.id:
            raise ValueError("report capabilities belong to its snapshot")
        if self.supplementary and (
            self.supplementary.run_id != self.run.id
            or self.supplementary.snapshot_id != self.snapshot.id
        ):
            raise ValueError("supplementary signals belong to the report run and snapshot")
        if any(p.snapshot_id != self.snapshot.id for p in self.policies):
            raise ValueError("report requirements belong to its snapshot")
        if any(p not in self.policies for f in self.findings for p in f.policy_basis):
            raise ValueError("finding requirements must appear in the frozen report set")
        if self.run.snapshot_id != self.snapshot.id:
            raise ValueError("the run and report must reference the same snapshot")
        for records in (self.findings, self.guards, self.probe_runs, self.suggested_changes):
            if len({record.id for record in records}) != len(records):
                raise ValueError("record IDs are unique within each report collection")
        if len({finding.display_id for finding in self.findings}) != len(self.findings):
            raise ValueError("finding display IDs are unique within a report")
        if len(set(self.run.finding_ids)) != len(self.run.finding_ids) or set(
            self.run.finding_ids
        ) != {finding.id for finding in self.findings}:
            raise ValueError("every finding of the run must appear exactly once in the report")
        if any(
            finding.run_id != self.run.id or finding.snapshot_id != self.snapshot.id
            for finding in self.findings
        ) or any(guard.snapshot_id != self.snapshot.id for guard in self.guards):
            raise ValueError("findings and guards belong to the report's run and snapshot")
        by_id = {finding.id: finding for finding in self.findings}
        from backend.disposition_store import validate_history

        if any(d.finding_id not in by_id for d in self.disposition_history):
            raise ValueError("reviewer decisions must belong to report findings")
        for finding in self.findings:
            validate_history(
                finding,
                [d for d in self.disposition_history if d.finding_id == finding.id],
                projected=True,
            )
        if len({p.finding_id for p in self.proposals}) != len(self.proposals):
            raise ValueError("each finding has at most one frozen proposal")
        for proposal in self.proposals:
            case = by_id.get(proposal.finding_id)
            if (
                case is None
                or case.conclusion is not Conclusion.SUPPORTED
                or proposal.snapshot_id != self.snapshot.id
            ):
                raise ValueError("proposals belong to Supported findings on this snapshot")
            if proposal.change and (
                proposal.change not in self.suggested_changes
                or case.suggested_change_id != proposal.change.id
            ):
                raise ValueError("proposal change must match the saved finding and report change")
        if len({p.finding_id for p in self.peer_comparisons}) != len(self.peer_comparisons):
            raise ValueError("each finding has at most one recorded peer comparison")
        for peer in self.peer_comparisons:
            finding = by_id.get(peer.finding_id)
            if (
                finding is None
                or peer.group.snapshot_id != self.snapshot.id
                or finding.peer_group_id != peer.group.id
                or peer.question_id not in finding.question_ids
            ):
                raise ValueError("peer comparison must be cited by its finding on this snapshot")
        for change in self.suggested_changes:
            finding = by_id.get(change.finding_id)
            if finding is None or finding.suggested_change_id != change.id:
                raise ValueError("a suggested change must be cited by its finding in this report")
        for probe in self.probe_runs:
            finding = by_id.get(probe.finding_id)
            if finding is None:
                raise ValueError("a probe belongs to a finding in this report")
            if probe.snapshot_role.value == "vulnerable":
                if probe.snapshot_id != self.snapshot.id or probe.id not in finding.probe_run_ids:
                    raise ValueError("a probe must be cited by its finding on this snapshot")
            elif not any(
                probe.id in change.replay_probe_run_ids and change.finding_id == finding.id
                for change in self.suggested_changes
            ):
                raise ValueError("a patched probe must be cited by a suggested change")
        if any(not limitation.strip() for limitation in self.limitations):
            raise ValueError("a limitation must say what remains unverified")
        return self


def _validate(bundle: ReportBundle, store: SnapshotStore) -> ReportBundle:
    # model_copy can bypass Pydantic invariants; revalidate dictionaries at the export boundary.
    bundle = ReportBundle.model_validate(bundle.model_dump())
    if store.load(bundle.snapshot.id) != bundle.snapshot:
        raise ValueError("the report snapshot differs from the stored manifest")
    validator = Validator(bundle.snapshot, store)
    if bundle.supplementary:
        for signal in bundle.supplementary.signals:
            if errors := validator.span(signal.source):
                raise ValueError("; ".join(error.message for error in errors))
    for policy in bundle.policies:
        for span in [*(s.span for s in policy.sites), *policy.assertion.evidence]:
            if errors := validator.evidence(span):
                raise ValueError("; ".join(error.message for error in errors))
    for peer in bundle.peer_comparisons:
        for row in peer.rows:
            for span in (row.site.span, row.entry.span, *row.evidence):
                if errors := validator.evidence(span):
                    raise ValueError("; ".join(error.message for error in errors))
            for guard in row.guards:
                validator.confirm(guard, subject=guard.subject, object=guard.object)
    guards = [
        validator.confirm(guard, subject=guard.subject, object=guard.object)
        if guard.confirmed
        else guard
        for guard in bundle.guards
    ]
    changes = {change.id: change for change in bundle.suggested_changes}
    for proposal in bundle.proposals:
        if proposal.probe_spec:
            from agent.questions import ProbeParameters
            from verification.proposals import regression

            case = next(f for f in bundle.findings if f.id == proposal.finding_id)
            expected, manifest, _ = regression(
                case,
                ProbeParameters.model_validate(
                    dict(parameter="order_id", denied="other_user", allowed="owner")
                ),
                bundle.snapshot,
                store,
            )
            if expected != proposal.probe_spec or manifest != proposal.adapter_manifest_sha256:
                raise ValueError("regression probe differs from its trusted frozen fixture mapping")
    for finding in bundle.findings:
        if finding.conclusion is Conclusion.SUPPORTED and not any(
            exhibit.role is not ExhibitRole.DEVELOPER_NOTE for exhibit in finding.exhibits
        ):
            raise ValueError("a supported finding must cite code")
        errors = validator.finding(
            finding,
            guards=guards,
            probe_runs=bundle.probe_runs,
            change=changes.get(finding.suggested_change_id),
        )
        if errors:
            raise ValueError("; ".join(error.message for error in errors))
    return bundle


_IDENTITIES = frozenset(
    {
        "id",
        "display_id",
        "snapshot_id",
        "run_id",
        "finding_id",
        "resolution_commit",
        "tag",
        "exhibit_tag",
        "path",
        "finding_ids",
        "subject_site_id",
        "site_id",
        "site_ids",
        "entry_point_id",
        "handler_symbol_id",
        "via_symbol_id",
        "guard_ids",
        "applied_site_ids",
        "question_ids",
        "probe_run_ids",
        "replay_probe_run_ids",
        "suggested_change_id",
        "files",
    }
)


def _redacted(value: JsonValue, secrets: Sequence[str], key: str = "") -> JsonValue:
    if isinstance(value, str):
        cleaned = redact(value, secrets)
        if cleaned != value and (key in _IDENTITIES or key.endswith("sha256")):
            raise ValueError(
                "a secret occurs in citation identity; export refused to preserve evidence IDs"
            )
        return cleaned
    if isinstance(value, list):
        return [_redacted(item, secrets, key) for item in value]
    if isinstance(value, dict):
        return {name: _redacted(item, secrets, name) for name, item in value.items()}
    return value


def _prepare(bundle: ReportBundle, store: SnapshotStore, secrets: Sequence[str]) -> ReportBundle:
    if any(not value for value in secrets):
        raise ValueError("a redaction value cannot be empty")
    bundle = _validate(bundle, store)
    if any(
        change.source_edits and redact(change.diff, secrets) != change.diff
        for change in bundle.suggested_changes
    ):
        raise ValueError("redaction would change the frozen proposed diff; export refused")
    limitations = [*BASE_LIMITATIONS, *bundle.limitations]
    if bundle.supplementary:
        limitations.extend(bundle.supplementary.limitations)
    coverage = bundle.run.coverage
    if bundle.run.lifecycle is not RunLifecycle.COMPLETED or coverage.pending:
        limitations.append(
            f"This {bundle.run.lifecycle.value} run is partial; "
            f"{coverage.pending} questions remain pending."
        )
    if bundle.run.model is None or bundle.run.toolchain is None:
        limitations.append("Model or toolchain provenance was not recorded for this run.")
    limitations.extend(condition.message for condition in bundle.run.conditions)
    limitations.extend(
        f"{item.path}: excluded ({item.reason.value})." for item in bundle.snapshot.excluded
    )
    for finding in bundle.findings:
        limitations.extend(
            f"{finding.display_id}: {gap}" for gap in [*finding.gaps, *finding.unknowns]
        )
    # A redacted export can be loaded and re-exported without piling up standard limitations.
    bundle = bundle.model_copy(update={"limitations": list(dict.fromkeys(limitations))})
    return ReportBundle.model_validate(_redacted(bundle.model_dump(mode="json"), secrets))


def _case_lines(finding: Finding, changes: dict[str, SuggestedChange]) -> list[str]:
    lines = [
        f"{finding.display_id}: {finding.title}",
        finding.lede,
        f"Finding ID: {finding.id}; family: {finding.family.value}; "
        + ", ".join(f"CWE-{cwe}" for cwe in finding.cwe),
        f"Conclusion: {finding.conclusion.value}",
        f"Runtime verification: {finding.runtime_verification.value}",
        f"Severity: {finding.severity.value}. {finding.severity_rationale}",
        f"Evidence strength: {finding.strength.value}",
        f"Disposition: {finding.disposition.value}"
        + (f". {finding.disposition_reason}" if finding.disposition_reason else ""),
    ]
    for exhibit in finding.exhibits:
        span = exhibit.span
        lines.append(
            f"{finding.display_id}/{exhibit.tag} ({exhibit.role.value}): "
            f"{span.path}:{span.start_line}-{span.end_line}; snapshot {span.snapshot_id}; "
            f"content SHA256 {span.content_sha256}. {exhibit.gloss}"
        )
    for policy in finding.policy_basis:
        a = policy.assertion
        lines.append(
            f"Requirement ({a.status.value}): {a.id}; {a.statement}; "
            f"author {a.author}; {a.created_at.isoformat()}; {policy.provenance}; "
            f"policy SHA256 {policy.sha256}. Human requirement, not guard evidence."
        )
        if policy.forbidden_fields:
            lines.append(
                "Fields forbidden at client boundary: " + ", ".join(policy.forbidden_fields)
            )
    for check in finding.checks:
        outcome = "found" if check.found else "not found"
        citation = f"; {finding.display_id}/{check.exhibit_tag}" if check.exhibit_tag else ""
        lines.append(f"Challenge: {check.item} — {outcome}; searched {check.searched}{citation}.")
    lines.extend(
        f"Flow: {step.label} — {finding.display_id}/{step.exhibit_tag}" for step in finding.flow
    )
    lines.extend(f"Gap: {gap}" for gap in finding.gaps)
    lines.extend(f"Unknown: {unknown}" for unknown in finding.unknowns)
    if finding.peer_group_id:
        lines.append(f"Peer group: {finding.peer_group_id}")
    if finding.question_ids:
        lines.append("Questions: " + ", ".join(finding.question_ids))
    if finding.probe_run_ids:
        lines.append("Probe runs: " + ", ".join(finding.probe_run_ids))
    change = changes.get(finding.suggested_change_id)
    if change:
        lines.extend(
            [f"Suggested change: {change.id} ({change.status.value}). {change.intent}", change.diff]
        )
    return lines


def _sections(bundle: ReportBundle) -> list[tuple[str, list[str]]]:
    run, coverage = bundle.run, bundle.run.coverage
    summary = [
        f"Run: {run.id}; type: {run.run_type.value}; lifecycle: {run.lifecycle.value}",
        f"Project: {bundle.snapshot.root_name}; snapshot: {run.snapshot_id}",
        f"Created: {run.created_at.isoformat()}",
        f"Coverage: {coverage.completed} completed, {coverage.pending} pending, "
        f"{coverage.excluded} excluded, {coverage.unsupported} unsupported, "
        f"{coverage.total} total.",
        "Model: " + (run.model.model_dump_json() if run.model else "not recorded"),
        "Toolchain: " + (run.toolchain.model_dump_json() if run.toolchain else "not recorded"),
    ]
    for policy in bundle.policies:
        a = policy.assertion
        summary.append(
            f"Frozen requirement ({a.status.value}): {a.id}; {a.statement}; "
            f"author {a.author}; {a.created_at.isoformat()}; {policy.provenance}; "
            f"SHA256 {policy.sha256}; access IDs: " + ", ".join(s.id for s in policy.sites)
        )
    if run.started_at:
        summary.append(f"Started: {run.started_at.isoformat()}")
    if run.finished_at:
        summary.append(f"Finished: {run.finished_at.isoformat()}")
    sections = [("Plumb review", summary), ("Limitations", bundle.limitations)]
    if bundle.capabilities:
        capability = bundle.capabilities
        sections.append(
            (
                "Capability accounting",
                [
                    capability.quality_note,
                    *[
                        f"{row.name} ({row.category}): Parsed {row.parsed}"
                        + (f" ({row.parsed_units}/{row.units})" if row.units is not None else "")
                        + f"; Indexed {row.indexed}"
                        + (f" ({row.indexed_units}/{row.units})" if row.units is not None else "")
                        + "; Investigated unverified; Runtime-testable unavailable. "
                        + row.reason
                        for row in capability.rows
                    ],
                    capability.runtime_note,
                    *[
                        f"Historical evidence: {e.record} (SHA256 {e.sha256}). {e.scope}"
                        for e in capability.evidence
                    ],
                ],
            )
        )
    if bundle.supplementary:
        observed = bundle.supplementary
        sections.append(
            (
                "Supplementary security signals",
                [
                    f"{len(observed.signals)} observations; status {observed.status}; "
                    "separate from findings and coverage. Exposure is not exploitability.",
                    f"Rule version {observed.tool_version}; advisory date {observed.pack_date}; "
                    f"source {observed.pack_source}; pack SHA256 {observed.pack_sha256}",
                    *[s.model_dump_json() for s in observed.signals],
                ],
            )
        )
    changes = {change.id: change for change in bundle.suggested_changes}
    sections.extend(
        (finding.display_id, _case_lines(finding, changes)) for finding in bundle.findings
    )
    if not bundle.findings:
        sections.append(
            (
                "Findings",
                ["No findings recorded. This is not a claim that the application is safe."],
            )
        )
    sections.extend((f"Probe {probe.id}", [probe.model_dump_json()]) for probe in bundle.probe_runs)
    sections.extend((f"Fix proposal {p.id}", [p.model_dump_json()]) for p in bundle.proposals)
    if bundle.disposition_history:
        sections.append(
            (
                "Reviewer decisions",
                [
                    "Current reviewer view; original reports are preserved. "
                    "These decisions do not change source conclusions, severity, "
                    "coverage or runtime proof.",
                    *[d.model_dump_json() for d in bundle.disposition_history],
                ],
            )
        )
    return sections


def _markdown(text: str) -> str:
    # No repository-controlled HTML, links, headings, tables, or line breaks.
    text = html.escape(" ".join(text.splitlines()), quote=False)
    text = re.sub(r"([\\`*_{}\[\]()#+.!|>~])", r"\\\1", text)
    return re.sub(r"^-(?=\s)", r"\\-", text)


def _markdown_block(text: str) -> str:
    if text.startswith("--- ") and "\n+++ " in text:
        fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
        return f"{fence}diff\n{text.rstrip()}\n{fence}"
    return _markdown(text)


def _location(finding: Finding, index: int) -> dict[str, JsonValue]:
    exhibit = finding.exhibits[index]
    span = exhibit.span
    return {
        "id": index + 1,
        "physicalLocation": {
            "artifactLocation": {"uri": quote(span.path, safe="/")},
            "region": {"startLine": span.start_line, "endLine": span.end_line},
        },
        "message": {"text": f"{finding.display_id}/{exhibit.tag}: {exhibit.gloss}"},
        "properties": {
            "evidenceId": f"{finding.display_id}/{exhibit.tag}",
            "role": exhibit.role.value,
            "span": span.model_dump(mode="json"),
        },
    }


def _sarif(bundle: ReportBundle) -> dict[str, JsonValue]:
    families = sorted({finding.family.value for finding in bundle.findings})
    changes = {change.id: change for change in bundle.suggested_changes}
    limitations: list[JsonValue] = [*bundle.limitations]
    levels = {
        "critical": "error",
        "high": "error",
        "medium": "warning",
        "low": "note",
        "unknown": "note",
    }
    kinds = {
        "supported": "fail",
        "rejected": "notApplicable",
        "candidate": "review",
        "inconclusive": "open",
    }
    results: list[JsonValue] = []
    for finding in bundle.findings:
        result: dict[str, JsonValue] = {
            "ruleId": "plumb/" + finding.family.value,
            "ruleIndex": families.index(finding.family.value),
            "kind": kinds[finding.conclusion.value],
            "level": levels[finding.severity.value]
            if finding.conclusion is Conclusion.SUPPORTED
            else "none",
            "message": {"text": "\n".join(_case_lines(finding, changes))},
            "partialFingerprints": {"plumbFindingId/v1": finding.id},
            "relatedLocations": [
                _location(finding, index) for index in range(len(finding.exhibits))
            ],
            "properties": {
                "finding": finding.model_dump(mode="json"),
                "limitations": limitations,
            },
        }
        primary = next(
            (
                index
                for index, exhibit in enumerate(finding.exhibits)
                if exhibit.role in (ExhibitRole.DEVIANT, ExhibitRole.SINK)
            ),
            None,
        )
        if primary is None:
            primary = next(
                (
                    index
                    for index, exhibit in enumerate(finding.exhibits)
                    if exhibit.role is not ExhibitRole.DEVELOPER_NOTE
                ),
                None,
            )
        if primary is not None:
            result["locations"] = [_location(finding, primary)]
        results.append(result)
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Plumb",
                        "version": version("plumb"),
                        "rules": [
                            {
                                "id": "plumb/" + family,
                                "shortDescription": {"text": family.replace("_", " ")},
                            }
                            for family in families
                        ],
                    }
                },
                "automationDetails": {"id": bundle.run.id},
                "invocations": [
                    {
                        "executionSuccessful": bundle.run.lifecycle is RunLifecycle.COMPLETED,
                        "toolExecutionNotifications": [
                            {"level": "note", "message": {"text": limitation}}
                            for limitation in bundle.limitations
                        ],
                    }
                ],
                "artifacts": [
                    {
                        "location": {"uri": quote(file.path, safe="/")},
                        "hashes": {"sha-256": file.sha256},
                    }
                    for file in bundle.snapshot.files
                ],
                "redactionTokens": [TOKEN],
                "results": results,
                "properties": {"plumbReport": bundle.model_dump(mode="json")},
            }
        ],
    }


def render(
    bundle: ReportBundle, store: SnapshotStore, format: Format, *, secrets: Sequence[str] = ()
) -> str:
    """Validate, redact once, then export. No format can bypass the evidence validator."""
    bundle = _prepare(bundle, store, (*Redactor.configured().secrets, *secrets))
    if format == "json":
        return json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n"
    if format == "sarif":
        return json.dumps(_sarif(bundle), indent=2, ensure_ascii=True) + "\n"
    sections = _sections(bundle)
    if format == "markdown":
        return (
            "\n\n".join(
                f"{'#' if index == 0 else '##'} {_markdown(title)}\n\n"
                + "\n\n".join(_markdown_block(line) for line in lines)
                for index, (title, lines) in enumerate(sections)
            )
            + "\n"
        )
    if format == "html":
        from backend.reports.html_report import render_html

        return render_html(bundle)
    raise ValueError(f"unknown report format: {format}")
