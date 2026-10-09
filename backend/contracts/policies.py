"""Human requirements bound to exact frozen accesses, never guard evidence."""

import hashlib
from typing import Self

from pydantic import Field, model_validator

from backend.contracts.code import AccessSite, GuardKind, PolicyAssertion, PolicyStatus
from backend.contracts.common import Contract, Id, Sha256

ACCESS_KINDS = {
    GuardKind.AUTHENTICATED,
    GuardKind.OWNER,
    GuardKind.TENANT,
    GuardKind.ROLE,
    GuardKind.NONE,
}


class PolicyInput(Contract):
    snapshot_id: Sha256
    site_ids: list[Id] = Field(min_length=1, max_length=100)
    statement: str = Field(min_length=1, max_length=1000)
    author: str = Field(min_length=1, max_length=100)
    required_guard: GuardKind | None = None
    required_role: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
    forbidden_fields: list[str] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _requirement(self) -> Self:
        if self.required_role is not None and self.required_guard is not GuardKind.ROLE:
            raise ValueError("a required role qualifies only a role guard requirement")
        if self.required_guard is not None and self.required_guard not in ACCESS_KINDS:
            raise ValueError("select an access guard requirement")
        if self.required_guard is None and not self.forbidden_fields:
            raise ValueError("declare a guard or data-minimization requirement")
        if len(set(self.site_ids)) != len(self.site_ids):
            raise ValueError("policy accesses must be distinct")
        if any(
            not s.strip() or any(ord(c) < 32 for c in s)
            for s in [self.statement, self.author, *self.forbidden_fields]
        ):
            raise ValueError("requirements must be bounded plain text")
        if any(not s.isidentifier() or len(s) > 100 for s in self.forbidden_fields):
            raise ValueError("minimization rules name explicit source fields")
        if len(set(self.forbidden_fields)) != len(self.forbidden_fields):
            raise ValueError("minimization fields must be distinct")
        return self


class BoundPolicy(Contract):
    assertion: PolicyAssertion
    snapshot_id: Sha256
    source_run_id: Id
    sites: list[AccessSite] = Field(min_length=1, max_length=1000)
    provenance: str = Field(min_length=1, max_length=1000)
    forbidden_fields: list[str] = Field(default=[], max_length=100)
    required_role: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")

    @model_validator(mode="after")
    def _binding(self) -> Self:
        if self.required_role is not None and self.assertion.kind is not GuardKind.ROLE:
            raise ValueError("a required role qualifies only a role guard requirement")
        if self.assertion.status not in {PolicyStatus.DECLARED, PolicyStatus.CONFIRMED}:
            raise ValueError("only human declarations/confirmations are requirements")
        if (
            len({s.id for s in self.sites}) != len(self.sites)
            or any(
                s.snapshot_id != self.snapshot_id
                or s.span.snapshot_id != self.snapshot_id
                or s.resource != self.assertion.resource
                for s in self.sites
            )
            or any(s.snapshot_id != self.snapshot_id for s in self.assertion.evidence)
        ):
            raise ValueError("policy must bind exact accesses of one resource and snapshot")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class FrozenPolicies(Contract):
    snapshot_id: Sha256
    policies: list[BoundPolicy] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _snapshot(self) -> Self:
        if any(p.snapshot_id != self.snapshot_id for p in self.policies) or len(
            {p.assertion.id for p in self.policies}
        ) != len(self.policies):
            raise ValueError("frozen policies must have unique identities on this snapshot")
        return self

    def for_site(self, site: AccessSite) -> list[BoundPolicy]:
        return [p for p in self.policies if site in p.sites]

    def conflicts(self, site: AccessSite) -> list[str]:
        policies = self.for_site(site)
        kinds = {p.assertion.kind for p in policies} - {GuardKind.UNKNOWN}
        if GuardKind.NONE in kinds and len(kinds) > 1:
            return ["Declared public access conflicts with a required access guard; review rules."]
        if len({p.required_role for p in policies if p.required_role is not None}) > 1:
            return ["Conflicting qualified role requirements for the same access."]
        for kind in kinds:
            if len({p.assertion.canonical for p in policies if p.assertion.kind is kind}) > 1:
                return ["Conflicting canonical requirements for the same guard and access."]
        return []
