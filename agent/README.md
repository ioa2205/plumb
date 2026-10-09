# agent

The investigator: the seven typed question types, prompts and evidence packets, guard classification, the peer check, the challenge stage, the validator, and prioritization.

- **Plan:** §3 Core mechanisms, §6 The investigator, §7 Prioritization.
- **Tasks:** M3.1–M3.6, M3.8–M3.10.

## Model adapter (M3.1)

`agent/llm.py` is the only way the investigator reaches the model. `ModelAdapter.ask()` sends one
`ModelRequest` (a system prompt, a user prompt and a JSON Schema) and returns the parsed answer.
A request has no field for earlier turns and always sets `cache_prompt: false`, so every question
is answered from its own evidence (PROJECT_PLAN §9).

Each question carries a `Spend` against its `Budget` contract, shared by all of its requests:

| Budget | How it is enforced | When it runs out |
| --- | --- | --- |
| `max_prompt_tokens` | Counted with `/tokenize` before sending; the server's own count is charged after an answer | `BudgetStop("prompt_tokens")`, nothing generated |
| `max_seconds` | Every attempt, the token count and the pauses between retries; an attempt's timeout is the time left | `BudgetStop("seconds")` |
| `max_retries` | Transient failures only: timeouts, dropped connections, 5xx | The failure itself: `ModelTimeout` or `ModelUnavailable` |

A request the server refuses (4xx) raises `RequestRejected`; an answer cut off at `max_tokens`
raises `AnswerTruncated`, and any other unparseable answer `AnswerError`. None of these is
retried: at a fixed seed the same request gives the same result. `attempt_seconds` optionally caps
one attempt so that a stalled request can be retried inside the time budget.

The adapter owns the server's lifecycle. `start()` runs the preflight first and raises
`PreflightRefused` with the message for the interface when the model does not fit in free memory;
the server is then never started. `ask_json()` remains for the recorded baselines: one unbudgeted
attempt on an already running server, with the same request body and parsing.

Limits: the pre-send count covers the two prompts but not the chat template's own tokens, so a
question can end a few tokens over its prompt budget; `max_looks` is counted by the state machine
(M3.7), not here; a server that died is reported as unavailable and is not restarted. The adapter
is tested against a scripted loopback server (`agent/tests/fake_llama.py`), not yet against the
real model through a budgeted question; the first task that does so is M3.4.

## Evidence packets and questions (M3.2)

`agent/evidence.py` builds what the model is shown. `EvidencePacket.build()` takes one or more
`Cut`s (a file, a line range, and a label written by Plumb) and numbers their code lines `L1`,
`L2`, ... across the packet; `location()` maps an ID back to its file and line.

- **Comments are not evidence.** Comments and Python docstrings (any string used as a statement)
  are found with tree-sitter and taken out of the code. They follow it in a `developer-notes`
  block, shortened and capped, with no IDs, so they can be read but never cited. A line left
  empty has no ID either. TypeScript directives such as `"use server"` are code and stay.
- **Spotlighting.** Each excerpt sits in a delimiter with a per-packet random boundary, every
  line is marked with its ID, and control, format and line-separator characters (bidirectional
  overrides, zero-width marks, U+2028) are written as visible escapes, so code can neither end
  the evidence nor begin a line without an ID.
- **Limits stop, they do not trim.** A packet over 80 code lines, a cut outside its file, or a
  cut with no code is refused.

`agent/questions.py` holds the seven question types of PROJECT_PLAN §3.1. Each builder returns a
`Prompt`: system prompt, user prompt, answer schema and `parse()` into a typed answer.

| Type | Builder arguments | Answer |
| --- | --- | --- |
| `guard_summary` | packet | guards: kind, subject, object, line IDs |
| `guard_equivalent` | packet with parts `first` and `second` | yes/no/unknown, line IDs per part |
| `input_origin` | packet, line, optional value name | origin, line IDs |
| `sink_safety` | packet, sink kind, line | parameterized/allowlisted/contained/none_found, line IDs |
| `intentional_exception` | packet, missing guard kind, resource name | admin_only/public_resource/scoped_elsewhere/none_found, line IDs |
| `client_exposure` | packet | fields that cross, each with the line IDs of its path |
| `fix_sketch` | packet, the rule to restore | intent, line edits, probe parameters |

The system prompt is the shared rules plus that type's definitions. The user prompt puts the
evidence first and the question last. Line IDs in a schema are an enum of the packet's own lines,
so the grammar cannot emit a citation to a line that was not shown. Schemas use only the
constructs the pinned build was seen to enforce in M0.6. Text placed in a question is outside the
spotlighted evidence, so names taken from code must be plain dotted identifiers and a rule must
be one printable line written by Plumb.

Every prompt has a snapshot in `agent/tests/snapshots/`; after a deliberate change, rerun the
tests with `PLUMB_UPDATE_SNAPSHOTS=1`. System prompts are measured with the pinned tokenizer by
`uv run python -m eval.feasibility.prompt_tokens`, which reads the vocabulary only. The test
compares each prompt's hash with the measured one, so a prompt cannot change without being
measured again.

