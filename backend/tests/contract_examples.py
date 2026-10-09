"""One realistic instance of every contract, built around the F-07 receipt story."""

import hashlib
from datetime import UTC, date, datetime

from backend.contracts import (
    AccessSite,
    ApplicationMap,
    Contract,
    EntryPoint,
    Finding,
    Guard,
    PeerGroup,
    PolicyAssertion,
    ProbeRun,
    ProjectSnapshot,
    Question,
    ReviewRun,
    SourceSpan,
    SuggestedChange,
    Symbol,
    ToolObservation,
)
from backend.contracts.application_map import LinkKind, MapLink, UnknownTarget
from backend.contracts.code import (
    DataLayer,
    EntryPointKind,
    GuardKind,
    GuardMechanism,
    Operation,
    PeerColumn,
    PeerDeviation,
    PeerExclusion,
    PolicyStatus,
    SnapshotFile,
    SymbolKind,
    snapshot_id,
)
from backend.contracts.common import Family, Framework, InputOrigin, Language, LinkStatus
from backend.contracts.investigation import (
    ChallengeCheck,
    Conclusion,
    EvidenceStrength,
    Exhibit,
    ExhibitRole,
    ObservationStatus,
    QuestionStage,
    QuestionStatus,
    QuestionType,
    RuntimeVerification,
    Severity,
)
from backend.contracts.runs import (
    Condition,
    ConditionKind,
    Coverage,
    EventKind,
    ModelRef,
    RunEvent,
    RunLifecycle,
    RunStage,
    RunType,
    Toolchain,
)
from backend.contracts.verification import (
    Access,
    ChangeStatus,
    HTTPProbeRequest,
    ProbeOutcome,
    ProbeSpec,
    ProbeStep,
    RunnerKind,
    SnapshotRole,
    StepRole,
)

T0 = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 3, 9, 5, tzinfo=UTC)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


FILES = [
    SnapshotFile(path="api/routes/orders.py", sha256=h("orders"), size=2048, language="python"),
    SnapshotFile(path="api/services/orders.py", sha256=h("services"), size=1024, language="python"),
]
SNAP = snapshot_id(FILES)


def span(path: str, start: int, end: int) -> SourceSpan:
    return SourceSpan(
        snapshot_id=SNAP, path=path, start_line=start, end_line=end, content_sha256=h(path)
    )


RECEIPT = span("api/routes/orders.py", 41, 47)
INVOICE_GUARD = span("api/services/orders.py", 12, 18)


def snapshot() -> ProjectSnapshot:
    return ProjectSnapshot(
        id=SNAP,
        root_name="tandir",
        created_at=T0,
        git_commit="3f9c1a2",
        dirty=True,
        files=FILES,
        excluded=[{"path": "api/.env", "reason": "secret"}],
    )


def symbol() -> Symbol:
    return Symbol(
        id="sym:get_receipt",
        snapshot_id=SNAP,
        name="get_receipt",
        qualified_name="api.routes.orders.get_receipt",
        kind=SymbolKind.FUNCTION,
        language=Language.PYTHON,
        span=RECEIPT,
    )


def entry_point() -> EntryPoint:
    return EntryPoint(
        id="ep:receipt",
        snapshot_id=SNAP,
        kind=EntryPointKind.HTTP_ROUTE,
        framework=Framework.FASTAPI,
        method="GET",
        route="/orders/{order_id}/receipt",
        handler_symbol_id="sym:get_receipt",
        span=RECEIPT,
    )


def guard() -> Guard:
    return Guard(
        id="g:owner-invoice",
        snapshot_id=SNAP,
        kind=GuardKind.OWNER,
        canonical="OWNER(Order.customer_id = principal.id)",
        mechanism=GuardMechanism.QUERY_FILTER,
        subject="principal.id",
        object="Order.customer_id",
        span=INVOICE_GUARD,
        via_symbol_id="sym:load_order_scoped",
        confirmed=True,
    )


def access_site() -> AccessSite:
    return AccessSite(
        id="site:receipt",
        snapshot_id=SNAP,
        entry_point_id="ep:receipt",
        resource="Order",
        operation=Operation.READ,
        key_origin=InputOrigin.PATH,
        data_layer=DataLayer.SQLALCHEMY,
        span=span("api/routes/orders.py", 44, 44),
        guard_ids=["g:authn"],
    )


SITES = [f"site:{n}" for n in range(1, 9)]


def peer_group() -> PeerGroup:
    return PeerGroup(
        id="peers:order",
        snapshot_id=SNAP,
        resource="Order",
        site_ids=SITES,
        columns=[
            PeerColumn(key="AUTHN", label="Signed in", applied_site_ids=SITES),
            PeerColumn(key="OWNER", label="Owns the order", applied_site_ids=SITES[:7]),
        ],
        excluded=[PeerExclusion(site_id="site:admin-search", reason="staff-only route")],
        deviations=[
            PeerDeviation(site_id="site:8", missing="OWNER", peers_applying=7, peers_total=8)
        ],
    )


