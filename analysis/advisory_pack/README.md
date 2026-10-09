# Dated offline advisory subset

Snapshot: **2026-10-07**. Publisher: GitHub Advisory Database via the official OSV
endpoint. This small shipped pack contains two genuine advisories, not a complete
advisory database. The normalized pack preserves affected packages, exact versions,
OSV range events and modification dates. `sources/` retains canonical JSON copies
of the retrieved source records (UTF-8, LF); `source_sha256` hashes these copies.
`pin.json` pins the normalized pack's size and SHA256. No records/ranges are invented.
License: CC-BY-4.0; full upstream terms are in `LICENSE.md`.

- [GHSA-fv66-9v8q-g76r source](https://api.osv.dev/v1/vulns/GHSA-fv66-9v8q-g76r)
  ([upstream advisory](https://github.com/advisories/GHSA-fv66-9v8q-g76r))
- [GHSA-9wx4-h78v-vm56 source](https://api.osv.dev/v1/vulns/GHSA-9wx4-h78v-vm56)
  ([upstream advisory](https://github.com/advisories/GHSA-9wx4-h78v-vm56))
- [Upstream attribution/license](https://github.com/github/advisory-database/blob/main/LICENSE.md)

OSV is data, not code. Reviews never access the network and never trust a pack from
the reviewed folder. Import a reviewed, normalized pack explicitly:

```text
uv run --locked python -m analysis.advisories import <trusted-pack.json> --sha256 <independently-trusted-sha256>
```

Import checks size (2 MiB maximum), strict schema, unique records, source identity,
CC-BY attribution, ecosystem/range support, ordering, digest and snapshot freshness
(at most 90 days; future dates refused). Invalid updates leave the active selection
unchanged. Packs are content addressed under the configured external Plumb data
directory. Selecting a pack does not authenticate its publisher; obtain its hash
and data from a trusted source. No automatic download or refresh. The shipped subset
is the fallback only when no imported selection exists; a corrupt/stale selection
refuses advisory checks rather than silently switching packs.

Only OSV `SEMVER` for npm and `ECOSYSTEM` for PyPI are accepted. npm ordering uses
SemVer 2.0, including numeric/alphabetic prereleases and ignoring build metadata;
PyPI ordering uses pinned `packaging.version.Version` (PEP 440, epochs, prereleases,
post/dev/local releases). `introduced` is inclusive, `fixed`/`limit` exclusive,
`last_affected` inclusive, `introduced: "0"` unbounded. Separate ranges and explicit
version enumerations form a union; withdrawn records are ignored. GIT and other
ecosystems are refused. No range specifiers from target manifests are guessed into
resolved versions. Results state exposure only, with the exact used pack date/hash;
saved/resumed runs keep their original observations even after a pack update.

Specifications: [OSV schema](https://ossf.github.io/osv-schema/),
[SemVer 2.0](https://semver.org/),
[PEP 440 version handling](https://packaging.pypa.io/en/stable/version.html),
[PyPI name normalization](https://packaging.python.org/en/latest/specifications/name-normalization/).
