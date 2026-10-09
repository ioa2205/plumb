# Frozen fix proposals (M3.15)

One bounded `fix_sketch` request follows a validated Supported finding in RECORD,
using its remaining adapter budget (at most 768 output tokens). Decisive challenge
judgments are unchanged. A proposal is not evidence that the patch fixes anything.
Exhausted budget, truncated output, invalid edits and unsupported mapping retain the
finding and save a separate refused/unavailable outcome. No target checkout is edited.
The completed RECORD checkpoint keeps exact proposal/change/spec links; a resumed
completed question never asks again. An interrupted RECORD can repeat from its start
under the existing engine protocol; it cannot overwrite an already saved proposal.

The primary source cut is editable. Other cuts supply helper context, not editable
peer files. One to four edits cite packet code IDs, each anchored to one immutable
line and its full file hash. A scope citation pins the primary unit. Duplicate line
operations, unrelated paths/context, comments-only IDs, missing files/excluded links,
binary/non-LF/oversized files, control characters, missing final newline, no-ops and
invalid syntax are refused. At most 30 replacement lines per edit; 16 KiB maximum diff.
The diff is generated in memory with zero context lines so unrelated nearby secrets
are not copied into proposals. Credential-shaped/configured values in public edit
text/diffs are refused. Original comments can be removed by a proposed line replacement;
they remain part of the exact frozen preimage, never model evidence.

Reports independently reconstruct the diff from original snapshot bytes and exact
edits. This establishes patch provenance, not semantic correctness, reachability or
regression success. SuggestedChange retains legacy pinned-diff compatibility; new
model proposals always include snapshot/scope/edits and stay `proposed`.

The only supported declarative adapter is the pinned bundled Tandir API receipt:
all API source hashes must match, the finding must cite the receipt, and requested
parameter/principal roles must match its trusted template. Alice's setup creates the
marked order; bob attacks and alice controls. The existing trusted runner owns its
disposable credential fixture; the model supplies no HTTP path/body, credential,
setup command, script or host. Spec availability is not runner execution/availability.
Wrong/missing mapping yields an unavailable specification. General mappings/isolation
and applying arbitrary proposals are M4.3/M4.5a, not host execution fallbacks.

The existing pinned receipt replay does not overwrite saved model proposals. General
proposal replay/attachment remains step 09 after an isolated runner is available.
Existing legacy pinned replay artifacts remain readable. Fresh fix-sketch quality is
an explicitly bounded step-14 gate; UI appearance acceptance remains deferred.
