"""What Plumb knows about the code: snapshots, spans, symbols, entry points, guards, peers."""

import hashlib
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.common import (
    Contract,
    Framework,
    Id,
    InputOrigin,
    Language,
    Line,
    RelPath,
    Sha256,
)


class SnapshotFile(Contract):
    path: RelPath
    sha256: Sha256
    size: int = Field(ge=0)
    language: Language | None = None


class ExclusionReason(StrEnum):
    TOO_LARGE = "too_large"
    BINARY = "binary"
    LINK = "link"  # symlinks, junctions, and reparse points are refused
    UNSUPPORTED = "unsupported"
    SECRET = "secret"  # noqa: S105 - an exclusion reason, not a credential
    USER_EXCLUDED = "user_excluded"
    UNREADABLE = "unreadable"
    SEALED = "sealed"  # sealed evaluation cases are never indexed
    DEFAULT_IGNORED = "default_ignored"  # VCS metadata, dependency, cache, and build folders


class ExcludedFile(Contract):
    path: RelPath
    reason: ExclusionReason


def snapshot_id(files: list[SnapshotFile]) -> Sha256:
    """Content address of a snapshot: SHA256 over its sorted ``path NUL sha256`` lines."""
    digest = hashlib.sha256()
    for f in sorted(files, key=lambda f: f.path):
        digest.update(f"{f.path}\0{f.sha256}\n".encode())
    return digest.hexdigest()


class ProjectSnapshot(Contract):
    """The exact files a review looked at, including uncommitted changes."""

    id: Sha256
    root_name: str
    created_at: AwareDatetime
    git_commit: str | None = None
    # Whether the working tree differs from git_commit; None when not determined
    # (Plumb never runs git on a reviewed repository: its config can run commands).
    dirty: bool | None = None
    files: list[SnapshotFile]
    excluded: list[ExcludedFile] = []

    @model_validator(mode="after")
    def _content_addressed(self) -> Self:
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("a snapshot lists each path once")
        if self.id != snapshot_id(self.files):
            raise ValueError("snapshot id must be the content hash of its files")
        return self


class SourceSpan(Contract):
    """A citation: lines in one file of one snapshot, with the hash of their text."""

    snapshot_id: Sha256
    path: RelPath
    start_line: Line
    end_line: Line
    content_sha256: Sha256

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line comes before start_line")
        return self


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    COMPONENT = "component"  # a React component (capitalized function in a .tsx/.jsx file)
    TYPE = "type"  # a TypeScript type alias or interface (DTO shapes for client exposure)


class Symbol(Contract):
    id: Id
    snapshot_id: Sha256
    name: str
    qualified_name: str
    kind: SymbolKind
    language: Language
    span: SourceSpan


class EntryPointKind(StrEnum):
    HTTP_ROUTE = "http_route"  # FastAPI path operation
    ROUTE_HANDLER = "route_handler"  # Next.js app/**/route.ts
    SERVER_ACTION = "server_action"  # a public POST endpoint, whatever the UI shows
    PAGE = "page"  # Next.js Server Component page


class EntryPoint(Contract):
    id: Id
    snapshot_id: Sha256
    kind: EntryPointKind
    framework: Framework
    method: str | None = None
    route: str | None = None
    handler_symbol_id: Id
    span: SourceSpan


class GuardKind(StrEnum):
    """Canonical guard kinds from the ``guard_summary`` question (PROJECT_PLAN §3.1)."""

    AUTHENTICATED = "authenticated"
    OWNER = "owner"
    TENANT = "tenant"
    ROLE = "role"
    NONE = "none"
    UNKNOWN = "unknown"

    # Source-confirmed sink protections, distinct from access policy guards.
    PARAMETERIZED = "parameterized"
    ALLOWLISTED = "allowlisted"
    CONTAINED = "contained"
    MINIMIZED = "minimized"  # exact source-field omission at a Next.js crossing


class GuardMechanism(StrEnum):
    DEPENDENCY = "dependency"
    DECORATOR = "decorator"
    QUERY_FILTER = "query_filter"
    COMPARISON = "comparison"
    HELPER_CALL = "helper_call"
    DATA_ACCESS_LAYER = "data_access_layer"
    ROUTER = "router"
    PROXY_MATCHER = "proxy_matcher"  # Next.js proxy.ts: optimistic, never a boundary


