# Report exports

## Current reviewer view (M5.9)

Saved case/list/comparison reads overlay the append-only local disposition audit.
Each decision binds run, snapshot, finding and original finding digest, records
the prior state/version, reviewer, reason and UTC time, and advances one version.
Dismissal and accepted risk need a reason; resolution additionally needs a linked
40-character commit hash. A closed case must reopen before another closing decision.
Commit links are reviewer declarations, never runtime proof.

The protected case API accepts only disposition intent; it cannot edit severity,
conclusion, coverage, source or probe records. Concurrent/stale writes return 409.
Invalid/corrupt audit data refuses rather than silently falling back to Open.
The inline workbench form changes its displayed state only after a validated save
acknowledgment. Cancel or an uncertain transfer requires refresh before retrying.

`GET /api/runs/<run-id>/current-report?format=json|markdown|html|sarif` exports the
current reviewer view with the complete audit in each format. These downloads and
`plumb report` summary reads run no inference or target code. Original report files
and bundled replay sidecars remain immutable; `plumb report --open` opens their
original HTML, while the workbench's current export includes later decisions.
Missing audit storage preserves legacy dispositions. Desktop interaction acceptance
belongs to completion step 15; a software test does not claim it passed.

`render(bundle, snapshot_store, format)` exports Markdown, standalone HTML, JSON, or SARIF
2.1.0 from a `ReportBundle`. The bundle holds the run, snapshot manifest, findings, guards,
probe records, suggested changes, frozen supplementary observations and caller-supplied limitations. Its
[generated schema](schemas/report-bundle.schema.json) describes the interchange.

Supplementary signals retain rule/citation/status and dated advisory pack provenance
in each format. They are separate from challenged findings and coverage. SARIF keeps
them in `properties.plumbReport.supplementary`, never in finding `results`; HTML and
Markdown use a separate section. Legacy reports retain an unrecorded signal set.

```text
uv run python -m backend.reports bundle.json --format markdown --output report.md
uv run python -m backend.reports bundle.json --format html --output report.html
uv run python -m backend.reports bundle.json --format json --output report.json
uv run python -m backend.reports bundle.json --format sarif --output report.sarif
```

The CLI reads the existing snapshot in `PLUMB_DATA_DIR/cache`. It never starts a review or
loads a model. Without `--output` it writes to stdout. Output files must be new; it refuses
to overwrite one. Failed exports return 1 and omit input values from stderr.

All formats pass the M3.3 validator before redaction or serialization. Every finding must
belong to the run and snapshot, and every recorded finding must be included. Citations must
resolve to the snapshot's bytes. Confirmed guards are checked again against executable
comparisons; owner/tenant guards must retain their actual code operands in `subject` and
`object`. Reproduction claims require matching probe records with both attack and control.
Suggested changes and replay probes must belong to the finding that cites them.

Exhibit tags stay local to their finding (`E01`); human reports and SARIF related locations
label them with their finding (`F-07/E01`). JSON retains the same finding ID, tag, source span
and content hash. Reports retain negative checks, flow, evidence gaps, unknowns, proposed
diffs, disposition, coverage and provenance. A proposed diff stays proposed. A rejected or
inconclusive result is never exported as a SARIF failure; severity is preserved independently
in its properties. SARIF severity levels are error for critical/high, warning for medium,
and note for low/unknown supported findings. Candidate/rejected/inconclusive results have
level none and kinds review/notApplicable/open. Unknown severity is not assigned a score.

Standard limitations appear even in empty or completed reports. Pending work, run conditions,
excluded files, missing provenance and each finding's gaps and unknowns add limitations.
SARIF retains them in run and result properties and invocation notifications. Snapshot paths
are relative, URI-encoded locations with whole-file hashes; no host paths are exported.
The complete [official OASIS schema](schemas/README.md) is bundled for offline test validation.

HTML uses text escaping, semantic sections, and a restrictive CSP with no scripts or external
assets. Markdown escapes repository-controlled markup and fences proposed diffs without
letting diff content close the fence. Both render source claims as text.

HTML now uses the Day/Night tokens from `design.md`, with an offline theme selector,
findings navigation, a count-based scope bar, independent source/runtime states,
three-step proof records and expandable evidence/hash details. Its only style
permission is the SHA256 hash of the trusted bundled CSS; repository-controlled
strings cannot add CSS, links or script. Navigation points only to generated local
anchors. A failing control or 500 remains inconclusive. The palette's text contrast,
content, local links, redaction and oracle behavior have actual test coverage;
1440/390 px screenshots in both themes remain pending because the browser tool
refused local file URLs. Fonts use local Atkinson where installed, otherwise the
system fallback. This export is separate from the unfinished M5 workbench.

`backend.redaction.redact` is the shared text helper used by all four exports. It masks known
credential shapes, assignments and URL credentials; callers of `render` can supply literal
secret values, including the process's `PLUMB_REDACTION_SECRETS` setting. Source text is omitted.
Redaction is not a general detector for arbitrary secrets; a credential in a citation identity
refuses the export rather than changing evidence IDs. Model requests and logs share this policy
(M3.11a). Exporting does not establish that the project has been investigated:
only the recorded source judgments and matching probe observations establish a
particular review's evidence. The real-model CLI slice and limited bundled-lab
runtime checks now exist; broader detection and automatic proof integration remain pending.