def question() -> Question:
    return Question(
        id="q:1",
        run_id="run:1",
        type=QuestionType.GUARD_SUMMARY,
        family=Family.AUTHORIZATION,
        stage=QuestionStage.RECORD,
        status=QuestionStatus.ANSWERED,
        subject_ids=["site:receipt"],
        evidence=[RECEIPT],
        priority_reasons=["request-controlled identifier", "personal data", "peer deviation"],
        answer={"guards": [{"kind": "authenticated", "line_ids": ["L3"]}]},
        observation_ids=["obs:1"],
    )


def observation() -> ToolObservation:
    return ToolObservation(
        id="obs:1",
        run_id="run:1",
        question_id="q:1",
        tool="llama-server",
        tool_version="b11146",
        inputs={"question": "guard_summary", "prompt_tokens": 812},
        started_at=T0,
        finished_at=T1,
        output_sha256=h("answer"),
        status=ObservationStatus.OK,
    )


def finding() -> Finding:
    return Finding(
        id="finding:1",
        display_id="F-07",
        run_id="run:1",
        snapshot_id=SNAP,
        family=Family.AUTHORIZATION,
        cwe=[639],
        title="Any signed-in customer can read another customer's receipt",
        lede="The receipt route loads the order by ID without checking who owns it [E01].",
        conclusion=Conclusion.SUPPORTED,
        runtime_verification=RuntimeVerification.REPRODUCED,
        severity=Severity.HIGH,
        severity_rationale="personal data x read x any signed-in customer",
        strength=EvidenceStrength.COMPLETE,
        exhibits=[
            Exhibit(tag="E01", span=RECEIPT, role=ExhibitRole.DEVIANT, gloss="Loads by ID only."),
            Exhibit(tag="E02", span=INVOICE_GUARD, role=ExhibitRole.GUARD, gloss="Peer guard."),
        ],
        checks=[
            ChallengeCheck(
                item="A query filter scoped to the principal",
                searched="api/routes/orders.py:41-47",
                found=False,
            ),
        ],
        peer_group_id="peers:order",
        unknowns=["Whether receipts are meant to be shareable links."],
        question_ids=["q:1"],
        probe_run_ids=["probe:1"],
        suggested_change_id="change:1",
    )


def steps(attack_status: int, attack_marker: bool) -> list[ProbeStep]:
    return [
        ProbeStep(
            role=StepRole.SETUP,
            principal="alice",
            method="POST",
            path="/orders",
            expected_if_safe=Access.ALLOWED,
            status=201,
            marker_present=True,
        ),
        ProbeStep(
            role=StepRole.ATTACK,
            principal="bob",
            method="GET",
            path="/orders/1/receipt",
            expected_if_safe=Access.DENIED,
            status=attack_status,
            marker_present=attack_marker,
        ),
        ProbeStep(
            role=StepRole.CONTROL,
            principal="alice",
            method="GET",
            path="/orders/1/receipt",
            expected_if_safe=Access.ALLOWED,
            status=200,
            marker_present=True,
        ),
    ]


def probe_run() -> ProbeRun:
    return ProbeRun(
        id="probe:1",
        finding_id="finding:1",
        runner=RunnerKind.BUNDLED_LAB,
        runner_manifest_sha256=h("tandir manifest"),
        snapshot_id=SNAP,
        snapshot_role=SnapshotRole.VULNERABLE,
        steps=steps(200, True),
        outcome=ProbeOutcome.REPRODUCED,
        started_at=T0,
        finished_at=T1,
    )


DIFF = """\
--- a/api/routes/orders.py
+++ b/api/routes/orders.py
@@ -44 +44 @@
-    order = session.get(Order, order_id)
+    order = load_order_scoped(session, order_id, principal)
"""


def suggested_change() -> SuggestedChange:
    return SuggestedChange(
        id="change:1",
        finding_id="finding:1",
        intent="Load the order through the scoped loader the invoice route already uses.",
        diff=DIFF,
        files=["api/routes/orders.py"],
        status=ChangeStatus.REPLAYED_FIXED,
        replay_probe_run_ids=["probe:2"],
    )


