"""Deterministic task resolution, observed coverage and conservative comparisons."""

import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlsplit

from backend.contracts.assessment import (
    AssessmentAnswer,
    AssessmentBudget,
    AssessmentChecklist,
    AssessmentTask,
    AssessmentView,
    ChecklistItem,
    ComparisonRequest,
    EvidenceArtifact,
    ObservationComparison,
    ObservedEndpoint,
    ObservedMap,
)
from backend.redaction import Redactor

from .evidence import artifact_citation, check_scope, digest


def interpret_prompt(
    prompt: str,
    target_id: str,
    evidence_ids: tuple[str, ...] = (),
    *,
    budget: AssessmentBudget | None = None,
    known_evidence_ids: tuple[str, ...] | None = None,
    target_kind: str = "assessment",
    redactor: Redactor | None = None,
) -> AssessmentTask:
    """Resolve the same typed task for CLI/UI; arbitrary text never reaches source judgments."""
    prompt = (redactor or Redactor()).text(prompt).strip()
    if not prompt or len(prompt) > 4096:
        raise ValueError("prompt must contain between 1 and 4096 characters")
    lowered = prompt.lower()
    selected = list(evidence_ids)
    if known_evidence_ids is not None:
        for identity in known_evidence_ids:
            if identity not in selected and re.search(
                r"(?<![\w.-])" + re.escape(identity) + r"(?![\w.-])", prompt
            ):
                selected.append(identity)
    status = "resolved"
    clarification = None
    if re.search(
        r"\b(browse|visit|crawl|fetch|download|execute|shell|upload|publish)\b|https?://|"
        r"grant\s+(?:permission|authority)|expand\s+scope|change\s+verdict|mark\s+reproduced",
        lowered,
    ):
        status = "refused"
        clarification = (
            "This prompt cannot authorize network activity, execution, "
            "publication or verdict changes."
        )
    if re.search(r"\breport\b", lowered):
        action = "report"
    elif re.search(r"\b(compare|comparison)\b", lowered):
        action = "compare"
    elif re.search(r"\b(missing|limitations?|unknowns?|evidence needed)\b", lowered):
        action = "missing"
    elif re.search(r"\b(plan|checklist|methodology)\b", lowered):
        action = "plan"
    elif re.search(r"\b(explain|describe|what|why)\b", lowered):
        action = "explain"
    elif re.search(r"\b(analy[sz]e|challenge|mitigat\w*)\b", lowered):
        action = "analyze"
    elif re.search(r"\breview\b", lowered) and target_kind == "source":
        action = "source_review"
    else:
        action = "explain"
        if status != "refused":
            status = "clarification_required"
            clarification = (
                "Choose compare, explain, missing evidence, plan, analyze or private report."
            )
    if len(selected) > 3:
        selected = selected[:3]
        status = "clarification_required"
        clarification = "Select at most three evidence artifacts for a bounded task."
    if known_evidence_ids is not None and any(item not in known_evidence_ids for item in selected):
        status = "clarification_required"
        clarification = "Select evidence IDs that exist in this assessment."
    mentioned = re.findall(r"\bE-?\d+[A-Za-z0-9._:-]*\b", prompt)
    if known_evidence_ids is not None and any(item not in known_evidence_ids for item in mentioned):
        status = "clarification_required" if status != "refused" else status
        clarification = "The prompt names an unknown evidence artifact; select saved artifact IDs."
    if action == "compare" and len(selected) < 2 and status != "refused":
        status = "clarification_required"
        clarification = (
            "Select the two observations to compare and a protected control when available."
        )
    return AssessmentTask.model_validate(
        {
            "task_id": "T-" + digest(target_id + "\0" + prompt + "\0" + ",".join(selected))[:16],
            "target_id": target_id,
            "action": action,
            "prompt": prompt,
            "evidence_ids": selected,
            "focus": "ownership"
            if re.search(r"\b(owner|ownership|authorization)\b", lowered)
            else "",
            "budget": budget or AssessmentBudget(),
            "status": status,
            "clarification": clarification,
        }
    )


