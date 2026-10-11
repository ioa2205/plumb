"""Cited private drafts; no upload, publication or promotion to reproduced probes."""

import html
import json

from backend.contracts.assessment import (
    AssessmentReport,
    AssessmentView,
    ReportClaim,
    ReportPreview,
)
from backend.contracts.assessment_engine import ObservationAnalysis

from .evidence import artifact_citation, digest, resolve_citation
from .planning import build_checklist, observed_map


def build_private_report(view: AssessmentView) -> AssessmentReport:
    observed = observed_map(view)
    checklist = build_checklist(view)
    claims = []
    for artifact in view.artifacts:
        if artifact.kind == "request_response":
            claims.append(
                ReportClaim(
                    text=(
                        f"{artifact.artifact_id}: imported {artifact.fields['request.method']} "
                        f"{artifact.fields['request.url']}, response status "
                        f"{artifact.fields['response.status']}."
                    ),
                    citations=[
                        artifact_citation(artifact, field)
                        for field in ("request.method", "request.url", "response.status")
                    ],
                )
            )
        else:
            field = "note.text" if artifact.kind == "note" else "screenshot.description"
            claims.append(
                ReportClaim(
                    text=(
                        f"{artifact.artifact_id}: human-reviewed {artifact.kind}; "
                        "its interpretation remains an imported statement/attachment."
                    ),
                    citations=[artifact_citation(artifact, field)],
                )
            )
    for comparison in view.comparisons:
        if comparison.citations:
            claims.append(ReportClaim(text=comparison.summary, citations=comparison.citations))
    analyses = [
        ObservationAnalysis.model_validate(value)
        for value in view.analyses
        if value.get("generated_by") == "local_model"
    ]
    for analysis in analyses:
        if analysis.citations:
            claims.append(
                ReportClaim(
                    text=(
                        f"Recorded local analysis of {analysis.comparison_id}: "
                        f"{analysis.conclusion}; "
                        "this remains an interpretation of imported evidence."
                    ),
                    citations=analysis.citations,
                )
            )
        for sample in analysis.judgments:
            if sample.answer and not sample.error and not sample.violations:
                claims.append(
                    ReportClaim(
                        text=f"Local judgment seed {sample.seed}: {sample.answer.rationale}",
                        citations=[claim.citation for claim in sample.answer.claims],
                    )
                )
    for claim in claims:
        for citation in claim.citations:
            resolve_citation(view, citation)
    return AssessmentReport(
        assessment_id=view.scope.assessment_id,
        title=f"Private assessment draft: {view.scope.application_name}",
        description=(
            "Source-free assessment of human-reviewed imported observations "
            "within the declared scope."
        ),
        affected_endpoints=[endpoint.path for endpoint in observed.endpoints],
        safe_reproduction=[
            (
                "Proposed manual procedure only: use the designated accounts and "
                "synthetic objects within the explicit scope."
            ),
            (
                "Record a legitimate owner response, the same object/request under "
                "the other account, and a protected denial control; stop on "
                "unexpected sensitive information."
            ),
        ],
        impact=(
            "Potential impact is unestablished until the declared access rule, "
            "matching contexts and relevant synthetic-object evidence support "
            "it."
        ),
        claims=claims,
        evidence=view.artifacts,
        expected_behavior=view.expectations,
        comparisons=view.comparisons,
        mitigation=[
            (
                "If the hypothesis is confirmed, enforce the declared access rule "
                "at the affected endpoint and repeat the same owner and denial "
                "controls."
            ),
            *list(
                dict.fromkeys(
                    sample.answer.mitigation
                    for analysis in analyses
                    for sample in analysis.judgments
                    if sample.answer and not sample.error and not sample.violations
                )
            ),
        ],
        tools_and_models=[
            (
                "Plumb deterministic inert-data importer, exact-field citation "
                "validator, observed map and manual comparison planner."
            ),
            (
                "No model inference was performed by this report export; recorded "
                "local-analysis details are included as recorded interpretations."
            ),
            *[
                f"Recorded local-model analysis: {analysis.comparison_id}; packet "
                f"SHA-256 {analysis.packet_sha256}; requests {analysis.requests_used}. "
                + (
                    "; ".join(analysis.model_provenance)
                    if analysis.model_provenance
                    else "Exact model/profile identity was not supplied in this analysis record."
                )
                for analysis in analyses
            ],
        ],
        methodology=[
            (
                "Human attachment review precedes local storage; credentials are "
                "removed and unexpected personal information stops assessment "
                "activity."
            ),
            (
                "Observations, human expectations, comparison hypotheses, "
                "counterevidence and executed-run records remain separate."
            ),
            "Every observation claim resolves to its artifact and exact sanitized field hash.",
        ],
        limitations=[
            (
                "Imports are user-collected observations, not independently "
                "verified runtime reproduction."
            ),
            "A successful HTTP response or missing header alone proves no unauthorized access.",
            "Screenshots are reviewed attachments; image understanding is unavailable.",
            "Undiscovered endpoints, untested roles and application-wide security remain unknown.",
            *list(
                dict.fromkeys(
                    gap
                    for analysis in analyses
                    for gap in [*analysis.alternative_explanations, *analysis.missing_evidence]
                )
            ),
            *([f"Assessment stopped: {view.stop_reason}"] if view.stopped else []),
        ],
        dismissed_leads=[
            comparison.summary
            for comparison in view.comparisons
            if comparison.conclusion == "rejected"
        ],
        tested_coverage=[
            f"Imported observations: {endpoint.method} {endpoint.path}"
            for endpoint in observed.endpoints
        ],
        untested_coverage=checklist.untested_paths,
    )


