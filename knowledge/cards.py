"""Reviewed offline methodology; guidance is neither target proof nor action authority.

The three small cards are deliberately data, not executable test scripts. Their
pack and source provenance are pinned; retrieval reuses the source index's safe
lexical FTS5 query builder and never fetches the web or loads a model.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from analysis.index import _fts_query
from backend.contracts.common import Contract, Id, Sha256

PACK_VERSION = "1.0.0"
PACK_PATH = Path(__file__).with_name("data") / "security-cards-v1.json"
PACK_SHA256 = "aaf9944796a97f42db88faa0cfc54612a8ecc5ef78cef18d500b977689644aff"
MAX_QUERY_CHARS = 512
MAX_GUIDANCE_CHARS = 2600
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

ShortText = Annotated[str, Field(min_length=1, max_length=180)]
Steps = Annotated[tuple[ShortText, ...], Field(min_length=1, max_length=4)]


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class ReviewedSource(Contract):
    """Pinned primary publication reviewed during pack construction, never at inference."""

    source_id: Id
    title: ShortText
    version: Literal["WSTG-4.2", "ASVS-5.0.0"]
    url: str = Field(min_length=1, max_length=512)
    source_sha256: Sha256
    source_bytes: int = Field(gt=0, le=300_000)
    license_id: Literal["CC-BY-SA-4.0"]
    license_url: Literal["https://creativecommons.org/licenses/by-sa/4.0/"]
    license_evidence_url: str = Field(min_length=1, max_length=512)
    license_evidence_sha256: Sha256
    reviewed_on: Literal["2026-10-11"]
    reviewed_by: Literal["Plumb implementation review"]
    review_scope: ShortText

    @model_validator(mode="after")
    def pinned_primary_source(self) -> Self:
        prefix = (
            "https://raw.githubusercontent.com/OWASP/wstg/v4.2/document/"
            if self.version == "WSTG-4.2"
            else "https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/"
        )
        if not self.url.startswith(prefix) or not self.license_evidence_url.startswith(prefix):
            raise ValueError(
                "guidance sources and license review must use pinned official versions"
            )
        return self


class WorkedExample(Contract):
    """An original inert synthetic example; never observations about a reviewed target."""

    scenario: ShortText
    issue_lead: ShortText
    protected_control: ShortText
    limitation: ShortText


class SecurityTestCard(Contract):
    id: Id
    version: Literal["1.0.0"]
    family: Literal["authorization", "session_management"]
    title: ShortText
    tags: Annotated[tuple[ShortText, ...], Field(min_length=1, max_length=12)]
    summary: ShortText
    prerequisites: Steps
    permitted_actions: Steps
    expected_controls: Steps
    alternative_explanations: Steps
    stop_conditions: Steps
    worked_example: WorkedExample
    source_sections: Annotated[tuple[ShortText, ...], Field(min_length=1, max_length=6)]
    sources: Annotated[tuple[ReviewedSource, ...], Field(min_length=1, max_length=3)]
    content_sha256: Sha256
    license_id: Literal["CC-BY-SA-4.0"]
    license_url: Literal["https://creativecommons.org/licenses/by-sa/4.0/"]
    attribution: ShortText
    changes: ShortText
    kind: Literal["methodology_only"] = "methodology_only"

    @model_validator(mode="after")
    def hash_and_sources(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        if _digest(payload) != self.content_sha256:
            raise ValueError("guidance card content hash does not match")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("guidance source identities must be unique")
        return self


class _Pack(Contract):
    pack_id: Literal["plumb-security-cards"]
    version: Literal["1.0.0"]
    license_id: Literal["CC-BY-SA-4.0"]
    license_url: Literal["https://creativecommons.org/licenses/by-sa/4.0/"]
    cards: Annotated[tuple[SecurityTestCard, ...], Field(min_length=1, max_length=3)]


def _read_pack(raw: bytes, expected_sha256: str) -> tuple[SecurityTestCard, ...]:
    if len(raw) > 64_000 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("reviewed guidance pack bytes do not match the pinned manifest")
    pack = _Pack.model_validate_json(raw)
    ids = [card.id for card in pack.cards]
    if len(ids) != len(set(ids)):
        raise ValueError("guidance card identities must be unique")
    return pack.cards


@lru_cache(maxsize=1)
def load_cards() -> tuple[SecurityTestCard, ...]:
    """Return the immutable shipped pack; arbitrary paths or runtime imports are unsupported."""
    with PACK_PATH.open("rb") as handle:
        raw = handle.read(64_001)
    return _read_pack(raw, PACK_SHA256)


def pack_identity() -> dict[str, str]:
    """Version/hash for approach manifests, independently of any target snapshot."""
    load_cards()
    return {"pack_id": "plumb-security-cards", "version": PACK_VERSION, "sha256": PACK_SHA256}


def retrieve_cards(
    query: str, *, family: str | None = None, limit: int = 1
) -> tuple[SecurityTestCard, ...]:
    """Return only matching methodology, all words first and then any word.

    A request cannot import guidance, interpret SQL/FTS syntax, or select more than
    three cards. Default one-card retrieval supports the explicit matched experiment.
    No match stays empty; there is no fallback to unrelated guidance.
    """
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("guidance query exceeds its character budget")
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError("guidance retrieval limit must be an integer from one to three")
    cards = load_cards()
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, title, tags, summary)")
        db.executemany(
            "INSERT INTO search (id, title, tags, summary) VALUES (?, ?, ?, ?)",
            [
                (card.id, card.title, " ".join(card.tags), card.summary)
                for card in cards
                if family is None or card.family == family
            ],
        )
        for operator in ("AND", "OR"):
            match = _fts_query(query, operator)
            if match is None:
                return ()
            rows = db.execute(
                "SELECT id FROM search WHERE search MATCH ? "
                "ORDER BY bm25(search, 0.0, 4.0, 5.0, 1.0), id LIMIT ?",
                (match, limit),
            ).fetchall()
            if rows:
                by_id = {card.id: card for card in cards}
                return tuple(by_id[row[0]] for row in rows)
    return ()


def reviewed_card(payload: dict[str, object]) -> SecurityTestCard:
    """Resolve only an exact shipped card payload; model or page content cannot add cards."""
    proposed = SecurityTestCard.model_validate(payload)
    if proposed not in load_cards():
        raise ValueError("guidance must be an exact reviewed builtin card")
    return proposed


def guidance_context(card: SecurityTestCard, *, owner_policy: str) -> dict[str, object]:
    """Bounded prompt methodology with explicit, unmodified owner requirements.

    Full official URLs, licenses and raw-byte hashes remain in the card manifest.
    Prompt references use a separate namespace and never enter field/source validators.
    """
    if card not in load_cards():
        raise ValueError("guidance must be an exact reviewed builtin card")
    if not owner_policy.strip() or len(owner_policy) > 4096:
        raise ValueError("guidance requires the explicit owner policy within its existing budget")
    methodology: dict[str, object] = {
        "kind": "methodology_only",
        "guidance_id": card.id,
        "version": card.version,
        "content_sha256": card.content_sha256,
        "source_sections": list(card.source_sections),
        "license_id": card.license_id,
        "rule": "Guidance is not target evidence, access policy, action approval or a verdict.",
        "prerequisites": list(card.prerequisites),
        "permitted_actions": list(card.permitted_actions),
        "expected_controls": list(card.expected_controls),
        "alternative_explanations": list(card.alternative_explanations),
        "stop_conditions": list(card.stop_conditions),
        "worked_example": card.worked_example.model_dump(mode="json"),
    }
    if len(json.dumps(methodology, ensure_ascii=False)) > MAX_GUIDANCE_CHARS:
        raise ValueError("reviewed methodology exceeds its prompt character budget")
    return {"owner_requirements": owner_policy, "methodology": methodology}