def observed_map(view: AssessmentView) -> ObservedMap:
    groups: dict[tuple[str, str], list[EvidenceArtifact]] = defaultdict(list)
    for artifact in view.artifacts:
        if artifact.kind == "request_response":
            key = (artifact.fields["request.method"], urlsplit(artifact.fields["request.url"]).path)
            groups[key].append(artifact)
    endpoints = []
    for (method, path), artifacts in sorted(groups.items()):
        contexts = [artifact.context for artifact in artifacts if artifact.context is not None]
        endpoints.append(
            ObservedEndpoint(
                endpoint_id="EP-" + digest(method + " " + path)[:12],
                method=method,
                path=path,
                account_ids=sorted({context.account_id for context in contexts}),
                object_ids=sorted({context.object_id for context in contexts}),
                artifact_ids=[artifact.artifact_id for artifact in artifacts],
                citations=[artifact_citation(artifact, "request.url") for artifact in artifacts],
            )
        )
    return ObservedMap(
        assessment_id=view.scope.assessment_id,
        endpoints=endpoints,
        declared_roles=view.scope.accounts,
        unknowns=[
            (
                "Only imported endpoints are mapped; undiscovered endpoints and "
                "application-wide security are unknown."
            ),
            (
                "Declared roles and objects are human statements, not verified "
                "authentication or policy behavior."
            ),
        ],
    )


def build_checklist(view: AssessmentView) -> AssessmentChecklist:
    observed = observed_map(view)
    items = []
    paths = sorted(
        set(view.scope.allowed_paths) | {endpoint.path for endpoint in observed.endpoints}
    )
    untested = []
    for path in paths:
        artifacts = [
            artifact
            for artifact in view.artifacts
            if artifact.kind == "request_response"
            and urlsplit(artifact.fields["request.url"]).path == path
        ]
        expectations = [item for item in view.expectations if item.path == path]
        related = {artifact.artifact_id for artifact in artifacts}
        compared = any(
            comparison.request.left_artifact_id in related
            and comparison.request.right_artifact_id in related
            for comparison in view.comparisons
        )
        status = "compared" if compared else "observations_available" if artifacts else "planned"
        if not artifacts:
            untested.append(path)
        items.append(
            ChecklistItem.model_validate(
                {
                    "check_id": "CK-" + digest(path)[:12],
                    "path": path,
                    "account_ids": [account.account_id for account in view.scope.accounts],
                    "object_ids": [item.object_id for item in view.scope.synthetic_objects],
                    "expectation_id": expectations[0].expectation_id if expectations else None,
                    "status": status,
                    "instructions": (
                        "Plan a legitimate owner observation, a designated other-account "
                        "observation and a protected control using only the declared "
                        "synthetic object and identical request context."
                    ),
                    "artifact_ids": sorted(related),
                    "limitations": [
                        (
                            "This checklist is a plan; imported observations are not trusted "
                            "executed tests."
                        )
                    ],
                }
            )
        )
    return AssessmentChecklist(
        assessment_id=view.scope.assessment_id, items=items, untested_paths=untested
    )


