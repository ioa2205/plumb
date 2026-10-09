from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent import questions
from agent.validator import Rule, Unconfirmed, Validator, Violation, check_answer, mentions
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from backend.contracts.code import Guard, GuardKind, GuardMechanism, SourceSpan
from backend.contracts.investigation import Finding, QuestionType
from backend.contracts.verification import ProbeRun, SuggestedChange

from . import examples
from .examples import INVOICE, ORDERS, RECEIPT, SERVICES, packet

ORDERS_PY = "api/routes/orders.py"
SERVICES_PY = "api/services/orders.py"
HELPERS_PY = "api/helpers.py"
ADMIN_PY = "api/routes/admin.py"
DAL_TS = "web/lib/dal.ts"

HELPERS = b"""\
def require_owner(order, user):
    # order.customer_id != user.id is checked upstream
    return order


def read(order, user, admin_user):
    require_owner(order, user)
    if order.customer_id != admin_user.id:
        raise HTTPException(status_code=404)
    return order
"""

ADMIN = b"""\
def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403)
    return user
"""

DAL = b"""\
export function getOrder(viewer: Viewer, id: string) {
  const order = db.prepare("SELECT * FROM orders WHERE id = ?").get(id);
  if (!order || order.customerId !== viewer.id) return null;
  return order;
}
"""

FILES = {
    ORDERS_PY: ORDERS,
    SERVICES_PY: SERVICES,
    HELPERS_PY: HELPERS,
    ADMIN_PY: ADMIN,
    DAL_TS: DAL,
    ".env": b"SESSION_SECRET=not-a-real-secret\n",
}

T0 = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
OTHER = "0" * 64


class Lab:
    """A snapshot of the small project above, its validator, and builders for records."""

    def __init__(self, root: Path) -> None:
        project = root / "project"
        for path, data in FILES.items():
            (project / path).parent.mkdir(parents=True, exist_ok=True)
            (project / path).write_bytes(data)
        self.project = project
        self.store = SnapshotStore(root / "store")
        self.snapshot = take_snapshot(project, self.store)
        self.validator = Validator(self.snapshot, self.store)

    def span(self, path: str, start: int, end: int) -> SourceSpan:
        return SourceSpan(
            snapshot_id=self.snapshot.id,
            path=path,
            start_line=start,
            end_line=end,
            content_sha256=span_sha256(FILES[path], start, end),
        )

    def guard(
        self,
        span: SourceSpan,
        kind: GuardKind = GuardKind.OWNER,
        mechanism: GuardMechanism = GuardMechanism.COMPARISON,
        **fields: object,
    ) -> Guard:
        data = {
            "id": "g:1",
            "snapshot_id": self.snapshot.id,
            "kind": kind,
            "canonical": "OWNER(Order.customer_id = principal.id)",
            "mechanism": mechanism,
            "span": span,
            **fields,
        }
        return Guard.model_validate(data)

    def owner_guard(self) -> Guard:
        """The invoice route's ownership comparison, confirmed by the validator."""
        return self.validator.confirm(
            self.guard(self.span(ORDERS_PY, 16, 21)), subject="user.id", object="order.customer_id"
        )

    def finding(self, **changes: object) -> Finding:
        data = {
            "id": "finding:1",
            "display_id": "F-07",
            "run_id": "run:1",
            "snapshot_id": self.snapshot.id,
            "family": "authorization",
            "cwe": [639],
            "title": "Any signed-in customer can read another customer's receipt",
            "lede": "The receipt route loads the order by ID without checking who owns it.",
            "conclusion": "supported",
            "severity": "high",
            "severity_rationale": "personal data x read x any signed-in customer",
            "strength": "complete",
            "exhibits": [
                {
                    "tag": "E01",
                    "span": self.span(ORDERS_PY, 10, 13),
                    "role": "deviant",
                    "gloss": "Loads by ID only.",
                }
            ],
            **changes,
        }
        return Finding.model_validate(data)

    def rejected(self, exhibit: SourceSpan | None = None) -> Finding:
        """The invoice lookalike: rejected because a found check cites its guard."""
        return self.finding(
            conclusion="rejected",
            exhibits=[
                {
                    "tag": "E01",
                    "span": exhibit or self.span(ORDERS_PY, 16, 21),
                    "role": "guard",
                    "gloss": "Compares the order's customer with the caller.",
                }
            ],
            checks=[
                {
                    "item": "An ownership comparison in the handler",
                    "searched": "api/routes/orders.py:16-21",
                    "found": True,
                    "exhibit_tag": "E01",
                }
            ],
        )

    def run(
        self,
        run_id: str = "probe:1",
        *,
        attack: tuple[int | None, bool | None] = (200, True),
        control: tuple[int | None, bool | None] = (200, True),
        role: str = "vulnerable",
        outcome: str = "reproduced",
        finding_id: str = "finding:1",
        snapshot_id: str | None = None,
    ) -> ProbeRun:
        def step(kind: str, who: str, expected: str, seen: tuple[int | None, bool | None]) -> dict:
            return {
                "role": kind,
                "principal": who,
                "method": "GET",
                "path": "/orders/1/receipt",
                "expected_if_safe": expected,
                "status": seen[0],
                "marker_present": seen[1],
            }

        return ProbeRun.model_validate(
            {
                "id": run_id,
                "finding_id": finding_id,
                "runner": "bundled_lab",
                "runner_manifest_sha256": "1" * 64,
                "snapshot_id": snapshot_id or self.snapshot.id,
                "snapshot_role": role,
                "steps": [
                    step("attack", "bob", "denied", attack),
                    step("control", "alice", "allowed", control),
                ],
                "outcome": outcome,
                "started_at": T0,
                "finished_at": T0,
            }
        )

    def change(self, **changes: object) -> SuggestedChange:
        data = {
            "id": "change:1",
            "finding_id": "finding:1",
            "intent": "Compare the order's customer with the caller.",
            "diff": "--- a/api/routes/orders.py\n+++ b/api/routes/orders.py\n@@ -11 +11 @@\n",
            "files": [ORDERS_PY],
            "status": "replayed_fixed",
            "replay_probe_run_ids": ["probe:2"],
            **changes,
        }
        return SuggestedChange.model_validate(data)


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Lab:
    return Lab(tmp_path_factory.mktemp("validator"))


