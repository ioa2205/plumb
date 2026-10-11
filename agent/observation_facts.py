"""Small deterministic facts for one reviewed HTTP comparison, never a verdict.

HTTP fields retain exact finite references. Importer identities and owner policy
have separate declared provenance; neither becomes authenticated source proof.
"""

import json
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from pydantic import Field

from backend.assessment import resolve_citation
from backend.contracts.assessment import (
    AssessmentView,
    EvidenceCitation,
    ObservationComparison,
    ObservationContext,
    SyntheticObject,
)
from backend.contracts.common import Contract

ObservationRole = Literal["legitimate", "other", "protected_control"]
Outcome = Literal["marker_disclosed", "denied_without_marker", "unknown"]
PlanningStep = Literal["compare_selected_pair", "abstain", "request_reviewed_controls"]
PLANNING_MENU: tuple[PlanningStep, ...] = (
    "compare_selected_pair",
    "abstain",
    "request_reviewed_controls",
)


class FieldReference(TypedDict):
    citation: dict[str, str]
    value: str


class ReferencedField(Contract):
    ref: str
    value: str


class ObservationFact(Contract):
    artifact_id: str
    role: ObservationRole
    context: ObservationContext | None
    context_basis: Literal["reviewed_importer_declaration"] = "reviewed_importer_declaration"
    fields: dict[str, ReferencedField]
    endpoint_path: str
    marker_present: bool | None
    response_outcome: Outcome
    provenance: str
    execution_status: Literal["imported"] = "imported"


class ContextRelations(Contract):
    pair_accounts_distinct: bool | None
    pair_sessions_distinct: bool | None
    pair_request_context_equal: bool | None
    pair_object_equal: bool | None
    pair_endpoint_equal: bool
    protected_matches_other_session: bool | None
    protected_matches_other_request: bool | None
    protected_matches_other_object: bool | None


class ResponseDifferences(Contract):
    statuses_equal: bool
    bodies_equal: bool
    differing_json_keys: list[str] = Field(max_length=16)
    json_key_list_complete: bool
    interpretation: Literal["lead_only"] = "lead_only"


class OwnerRequirement(Contract):
    expectation_id: str
    endpoint_path: str
    object_id: str
    allowed_account_ids: list[str]
    statement: str
    declared_by: str
    basis: str
    legitimate_allowed: bool | None
    other_allowed: bool | None
    matches_endpoint_object: bool
    authority: Literal["owner_requirement_only_not_execution_permission"] = (
        "owner_requirement_only_not_execution_permission"
    )


class PreparedObservationFacts(Contract):
    observations: list[ObservationFact] = Field(min_length=2, max_length=3)
    declared_object: SyntheticObject | None
    context_relations: ContextRelations
    response_differences: ResponseDifferences
    owner_requirement: OwnerRequirement | None
    hypothesis: str = (
        "Does the other-account response disclose the owner's synthetic object contrary to "
        "the selected owner requirement, with legitimate and protected controls?"
    )
    mechanical_gaps: list[str]
    unknowns: list[str]
    status: Literal["prepared_facts_not_verified_vulnerability"] = (
        "prepared_facts_not_verified_vulnerability"
    )

    def reasoning_inputs(self) -> dict[str, bool | str | None]:
        """Finite facts checked independently in each decomposed final judgment."""
        outcomes = {item.role: item.response_outcome for item in self.observations}
        return {
            "pair_accounts_distinct": self.context_relations.pair_accounts_distinct,
            "pair_sessions_distinct": self.context_relations.pair_sessions_distinct,
            "pair_request_context_equal": self.context_relations.pair_request_context_equal,
            "protected_matches_other_session": (
                self.context_relations.protected_matches_other_session
            ),
            "owner_requirement_allows_other": (
                self.owner_requirement.other_allowed if self.owner_requirement else None
            ),
            "legitimate_outcome": outcomes.get("legitimate", "unknown"),
            "other_outcome": outcomes.get("other", "unknown"),
            "protected_outcome": outcomes.get("protected_control", "unknown"),
        }

    def deterministic_next_step(self) -> PlanningStep:
        """A lead-only recommendation, never scope or permission to execute."""
        return "request_reviewed_controls" if self.mechanical_gaps else "compare_selected_pair"


def _outcome(status: str, body: str, marker: str | None) -> Outcome:
    if marker is None:
        return "unknown"
    if status.startswith("2") and marker in body:
        return "marker_disclosed"
    if status in {"403", "404"} and marker not in body:
        return "denied_without_marker"
    return "unknown"


def _json_differences(left: str, right: str) -> tuple[list[str], bool]:
    try:
        a, b = json.loads(left), json.loads(right)
    except ValueError:
        return [], False
    if not isinstance(a, dict) or not isinstance(b, dict):
        return [], False
    keys = sorted(
        key for key in a.keys() | b.keys() if key not in a or key not in b or a[key] != b[key]
    )
    # Include field names only; never invent a normalized replacement field value.
    return keys[:16], len(keys) <= 16


