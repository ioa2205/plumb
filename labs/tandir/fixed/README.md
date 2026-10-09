# Tandir fixed snapshot

The fixed snapshot is the lab with every intentional flaw repaired. It supports the before/after demonstration (PROJECT_PLAN §10.1) and paired vulnerable/fixed scoring (§11).

It is kept as a patch set, not as a second copy of the lab, so each fix is a small diff against the code it repairs:

| Patch | Flaw (vulnerable lab) | Fix, mirroring its lookalike |
| --- | --- | --- |
| `api.patch` | `GET /orders/{id}/receipt` loads any order | Uses `load_order_scoped`, like the invoice |
| `api.patch` | Menu edit checks the role but not the branch | Checks branch membership, like the hours update |
| `api.patch` | Admin order search puts `sort` into `ORDER BY` | Maps `sort` through an allowlist, like the customer search |
| `api.patch` | Cake label printing runs a `shell=True` command string | Passes an argument list, like receipt printing |
| `api.patch` | Photo download joins the requested name | Resolves the path and checks containment, like the avatar |
| `web.patch` | `refundOrder` Server Action has no authorization | Delegates to the Data Access Layer (staff role, branch scope), like `cancelOrder` |
| `web.patch` | Courier page passes the full customer record to a Client Component | Passes a minimal DTO, like the order page |
| `web.patch` | `/api/admin/export` relies on the `proxy.ts` matcher alone | Checks the role in the handler, like `/api/admin/reports` |

## Commands

~~~text
uv run python labs/tandir/fixed/snapshot.py check        # build in a temp folder, run both lab suites as "fixed"
uv run python labs/tandir/fixed/snapshot.py make DEST    # just build it (DEST outside the repository)
~~~

`check` copies `api/` and `web/`, applies both patches with `git apply`, links the lab's installed `node_modules`, and runs the API tests, the web type check, and the web tests with `TANDIR_VARIANT=fixed`. That variable switches on the fixed-only protection tests (`api/tests/test_fixed.py`, the `fixedOnly` blocks in `web/tests/staff.test.ts`), which are skipped on the vulnerable lab (ADR-0005).

## Updating a patch

Apply the patch in place (`git apply labs/tandir/fixed/api.patch` from `labs/tandir`), edit, regenerate with `git diff --relative=labs/tandir -- api/tandir > fixed/api.patch` (or `web/app web/lib web/proxy.ts` for `web.patch`), then restore the vulnerable files with `git checkout -- api/tandir web/app web/lib` and run `check`.