def rules(violations: list[Violation]) -> list[Rule]:
    return [violation.rule for violation in violations]


# --- rule: bad spans -----------------------------------------------------------------------


def test_a_span_that_matches_the_snapshot_is_accepted(lab: Lab) -> None:
    assert lab.validator.span(lab.span(ORDERS_PY, 10, 13)) == []
    assert lab.validator.span(lab.span(DAL_TS, 1, 5)) == []


def test_spans_are_refused_when_they_do_not_match_the_snapshot(lab: Lab) -> None:
    good = lab.span(ORDERS_PY, 10, 13)
    cases = {
        "cites another snapshot": good.model_copy(update={"snapshot_id": OTHER}),
        "is not a file of the snapshot": good.model_copy(update={"path": "api/missing.py"}),
        "is outside the file (21 lines)": good.model_copy(
            update={"start_line": 21, "end_line": 22}
        ),
        "does not have the content it was cited for": good.model_copy(update={"end_line": 14}),
    }
    for message, span in cases.items():
        (violation,) = lab.validator.span(span)
        assert violation.rule is Rule.BAD_SPAN
        assert message in violation.message


def test_a_file_the_snapshot_excluded_cannot_be_cited(lab: Lab) -> None:
    assert ".env" not in {file.path for file in lab.snapshot.files}
    span = SourceSpan(
        snapshot_id=lab.snapshot.id,
        path=".env",
        start_line=1,
        end_line=1,
        content_sha256=span_sha256(FILES[".env"], 1, 1),
    )
    assert rules(lab.validator.span(span)) == [Rule.BAD_SPAN]


def test_spans_are_checked_against_the_snapshot_not_the_working_tree(tmp_path: Path) -> None:
    own = Lab(tmp_path)
    span = own.span(ORDERS_PY, 19, 19)
    (own.project / ORDERS_PY).write_bytes(ORDERS.replace(b"order.customer_id != user.id", b"False"))
    assert own.validator.span(span) == []
    assert own.owner_guard().confirmed


# --- rule: comment citations ---------------------------------------------------------------