def compare_observations(
    view: AssessmentView, request: ComparisonRequest, *, now: datetime | None = None
) -> ObservationComparison:
    check_scope(view.scope, action="compare", now=now)
    if view.stopped:
        raise ValueError("assessment is stopped; further comparisons are refused")
    request = ComparisonRequest.model_validate(request.model_dump())
    indexed = {artifact.artifact_id: artifact for artifact in view.artifacts}
    identities = [request.left_artifact_id, request.right_artifact_id]
    if request.control_artifact_id:
        identities.append(request.control_artifact_id)
    if len(set(identities)) != len(identities) or any(
        identity not in indexed for identity in identities
    ):
        raise ValueError("comparison requires distinct existing evidence artifacts")
    left, right = indexed[request.left_artifact_id], indexed[request.right_artifact_id]
    control = indexed.get(request.control_artifact_id or "")
    missing = []
    citations = []

    def request_headers(artifact: EvidenceArtifact) -> dict[str, str]:
        return {
            key: value
            for key, value in artifact.fields.items()
            if key.startswith("request.headers.")
            and key not in {"request.headers.authorization", "request.headers.cookie"}
        }

    if left.kind != "request_response" or right.kind != "request_response":
        missing.append("Both selected artifacts must contain request/response observations.")
    else:
        for artifact in [
            left,
            right,
            *([control] if control and control.kind == "request_response" else []),
        ]:
            for field in (
                "request.method",
                "request.url",
                "request.body",
                "response.status",
                "response.body",
            ):
                citations.append(artifact_citation(artifact, field))
    expectation = next(
        (item for item in view.expectations if item.expectation_id == request.expectation_id), None
    )
    if expectation is None:
        missing.append("A declared access expectation with its human basis is required.")
    left_context, right_context = left.context, right.context
    obj = None
    if left_context is None or right_context is None:
        missing.append(
            "Designated account, session, request and synthetic-object contexts are required."
        )
    else:
        obj = next(
            (
                item
                for item in view.scope.synthetic_objects
                if item.object_id == left_context.object_id
            ),
            None,
        )
        if (
            left_context.object_id != right_context.object_id
            or left_context.request_context_id != right_context.request_context_id
            or left_context.account_id == right_context.account_id
            or left_context.session_context_id == right_context.session_context_id
            or left.fields.get("request.method") != right.fields.get("request.method")
            or left.fields.get("request.url") != right.fields.get("request.url")
            or left.fields.get("request.body") != right.fields.get("request.body")
            or request_headers(left) != request_headers(right)
        ):
            missing.append(
                "The pair must share endpoint, method, body, object and request "
                "context, with distinct designated account sessions."
            )
        if expectation is not None and (
            expectation.object_id != left_context.object_id
            or expectation.path != urlsplit(left.fields.get("request.url", "")).path
            or left_context.account_id not in expectation.allowed_account_ids
            or right_context.account_id in expectation.allowed_account_ids
        ):
            missing.append(
                "The expectation must bind this endpoint/object and allow the "
                "legitimate account while denying the other account."
            )
    marker = obj.synthetic_marker if obj else None
    if marker is None:
        missing.append(
            "A declared synthetic-object marker is required; an HTTP success "
            "status alone cannot prove disclosure."
        )
    if marker and (
        marker not in left.fields.get("response.body", "")
        or not left.fields.get("response.status", "").startswith("2")
    ):
        missing.append(
            "The legitimate control must succeed and contain the declared synthetic-object marker."
        )
    if control is None or control.kind != "request_response" or control.context is None:
        missing.append("A matching protected control observation is required.")
    elif right_context and (
        control.context.account_id != right_context.account_id
        or control.context.object_id != right_context.object_id
        or control.context.session_context_id != right_context.session_context_id
        or control.context.request_context_id != right_context.request_context_id
        or control.fields.get("request.method") != right.fields.get("request.method")
        or control.fields.get("request.body") != right.fields.get("request.body")
        or request_headers(control) != request_headers(right)
        or control.fields.get("response.status") not in {"403", "404"}
        or (marker is not None and marker in control.fields.get("response.body", ""))
    ):
        missing.append(
            "Protected control must match the other session/object/request and "
            "deny access without the synthetic marker."
        )
    if not missing and marker:
        if right.fields.get("response.status") in {"403", "404"} and marker not in right.fields.get(
            "response.body", ""
        ):
            conclusion = "rejected"
            summary = (
                "Imported observations show denial under the declared comparison "
                "conditions; broader safety is unknown."
            )
        elif right.fields.get("response.status", "").startswith("2") and marker in right.fields.get(
            "response.body", ""
        ):
            conclusion = "candidate"
            summary = (
                "Imported observations contain the same declared synthetic object "
                "in the other-account response; local analysis and provenance "
                "review remain necessary."
            )
        else:
            conclusion = "inconclusive"
            summary = (
                "The imported response does not establish either synthetic-object "
                "disclosure or explicit denial."
            )
            missing.append(
                "An unambiguous marker-bearing response or explicit protected denial is needed."
            )
    else:
        conclusion = "inconclusive"
        summary = (
            "The imported comparison lacks matching controls, expectations or "
            "context; no unauthorized-access conclusion is supported."
        )
    return ObservationComparison.model_validate(
        {
            "comparison_id": "CP-" + digest(request.model_dump_json())[:16],
            "request": request,
            "conclusion": conclusion,
            "summary": summary,
            "citations": citations,
            "missing_evidence": missing,
            "alternative_explanations": [
                (
                    "Session identity and collection provenance are supplied by the "
                    "importer and have not been independently verified."
                ),
                (
                    "Different authorization context, public synthetic data or stale "
                    "collection could explain an apparent discrepancy."
                ),
            ],
        }
    )


