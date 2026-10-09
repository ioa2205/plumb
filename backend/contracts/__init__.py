"""Plumb's persisted entities (PROJECT_PLAN §6).

These Pydantic models are the single source of truth. JSON Schemas in
``schemas/`` are generated from them (``python -m backend.contracts.export``),
and the workbench's TypeScript types are generated from those schemas.
"""

from backend.contracts.application_map import ApplicationMap
from backend.contracts.capabilities import CapabilityTable
from backend.contracts.cases import (
    CaseDetail,
    CitedExcerpt,
    FindingPage,
    PeerExcerpt,
    SnapshotCodePage,
)
from backend.contracts.code import (
    AccessSite,
    EntryPoint,
    Guard,
    PeerGroup,
    PolicyAssertion,
    ProjectSnapshot,
    SourceSpan,
    Symbol,
)
from backend.contracts.common import Contract
from backend.contracts.investigation import (
    DispositionDecision,
    DispositionUpdate,
    Finding,
    Question,
    ToolObservation,
)
from backend.contracts.policies import BoundPolicy, PolicyInput
from backend.contracts.project_view import PolicyConfirm, ProjectExcerpt, ProjectPage, ProjectRule
from backend.contracts.review_view import FindingList, QueueEdit, ReviewPage
from backend.contracts.run_history import RunComparison, RunHistory
from backend.contracts.runs import ReviewRun, RunEvent
from backend.contracts.setup_view import (
    InspectionView,
    InspectRequest,
    LaunchRequest,
    ResumeRequest,
    SetupReadiness,
    SourceCheck,
)
from backend.contracts.signals import SignalSet
from backend.contracts.verification import FixProposal, ProbeRun, ProbeSpec, SuggestedChange

CONTRACTS: tuple[type[Contract], ...] = (
    ProjectSnapshot,
    SourceSpan,
    Symbol,
    EntryPoint,
    AccessSite,
    Guard,
    PeerGroup,
    Question,
    ToolObservation,
    Finding,
    ProbeRun,
    ProbeSpec,
    SuggestedChange,
    ReviewRun,
    PolicyAssertion,
    ApplicationMap,
    RunEvent,
)

# Transport projections are generated alongside entities, but are not persisted entities.
READ_CONTRACTS: tuple[type[Contract], ...] = (
    CapabilityTable,
    DispositionUpdate,
    DispositionDecision,
    FixProposal,
    SignalSet,
    PolicyInput,
    BoundPolicy,
    LaunchRequest,
    ResumeRequest,
    SourceCheck,
    InspectionView,
    InspectRequest,
    SetupReadiness,
    RunHistory,
    RunComparison,
    PolicyConfirm,
    ProjectPage,
    ProjectRule,
    ProjectExcerpt,
    QueueEdit,
    ReviewPage,
    FindingList,
    FindingPage,
    CaseDetail,
    CitedExcerpt,
    PeerExcerpt,
    SnapshotCodePage,
)

__all__ = [
    "CONTRACTS",
    "READ_CONTRACTS",
    "AccessSite",
    "ApplicationMap",
    "CaseDetail",
    "CitedExcerpt",
    "Contract",
    "EntryPoint",
    "Finding",
    "FindingPage",
    "Guard",
    "PeerExcerpt",
    "PeerGroup",
    "PolicyAssertion",
    "ProbeRun",
    "ProbeSpec",
    "ProjectSnapshot",
    "Question",
    "ReviewRun",
    "RunEvent",
    "SnapshotCodePage",
    "SourceSpan",
    "SuggestedChange",
    "Symbol",
    "ToolObservation",
]