@pytest.mark.parametrize(("start", "end"), [(8, 9), (9, 9), (4, 5)])
def test_lines_without_code_are_not_evidence(lab: Lab, start: int, end: int) -> None:
    span = lab.span(ORDERS_PY, start, end)
    assert lab.validator.span(span) == []  # the lines exist
    (violation,) = lab.validator.evidence(span)
    assert violation.rule is Rule.COMMENT_CITATION
    assert "holds no code" in violation.message


def test_code_next_to_a_comment_is_evidence(lab: Lab) -> None:
    assert lab.validator.evidence(lab.span(ORDERS_PY, 8, 10)) == []
    assert lab.validator.evidence(lab.span(ORDERS_PY, 19, 19)) == []


def test_a_finding_cannot_use_a_comment_as_an_exhibit(lab: Lab) -> None:
    def with_role(role: str) -> Finding:
        exhibit = {
            "tag": "E02",
            "span": lab.span(ORDERS_PY, 8, 9),
            "role": role,
            "gloss": "Says safe.",
        }
        return lab.finding(exhibits=[*lab.finding().model_dump()["exhibits"], exhibit])

    for role in ("evidence", "guard", "source", "sink", "deviant"):
        assert rules(lab.validator.finding(with_role(role))) == [Rule.COMMENT_CITATION]
    # Shown as a developer note, the same lines are allowed: they prove nothing.
    assert lab.validator.finding(with_role("developer_note")) == []


def test_a_finding_with_a_bad_exhibit_span_is_refused(lab: Lab) -> None:
    stale = lab.span(ORDERS_PY, 10, 13).model_copy(update={"content_sha256": "2" * 64})
    finding = lab.finding(
        exhibits=[{"tag": "E01", "span": stale, "role": "deviant", "gloss": "Loads by ID only."}]
    )
    assert rules(lab.validator.finding(finding)) == [Rule.BAD_SPAN]
    other = Lab.finding(lab, snapshot_id=OTHER, exhibits=[])
    assert rules(lab.validator.finding(other)) == [Rule.BAD_SPAN]


# --- confirming a guard --------------------------------------------------------------------


def test_a_comparison_of_caller_and_resource_confirms_an_owner_guard(lab: Lab) -> None:
    candidate = lab.guard(lab.span(ORDERS_PY, 16, 21))
    assert candidate.confirmed is False
    guard = lab.validator.confirm(candidate, subject="user.id", object="order.customer_id")
    assert guard.confirmed is True
    # Keep the comparison and denial together so its enforcement can be rechecked.
    assert (guard.span.start_line, guard.span.end_line) == (19, 20)
    assert lab.validator.evidence(guard.span) == []
    assert guard.model_dump(exclude={"span", "confirmed"}) == candidate.model_dump(
        exclude={"span", "confirmed"}
    )


def test_a_query_filter_and_a_typescript_comparison_confirm_too(lab: Lab) -> None:
    scoped = lab.validator.confirm(
        lab.guard(lab.span(SERVICES_PY, 1, 3), mechanism=GuardMechanism.QUERY_FILTER),
        subject="user.id",
        object="Order.customer_id",
    )
    assert (scoped.confirmed, scoped.span.start_line) == (True, 2)
    dal = lab.validator.confirm(
        lab.guard(lab.span(DAL_TS, 1, 5), mechanism=GuardMechanism.DATA_ACCESS_LAYER),
        subject="viewer.id",
        object="order.customerId",
    )
    assert (dal.confirmed, dal.span.start_line) == (True, 3)


def test_a_role_comparison_confirms_a_role_guard(lab: Lab) -> None:
    span = lab.span(ADMIN_PY, 1, 4)
    guard = lab.validator.confirm(lab.guard(span, GuardKind.ROLE, role="admin"))
    assert (guard.confirmed, guard.span.start_line) == (True, 2)
    for role in ("manager", "adm", None):
        with pytest.raises(Unconfirmed):
            lab.validator.confirm(lab.guard(span, GuardKind.ROLE, role=role))


Confirm = Callable[[Lab], Guard]