Limits: the prompts have not been scored on the model yet. Their wording, the evidence-then-
question order and the note format are design choices that M3.4 onward will measure, and the
guard_summary prompt differs from the one M0.6 ran. `fix_sketch` returns line edits, not a diff;
building the unified diff from them belongs to the task that replays fixes. Answer parsing checks
shape only; whether cited lines contain what the answer claims is the validator's job (M3.3).

## Validator (M3.3)

`agent/validator.py` checks claims against the snapshot before they are recorded. It reads files
only through the snapshot store, so a working tree that changed afterwards makes no difference.

| Rule | Refused |
| --- | --- |
| `bad_span` | A citation to another snapshot, to a file the snapshot does not hold (excluded secrets included), to lines outside the file, or with a content hash that does not match |
| `comment_citation` | An exhibit used as evidence whose lines hold no code. The same lines are allowed as a developer note, which proves nothing |
| `unknown_line` | An answer citing a line it was not shown, or citing one part's lines for the other in `guard_equivalent` |
| `missing_citation` | A claim with no cited line: a yes in `guard_equivalent`, an origin other than unknown, a reason other than none_found |
| `construct_not_found` | A named thing that is not in the cited code: a guard's subject or object, an exposed field, an owner guard that names no sides, an edit without code |
| `unconfirmed_rejection` | A rejected finding whose guard exhibit does not contain a guard confirmed in code |
| `unproven_runtime_claim` | "Reproduced", "not reproduced" or "inconclusive" without a probe run on record that ended that way for this finding and snapshot; "not attempted" next to probe runs; a replayed fix without its replay |

`check_answer(prompt, answer)` applies the answer rules; `Validator.finding()` applies the rest
to a finding together with its guards, probe runs and suggested change.

**Confirming a guard.** `Validator.confirm()` is the only place a guard becomes `confirmed`. It
needs an equality or membership test inside the guard's span with the caller on one side and the
resource on the other (or the role literal, for a role guard), found with tree-sitter after
comments are blanked, and it narrows the guard's span to that test. Names match whole: `user.id`
is not found in `admin_user.id`. So a comment that describes the check, a helper whose name
promises one, and a call that only passes both values confirm nothing; the guard has to be
confirmed where the comparison is, inside the helper.

Confirmation now also recognizes enforced sign-in denial/redirect checks, role membership
factories and bounded executed query filters (M3.4). Legacy direct-comparison confirmation
remains for earlier evidence; it alone does not establish path dominance or the correct policy.

## Guard classification (M3.4)

`agent/guards.Classifier` classifies one exact snapshot symbol with one executable check per
model question. Code determines allowable fields and kinds, while the model distinguishes
owner and tenant semantics. The validator requires the actual denial or executed filter.
SQL-shaped strings or helper names alone prove nothing: the imported wrapper must show
preparation/execution with unchanged positional bindings. Authentication context can include
validated cookie/session lookup bodies. Target code is read, never executed.

Canonical forms preserve the raw compared expressions for later revalidation. Role factories
produce a symbolic `ROLE(roles)` summary; a literal admin exemption needs separately validated
factory binding code. A missing recognized local check never proves the entire path unguarded.
Keyed filters and conditional TypeScript role/tenant paths remain unsupported (M3.4a).

The SQLite cache lives outside the repository. Keys cover model/runtime identity, snapshot,
source, context, prompt/schema and version. Reads revalidate the evidence and candidate coverage;
invalid answers are not cached. Run `uv run python -m eval.feasibility.guard_classification
--focused` for the eight predeclared development cases. The final real-model run passed 8/8
exact case expectations; this tuned development result is not a general accuracy estimate.

## Peer check (M3.5)

`agent/peers.PeerCheck` joins guard summaries to source-bound FastAPI access paths.
It validates direct uncaught helper calls, the loaded record passed to each helper,
and the actual dependency principal bound to comparisons. Conditional calls, another
record/caller, early exposure, rebinding and optional tenant filters cannot establish
the checked scope. Role factories need their actual literal binding and enforcing body.
Admin-only and role-plus-tenant policies retain their sites and cited exclusion reasons.
These are candidate exceptions; the challenge stage still owns verdicts.

`consensus` counts distinct sites once per resource/guard kind. A subject does not vote
as its own peer. At least `PLUMB_PEER_MIN_PEERS` other sites (default 3) and
`PLUMB_PEER_MIN_SHARE` of other eligible sites (default 0.75) must apply a missing kind.
Unsupported and unresolved sites remain visible in the denominator. Resource identities
are not merged by spelling, and inferred code rules remain separate from user policy.

