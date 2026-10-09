# backend

## Measured MX350 runtime (M0.7a)

`vulkan_profile.create(settings, log_name)` returns a server for the measured
Qwen3.5-2B / b11146 Vulkan configuration. Pass `server.preflight` to
`ModelAdapter`; the server also checks it on direct startup. It needs 1.36 GB
available RAM and 1.78 GB free VRAM, verifies the pinned assets and MX350 identity,
and stops its own process if available RAM falls below 256 MiB. The original CPU
preflight is unchanged. The profile retains 8K context and stateless, authenticated,
offline loopback requests. See ADR-0006 for exact settings and measurements.

Reproduce calibration with `python -m eval.feasibility.memory_profile --profile
vulkan`; exercise the real budgeted adapter with `python -m
eval.feasibility.vulkan_adapter`. These load the model after preflight. The CPU
no-repack profile remains experimental; the tested CUDA profile is disabled
after a kernel failure. M3.4 still needs to establish classification correctness.

## CPU profile for other laptops (ADR-0024)

`cpu_profile.create(settings, log_name)` returns a server for the same model on
the pinned CPU build: 8K context, 4 threads, batches 2048/512, nothing on a
graphics card. Its admission check is the original CPU gate, 2.44 GB of available
RAM, and it keeps the same 256 MiB live stop. `profiles.REGISTRY` lists both
profiles; `profiles.doctor` judges each one and `profiles.create` starts the runner
that belongs to the chosen profile. `acceptance.py` holds the first-use check that
each computer passes before its first review with a CPU profile.

The local FastAPI service: settings, contracts (Pydantic models exported as JSON Schema, with generated TypeScript types for the workbench), jobs, the run store, and the memory preflight.

- **Plan:** §5 Architecture, §6 The investigator (contracts), §8 Security of Plumb itself.
- **Tasks:** M0.5 contracts, M0.7 memory preflight, M2.8 application map API, M3.7 jobs, M3.12 local API security.
- **Now:** `settings.py` resolves `PLUMB_DATA_DIR`; `contracts/` holds the persisted entities and
  their JSON Schemas; `preflight.py` refuses a model that does not fit in memory; `map_store.py`
  persists application maps; `app.py` builds the FastAPI app, `security.py` guards it and
  `serve.py` runs it on loopback.

## API

`uv run python -m backend.serve` binds 127.0.0.1 (port `PLUMB_PORT`, default 8700) and prints a
link to open once. `create_app()` returns the same app for in-process tests. Requests are not
logged, and the address is not a setting.

| Route | Returns |
| --- | --- |
| `GET /bootstrap?token=...` | Exchanges the one-time token for the session cookie and redirects to `/`. 403 once used or wrong. |
| `GET /api/snapshots/{snapshot_id}/map` | The saved `ApplicationMap` for a snapshot. 404 when none was built, 422 for a malformed ID, 503 when the cache cannot be read. Never starts analysis. |

### Who may call it (M3.12)

`backend/security.py` wraps every request (PROJECT_PLAN §8):

| Check | Refused with |
| --- | --- |
| `Host` is exactly `127.0.0.1:<port>`, once | 421. Stops DNS rebinding: a page under its own name is not Plumb's address |
| `Origin`, when sent, is Plumb's own; `Sec-Fetch-Site`, when sent, is `same-origin` (or `none` for a link the user opened); a write names its origin | 403. Another port on this machine is another origin |
| The session cookie is present, for everything except the bootstrap | 401, with the next step in words |
| No WebSocket endpoint exists | closed before it opens |

Every answer, refusals and failures included, carries a strict Content-Security-Policy
(`default-src 'none'`, scripts and styles from `'self'`, no framing). Verified workbench
HTML also allows only the exact hashes of its build-generated inline scripts; style/event
attributes and unsafe-inline/unsafe-eval remain forbidden. API/refusal/asset responses keep
the base policy. The API also sends
`nosniff`, `no-referrer`, same-origin opener and resource policies, and `no-store`. No CORS
header is ever sent. The bootstrap token works once and is exchanged for an HttpOnly,
SameSite=Strict cookie; the session token never appears in a URL; both live in memory for one
launch. A failed or foreign attempt does not use the link up.

Limits:

