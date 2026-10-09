"""Bounded source navigation and human policy decisions for the Project screen."""

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.capabilities import CapabilityTable
from backend.contracts.code import ExcludedFile, PolicyAssertion, SourceSpan
from backend.contracts.common import Contract, Id, LinkStatus, Sha256
from backend.contracts.policies import BoundPolicy


class ProjectCitation(Contract):
    id: Id
    span: SourceSpan


class ProjectNode(Contract):
    id: Id
    label: str
    detail: str
    citation: ProjectCitation
    optimistic: bool = False


class ProjectEdge(Contract):
    id: Id
    source: Id
    target: Id
    status: LinkStatus
    kind: str
    reason: str
    optimistic: bool


class ProjectFlow(Contract):
    entry: ProjectNode
    guards: list[ProjectNode] = Field(max_length=5)
    data: list[ProjectNode] = Field(max_length=6)
    links: list[ProjectEdge] = Field(max_length=100)
    guards_total: int = Field(ge=0)
    data_total: int = Field(ge=0)
    unresolved_links: int = Field(ge=0)
    optimistic_links: int = Field(ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> Self:
        if self.guards_total < len(self.guards) or self.data_total < len(self.data):
            raise ValueError("shown nodes must fit the full flow counts")
        nodes = [self.entry, *self.guards, *self.data]
        if len({n.id for n in nodes}) != len(nodes):
            raise ValueError("flow node identities must be unique")
        ids = {n.id for n in nodes}
        if any(e.source not in ids or e.target not in ids for e in self.links):
            raise ValueError("shown flow links need both shown endpoints")
        return self


class ProjectRule(Contract):
    assertion: PolicyAssertion
    source_run_id: Id
    sites_applying: int = Field(ge=3)
    sites_total: int = Field(ge=3)
    guard_forms: list[str] = Field(min_length=1, max_length=100)
    proposal_sha256: Sha256
    citations: list[ProjectCitation] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _provenance(self) -> Self:
        if self.sites_applying > self.sites_total or self.sites_applying / self.sites_total < 0.75:
            raise ValueError("rule observations must fit their denominator")
        if [c.span for c in self.citations] != self.assertion.evidence:
            raise ValueError("rule citations must preserve their source evidence")
        return self


class PolicyConfirm(Contract):
    proposal_sha256: Sha256


class ProjectPage(Contract):
    capabilities: CapabilityTable | None = None
    run_id: Id
    snapshot_id: Sha256
    name: str
    captured_at: AwareDatetime
    languages: dict[str, int]
    frameworks: dict[str, int]
    resources: dict[str, int]
    included_files: int = Field(ge=0)
    excluded_files: int = Field(ge=0)
    exclusion_reasons: dict[str, int]
    unresolved_links: int = Field(ge=0)
    optimistic_links: int = Field(ge=0)
    flows: list[ProjectFlow] = Field(max_length=12)
    flows_total: int = Field(ge=0)
    offset: int = Field(ge=0)
    next_offset: int | None
    exclusions: list[ExcludedFile] = Field(max_length=20)
    scope_offset: int = Field(ge=0)
    scope_next_offset: int | None
    rules: list[ProjectRule] = Field(max_length=20)
    rules_total: int = Field(ge=0)
    policy_offset: int = Field(ge=0)
    policy_next_offset: int | None
    limitations: list[str]
    bound_policies: list[BoundPolicy] = Field(default=[], max_length=100)
    policy_conflicts: list[str] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _identity_and_pages(self) -> Self:
        if self.capabilities and self.capabilities.snapshot_id != self.snapshot_id:
            raise ValueError("capabilities must describe this project snapshot")
        if any(p.snapshot_id != self.snapshot_id for p in self.bound_policies):
            raise ValueError("project requirements belong to this frozen snapshot")
        for rows, total, offset, next_offset in (
            (self.flows, self.flows_total, self.offset, self.next_offset),
            (self.exclusions, self.excluded_files, self.scope_offset, self.scope_next_offset),
            (self.rules, self.rules_total, self.policy_offset, self.policy_next_offset),
        ):
            end = offset + len(rows)
            if (rows and end > total) or next_offset != (end if end < total else None):
                raise ValueError("project pages must preserve their full counts")
        nodes = [n for f in self.flows for n in [f.entry, *f.guards, *f.data]]
        citations = [n.citation for n in nodes] + [c for r in self.rules for c in r.citations]
        if any(c.span.snapshot_id != self.snapshot_id for c in citations) or any(
            r.source_run_id != self.run_id for r in self.rules
        ):
            raise ValueError("project evidence must belong to the selected run/snapshot")
        counts = [*self.languages.values(), *self.frameworks.values(), *self.resources.values()]
        if (
            any(n < 0 for n in counts)
            or sum(self.exclusion_reasons.values()) != self.excluded_files
        ):
            raise ValueError("project inventory counts must agree")
        return self


class ProjectExcerpt(Contract):
    run_id: Id
    citation: ProjectCitation
    offset: int = Field(ge=0)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    lines: list[str] = Field(min_length=1, max_length=80)
    next_offset: int | None

    @model_validator(mode="after")
    def _range(self) -> Self:
        span = self.citation.span
        if (
            self.start_line != span.start_line + self.offset
            or self.end_line != self.start_line + len(self.lines) - 1
            or self.end_line > span.end_line
            or self.next_offset
            != (self.offset + len(self.lines) if self.end_line < span.end_line else None)
        ):
            raise ValueError("excerpt pages must stay within their exact citation")
        return self