Path propagation supports bounded Python/FastAPI paths and TypeScript DAL query
filters tied to their exact query/table and returned null-checked receiver.
Resolved unconditional calls carry the evidence; supplied or modified identities,
other queries and unsupported control flow cannot inherit the constraint. All
unsupported sites remain in the denominator. This TypeScript slice creates no
new exemptions or whole-application verdicts: identity-provider correctness and
required policy remain gaps, and fresh model acceptance is deferred. Missing
guards are leads, not proof of absence. The Python development runner is
`uv run python -m eval.feasibility.peer_check`.

## Prioritization (M3.8)

`agent/priority.py` decides which access sites to investigate first and says why
(PROJECT_PLAN §7). A site is ranked by how many of the plan's seven rules apply to it; ties go
to the site whose rules come earlier in the plan's list, then to the lower ID. There is no score
and no probability. Each rule that applies is a sentence that travels with the question.

| Rule | Read from |
| --- | --- |
| Public exposure | The map: no check candidate reaches the query, or only a proxy matcher does |
| Personal or payment data | The resource's name, word by word; said to be a guess from the name |
| Write or delete action | The query's operation, or its entry's method (POST, PUT, PATCH, DELETE, Server Action) |
| Request-controlled identifier | The key's origin: path, query, body or header |
| Peer deviation, uncertain guard, recent change | Passed in by the stages that know (M3.5, M3.4, a later diff) |

`queue()` fills every fifth place (a share of 0.2, a setting capped at 0.5) from the lower half of
what is still waiting and labels it exploration, so the share holds at any point where a run
stops. The draw is seeded by the snapshot ID. Each item keeps its place by the rules alone
(`recommended`) next to its place in the queue.

A query inside a check candidate's own function (the session lookup of a sign-in dependency) is
ranked by what it is, not by what its route does. Without that, the Tandir queue put the
sign-in lookups of writing routes above the unguarded receipt read; the lab test now pins the
order.

On the Tandir map (74 sites): the two Server Actions that update orders behind the proxy alone
come first, then the pages that load orders and customers by a path ID, then the writing routes
on an order; 14 places are exploration.

Limits: the subjects are access sites only; sinks and client-prop transfers join with their
families (M3.10). "No sign-in check found" is what the map sees, and the map sees no checks
inside TypeScript data-access functions yet, so it over-reports for the web lab until M3.4. The
name-based data guess will miss resources with unusual names. Reordering or narrowing by the
user is not built; `recommended` is kept so that it can be shown when it is.

## Context redaction (M3.11a)

Evidence rendering and model requests use `backend.redaction.Redactor`. Known credential shapes
and configured literal values (`PLUMB_REDACTION_SECRETS`, a JSON array) are replaced before
serialization. Developer notes are redacted before display truncation. Multiline replacements
keep each code line's citation ID and source location. The packet's original code and snapshot
hashes remain available to the validator; a credential in a path or schema identity refuses
the request instead of changing the evidence's identity.

The budgeted adapter counts the exact sanitized system/user text it sends for generation.
The unbudgeted baseline helper and direct server tokenization use the same policy. Each request
still stands alone. Model errors omit raw response snippets; valid answers remain available
to the validator. Redacted code can hide a policy-relevant literal, so an absent value must
stay unknown rather than being inferred from the replacement token.
# Challenge stage (M3.6)

`AuthorizationChallenge` rebuilds path facts from the snapshot, searches the
handler, dependencies and resolved helpers, and records the searched spans for
each acquittal item. Three independent shuffled judgments must agree and pass
validation. A known applicable predicate gets a narrow `guard_summary` question;
otherwise `intentional_exception` searches for an exception. Raw answers remain
separate from their interpreted reason. Only a cited source-confirmed guard can
reject a case. Unknown paths, contradictory answers and unsupported evidence
remain inconclusive. Runtime reachability, public policy and impact are not
inferred.

## Remaining-family workflows (M3.10)

`SinkInvestigator` asks three independent `sink_safety` questions and compares
their citations and mechanisms with bounded executable Python facts. Recognized
closed literal maps must reject unknown keys; command argument arrays require a
literal executable and shell disabled; canonical paths require mandatory
containment. Escaped maps, dynamic shell options, unstable bindings, unsupported
control flow and unresolved stored-value provenance cannot acquit or establish
an unsafe request flow. Safety guards bind to the exact sink and are rechecked
by the validator during export.

`BoundaryInvestigator` includes resolved Next.js helpers in its evidence packets
and never treats a proxy matcher as authorization. A bounded TypeScript role form
now follows a const receiver's named factory to its class membership predicate
and unconditional HTTP denial. The source proof accompanies each model question
and the report; a helper name or signature alone cannot establish protection.
This form passes software tests; its fresh model acceptance is pending a refused
RAM preflight. General helper/resource binding, conditional tenant checks and
client DTO intent remain unresolved. A SQL operation alone cannot establish a
required role policy.
All model misses remain recorded; these workflows do not yet constitute passing
investigation slices for every family. The CLI selects them with `--family` and
retains the existing pause/resume, coverage and four-format reports.
