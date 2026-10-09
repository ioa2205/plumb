"""Exact source-field to boundary-output facts; policies supply meaning separately."""

from analysis.nextjs import NextJSMap, Serialization, SerializedField
from backend.contracts.code import EntryPointKind, SourceSpan


def crossings(nextjs: NextJSMap, handler: str) -> list[Serialization]:
    entry = next((e.entry for e in nextjs.entries if e.entry.handler_symbol_id == handler), None)
    if entry is None:
        return []
    return [
        c
        for c in nextjs.serializations
        if c.owner_symbol_id == handler
        and (c.kind == "props" if entry.kind is EntryPointKind.PAGE else c.kind == "return")
    ]


def matches(field: SerializedField, owner: str, source: SourceSpan) -> bool:
    # A joined field belongs to its own resource even when returned by this query.
    # Both missing identities keep old records readable; rebuilt proofs use current facts.
    return (
        field.source_owner_symbol_id == owner
        and field.source == source
        and field.source_resource == field.query_resource
    )


def exposed(
    nextjs: NextJSMap, handler: str, owner: str, source: SourceSpan, forbidden: list[str]
) -> list[tuple[Serialization, SerializedField, str]]:
    return [
        (c, f, name)
        for c in crossings(nextjs, handler)
        for f in c.fields
        for name in forbidden
        if matches(f, owner, source) and f.field == name
    ]


def minimized(
    nextjs: NextJSMap, handler: str, owner: str, source: SourceSpan, forbidden: list[str]
) -> bool:
    found = crossings(nextjs, handler)
    return bool(
        forbidden
        and found
        and any(matches(f, owner, source) for c in found for f in c.fields)
        and not any(c.unknowns for c in found)
        and not exposed(nextjs, handler, owner, source, forbidden)
    )