class Guard(Contract):
    """A check on the path to an access site, normalized to a canonical form.

    ``confirmed`` means the validator found executable code at ``span`` that
    performs the check. A name or a comment never confirms a guard.
    """

    id: Id
    snapshot_id: Sha256
    kind: GuardKind
    canonical: str  # for example "OWNER(Order.customer_id = principal.id)"
    mechanism: GuardMechanism
    subject: str | None = None  # principal side, for example "principal.id"
    object: str | None = None  # resource side, for example "Order.customer_id"
    role: str | None = None
    span: SourceSpan
    via_symbol_id: Id | None = None
    confirmed: bool = False

    @property
    def optimistic(self) -> bool:
        return self.mechanism is GuardMechanism.PROXY_MATCHER


class Operation(StrEnum):
    READ = "read"
    LIST = "list"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class DataLayer(StrEnum):
    SQLALCHEMY = "sqlalchemy"
    RAW_SQL = "raw_sql"
    PRISMA = "prisma"
    DRIZZLE = "drizzle"
    OTHER = "other"


class AccessSite(Contract):
    """A place where a resource is loaded by a request-controlled identifier."""

    id: Id
    snapshot_id: Sha256
    entry_point_id: Id
    resource: str
    operation: Operation
    key_origin: InputOrigin
    data_layer: DataLayer
    span: SourceSpan
    guard_ids: list[Id] = []


class PeerColumn(Contract):
    key: str  # canonical guard key, for example "OWNER"
    label: str  # plain words for the matrix header, for example "Owns the order"
    applied_site_ids: list[Id]


class PeerExclusion(Contract):
    site_id: Id
    reason: str  # for example "staff-only route"


class PeerDeviation(Contract):
    site_id: Id
    missing: str  # the PeerColumn key the site lacks
    peers_applying: int = Field(ge=0)
    peers_total: int = Field(ge=1)


class PeerGroup(Contract):
    """Consensus for one resource type, and the sites that deviate from it (§3.2)."""

    id: Id
    snapshot_id: Sha256
    resource: str
    site_ids: list[Id]
    columns: list[PeerColumn]
    excluded: list[PeerExclusion] = []
    min_peers: int = Field(default=3, ge=1)
    min_share: float = Field(default=0.75, gt=0, le=1)
    deviations: list[PeerDeviation] = []

    @model_validator(mode="after")
    def _deviations_meet_thresholds(self) -> Self:
        keys = {c.key for c in self.columns}
        sites = set(self.site_ids)
        for d in self.deviations:
            if d.missing not in keys or d.site_id not in sites:
                raise ValueError(f"deviation {d.site_id}/{d.missing} is not in this group")
            if d.peers_applying < self.min_peers:
                raise ValueError(f"{d.site_id}: fewer than {self.min_peers} peers apply it")
            if d.peers_applying / d.peers_total < self.min_share:
                raise ValueError(f"{d.site_id}: fewer than {self.min_share:.0%} of peers apply it")
        return self


class PolicyStatus(StrEnum):
    INFERRED = "inferred"  # shown in blue pencil until a person confirms it
    CONFIRMED = "confirmed"
    DECLARED = "declared"


class PolicyAssertion(Contract):
    """An access rule, inferred from code or declared by a person.

    Kept separate from code-derived facts, with author and provenance. A policy
    never expands what the agent is allowed to do.
    """

    id: Id
    statement: str  # "An order belongs to its customer."
    resource: str
    kind: GuardKind
    canonical: str
    status: PolicyStatus
    author: str  # "plumb" for inferred rules, otherwise the person
    created_at: AwareDatetime
    evidence: list[SourceSpan] = []
    confirmed_by: str | None = None
    confirmed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _confirmation_recorded(self) -> Self:
        confirmed = self.status is PolicyStatus.CONFIRMED
        if confirmed != (self.confirmed_by is not None and self.confirmed_at is not None):
            raise ValueError("confirmed policies, and only those, record who confirmed them")
        return self
