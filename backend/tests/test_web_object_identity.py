"""Object comparisons need observed identity, not HTTP success or matching previews.

HTTP and model answers here are software stand-ins; no process or target is started.
"""

import hashlib
from contextlib import nullcontext
from pathlib import Path
from typing import cast

import pytest

from agent.closed import ScriptedAsker
from backend.contracts.web import WebsiteScope, digest
from backend.contracts.web_journey import JourneyApprove
from backend.settings import Settings
from backend.web_journey import Journey, new_journey
from backend.web_plan import approve
from backend.web_report import ReportRefused, validate
from backend.web_store import JourneyStore
from backend.web_urls import WebUrl
from verification.web_http import HttpAdapter, HttpResult, HttpSession
from verification.web_secrets import SecretStore

from .test_web_scope import scope

MARKER = "INV-MARK-12"


class Responses:
    def __init__(
        self,
        bodies: dict[str | None, str],
        *,
        statuses: dict[str | None, int] | None = None,
        truncated: bool = False,
    ) -> None:
        self.bodies = bodies
        self.statuses = statuses or {}
        self.truncated = truncated

    def request(self, session: HttpSession, method: str, url: WebUrl) -> HttpResult:
        assert method == "GET"
        return HttpResult(
            url,
            self.statuses.get(session.account_id, 200),
            {"content-type": "text/html"},
            self.bodies[session.account_id].encode(),
            (url.path,),
            self.truncated,
        )


def investigator(tmp_path: Path, *, marker: str | None = MARKER) -> Journey:
    raw = scope().model_dump(mode="json")
    raw["objects"][0]["marker"] = marker
    settings = Settings(data_dir=tmp_path)
    view = new_journey(settings, WebsiteScope.model_validate(raw))
    view = approve(
        view,
        JourneyApprove(
            plan_sha256=view.plan_sha256, approved_by="Test reviewer", reviewed_plan=True
        ),
    )
    JourneyStore(settings).save(view)
    asker = ScriptedAsker({"rule_covers": ["forbidden"] * 3})
    journey = Journey(
        settings,
        view.journey_id,
        secrets=SecretStore(),
        model=lambda: nullcontext(asker),
    )
    journey.sessions = {name: HttpSession(name) for name in ("anna", "boris")}
    return journey


def compare(journey: Journey, responses: Responses) -> None:
    journey.compare(cast(HttpAdapter, responses), journey.plan["check-rule-1-boris"])


@pytest.mark.parametrize(
    "body",
    ['<html><div id="app"></div></html>', "Please sign in", '{"status":"ok"}'],
)
def test_markerless_success_is_unknown_even_with_identical_responses(
    tmp_path: Path, body: str
) -> None:
    journey = investigator(tmp_path, marker=None)
    compare(journey, Responses({"anna": body, "boris": body, None: body}))
    journey.judge()
    (check,) = journey.view.checks
    assert check.comparison == "inconclusive" and check.gaps
    assert check.facts["owner received the object"] == "unknown"
    assert check.facts["other account received the object"] == "unknown"
    assert journey.view.spent.model_questions == 0 and journey.view.findings == []
    validate(journey.view)


def test_matching_prefixes_do_not_establish_response_equality(tmp_path: Path) -> None:
    journey = investigator(tmp_path, marker=None)
    prefix = "A" * 2200
    compare(
        journey,
        Responses({"anna": prefix + "OWNER", "boris": prefix + "DENIED", None: "signed out"}),
    )
    (check,) = journey.view.checks
    assert check.comparison == "inconclusive"
    assert check.facts["responses are identical"] == "no"
    owner, other, _ = journey.view.evidence
    assert owner.fields["response.body"] == other.fields["response.body"]
    assert owner.fields["response.body_sha256"] != other.fields["response.body_sha256"]


