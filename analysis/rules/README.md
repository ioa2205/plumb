# Pattern leads and supplementary observations

The YAML rules in this directory are Opengrep leads for investigated families.
They are not conclusions. `analysis/security_signals.py` is a separate bounded
observer, with no model/scanner/runtime dependency. Its observations do not enter
the question queue, finding counts, or coverage denominator.

`supplementary-signals-1` recognizes these executable Python configuration forms:

| Rule | Recognized source | Boundary |
| --- | --- | --- |
| `config-fastapi-debug` | Direct imported `fastapi.FastAPI(debug=True)` | Literal boolean, module import/alias; any rebinding/shadowing/attribute write refuses that alias |
| `config-httpx-tls` | Direct imported `httpx.Client(verify=False)` or `AsyncClient` | Same binding and literal rules; no inferred flags, kwargs dictionaries, wrappers or runtime deployment claim |

Aliases of direct imports are supported. Comments, strings, docstrings, lookalike
names and dynamically constructed calls cannot produce configuration observations.
Only included frozen files are opened, never excluded `.env`, key files or links.
Credential *shape* rules reuse `backend.redaction`: private keys, GitHub tokens,
AWS key IDs, API tokens, JWTs, credential assignments and URL authentication.
They may match placeholders. Only a snapshot-salted SHA256, citation and the
literal `[REDACTED]` label leave the observer, with no value/snippet or remote check.
The per-review observation limit is 100; exceeding it records incomplete scope.

Dependencies: statically parse `package-lock.json` / `npm-shrinkwrap.json` v2/v3
`packages` and `uv.lock` v1 `package` records. Exact versions and official registry
sources are required. npm nested/scoped packages and aliases use the installed
record's actual `name`, corroborated by the registry tarball path; PyPI identities
use normalized names. Git, local, linked, private registry and ambiguous sources
are unknown, never installations. Duplicate JSON keys and malformed/oversized
lockfiles are refused; lockfile citations cover the complete parsed file. pnpm,
Yarn and other lockfiles are explicitly unsupported in this first version.

Official definitions used: [npm lock format](https://docs.npmjs.com/files/package-lock.json/),
[npm aliases](https://docs.npmjs.com/cli/install/),
[uv lockfile](https://docs.astral.sh/uv/concepts/projects/layout/),
[FastAPI debug](https://fastapi.tiangolo.com/reference/fastapi/),
[HTTPX SSL](https://www.python-httpx.org/advanced/ssl/).
