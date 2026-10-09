The SARIF schema is the complete [OASIS SARIF 2.1.0 schema](https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json), retrieved 2026-10-04. Only CRLF line endings were normalized to LF, following the repository's checkout convention; the parsed schema is unchanged.

Upstream SHA256 (CRLF): `ad6db49878699b091f3eeb765b6e29e92a34bad4da88664d000c923b549c3a25`.

Committed SHA256 (LF): `2b19d2358baef0251d7d24e208d05ffabf1b2a3ab5e1b3a816066fc57fd4a7e8`.

Tests use this complete draft-07 schema and its format checker offline, and pin the committed LF bytes. Source and terms: [OASIS document and schema policy](https://www.oasis-open.org/policies-guidelines/ipr/).

`report-bundle.schema.json` is generated from `backend.reports.ReportBundle`; it describes the local export interchange, not a new persisted entity or API endpoint.