def answer_task(view: AssessmentView, task: AssessmentTask) -> AssessmentAnswer:
    task = AssessmentTask.model_validate(task.model_dump())
    if task.target_id != view.scope.assessment_id:
        raise ValueError("task target does not match this assessment")
    citations = []
    unknowns = [
        (
            "Imported observations do not establish trusted runtime "
            "reproduction or application-wide security."
        )
    ]
    if task.status != "resolved":
        text = task.clarification or "The task needs clarification."
    elif task.action == "compare":
        result = compare_observations(
            view,
            ComparisonRequest(
                left_artifact_id=task.evidence_ids[0],
                right_artifact_id=task.evidence_ids[1],
                control_artifact_id=task.evidence_ids[2] if len(task.evidence_ids) > 2 else None,
                expectation_id=view.expectations[0].expectation_id
                if len(view.expectations) == 1
                else None,
            ),
        )
        text = result.summary
        citations = result.citations
        unknowns.extend(result.missing_evidence)
    elif task.action in {"plan", "report", "missing"}:
        check_scope(view.scope, action="report" if task.action == "report" else "plan")
        checklist = build_checklist(view)
        text = (
            f"Private report preview is available for {view.scope.assessment_id}; "
            "human review is required before export."
            if task.action == "report"
            else f"The manual checklist contains {len(checklist.items)} planned scopes; "
            f"{len(checklist.untested_paths)} have no imported observation."
        )
        unknowns.extend(
            [
                (
                    "Declare an expected access rule and retain matching legitimate and "
                    "protected controls."
                )
            ]
        )
    elif task.action == "analyze":
        check_scope(view.scope, action="analyze")
        text = (
            "Local-model analysis requires an explicit bounded comparison "
            "request; this resolved prompt has not loaded a model."
        )
        unknowns.append(
            "Fresh local-model acceptance is separate from deterministic task resolution."
        )
    else:
        check_scope(view.scope, action="read")
        selected = task.evidence_ids or [item.artifact_id for item in view.artifacts[:3]]
        parts = []
        for artifact in view.artifacts:
            if artifact.artifact_id not in selected:
                continue
            if artifact.kind == "request_response":
                parts.append(
                    f"{artifact.artifact_id}: imported {artifact.fields['request.method']} "
                    f"observation with response status {artifact.fields['response.status']}."
                )
                citations.extend(
                    artifact_citation(artifact, field)
                    for field in ("request.method", "request.url", "response.status")
                )
            else:
                parts.append(
                    f"{artifact.artifact_id}: human-reviewed {artifact.kind} attachment/statement."
                )
                citations.append(artifact_citation(artifact, next(iter(artifact.fields))))
        text = " ".join(parts) or "No selected saved observations are available."
    return AssessmentAnswer(
        answer_id="A-" + digest(task.model_dump_json() + text)[:16],
        task=task,
        text=text,
        citations=citations,
        unknowns=list(dict.fromkeys(unknowns)),
    )