@pytest.mark.parametrize(
    ("attempt", "rule", "message"),
    [
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(HELPERS_PY, 2, 2)), subject="user.id", object="order.customer_id"
            ),
            Rule.COMMENT_CITATION,
            "holds no code",
            id="a comment that describes the check",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(HELPERS_PY, 1, 3)), subject="user.id", object="order.customer_id"
            ),
            Rule.UNCONFIRMED_REJECTION,
            "holds no test of user.id against order.customer_id",
            id="a helper whose body does not check",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(HELPERS_PY, 7, 7), mechanism=GuardMechanism.HELPER_CALL),
                subject="user",
                object="order",
            ),
            Rule.UNCONFIRMED_REJECTION,
            "holds no test of user against order",
            id="a call that only passes both values",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(HELPERS_PY, 6, 10)),
                subject="user.id",
                object="order.customer_id",
            ),
            Rule.UNCONFIRMED_REJECTION,
            "holds no test",
            id="another variable whose name ends the same",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(ORDERS_PY, 16, 21)), subject="user.id", object="order.id"
            ),
            Rule.UNCONFIRMED_REJECTION,
            "holds no test of user.id against order.id",
            id="a comparison of something else",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(ORDERS_PY, 6, 13)), subject="user.id", object="order.customer_id"
            ),
            Rule.UNCONFIRMED_REJECTION,
            "holds no test",
            id="a comparison outside the cited span",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(ORDERS_PY, 16, 21)), subject="user.id"
            ),
            Rule.UNCONFIRMED_REJECTION,
            "needs both sides",
            id="an owner guard that names one side",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(ORDERS_PY, 16, 21), GuardKind.AUTHENTICATED)
            ),
            Rule.UNCONFIRMED_REJECTION,
            "no check in code can be recognized for a authenticated guard yet",
            id="a kind with no recognizable check yet",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(ORDERS_PY, 16, 21), GuardKind.NONE)
            ),
            Rule.UNCONFIRMED_REJECTION,
            "no check in code",
            id="the absence of a guard",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(ORDERS_PY, 16, 21), mechanism=GuardMechanism.PROXY_MATCHER),
                subject="user.id",
                object="order.customer_id",
            ),
            Rule.UNCONFIRMED_REJECTION,
            "never a guard",
            id="a proxy matcher",
        ),
        pytest.param(
            lambda lab: lab.validator.confirm(
                lab.guard(lab.span(ORDERS_PY, 16, 21).model_copy(update={"end_line": 20})),
                subject="user.id",
                object="order.customer_id",
            ),
            Rule.BAD_SPAN,
            "does not have the content",
            id="a span that does not match the snapshot",
        ),
    ],
)
def test_a_guard_is_not_confirmed_by(lab: Lab, attempt: Confirm, rule: Rule, message: str) -> None:
    with pytest.raises(Unconfirmed) as refused:
        attempt(lab)
    assert rules(refused.value.violations) == [rule]
    assert message in str(refused.value)


def test_names_match_whole_and_never_inside_longer_ones() -> None:
    assert mentions("if order.customer_id != user.id:", "user.id")
    assert mentions("where(Order.customer_id == user.id)", "Order.customer_id")
    assert not mentions("if order.customer_id != admin_user.id:", "user.id")
    assert not mentions("if order.customer_id != user.identity:", "user.id")
    assert not mentions("session.user.id", "user.id")
    assert not mentions("order.customer_id", "id")


# --- rule: a rejection needs a confirmed guard ---------------------------------------------


def test_a_rejection_that_cites_a_confirmed_guard_is_accepted(lab: Lab) -> None:
    assert lab.validator.finding(lab.rejected(), guards=[lab.owner_guard()]) == []