def report_preview(view: AssessmentView) -> ReportPreview:
    report = build_private_report(view)

    def safe(value: str) -> str:
        # Markdown remains a private text artifact; hostile HTML and link syntax is inert.
        return html.escape(value).replace("[", "\\[").replace("]", "\\]").replace("`", "\\`")

    lines = [
        f"# {safe(report.title)}",
        "",
        "Private local draft. Human review required before export.",
        "",
        safe(report.description),
        "",
    ]
    for label, values in (
        ("Affected endpoints", report.affected_endpoints),
        ("Proposed safe reproduction", report.safe_reproduction),
        ("Impact", [report.impact]),
        ("Mitigation", report.mitigation),
        ("Tools and models", report.tools_and_models),
        ("Methodology", report.methodology),
        ("Limitations", report.limitations),
        ("Imported coverage", report.tested_coverage),
        ("Untested scope", report.untested_coverage),
        ("Dismissed leads", report.dismissed_leads),
    ):
        lines.extend([f"## {label}", "", *[f"- {safe(value)}" for value in values], ""])
    lines.extend(["## Sanitized evidence", ""])
    for claim in report.claims:
        citations = "; ".join(
            f"{citation.artifact_id} / {citation.field} / SHA-256 {citation.sha256}"
            for citation in claim.citations
        )
        lines.extend([safe(claim.text), "", f"Citation: {safe(citations)}", ""])
    for artifact in report.evidence:
        lines.extend([f"### {safe(artifact.artifact_id)}", "", safe(artifact.provenance), ""])
        for field, value in artifact.fields.items():
            shown = (
                value
                if len(value) <= 512
                else value[:512] + (" [preview abbreviated; complete field in private JSON export]")
            )
            lines.extend([f"Field: {safe(field)}", "", safe(shown), ""])
    lines.extend(["## Declared expected behavior", ""])
    for expectation in report.expected_behavior:
        lines.extend(
            [
                safe(expectation.statement),
                "",
                f"Declared by: {safe(expectation.declared_by)}. Basis: {safe(expectation.basis)}.",
                "",
            ]
        )
    if view.stopped:
        lines.extend(
            [
                "## Private incident draft",
                "",
                (
                    "Stop collection and report the unexpected discovery through the "
                    "authorized private channel. No automatic submission is performed."
                ),
                "",
            ]
        )
    markdown = "\n".join(lines)
    if len(markdown.encode()) > 900000:
        markdown = markdown.encode()[:890000].decode("utf-8", errors="ignore") + (
            "\n\nPreview budget reached. Complete cited evidence and analysis "
            "remain in the private JSON export.\n"
        )
    preview_sha256 = digest(
        json.dumps(
            {"report": report.model_dump(mode="json"), "markdown": markdown},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return ReportPreview(report=report, markdown=markdown, preview_sha256=preview_sha256)
