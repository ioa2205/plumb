# analysis

Application understanding: content-addressed snapshots, the tree-sitter index, Python and TypeScript reference resolution, framework adapters, access sites, the application map, and the pinned Opengrep rules. Nothing here executes target code.

- **Plan:** §4 Scope, §5 Architecture.
- **Tasks:** M2.1–M2.8, M1.8 (Opengrep rules).

## Immutable snapshot manifests (M2.1a)

Recapturing identical content returns the first saved manifest, including its original
`created_at`. `SnapshotStore.save()` returns that canonical record. A complete manifest is
published atomically without replacing an existing one, including during concurrent saves.
Corrupt or mis-keyed records fail closed; recapture never repairs them silently.

Only the capture timestamp may differ. The same content hash with different root, commit,
dirty state, exclusions, file sizes or language metadata raises `SnapshotConflictError` and
leaves the original record intact. The content ID still hashes included paths and bytes;
it does not distinguish these metadata variants. They require a separate store rather than
overwriting past provenance. Existing report validation remains strict. This prevents new
timestamp replacements; it does not retroactively repair reports affected before this fix.

## Project overview (M2.9)

`uv run plumb inspect <folder>` builds the same source map used by review, prints
a bounded summary, and saves a full `overview.json`. No model is constructed. It
lists snapshot files/exclusions, language counts, frameworks by discovered entry
count, modules, resource access paths, extraction issues and all map facts.

Review units follow entries through call/dependency links and input-bound access
paths, retaining shared cross-file helpers and peer navigation. Unresolved and
optimistic links stay labeled. Shared helpers cannot inherit another route's
access IDs. Resource names do not establish sensitivity or policy. All code spans
are validated against frozen bytes; empty unlinked modules are file inventory
without invented code lines. A linked empty synthetic module fails explicitly.
Structured JSON exports and terminal summaries use configured redaction. No HTML
screen or security coverage claim is introduced by this overview.

## Python call resolution (M2.3)