def review_run() -> ReviewRun:
    return ReviewRun(
        id="run:1",
        snapshot_id=SNAP,
        run_type=RunType.LIVE,
        lifecycle=RunLifecycle.RUNNING,
        stage=RunStage.INVESTIGATING,
        conditions=[
            Condition(
                kind=ConditionKind.RUNNER_UNAVAILABLE,
                message="Runtime verification is unavailable: Windows Sandbox is not enabled.",
                action="How to enable",
            )
        ],
        created_at=T0,
        started_at=T0,
        model=ModelRef(id="qwen3.5-2b-q4_k_m", file_sha256=h("model"), quantization="Q4_K_M"),
        toolchain=Toolchain(
            llama_cpp_release="v0.5.0",
            llama_cpp_build="b11146",
            backend="cpu",
            knowledge_pack_date=date(2026, 10, 1),
        ),
        coverage=Coverage(total=40, completed=12, pending=26, excluded=1, unsupported=1),
        finding_ids=["finding:1"],
    )


def policy() -> PolicyAssertion:
    return PolicyAssertion(
        id="policy:order-owner",
        statement="An order belongs to its customer.",
        resource="Order",
        kind=GuardKind.OWNER,
        canonical="OWNER(Order.customer_id = principal.id)",
        status=PolicyStatus.CONFIRMED,
        author="plumb",
        created_at=T0,
        evidence=[INVOICE_GUARD],
        confirmed_by="owner",
        confirmed_at=T1,
    )


def run_event() -> RunEvent:
    return RunEvent(
        run_id="run:1",
        seq=7,
        at=T1,
        kind=EventKind.QUESTION_FINISHED,
        question_id="q:1",
        stage=QuestionStage.RECORD,
        status=QuestionStatus.ANSWERED,
        message="Found a sign-in check and no owner check in get_receipt",
        coverage=Coverage(total=40, completed=13, pending=25, excluded=1, unsupported=1),
    )


def application_map() -> ApplicationMap:
    """The receipt route as the map shows it before any investigation.

    The authentication dependency is a candidate that may or may not cover the
    Order load, and the receipt renderer is a call nothing could resolve.
    """
    site = access_site().model_copy(update={"guard_ids": []})
    signed_in = Guard(
        id="g:authn",
        snapshot_id=SNAP,
        kind=GuardKind.UNKNOWN,
        canonical="http_401_raise: executable rejection syntax; protection not established",
        mechanism=GuardMechanism.DEPENDENCY,
        span=span("api/services/orders.py", 4, 9),
    )
    renderer = UnknownTarget(
        id="unknown:render-receipt",
        label="render_receipt",
        reason="External callable; no snapshot definition",
        span=span("api/routes/orders.py", 46, 46),
    )

    def link(
        name: str,
        source: str,
        target: str,
        kind: LinkKind,
        status: LinkStatus,
        cited: SourceSpan,
        reason: str,
    ) -> MapLink:
        return MapLink(
            id=f"link:{name}",
            source=source,
            target=target,
            kind=kind,
            status=status,
            reason=reason,
            span=cited,
        )

    return ApplicationMap(
        snapshot_id=SNAP,
        entries=[entry_point()],
        symbols=[symbol()],
        guards=[signed_in],
        access_sites=[site],
        unknown_targets=[renderer],
        links=[
            link(
                "handler",
                "ep:receipt",
                "sym:get_receipt",
                "handler",
                LinkStatus.INFERRED,
                RECEIPT,
                "Static FastAPI declaration and router mount",
            ),
            link(
                "load",
                "sym:get_receipt",
                site.id,
                "access",
                LinkStatus.RESOLVED,
                site.span,
                "Order loaded by the order_id path parameter",
            ),
            link(
                "may-check",
                signed_in.id,
                site.id,
                "may_check",
                LinkStatus.UNRESOLVED,
                signed_in.span,
                "Candidate dependency check; protected object is unverified",
            ),
            link(
                "render",
                "sym:get_receipt",
                renderer.id,
                "call",
                LinkStatus.UNRESOLVED,
                renderer.span,
                renderer.reason,
            ),
        ],
        issues=["api/routes/orders.py:46: external call is not resolved"],
        limitations=["Static source map, not a runtime trace or a vulnerability verdict."],
    )


def probe_spec() -> ProbeSpec:
    return ProbeSpec(
        id="probe:receipt",
        finding_id="finding:receipt",
        marker="OWNER_MARKER_123",
        requests=[
            HTTPProbeRequest(
                role=role,
                principal=user,
                method="GET",
                path="/orders/1/receipt",
                expected_if_safe=expected,
            )
            for role, user, expected in [
                (StepRole.ATTACK, "bob", Access.DENIED),
                (StepRole.CONTROL, "alice", Access.ALLOWED),
            ]
        ],
    )


EXAMPLES: dict[type[Contract], Contract] = {
    type(e): e
    for e in (
        snapshot(),
        RECEIPT,
        symbol(),
        entry_point(),
        access_site(),
        guard(),
        peer_group(),
        question(),
        observation(),
        finding(),
        probe_run(),
        probe_spec(),
        suggested_change(),
        review_run(),
        policy(),
        application_map(),
        run_event(),
    )
}