def test_a_rejection_is_refused_without_a_guard_confirmed_in_code(lab: Lab) -> None:
    confirmed = lab.owner_guard()
    span = lab.span(ORDERS_PY, 16, 21)
    elsewhere = lab.validator.confirm(
        lab.guard(lab.span(SERVICES_PY, 1, 3)), subject="user.id", object="Order.customer_id"
    )
    line = lab.span(ORDERS_PY, 19, 19)
    proxy = GuardMechanism.PROXY_MATCHER
    cases: dict[str, list[Guard]] = {
        "no guard on record": [],
        "a guard nobody confirmed": [lab.guard(span)],
        "a confirmed guard in another place": [elsewhere],
        "a proxy marked confirmed": [lab.guard(line, mechanism=proxy, confirmed=True)],
        "no guard at all, marked confirmed": [lab.guard(line, GuardKind.NONE, confirmed=True)],
        "an unknown check, marked confirmed": [lab.guard(line, GuardKind.UNKNOWN, confirmed=True)],
        "a guard on a comment, marked confirmed": [
            lab.guard(lab.span(ORDERS_PY, 8, 9), confirmed=True)
        ],
    }
    for name, guards in cases.items():
        (violation,) = lab.validator.finding(lab.rejected(), guards=guards)
        assert violation.rule is Rule.UNCONFIRMED_REJECTION, name
        assert "F-07 is rejected without a guard confirmed in code" in violation.message
    # The exhibit must contain the guard; a rejection cannot borrow one from other lines.
    wrong_exhibit = lab.rejected(exhibit=lab.span(ORDERS_PY, 6, 13))
    assert rules(lab.validator.finding(wrong_exhibit, guards=[confirmed])) == [
        Rule.UNCONFIRMED_REJECTION
    ]


def test_only_a_rejection_needs_a_guard(lab: Lab) -> None:
    assert lab.validator.finding(lab.finding()) == []
    assert lab.validator.finding(lab.finding(conclusion="inconclusive")) == []


# --- rule: runtime claims need the probe run that shows them -------------------------------


def reproduced(lab: Lab, **changes: object) -> Finding:
    fields = {"runtime_verification": "reproduced", "probe_run_ids": ["probe:1"], **changes}
    return lab.finding(**fields)


def test_reproduced_with_a_passing_attack_and_control_is_accepted(lab: Lab) -> None:
    assert lab.validator.finding(reproduced(lab), probe_runs=[lab.run()]) == []


def test_reproduced_is_refused_without_an_attack_and_a_control_that_ran(lab: Lab) -> None:
    cases: dict[str, list[ProbeRun]] = {
        "the run is not on record": [],
        "the attack was denied": [lab.run(attack=(404, False), outcome="not_reproduced")],
        "the control failed, so the probe proves nothing": [
            lab.run(control=(500, False), outcome="inconclusive")
        ],
        "the attack never completed": [lab.run(attack=(None, None), outcome="inconclusive")],
        "the run belongs to another finding": [lab.run(finding_id="finding:2")],
        "the run used another snapshot": [lab.run(snapshot_id=OTHER)],
        "the run was on the patched copy": [lab.run(role="patched", outcome="not_fixed")],
    }
    for name, runs in cases.items():
        violations = lab.validator.finding(reproduced(lab), probe_runs=runs)
        assert violations, name
        assert set(rules(violations)) == {Rule.UNPROVEN_RUNTIME_CLAIM}, name
        assert any("says 'reproduced'" in violation.message for violation in violations), name


@pytest.mark.parametrize("claim", ["not_reproduced", "inconclusive"])
def test_a_test_that_did_not_run_cannot_be_claimed(lab: Lab, claim: str) -> None:
    (violation,) = lab.validator.finding(lab.finding(runtime_verification=claim))
    assert violation.rule is Rule.UNPROVEN_RUNTIME_CLAIM
    assert f"says '{claim}', and no probe run on record ended that way" in violation.message


def test_runtime_claims_match_the_runs_on_record(lab: Lab) -> None:
    denied = lab.run(attack=(404, False), outcome="not_reproduced")
    not_reproduced = lab.finding(runtime_verification="not_reproduced", probe_run_ids=["probe:1"])
    assert lab.validator.finding(not_reproduced, probe_runs=[denied]) == []
    both = lab.finding(runtime_verification="not_reproduced", probe_run_ids=["probe:1", "probe:9"])
    contradicted = lab.validator.finding(both, probe_runs=[denied, lab.run("probe:9")])
    assert [v.message for v in contradicted] == [
        "F-07 says 'not_reproduced', and a probe run reproduced it"
    ]
    for claim in ("not_attempted", "unavailable"):
        assert lab.validator.finding(lab.finding(runtime_verification=claim)) == []
        hidden = lab.finding(runtime_verification=claim, probe_run_ids=["probe:1"])
        assert rules(lab.validator.finding(hidden, probe_runs=[lab.run()])) == [
            Rule.UNPROVEN_RUNTIME_CLAIM
        ]


