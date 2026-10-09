# verification

Differential proof: the declarative probe schema, the attack-plus-control oracle, the runners (bundled lab, Windows Sandbox, optional Docker), fix replay, and the isolation suite.

- **Plan:** §3.4 Differential proof.
- **Tasks:** M4.1–M4.6.

`ProbeSpec` is data: bounded relative HTTP requests, principal labels, a victim
marker and optional positive-integer response captures. `verification.probes.execute`
accepts only an explicit IPv4 loopback origin, refuses redirects and bounds
requests and responses. A runner must validate its environment and admit the
spec before calling it. No script, shell command or response code is executed.
Credentials and bodies are absent from observation records.

The oracle requires both attack and owner control. Failed controls, timeouts,
ambiguous responses and 500s remain Inconclusive. A fix additionally requires
denial of the attack with continued owner access. A transport fixture is a
software-boundary test, not runtime reproduction.

`uv run python -m verification` exercises the receipt; `--invoice` exercises its
protected lookalike. The runner admits only these exact reviewed templates.
Before execution it verifies every lab source/lock file, the trusted worker and
the local interpreter against `pins/tandir-api.json`. The child checks the exact
copied file set again before importing anything. Printing is disabled, fixture
credentials stay in memory and only the owned loopback process is terminated.
Its disposable database and verified source copy are removed on exit.

The interpreter pin records this laptop's installed locked environment. A fresh
machine needs a separately verified environment and release pin; automatically
installing or trusting a target environment is not supported. This exception is
for the bundled lab only and is not an isolation guarantee for arbitrary code.
The model must be stopped first. Raw successful receipt/invoice observations
and the validation record are saved under `docs/results/2026-10-05-m4.2-*`.

## Receipt fix replay (M4.5)

`uv run python -m verification --replay` applies the reviewed
`pins/receipt.patch` in disposable release copies. It records the before probe,
then runs the same receipt attack/control against the patched copy with a fresh
database. It never changes the lab checkout or a user's repository. Source
snapshots have identical API path sets; their hashes identify the exact before
and after bytes. The original single-probe command still snapshots the full lab.

Only this pinned diff and its one expected output file are admitted. The parent
checks original source, diff, output, worker and interpreter hashes before a
child starts. The worker independently checks the chosen release's complete
file set and hashes before importing the lab. Unknown variants, changed bytes,
different probe templates and unrelated findings refuse. No model-written diff
or arbitrary target can enter the host runner.

The manifest keeps the finding ID and both observations; `SuggestedChange` cites
the patched run ID as its replay evidence. Its status
becomes `replayed_fixed` only after actual baseline reproduction followed by
attack denial and continued owner access. A failed baseline stops replay; an
unavailable patched run retains the baseline and the unverified proposal, with
an explicit failure reason. Error/timeout/
failed-control observations cannot certify a fix. The saved manifest includes
the exact regression `ProbeSpec`, diff, release pins, snapshots, machine state
and both observation records. Servers run sequentially and their databases and
source copies are removed on exit; frozen evidence remains in the snapshot cache.

Release copies use a stable `tandir-api` root name in `cache/replay-snapshots`.
Repeated probes reuse their validated metadata instead of persisting a random
temporary root name. Normal review snapshots and earlier attempt records are
preserved separately; no cache or user files are overwritten or deleted.

This is the known bundled receipt demonstration. General authorized diffs still
need an isolated runner, a separate admission path and negative isolation checks.
There is no arbitrary-code execution or full-project safety claim.