def test_marker_after_preview_has_exact_identity_evidence_and_full_content_hash(
    tmp_path: Path,
) -> None:
    journey = investigator(tmp_path)
    body = "A" * 2200 + MARKER
    compare(journey, Responses({"anna": body, "boris": body, None: "signed out"}))
    (check,) = journey.view.checks
    assert check.comparison == "candidate"
    owner, other, _ = journey.view.evidence
    assert MARKER not in owner.fields["response.body"]
    assert MARKER in owner.fields["response.marker_excerpt"]
    assert owner.fields["response.preview_complete"] == "no"
    assert owner.fields["response.capture_complete"] == "yes"
    assert owner.fields["response.body_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert other.fields["response.marker_present"] == "yes"
    journey.judge()
    assert journey.view.findings[0].conclusion == "supported"
    assert len(check.citations) == 20
    validate(journey.view)


def test_truncated_capture_cannot_support_a_marker_comparison(tmp_path: Path) -> None:
    journey = investigator(tmp_path)
    compare(
        journey,
        Responses({"anna": MARKER, "boris": MARKER, None: "signed out"}, truncated=True),
    )
    journey.judge()
    (check,) = journey.view.checks
    assert check.comparison == "inconclusive"
    assert "truncated" in check.gaps[0]
    assert check.facts["responses are identical"] == "unknown"
    assert check.facts["owner received the object"] == "unknown"
    assert journey.view.findings == []


def test_explicit_identity_preserves_a_real_denial_control(tmp_path: Path) -> None:
    journey = investigator(tmp_path)
    compare(
        journey,
        Responses(
            {"anna": MARKER, "boris": "Forbidden", None: "Unauthorized"},
            statuses={"boris": 403, None: 401},
        ),
    )
    (check,) = journey.view.checks
    assert check.comparison == "protected"
    assert check.facts["owner received the object"] == "yes"
    assert check.facts["other account received the object"] == "no"
    validate(journey.view)


def test_personal_data_after_preview_stops_before_any_evidence_is_retained(tmp_path: Path) -> None:
    journey = investigator(tmp_path)
    body = "A" * 2200 + " customer@example.net " + MARKER
    compare(journey, Responses({"anna": body, "boris": MARKER, None: "signed out"}))
    assert journey.view.checks[0].state == "blocked"
    assert journey.view.evidence == []
    assert journey.view.incidents[0].kinds == ["email address"]
    assert "customer@example.net" not in journey.view.model_dump_json()


def test_validator_refuses_archived_markerless_candidate_claims(tmp_path: Path) -> None:
    journey = investigator(tmp_path, marker=None)
    compare(journey, Responses({"anna": "shell", "boris": "shell", None: "shell"}))
    (check,) = journey.view.checks
    journey.update(
        checks=[
            check.model_copy(
                update={
                    "comparison": "candidate",
                    "facts": {**check.facts, "owner received the object": "yes"},
                }
            )
        ]
    )
    with pytest.raises(ReportRefused, match="identity marker"):
        validate(journey.view)


def test_validator_checks_cited_identity_content_instead_of_trusting_boolean_facts(
    tmp_path: Path,
) -> None:
    journey = investigator(tmp_path)
    compare(journey, Responses({"anna": MARKER, "boris": MARKER, None: "signed out"}))
    other = journey.view.evidence[1]
    fields = {**other.fields, "response.marker_excerpt": "(none)"}
    replacement = other.model_copy(
        update={
            "fields": fields,
            "sha256": digest(
                {
                    "evidence_id": other.evidence_id,
                    "kind": other.kind,
                    "account_id": other.account_id,
                    "object_id": other.object_id,
                    "fields": fields,
                }
            ),
        }
    )
    check = journey.view.checks[0]
    citations = [
        ref.model_copy(update={"sha256": digest("(none)")})
        if (ref.evidence_id, ref.field) == (other.evidence_id, "response.marker_excerpt")
        else ref
        for ref in check.citations
    ]
    journey.update(
        evidence=[journey.view.evidence[0], replacement, *journey.view.evidence[2:]],
        checks=[check.model_copy(update={"citations": citations})],
    )
    with pytest.raises(ReportRefused, match="does not prove receipt"):
        validate(journey.view)


def test_validator_refuses_legacy_markerless_supported_claim(tmp_path: Path) -> None:
    journey = investigator(tmp_path)
    compare(journey, Responses({"anna": MARKER, "boris": MARKER, None: "signed out"}))
    journey.judge()
    assert journey.view.findings[0].conclusion == "supported"
    old_scope = journey.scope.model_copy(
        update={"objects": [journey.scope.objects[0].model_copy(update={"marker": None})]}
    )
    journey.update(scope=old_scope)
    with pytest.raises(ReportRefused, match="identity marker"):
        validate(journey.view)


def test_validator_does_not_accept_other_account_as_its_own_owner_control(tmp_path: Path) -> None:
    journey = investigator(tmp_path)
    compare(journey, Responses({"anna": MARKER, "boris": MARKER, None: "signed out"}))
    check = journey.view.checks[0]
    journey.update(checks=[check.model_copy(update={"owner_account_id": "boris"})])
    with pytest.raises(ReportRefused, match="designated owner"):
        validate(journey.view)