`uv run python -m analysis.python_resolution labs/tandir --caller tandir.routers.orders.get_invoice`
builds a snapshot and index, then resolves Python calls. The resulting graph lives at
`PLUMB_DATA_DIR/cache/resolution/<snapshot>.python.sqlite`. `--no-ty` exercises the fallback.
**Reviews use only the fallback:** `plumb inspect`, `plumb review` and the browser pass
`use_ty=False` (`backend/review.py`, `analysis/access.py`), so ty runs only from this command
and from `analysis.application_map`. Compared on the lab on 10 October 2026: both link the
same 103 of 663 call sites to the same targets, ty links one more (in the lab's test helper),
and the guard candidates and access sites are identical
([record](../docs/results/2026-10-10-a10a-ty-comparison.json)).
`CallGraph.calls()` and `callers()` retain exact snapshot spans, target symbol IDs, provenance,
and one of these statuses:

- `resolved`: ty uniquely identifies an indexed definition. Find-references is supplemented
  with go-to-definition because ty 0.0.84 misses some re-export aliases in reference lists.
- `inferred`: a lexical/import binding leads to a first-party symbol without ty confirmation.
- `unresolved`: external libraries, dynamic dispatch, shadowed names, ambiguous roots or
  multiple possible targets. These edges are kept, not discarded.

The helper receives only verified snapshot Python files in a disposable directory, with a
generated configuration. It receives no target configuration, virtual environment, package
installation or PATH. ty's `untrustedWorkspace` is enabled, uv integration and diagnostics are
disabled, and type-ignore comments cannot configure the analysis. Reference URIs must match
the staged source allowlist; external locations are never opened as evidence. Target Python
is parsed, never imported or executed. These settings follow the
[pinned ty editor documentation](https://github.com/astral-sh/ty/blob/0.0.84/docs/reference/editor-settings.md).

Default budgets are 10 seconds per request, 60 seconds per server and 384 MiB sampled RSS.
The watchdog checks every 50 ms and kills its own helper on excess; this is a resource guard,
not an OS sandbox or an instantaneous hard memory cap. Frames are bounded to 8 MiB and the
message queue to 128 items. A server failure discards partial resolution and records a visible
fallback issue. The fallback supports direct/aliased/relative imports, re-exports and lexical
functions; it does not infer instance dispatch, wildcard imports or assignments. No reviewed
project dependencies are installed. Static resolution does not prove runtime reachability,
guard behavior or the absence of monkey-patching.

## TypeScript call resolution (M2.4)

Install Plumb's compiler dependency with
`pnpm --dir analysis/typescript install --frozen-lockfile --ignore-scripts`, then run
`uv run python -m analysis.typescript_resolution labs/tandir --caller web/app/orders/actions:cancelOrder`.
TypeScript 6.0.3 is pinned separately from reviewed projects. Node 24+ is selected by the absolute
`PLUMB_NODE_BINARY` setting (defaults to the machine's `C:\Program Files\nodejs\node.exe` on Windows).
The helper has a strict TypeScript check: `pnpm --dir analysis/typescript typecheck`.

The compiler host holds snapshot source text in memory. It cannot read target files, dependencies,
libraries, config extensions or plugins. Only `baseUrl` and `paths` from the nearest snapshotted
`tsconfig.json`/`jsconfig.json` affect imports; all resolved paths must remain inside the snapshot.
Inherited config is reported as unavailable. No builds, project scripts, emit or target imports run.
The implementation uses the documented [TypeScript Compiler API](https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API)
with an explicit virtual host instead of the default filesystem host.

Node's permission mode allows filesystem reads only under the trusted helper directory. Its
environment excludes `NODE_OPTIONS`, PATH and target settings. Defaults: 192 MiB V8 old-space,
384 MiB sampled process RSS, 60 seconds, 32 MiB input and 16 MiB output. The V8 heap limit does
not bound all native memory; the RSS watchdog stops excess at its next 50 ms sample. Missing
runtime/dependency, oversized input, timeout and helper failure are visible errors, never empty
successful graphs. The graph is saved beside the Python graph with a `.typescript.sqlite` suffix.

Unique compiler symbols are `resolved`; ambiguous, dynamic and external calls stay `unresolved`.
JSX function/action values are `reference` edges, distinct from direct calls. Export/directive
facts remain in the index for the Next.js adapter. Third-party type-dependent dispatch, framework
execution, inherited configuration, package exports and runtime reachability are not established.

## FastAPI adapter (M2.5)

`uv run python -m analysis.fastapi labs/tandir` extracts route declarations and dependency trees
from the snapshot. `extract_fastapi()` returns typed `FastAPIMap` data; the CLI saves it under
`PLUMB_DATA_DIR/cache/adapters/<snapshot>.fastapi.json`. No FastAPI import or app startup is needed.

Recognized framework constructs must originate in actual FastAPI imports. Aliases, relative
project imports, factory-local app declarations, router/include prefixes, repeated and nested
mounts, router/app/decorator dependencies, parameter defaults and `Annotated`/`Security` syntax
are supported. Literal tuple/list include loops are expanded with a bound. A factory returning
one unrebound nested function links that function and retains the factory and argument text.
Its sub-dependencies are then followed, with cycle/depth limits. These follow FastAPI's
[router](https://fastapi.tiangolo.com/tutorial/bigger-applications/) and
[sub-dependency](https://fastapi.tiangolo.com/tutorial/dependencies/sub-dependencies/) structure.

All static mount/dependency links are labeled `inferred`; runtime reachability is not proven.
Dynamic prefixes and paths, unsupported callable objects, missing dependencies and ambiguous
module roots remain unknown. Conditional/dynamic registration, unresolved mounts and cycles
produce explicit issues. In particular, registration ordering across arbitrary runtime calls,
dependency overrides, callable classes, dynamic app factories, middleware and custom routing
are not established. `add_api_route`, `add_route` and mounted sub-apps are reported as unresolved.

Authentication-related metadata cites actual `raise HTTPException(401/403)` syntax inside
dependency bodies. It is only a signal, not a confirmed guard: dominance, dead branches and
what the check protects are later investigator work. Comments, docstrings and suggestive
names never produce these signals. A local module named `fastapi` is not trusted as the
external framework. The lab's role factory is inspected as code; its name proves nothing.

## Next.js adapter (M2.6)

`uv run python -m analysis.nextjs labs/tandir` saves a typed `NextJSMap` under
`cache/adapters/<snapshot>.nextjs.json`. A snapshotted package manifest with a Next.js dependency
identifies each project. The existing bounded TypeScript helper extracts exports (including
aliases and re-exports), static runtime imports and JSX props entirely in memory.

App Router pages and HTTP method exports, file-level and inline Server Actions, `app/` and
`src/app/`, route groups and parallel slots are recognized. Actions are separate public POST
entries, independent of UI references or layout checks. Component context follows runtime
imports; type-only and Server Action imports do not move implementation into a client bundle.
Functions used from both contexts are marked shared. JSX props at explicit client boundaries
retain the source expressions for later investigation; no serialization or disclosure verdict
is made here. `server-only` imports identify DAL candidate modules and their exported routines;
neither a filename nor the marker proves authorization.

Root and `src/` proxy/middleware handlers retain literal matchers. Exact paths and simple named
parameters are matched conservatively; regex, conditions, dynamic matchers and unknown action
URLs stay unresolved. Target regex is never executed. Every proxy and coverage link serializes
`optimistic: true`, and its guard remains unconfirmed. This follows the
[Next.js authentication guidance](https://nextjs.org/docs/app/guides/authentication) and
[Server Function conventions](https://nextjs.org/docs/app/api-reference/directives/use-server).

Interception/navigation context, Pages Router, framework-generated endpoints (such as metadata,
automatic HEAD/OPTIONS), dynamic imports, arbitrary component factories and custom Next.js
configuration are not resolved. Routes are App Router paths before rewrites/basePath/i18n.
Unknown exports and dynamic boundaries are reported as issues; test-source issues remain
visible too. Configuration and package scripts are never evaluated. A static entry or import
link does not prove a successful framework build or runtime reachability.

## Access sites (M2.7)

`uv run python -m analysis.access labs/tandir` saves `AccessMap` under
`cache/adapters/<snapshot>.access.json`. Access identity includes the entry point and query
location: two routes using the same loader retain two access paths. The acceptance set is
the eight customer Order routes; staff/courier and web paths are retained separately.

The Python frontend recognizes SQLAlchemy `Session` annotations, imported/aliased `select`,
`get`, keyed `where` expressions and bound raw SQL passed to `execute`. Model symbols resolve
through snapshot imports; a local `sqlalchemy` shadow cannot establish driver provenance.
The TypeScript frontend recognizes Prisma client origins and literal keyed `where` objects,
Drizzle fluent `select().from().where()` calls, raw SQL drivers and source-inspected wrappers.
Recognizers follow the documented [SQLAlchemy query API](https://docs.sqlalchemy.org/en/20/orm/session_basics.html),
[Prisma keyed queries](https://docs.prisma.io/docs/orm/v6/prisma-client/queries/crud) and
[Drizzle select syntax](https://orm.drizzle.team/docs/select).
Raw SQL retains its table name as the resource; ORM accesses retain their model name. They
are not silently merged into one peer group across frameworks.

Symbolic inputs propagate through local aliases and resolved/inferred call arguments, including
Python keywords and dependency paths. FastAPI path/scalar query/explicit binding parameters,
Next.js page params/searchParams, action arguments and Route Handler request properties seed
input origins. Assignments union possible influences, including across branches; this is
conservative possible dependence, not complete taint analysis. Unknown key sources remain
visible and unresolved. Constants are excluded. Sites carry source hashes and the symbol
chain; no guard is confirmed by access extraction.

SQL recognition is intentionally small: literal table names, `id`/`*_id` equality and positional
or named bindings, with strings/comments removed before recognizing syntax. Complex SQL,
custom key schemas, dynamic table names, arbitrary wrappers, object aliasing, polymorphic
dispatch, captured variables and framework binding variants can remain unknown or unsupported.
Dynamic SQL template gaps are reported. Calls are bounded to 16 levels and 2,048 contexts per
entry; exceeding the bound records incomplete coverage. Local alias propagation is bounded
to 16 passes. All helpers read snapshot syntax; neither databases nor target modules are opened.

## Application map (M2.8)

`uv run python -m analysis.application_map labs/tandir` joins the index, both call graphs, both
framework adapters and the access paths into one `ApplicationMap` and saves it in
`PLUMB_DATA_DIR/cache/application_maps.sqlite`, keyed by snapshot ID. `--without-ty` uses the
labeled import fallback. The backend serves a saved map read-only at
`GET /api/snapshots/<snapshot>/map`; a request never starts analysis, and a missing map is a 404.

Nodes are entry points, indexed symbols, guard candidates, access sites and explicit unknown
targets. Every link carries a kind, a `resolved`/`inferred`/`unresolved` status, a reason and a
cited snapshot span. A call or dependency nothing could resolve points at its own unknown-target
node, so an unresolved edge is never dropped or folded into a neighbour. The contract refuses a
map with a dangling endpoint, a duplicate node, a citation from another snapshot, a
non-`unresolved` link to an unknown target, or a proxy link that is not marked optimistic.

The map states what is connected, never what is protected. Guards are candidates only: FastAPI
dependencies that contain `raise HTTPException(401/403)` syntax, and Next.js proxy matchers. None
is confirmed, no access site lists a guard, and each `may_check` link from a candidate to an
access site on the same entry is `unresolved` until the investigator establishes what the check
compares and whether it dominates the load. Proxy links are always `optimistic`.

Server-only data modules and component boundaries stay in `NextJSMap` and are not map nodes yet.
Guards inside handler bodies, helpers and query filters are not candidates here; finding and
classifying them is M3.4. Each unresolved call site is its own node, so external library calls
dominate the unknown count.
