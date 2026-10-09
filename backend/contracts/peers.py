"""Saved source-bound peer observations, never a new verdict or inferred policy."""

from typing import Self

from pydantic import Field, model_validator

from backend.contracts.code import AccessSite, EntryPoint, Guard, GuardKind, PeerGroup, SourceSpan
from backend.contracts.common import Contract, Id

KINDS = (GuardKind.AUTHENTICATED, GuardKind.OWNER, GuardKind.TENANT, GuardKind.ROLE)


class PeerRow(Contract):
    site: AccessSite
    entry: EntryPoint
    guards: list[Guard] = Field(default_factory=list, max_length=100)
    evidence: list[SourceSpan] = Field(default_factory=list, max_length=100)
    exclusion: str | None = None
    issues: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _source_identity(self) -> Self:
        if self.site.entry_point_id != self.entry.id or any(
            snapshot != self.site.snapshot_id
            for snapshot in [
                self.entry.snapshot_id,
                self.site.span.snapshot_id,
                self.entry.span.snapshot_id,
                *[g.snapshot_id for g in self.guards],
                *[g.span.snapshot_id for g in self.guards],
                *[s.snapshot_id for s in self.evidence],
            ]
        ):
            raise ValueError("peer row identities must belong to the same entry/snapshot")
        if len({g.id for g in self.guards}) != len(self.guards) or any(
            not g.confirmed or g.optimistic or g.kind not in KINDS for g in self.guards
        ):
            raise ValueError("peer guards must be unique confirmed non-optimistic access guards")
        if self.exclusion is not None and (not self.exclusion.strip() or not self.evidence):
            raise ValueError("peer exclusion requires its recorded code citation")
        return self


class PeerComparison(Contract):
    finding_id: Id
    question_id: Id
    subject_site_id: Id
    group: PeerGroup
    rows: list[PeerRow] = Field(min_length=1, max_length=2000)
    limitations: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _membership_and_counts(self) -> Self:
        group = self.group
        sites = [row.site.id for row in self.rows]
        if len(set(sites)) != len(sites) or len(set(group.site_ids)) != len(group.site_ids):
            raise ValueError("peer membership cannot duplicate a site")
        if sites != group.site_ids or self.subject_site_id not in sites:
            raise ValueError("peer rows must preserve the complete recorded group membership")
        if any(
            row.site.snapshot_id != group.snapshot_id or row.site.resource != group.resource
            for row in self.rows
        ):
            raise ValueError("peer rows must belong to their resource and snapshot")
        expected_exclusions = {r.site.id: r.exclusion for r in self.rows if r.exclusion is not None}
        if (
            len({e.site_id for e in group.excluded}) != len(group.excluded)
            or {e.site_id: e.reason for e in group.excluded} != expected_exclusions
        ):
            raise ValueError("peer exclusions must match recorded row evidence")
        voters = [row for row in self.rows if row.exclusion is None]
        expected_columns = {
            kind.value: [row.site.id for row in voters if any(g.kind is kind for g in row.guards)]
            for kind in KINDS
        }
        expected_columns = {key: members for key, members in expected_columns.items() if members}
        if (
            len({c.key for c in group.columns}) != len(group.columns)
            or {c.key: c.applied_site_ids for c in group.columns} != expected_columns
        ):
            raise ValueError("peer columns must match distinct recorded guard-bearing voters")
        expected_deviations = {}
        for key, members in expected_columns.items():
            for row in voters:
                total = len(voters) - 1  # the subject is never its own peer
                if (
                    row.site.id not in members
                    and total > 0
                    and len(members) >= group.min_peers
                    and len(members) / total >= group.min_share
                ):
                    expected_deviations[(row.site.id, key)] = (len(members), total)
        actual = {
            (d.site_id, d.missing): (d.peers_applying, d.peers_total) for d in group.deviations
        }
        if len(actual) != len(group.deviations) or actual != expected_deviations:
            raise ValueError("peer deviations must retain exact subject-excluding denominators")
        seen: dict[str, Guard] = {}
        for row in self.rows:
            for guard in row.guards:
                if guard.id in seen and seen[guard.id] != guard:
                    raise ValueError("the same recorded guard ID cannot describe different code")
                seen[guard.id] = guard
        return self
