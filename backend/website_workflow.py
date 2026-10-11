"""Owned URL -> reviewed observations -> exact comparisons -> existing private report.

This orchestrates the existing assessment boundary. URL creation performs no
network activity; action approval and evidence review remain separate steps.
"""

from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlsplit

from backend.assessment import AssessmentStore, compare_observations
from backend.assessment.evidence import check_scope, digest
from backend.contracts.assessment import (
    AccessExpectation,
    AssessmentView,
    ComparisonRequest,
    normalized_path,
)
from backend.contracts.website import WebsiteScopeCreate
from verification.web_assessment import DECLARED_ORIGIN, preview_lab_assessment


def create_website_scope(store: AssessmentStore, request: WebsiteScopeCreate) -> AssessmentView:
    request = WebsiteScopeCreate.model_validate(request.model_dump())
    parsed = urlsplit(request.url)
    if (
        request.url not in {DECLARED_ORIGIN, DECLARED_ORIGIN + "/", DECLARED_ORIGIN + "/orders"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("external website interaction is disabled; use the exact owned Tandir URL")
    scope = request.scope
    if len(scope.synthetic_objects) != 1:
        raise ValueError("the website workflow requires one explicitly designated synthetic object")
    if not {"read", "compare", "plan", "report", "analyze"}.issubset(scope.allowed_actions):
        raise ValueError(
            "the complete workflow requires the explicitly approved assessment actions"
        )
    # Reuse every pinned-lab scope, account, object, expiry, action and path check.
    # Preview is in-memory here: no action permission, target process or HTTP exists.
    preview_lab_assessment(scope, paired=True)
    if scope.budget.max_requests < 18:
        raise ValueError("reserve twelve collection attempts and two sets of three judgments")
    expectations = [
        AccessExpectation(
            expectation_id="website-owner-" + endpoint,
            path="/orders/{order_id}/" + endpoint,
            object_id=scope.synthetic_objects[0].object_id,
            allowed_account_ids=["alice"],
            statement="Only the designated synthetic owner Alice may read this order's " + endpoint,
            declared_by=scope.authority.granted_by,
            basis=request.expectation_basis,
        )
        for endpoint in ("receipt", "invoice")
    ]
    # Scope and both prior declarations are validated and inserted atomically.
    # Observed success never supplies policy.
    return store.create(scope, expectations=tuple(expectations))


def prepared_website_comparisons(view: AssessmentView, preview_sha256: str) -> AssessmentView:
    """Bind the prior owner declaration to the exact reviewed paired collection.

    Refuse missing/ambiguous observations instead of dropping the protected
    invoice or legitimizing an HTTP success. Nothing is executed here.
    """
    for action in ("plan", "compare"):
        check_scope(view.scope, action=action)
    if view.stopped or datetime.now(UTC) >= view.scope.expires_at:
        raise ValueError("assessment stopped or expired")
    traces = [
        trace
        for trace in view.analyses
        if trace.get("execution_status") == "collected_owned_lab"
        and trace.get("preview_sha256") == preview_sha256
    ]
    if len(traces) != 1 or traces[0].get("stopped"):
        raise ValueError("one completed reviewed paired collection is required")
    raw_records = traces[0].get("records")
    if not isinstance(raw_records, list) or len(raw_records) != 6:
        raise ValueError(
            "the complete receipt/invoice pair requires all six collected observations"
        )
    ids = [row.get("artifact_id") for row in raw_records if isinstance(row, dict)]
    if len(ids) != 6 or len(set(ids)) != 6:
        raise ValueError("paired collection identities must be distinct")
    indexed = {artifact.artifact_id: artifact for artifact in view.artifacts}
    if any(identity not in indexed for identity in ids):
        raise ValueError("human review and import of every collected observation is required")
    artifacts = [indexed[str(identity)] for identity in ids]
    if any(
        artifact.trusted_lab_collection is None
        or artifact.trusted_lab_collection.preview_sha256 != preview_sha256
        or artifact.context is None
        for artifact in artifacts
    ):
        raise ValueError("only exactly bound owned-lab observations can be prepared")
    paths = [
        normalized_path(urlsplit(artifact.fields["request.url"]).path) for artifact in artifacts
    ]
    order = paths[0]
    if (
        order != "/orders"
        or not paths[1].endswith("/receipt")
        or paths[2] != paths[1]
        or not paths[3].endswith("/invoice")
        or paths[4:] != [paths[3], paths[3]]
        or paths[1].rsplit("/", 1)[0] != paths[3].rsplit("/", 1)[0]
        or [artifact.fields["request.method"] for artifact in artifacts] != ["POST", *(["GET"] * 5)]
        or [artifact.context.account_id for artifact in artifacts if artifact.context]
        != ["alice", "bob", "alice", "bob", "alice", "bob"]
    ):
        raise ValueError("collected observations differ from the exact approved paired actions")
    object_ids = Counter(artifact.context.object_id for artifact in artifacts if artifact.context)
    if len(object_ids) != 1:
        raise ValueError("all observations must bind the same designated synthetic object")
    declarations = [
        next(
            (
                item
                for item in view.expectations
                if item.expectation_id == "website-owner-" + endpoint
            ),
            None,
        )
        for endpoint in ("receipt", "invoice")
    ]
    if any(
        item is None
        or item.allowed_account_ids != ["alice"]
        or item.object_id not in object_ids
        or item.path != "/orders/{order_id}/" + endpoint
        for item, endpoint in zip(declarations, ("receipt", "invoice"), strict=True)
    ):
        raise ValueError("the prior explicit owner-only declaration is required for both endpoints")
    expectations = list(view.expectations)
    comparisons = list(view.comparisons)
    for index, (left, right, control) in enumerate(((2, 1, 3), (4, 3, 5))):
        declaration = declarations[index]
        if declaration is None:
            raise ValueError("explicit declaration missing")
        expectation = declaration.model_copy(
            update={
                "expectation_id": "website-owner-" + digest(preview_sha256 + paths[left])[:24],
                "path": paths[left],
            }
        )
        if expectation not in expectations:
            expectations.append(expectation)
        current = view.model_copy(update={"expectations": expectations})
        comparison = compare_observations(
            current,
            ComparisonRequest(
                left_artifact_id=artifacts[left].artifact_id,
                right_artifact_id=artifacts[right].artifact_id,
                control_artifact_id=artifacts[control].artifact_id,
                expectation_id=expectation.expectation_id,
            ),
        )
        if comparison not in comparisons:
            comparisons.append(comparison)
    return view.model_copy(update={"expectations": expectations, "comparisons": comparisons})
