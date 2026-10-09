# knowledge

Planned builder for a versioned, offline guidance pack (OWASP ASVS 5.0, OWASP API Security Top 10 2023, relevant CWE entries, Next.js and FastAPI security documentation). **Not implemented:** this package is currently a stub. Code-context retrieval elsewhere in Plumb does not mean this knowledge pack is available.

- **Plan:** §10.4 Knowledge pack.
- **Task:** M6.10, only if the M6.0 failure audit identifies a knowledge gap worth testing.
- **Decision:** [ADR-0007](../docs/decisions/ADR-0007-focused-handoff-and-hardware-profiles.md).

Start with small, licensed, versioned passages retrieved through FTS5, with source URL,
date and content hash. Guidance IDs remain separate from code citations and never prove
a vulnerability or clear a finding by themselves. No live retrieval during analysis.
Compare the same development cases with and without guidance before enabling it;
embeddings are a later E8 experiment, and fine-tuning is a separate E5 experiment.