- Browsers scope cookies by host, not port. Another server on 127.0.0.1 receives this cookie and
  could replay it, and can plant one of the same name (which only costs a wrong value, since any
  matching cookie is accepted). Run nothing untrusted on loopback next to Plumb.
- The link is printed to the terminal and is valid until first use or until Plumb stops; there
  is no way to issue a second one without restarting.
- The cookie has no `Secure` attribute because the origin is plain HTTP on loopback.
- After sign-in `/` answers 404 until the root shell exists (M5.2). M5.2a serves the verified
  `/foundation/` export and adds its exact generated-script hashes. Actual API acceptance
  passes, but in-app browser navigation was blocked; rendered CSP acceptance remains owed.
- A local process running as the same user can read the terminal and the process memory; these
  checks are about web pages, not about other programs of the same user.

### Trusted static export (M5.2a, browser gate incomplete)

`frontend/out/plumb-export.json` is generated after a successful single-worker build.
`workbench.py` loads only this trusted app directory, validates manifest names/limits and
serves manifested files as the router fallback. Later API routes retain precedence; no
target-project folder is exposed. Reads reuse the checked root/link/hardlink and opened-file
identity boundaries, and verify the exact bytes being returned against the build digest.
HTML is independently parsed for script hashes and refused if inline style/event attributes
or foreign script sources appear. Only that verified response adds its hashes through an
internal ASGI scope field; arbitrary response headers cannot replace the policy.

Manifest/file/script mismatches return a generic actionable 503. Missing builds keep the API
available. Rebuild then restart to load a new manifest. Bounds are 1 MiB for the manifest,
4096 files, 8 MiB per asset and 64 unique script hashes per page; these are configured limits,
not performance measurements. The build manifest is not a signature against a local process
with the same user's permissions. See [partial acceptance](../docs/results/2026-10-06-m5.2a-notes.md).

## Runs, the worker and the event stream (M3.7)

`run_store.py` keeps a run, its questions in queue order with each one's working state, and an
append-only event log in `PLUMB_DATA_DIR/cache/runs.sqlite`. Every change is one transaction
that saves the state and the events announcing it together; events are numbered from 1 without
gaps (`RunEvent`, the 16th contract).

`jobs.py` is the worker. `Engine.run()` takes the question under way, or the next pending one,
through `FRAME -> GATHER (up to max_looks) -> HYPOTHESIZE -> CHALLENGE -> DECIDE -> [VERIFY] ->
RECORD`, one stage per saved transition. The stage handlers are plugged in (they arrive with
M3.4 to M3.6 and M3.9); the engine owns the order of stages, the limit on looks, the budget
spent so far, and how a question ends:

| What happens in a stage | Result |
| --- | --- |
| The handler names a stage that cannot follow, or ends the question in a way that is not its to say | question `failed` |
| `BudgetStop` | question `budget_exhausted`, the run goes on |
| `PreflightRefused` | run `paused` with a "model too large" condition; the question waits at its stage |
| Another model error, or any exception | question `failed`; details go to the log, only the error's type to the record |
| Three failed questions in a row | run `failed`, results so far kept |

Cancel and pause are requests the worker reads at the next checkpoint. Cancel marks unfinished
questions `canceled` in one transaction and keeps finished ones. A worker lock held through the
operating system allows one worker per store and is released when the process dies, so a killed
worker can be replaced at once; the stage that was running runs again from its start, and
nothing finished is repeated.

`sse.py` serves `GET /api/runs/{id}/events` as server-sent events with the event number as the
SSE `id`. A reconnect with `Last-Event-ID` gets exactly what it missed. The stream ends when the
run has ended or paused. `GET /api/runs/{id}` and `/questions` return the run and its queue with
partial results; `POST /api/runs/{id}/cancel` and `/pause` record the request.

Limits: nothing starts a worker from the API yet, and no route creates a run; both come with the
vertical slice (M3.9). A cancel asked for while a run is paused takes effect when a worker next
picks the run up. A stage may run twice after a crash, so handlers must tolerate that.
The owed mutation check now catches all 28 deliberate breaks in jobs, the store and SSE
([evidence](../docs/results/2026-10-03-m3.7-mutations-final.json)). It added regression tests
for rollback of earlier writes, question IDs shared across runs, and completion between SSE
reads. All three production modules were restored byte-for-byte.