def test_a_fix_is_claimed_only_with_its_replay(lab: Lab) -> None:
    finding = reproduced(lab, suggested_change_id="change:1")
    before = lab.run()
    fixed = lab.run("probe:2", attack=(404, False), role="patched", outcome="fixed")
    check = lab.validator.finding
    assert check(finding, probe_runs=[before, fixed], change=lab.change()) == []
    still_open = lab.run("probe:2", role="patched", outcome="not_fixed")
    broken = lab.run("probe:2", control=(500, False), role="patched", outcome="inconclusive")
    unpatched = lab.run("probe:2", attack=(404, False), outcome="not_reproduced")
    cases: dict[str, tuple[list[ProbeRun], SuggestedChange | None]] = {
        "the change is not on record": ([before, fixed], None),
        "the replay is not on record": ([before], lab.change()),
        "the attack still succeeds": ([before, still_open], lab.change()),
        "the patched server broke": ([before, broken], lab.change()),
        "the replay ran on the unpatched code": ([before, unpatched], lab.change()),
        "the change is for another finding": ([before, fixed], lab.change(finding_id="finding:2")),
        "a failed replay is claimed without one": (
            [before, fixed],
            lab.change(status="replayed_not_fixed"),
        ),
    }
    for name, (runs, change) in cases.items():
        violations = check(finding, probe_runs=runs, change=change)
        assert violations and set(rules(violations)) == {Rule.UNPROVEN_RUNTIME_CLAIM}, name
    outside = lab.change(files=["api/routes/payments.py"])
    assert rules(check(finding, probe_runs=[before, fixed], change=outside)) == [Rule.BAD_SPAN]
    proposed = lab.change(status="proposed", replay_probe_run_ids=[])
    assert check(finding, probe_runs=[before], change=proposed) == []


# --- answers -------------------------------------------------------------------------------

PROMPTS = examples.prompts()


@pytest.mark.parametrize("kind", list(QuestionType), ids=lambda kind: kind.value)
def test_a_grounded_answer_passes(kind: QuestionType) -> None:
    prompt = PROMPTS[kind]
    assert check_answer(prompt, prompt.parse(examples.ANSWERS[kind])) == []


def guards(*items: dict[str, object]) -> dict[str, object]:
    return {"guards": [{"subject": None, "object": None, **item} for item in items]}


def test_an_answer_cannot_cite_a_line_it_was_not_shown() -> None:
    prompt = PROMPTS[QuestionType.GUARD_SUMMARY]
    answer = prompt.parse(guards({"kind": "authenticated", "line_ids": ["L2", "L99", "L99"]}))
    (violation,) = check_answer(prompt, answer)
    assert (violation.rule, violation.message) == (
        Rule.UNKNOWN_LINE,
        "L99 is not a line of the evidence",
    )


def test_operands_that_are_not_in_the_cited_code_are_refused() -> None:
    # What M0.6 saw: a sign-in check reported with an ownership comparison nobody wrote.
    prompt = questions.guard_summary(packet(RECEIPT))
    invented = guards(
        {
            "kind": "authenticated",
            "subject": "user.id",
            "object": "order.customer_id",
            "line_ids": ["L2"],
        }
    )
    violations = check_answer(prompt, prompt.parse(invented))
    assert rules(violations) == [Rule.CONSTRUCT_NOT_FOUND, Rule.CONSTRUCT_NOT_FOUND]
    assert violations[1].message == "order.customer_id does not appear in the code of L2"


def test_an_owner_guard_names_both_sides_and_cites_where_they_are_compared() -> None:
    prompt = questions.guard_summary(packet(INVOICE))
    owner = {"kind": "owner", "subject": "user.id", "object": "order.customer_id"}
    assert check_answer(prompt, prompt.parse(guards({**owner, "line_ids": ["L4"]}))) == []
    # The names exist in the function, but not on the line the answer cites.
    assert rules(check_answer(prompt, prompt.parse(guards({**owner, "line_ids": ["L3"]})))) == [
        Rule.CONSTRUCT_NOT_FOUND,
        Rule.CONSTRUCT_NOT_FOUND,
    ]
    nameless = prompt.parse(guards({"kind": "owner", "line_ids": ["L4"]}))
    (violation,) = check_answer(prompt, nameless)
    assert violation.message == "the owner guard does not name both sides it compares"


