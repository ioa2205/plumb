# Tandir (deliberately vulnerable lab)

Tandir is a bakery ordering platform written for this project as an evaluation target. It contains intentional security flaws, each next to a protected lookalike. It does not model any real company's system.

- **Loopback only.** Never deploy it, expose it on a network, or reuse its code. The API binds 127.0.0.1 and has no host option.
- Plumb never imports or installs this code. It runs only through the hash-pinned bundled-lab runner (PROJECT_PLAN §3.4).
- It has its own project and lint configuration, so the root ruff rules do not apply here.
- The kitchen printer is off unless `TANDIR_PRINTER=on`. The lab tests replace `subprocess.run` with a recorder, so nothing is ever executed.

## Running the API

~~~text
cd labs/tandir/api
uv sync
uv run python -m tandir              # http://127.0.0.1:8701, data in api/var/ (or TANDIR_DATA_DIR)
uv run pytest                        # lab tests on the vulnerable snapshot
~~~

## Running the web app

The Next.js 16 storefront and back office share the API's SQLite database and sessions through Node's built-in `node:sqlite` (Node 24). Seed the database first (or start the API once).

~~~text
cd labs/tandir/api && uv run python -m tandir --seed-only
cd ../web
pnpm install
pnpm test                            # lab tests (seeds a throwaway copy through the API's seed)
pnpm build && pnpm start             # http://127.0.0.1:8702, telemetry off
~~~

A session token from the API's `POST /auth/login` also works as the web's `tandir_session` cookie.

Fixture users and passwords are in `api/tandir/seed.py`: customers `alice` and `bob`, the courier `kamol`, branch managers `farrukh` (Chilonzor) and `nodira` (Yunusobod), and `admin`.

## What the tests cover

The lab tests check legitimate actions and every protection: each lookalike refuses what it should refuse, and each owner can still do what they should. The intentional flaws have no runtime tests here; they are declared, with location, family, and CWE, in [`eval/ground_truth/tandir.toml`](../../eval/ground_truth/tandir.toml) and checked against the code (`uv run python -m eval.ground_truth check`). Runtime reproduction is Plumb's job, through declarative probes on the bundled-lab runner. See [ADR-0005](../../docs/decisions/ADR-0005-lab-tests-cover-protections.md).

- **Plan:** §10.1 The lab: Tandir.
- **Tasks:** M1.1 API, M1.2 web, M1.3 fixed snapshot, M1.4 ground-truth manifest.