## Reports (M3.11)

[`backend.reports`](reports/README.md) exports Markdown, standalone HTML, JSON and SARIF
2.1.0 from the same validated, redacted bundle. Evidence IDs and snapshot hashes are retained;
limitations appear in every format, including partial and empty runs. It reads snapshot blobs,
never starts inference, and refuses invalid citations or unsupported runtime claims. The
interchange schema and complete official SARIF schema are bundled. See the report README for
the CLI, semantics and limits; persisted findings still come with M3.9.

## Redaction (M3.11a)

`backend.redaction.Redactor` shares the report helper with model-context and logging boundaries.
Known credential shapes, assignments (including quoted JSON keys), URL credentials and private
keys are masked. Additional literal values come from `PLUMB_REDACTION_SECRETS`, a JSON array of
nonempty strings read by `Settings`. Settings dumps and repr omit them. The local API also masks
its current session and consumed bootstrap token in exception logs; the model server masks its
API key. Authentication still sends the actual credential to the intended loopback service.

API and worker exceptions are formatted, including chained exceptions, then redacted before a
log record is created; no raw `exc_info` is handed to other handlers. Run event messages are
redacted before SQLite persistence and SSE replay. Evidence identities, snapshots, hashes and
working checkpoints retain their originals so validation and crash recovery remain meaningful.

The model process's stdout/stderr is drained through a pipe into at most 1 MiB of raw memory;
its complete sanitized log is written at process exit, including failed startup and timeout.
There is no raw disk spool and no live log tail. Exceeding the limit omits the whole log with
an explicit size-limit message while continuing to drain the pipe. This avoids persisting a
partial credential. Model HTTP/answer errors report failure kinds and status codes without
echoing raw response bodies. Returned answers remain in memory for validation.

This is a rule-based redactor, not a detector for arbitrary secrets. Configure values whose
shape is not recognized. Normalized/escaped forms of configured values are masked in context
and diagnostics. Existing stored logs are not rewritten.

## Read-only MCP (M7.4)

`uv run --locked python -m backend.mcp` serves only stdio. The client chooses
an explicit saved review ID; four tools read its summary, paged findings, one
finding, and one cited exhibit. There is no run enumeration, analysis, model,
browser, mutation or execution entry point. No HTTP/SSE listener is exposed.

The implementation pins the [official MCP SDK](https://py.sdk.modelcontextprotocol.io/)
at 2.3.0 and keeps existing lockfile versions. Modern and legacy clients use the
same saved-read functions. Read-only/closed-world tool annotations describe
behavior; storage validation, rather than annotations, enforces it.

`backend.saved_reports.load` checks ID/path boundaries, report identity, source
citations, confirmed guards, runtime records, redaction and the original HTML.
Reads do not create a RunStore, analyzer or cache. A lock serializes artifact
reads; each request validates current files rather than serving stale cached
claims. Finding pages are at most 50 items, evidence pages at most 80 lines,
parsed request parameters at most 16 KiB, and each tool's data at most 128 KiB.
These are configured bounds, not performance measurements or a raw-pipe memory
limit. Larger pages refuse instead of silently truncating a conclusion.

Evidence returns only the requested exhibit's frozen source, with comments and
docstrings blanked and configured/known credentials redacted. It records the
original returned span/hash separately from displayed text; redaction may change
visible text layout. Developer-note exhibits cannot become security evidence.
Malformed IDs, absent/uncited spans, unsupported source and corrupt artifacts
refuse without echoing original input, file paths or exception text. An outer
middleware also removes SDK argument-validation input from tool errors.

The SDK's OpenTelemetry middleware is explicitly removed using its documented
opt-out; no exporter is installed. This provisional API is pinned and checked
in tests. References: [tools/annotations](https://py.sdk.modelcontextprotocol.io/servers/tools/),
[telemetry opt-out](https://py.sdk.modelcontextprotocol.io/run/opentelemetry/),
[client lifecycle](https://py.sdk.modelcontextprotocol.io/client/).
Actual stdio acceptance reads the saved receipt/invoice bundle in both eras,
checks file hashes and owned child exit. Saved access is not fresh accuracy or
an inference-resume claim. See the root README for an example client config.