def test_null_written_as_a_word_is_read_as_null() -> None:
    prompt = questions.guard_summary(packet(RECEIPT))
    answer = prompt.parse(
        guards({"kind": "authenticated", "subject": "None", "object": " null ", "line_ids": ["L2"]})
    )
    assert check_answer(prompt, answer) == []


def test_guard_equivalent_cites_each_part_from_its_own_lines() -> None:
    prompt = PROMPTS[QuestionType.GUARD_EQUIVALENT]

    def check(same: str, first: list[str], second: list[str]) -> list[Violation]:
        data = {"same": same, "first_line_ids": first, "second_line_ids": second}
        return check_answer(prompt, prompt.parse(data))

    assert check("yes", ["L4"], ["L8"]) == []
    assert check("no", ["L4"], []) == []
    assert check("unknown", [], []) == []
    assert [v.message for v in check("yes", ["L8"], ["L4"])] == [
        "L8 is not a line of the first part",
        "L4 is not a line of the second part",
    ]
    assert rules(check("yes", [], ["L8"])) == [Rule.MISSING_CITATION]
    assert rules(check("yes", [], [])) == [Rule.MISSING_CITATION, Rule.MISSING_CITATION]


def test_a_claim_needs_a_cited_line_and_finding_nothing_does_not() -> None:
    origin = PROMPTS[QuestionType.INPUT_ORIGIN]
    exception = PROMPTS[QuestionType.INTENTIONAL_EXCEPTION]
    cases = [
        (origin, {"origin": "path", "line_ids": []}, [Rule.MISSING_CITATION]),
        (origin, {"origin": "constant", "line_ids": []}, [Rule.MISSING_CITATION]),
        (origin, {"origin": "unknown", "line_ids": []}, []),
        (exception, {"reason": "admin_only", "line_ids": []}, [Rule.MISSING_CITATION]),
        (exception, {"reason": "scoped_elsewhere", "line_ids": []}, [Rule.MISSING_CITATION]),
        (exception, {"reason": "none_found", "line_ids": []}, []),
    ]
    for prompt, data, expected in cases:
        assert rules(check_answer(prompt, prompt.parse(data))) == expected, data
    sink = PROMPTS[QuestionType.SINK_SAFETY]
    unsupported = sink.parse({"mechanism": "parameterized", "line_ids": []})
    assert rules(check_answer(sink, unsupported)) == [Rule.MISSING_CITATION]


def test_an_exposed_field_must_appear_on_its_cited_path() -> None:
    prompt = PROMPTS[QuestionType.CLIENT_EXPOSURE]

    def check(name: str, line_ids: list[str]) -> list[Rule]:
        return rules(
            check_answer(prompt, prompt.parse({"fields": [{"name": name, "line_ids": line_ids}]}))
        )

    assert check("card_last4", ["L11", "L5", "L6"]) == []
    assert check("email", ["L11", "L5", "L6"]) == [Rule.CONSTRUCT_NOT_FOUND]
    assert check("card_last4", ["L5", "L6"]) == [Rule.CONSTRUCT_NOT_FOUND]
    assert check("card", ["L11"]) == [Rule.CONSTRUCT_NOT_FOUND]
    assert check("card_last4", []) == [Rule.MISSING_CITATION]
    assert check_answer(prompt, prompt.parse({"fields": []})) == []


def test_a_fix_gives_code_for_every_line_it_changes() -> None:
    prompt = PROMPTS[QuestionType.FIX_SKETCH]
    good = examples.ANSWERS[QuestionType.FIX_SKETCH]

    def check(*edits: dict[str, str]) -> list[Rule]:
        return rules(check_answer(prompt, prompt.parse({**good, "edits": list(edits)})))

    assert check({"line_id": "L4", "action": "delete", "code": ""}) == []
    assert check({"line_id": "L4", "action": "replace", "code": "   "}) == [
        Rule.CONSTRUCT_NOT_FOUND
    ]
    assert check({"line_id": "L9", "action": "insert_after", "code": "    pass"}) == [
        Rule.UNKNOWN_LINE
    ]
    assert check() == [Rule.MISSING_CITATION]
