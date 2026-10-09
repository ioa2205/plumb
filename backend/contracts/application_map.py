"""A snapshot application graph; unknown endpoints are explicit nodes."""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.contracts.code import AccessSite, EntryPoint, Guard, SourceSpan, Symbol
from backend.contracts.common import Contract, Id, LinkStatus, Sha256


class UnknownTarget(Contract):
    id: Id
    label: str
    reason: str
    span: SourceSpan


LinkKind = Literal[
    "handler",
    "call",
    "reference",
    "dependency",
    "guard_candidate",
    "access",
    "may_check",
    "proxy",
    "client_props",
]


class MapLink(Contract):
    id: Id
    source: Id
    target: Id
    kind: LinkKind
    status: LinkStatus
    reason: str
    span: SourceSpan
    optimistic: bool = False


class ApplicationMap(Contract):
    schema_version: Literal[1] = 1
    snapshot_id: Sha256
    entries: list[EntryPoint]
    symbols: list[Symbol]
    guards: list[Guard]
    access_sites: list[AccessSite]
    unknown_targets: list[UnknownTarget]
    links: list[MapLink]
    issues: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent_graph(self) -> Self:
        entities = [
            *self.entries,
            *self.symbols,
            *self.guards,
            *self.access_sites,
            *self.unknown_targets,
        ]
        ids = {e.id for e in entities}
        if len(ids) != len(entities):
            raise ValueError("map node IDs must be unique")
        if len({link.id for link in self.links}) != len(self.links):
            raise ValueError("map link IDs must be unique")
        if any(e.span.snapshot_id != self.snapshot_id for e in entities) or any(
            link.span.snapshot_id != self.snapshot_id for link in self.links
        ):
            raise ValueError("map citations must use one snapshot")
        if any(
            e.snapshot_id != self.snapshot_id
            for e in [*self.entries, *self.symbols, *self.guards, *self.access_sites]
        ):
            raise ValueError("map entities must use one snapshot")
        if any(link.source not in ids or link.target not in ids for link in self.links):
            raise ValueError("map links must have both endpoints")
        unknown = {u.id for u in self.unknown_targets}
        if any(
            link.target in unknown and link.status is not LinkStatus.UNRESOLVED
            for link in self.links
        ):
            raise ValueError("links to unknown targets must be unresolved")
        symbols, entries = {s.id for s in self.symbols}, {e.id for e in self.entries}
        if any(e.handler_symbol_id not in symbols for e in self.entries):
            raise ValueError("entry handler must be in map symbols")
        if any(a.entry_point_id not in entries for a in self.access_sites):
            raise ValueError("access entry point must be in the map")
        guard_ids = {g.id for g in self.guards}
        if any(g not in guard_ids for a in self.access_sites for g in a.guard_ids):
            raise ValueError("access guards must be in the map")
        proxies = {g.id for g in self.guards if g.optimistic}
        if any(
            (link.kind == "proxy" or link.source in proxies or link.target in proxies)
            and not link.optimistic
            for link in self.links
        ):
            raise ValueError("proxy-related links must remain optimistic")
        return self