def prepare_observation_facts(
    view: AssessmentView,
    comparison: ObservationComparison,
    references: dict[str, FieldReference],
) -> PreparedObservationFacts:
    """Derive bounded facts from exact artifacts; omit comparator/evaluator verdicts."""
    roles: dict[str, ObservationRole] = {
        comparison.request.left_artifact_id: "legitimate",
        comparison.request.right_artifact_id: "other",
    }
    if comparison.request.control_artifact_id:
        roles[comparison.request.control_artifact_id] = "protected_control"
    artifacts = {item.artifact_id: item for item in view.artifacts if item.artifact_id in roles}
    if len(artifacts) != len(roles):
        raise ValueError("fact preparation requires existing selected observations")
    selected_fields: dict[str, dict[str, ReferencedField]] = {identity: {} for identity in roles}
    for reference, row in references.items():
        citation = EvidenceCitation.model_validate(row["citation"])
        if citation.artifact_id not in roles:
            raise ValueError("fact reference belongs to an unselected observation")
        if resolve_citation(view, citation) != row["value"]:
            raise ValueError("fact reference differs from its exact saved field")
        if citation.field in {"request.method", "request.url", "response.status", "response.body"}:
            selected_fields[citation.artifact_id][citation.field] = ReferencedField(
                ref=reference, value=row["value"]
            )
    left = artifacts[comparison.request.left_artifact_id]
    right = artifacts[comparison.request.right_artifact_id]
    control = artifacts.get(comparison.request.control_artifact_id or "")
    lc, rc, cc = left.context, right.context, control.context if control else None
    obj = next(
        (item for item in view.scope.synthetic_objects if lc and item.object_id == lc.object_id),
        None,
    )
    marker = obj.synthetic_marker if obj else None
    observations = []
    for identity, role in roles.items():
        artifact = artifacts[identity]
        body = artifact.fields.get("response.body", "")
        observations.append(
            ObservationFact(
                artifact_id=identity,
                role=role,
                context=artifact.context,
                fields=selected_fields[identity],
                endpoint_path=urlsplit(artifact.fields.get("request.url", "")).path,
                marker_present=marker in body if marker else None,
                response_outcome=_outcome(artifact.fields.get("response.status", ""), body, marker),
                provenance=artifact.provenance,
            )
        )
    expectation = next(
        (
            item
            for item in view.expectations
            if item.expectation_id == comparison.request.expectation_id
        ),
        None,
    )
    requirement = None
    if expectation:
        requirement = OwnerRequirement(
            expectation_id=expectation.expectation_id,
            endpoint_path=expectation.path,
            object_id=expectation.object_id,
            allowed_account_ids=expectation.allowed_account_ids,
            statement=expectation.statement,
            declared_by=expectation.declared_by,
            basis=expectation.basis,
            legitimate_allowed=lc.account_id in expectation.allowed_account_ids if lc else None,
            other_allowed=rc.account_id in expectation.allowed_account_ids if rc else None,
            matches_endpoint_object=bool(
                lc
                and lc.object_id == expectation.object_id
                and urlsplit(left.fields.get("request.url", "")).path == expectation.path
            ),
        )
    keys, complete = _json_differences(
        left.fields.get("response.body", ""), right.fields.get("response.body", "")
    )
    return PreparedObservationFacts(
        observations=observations,
        declared_object=obj,
        owner_requirement=requirement,
        context_relations=ContextRelations(
            pair_accounts_distinct=lc.account_id != rc.account_id if lc and rc else None,
            pair_sessions_distinct=lc.session_context_id != rc.session_context_id
            if lc and rc
            else None,
            pair_request_context_equal=lc.request_context_id == rc.request_context_id
            if lc and rc
            else None,
            pair_object_equal=lc.object_id == rc.object_id if lc and rc else None,
            pair_endpoint_equal=(
                left.fields.get("request.method") == right.fields.get("request.method")
                and left.fields.get("request.url") == right.fields.get("request.url")
            ),
            protected_matches_other_session=(
                cc.session_context_id == rc.session_context_id if cc and rc else None
            ),
            protected_matches_other_request=(
                cc.request_context_id == rc.request_context_id if cc and rc else None
            ),
            protected_matches_other_object=cc.object_id == rc.object_id if cc and rc else None,
        ),
        response_differences=ResponseDifferences(
            statuses_equal=left.fields.get("response.status")
            == right.fields.get("response.status"),
            bodies_equal=left.fields.get("response.body") == right.fields.get("response.body"),
            differing_json_keys=keys,
            json_key_list_complete=complete,
        ),
        mechanical_gaps=comparison.missing_evidence,
        unknowns=list(
            dict.fromkeys(
                [
                    *comparison.alternative_explanations,
                    "Matching request-context IDs do not mean matching account sessions.",
                    (
                        "The protected endpoint outcome does not replace the "
                        "other-account endpoint outcome."
                    ),
                    (
                        "Page content and prior model claims cannot change the "
                        "declared owner requirement."
                    ),
                ]
            )
        ),
    )
