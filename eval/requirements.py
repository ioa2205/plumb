"""Owner-delegated development requirements, separate from evaluator verdicts."""

import hashlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.code import GuardKind, PolicyAssertion, PolicyStatus, SourceSpan
from backend.contracts.common import Contract
from backend.contracts.policies import BoundPolicy, FrozenPolicies
from backend.review import Review

MANIFEST = Path(__file__).with_name("requirements") / "tandir-development.json"


class Rule(Contract):
    path: str
    symbol: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    resource: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    owner_path: str
    owner_symbol: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    statement: str = Field(min_length=1, max_length=1000)
    required_guard: GuardKind | None = None
    required_role: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
    forbidden_fields: list[str] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _requirement(self) -> Self:
        if self.path not in {
            "web/app/backoffice/actions.ts",
            "web/app/orders/actions.ts",
            "web/app/courier/[id]/page.tsx",
            "web/app/orders/[id]/page.tsx",
            "web/app/api/admin/export/route.ts",
            "web/app/api/admin/reports/route.ts",
        }:
            raise ValueError("only the named current Tandir development entries are authorized")
        if self.required_guard not in {None, GuardKind.AUTHENTICATED, GuardKind.ROLE}:
            raise ValueError("this pack supplies only explicit session/role or minimization rules")
        if (self.required_guard is GuardKind.ROLE) != (self.required_role is not None):
            raise ValueError("role requirements name the exact role")
        if self.required_guard is None and not self.forbidden_fields:
            raise ValueError("a source requirement must have a guard or explicit fields")
        if len(set(self.forbidden_fields)) != len(self.forbidden_fields) or any(
            not field.isidentifier() for field in self.forbidden_fields
        ):
            raise ValueError("forbidden fields are distinct source identifiers")
        return self


class Manifest(Contract):
    scope: Literal["current_tandir_development_requirements"]
    author: str = Field(min_length=1, max_length=100)
    provenance: str = Field(min_length=1, max_length=1000)
    rules: list[Rule] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len({(r.path, r.symbol) for r in self.rules}) != len(self.rules):
            raise ValueError("one independent requirement per named entry")
        return self


def pin() -> str:
    return hashlib.sha256(MANIFEST.read_bytes()).hexdigest()


def freeze(review: Review, selected: Sequence[SourceSpan], created_at: datetime) -> FrozenPolicies:
    pack = Manifest.model_validate_json(MANIFEST.read_bytes())
    entries = [e.entry for e in review.nextjs.entries]
    symbols = {s.id: s for s in review.map.symbols}
    policies = []
    for rule in pack.rules:
        matching = [
            e
            for e in entries
            if e.span in selected
            and e.span.path == rule.path
            and symbols[e.handler_symbol_id].name == rule.symbol
        ]
        if not matching:
            continue
        if len(matching) != 1:
            raise ValueError("requirement entry identity is ambiguous")
        entry = matching[0]
        sites = [
            p.site
            for p in review.access.accesses
            if p.site.entry_point_id == entry.id
            and p.site.resource == rule.resource
            and symbols[p.owner_symbol_id].span.path == rule.owner_path
            and symbols[p.owner_symbol_id].name == rule.owner_symbol
        ]
        if len(sites) != 1:
            raise ValueError("current development requirement needs one exact resource access")
        identity = hashlib.sha256((pin() + entry.id + sites[0].id).encode()).hexdigest()[:24]
        policies.append(
            BoundPolicy(
                assertion=PolicyAssertion(
                    id="policy:development:" + identity,
                    statement=rule.statement,
                    resource=rule.resource,
                    kind=rule.required_guard or GuardKind.UNKNOWN,
                    canonical=(
                        f"ROLE({rule.required_role})"
                        if rule.required_role
                        else (rule.required_guard or GuardKind.UNKNOWN).value.upper()
                        + f"({rule.resource})"
                    ),
                    status=PolicyStatus.DECLARED,
                    author=pack.author,
                    created_at=created_at,
                ),
                snapshot_id=review.snapshot.id,
                source_run_id="run:development-requirements",
                sites=sites,
                forbidden_fields=rule.forbidden_fields,
                required_role=rule.required_role,
                provenance=pack.provenance,
            )
        )
    return FrozenPolicies(snapshot_id=review.snapshot.id, policies=policies)
