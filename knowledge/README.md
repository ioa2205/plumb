# Reviewed local security cards

The versioned offline pack implements the small reviewed methodology experiment.
Three cards cover object access, role/function access and session
identity/termination. Each supplies prerequisites, proposed permitted actions,
expected controls, alternative explanations, stop conditions and an original inert
synthetic worked example. A card never approves an action or establishes application
policy, target evidence, a verdict or general standards compliance.

`cards.retrieve_cards(query, family="authorization", limit=1)` uses SQLite FTS5 and
the existing source index's quoted lexical query builder. It searches only the
shipped hash-pinned pack. No match stays empty; no network, embeddings, model or
runtime guidance import is used. The production default remains no guidance until
the matched development comparison supports changing it.

`cards.guidance_context(card, owner_policy=...)` validates the card against the exact
reviewed pack, provides bounded methodology separately from the unmodified owner
requirement, and uses distinct `GUIDE-*` identities. These identities are not source
or HTTP field citations. `reviewed_card` resolves an exact serialized builtin card;
`pack_identity` provides the version/hash for experiment manifests. Full source
URLs, versions, raw-byte hashes, review dates and license provenance remain in
[the pack](data/security-cards-v1.json).

The construction review read the official version-pinned WSTG 4.2 and ASVS 5.0.0
sources on 2026-10-11. A separate read-only fetch measured the source and license
files' actual byte hashes. The source copies are not redistributed; the cards are
small original summaries with stricter Plumb scope/privacy restrictions and original
synthetic examples. Broader injection/CWE/framework guidance is still unimplemented.
Adding a card requires a reviewed version/source/license, new card and pack hashes,
affected tests and a justified matched comparison; page/model content cannot add it.

Card data is distributed under CC-BY-SA-4.0 with its own
[attribution and license notice](data/LICENSE.md); this is separate from the code
license. OWASP does not endorse Plumb. Source/license attribution is metadata, not
proof about any application.
