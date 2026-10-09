# frontend

The workbench uses a Next.js 16 static export (`output: 'export'`), managed with
`pnpm`. M5.1 supplies `/foundation/`, a development page for the design tokens,
glyphs, fonts and themes. It does not load a project or security review. M5.2a now
serves the exact recorded export through the backend session gate, with hashes for
its generated scripts. Project/readiness/start/resume, review queue, saved findings,
case evidence, decisions, changes and run history are implemented. The picker reads
recorded metadata without inference. Source checks and review dispatch use the
protected backend and preserve frozen source identity. The current
[portable candidate](../docs/results/2026-10-08-m7.7f-current-candidate.md) includes
79 exported files and passes 68 frontend tests, strict types/contracts and protected
HTTP checks. Full authenticated browser rendering, desktop/accessibility and mobile
qualification remain separate and incomplete; HTTP does not prove hydration.

From the repository root, with Node 24 and pnpm 10.33.0:

```powershell
pnpm --dir frontend install --frozen-lockfile --ignore-scripts
pnpm --dir frontend test
pnpm --dir frontend typecheck
pnpm --dir frontend build
# Development preview only; stop it with Ctrl+C afterwards:
uv run --locked python -m http.server 8780 --bind 127.0.0.1 --directory frontend/out
```

Open `http://127.0.0.1:8780/foundation/`. Build before previewing; the export is
static and does not update automatically. The build uses one worker and disables
Next telemetry. No model is needed. Do not run it alongside model inference or a
test VM on this laptop.

The build also writes `out/plumb-export.json`. The backend loads that manifest at
startup, serves only its files and verifies current bytes before each response.
Rebuild and restart the backend together; altered/stale assets refuse. The policy
allows exact generated script hashes, with no unsafe-inline or unsafe-eval, and
forbids style/event attributes. Use classes and React handlers. Compiler-generated
styled error documents are excluded; the backend supplies plain refusals/404s.
The manifest is build metadata, not a signature against another process running
as the same user. No reviewed-project files are served through this path.

After building, `uv run --locked python -m backend.serve` prints the one-time
session link. Bootstrap opens the workbench with unloaded states until a project or
saved run is selected. `/foundation/` remains a development reference. Use
`uv run plumb web` for the public launcher or the portable package's **Start Plumb.cmd**.
Opening the workbench starts no model; only an explicitly requested review does.

`tokens.json` is the palette/role source; `pnpm --dir frontend tokens` regenerates
`app/tokens.css`, and builds regenerate it too. The tests check unrounded AA
contrast, agreement with the design, generated CSS and token-only component
colors. System follows the device theme; Day/Night overrides are saved locally.
Every state glyph has a visible word, and the skip link moves keyboard focus to
the main content.

Atkinson Hyperlegible Next and Mono are pinned Fontsource packages. Latin normal
weights only are bundled as local assets, without a font service. Their exact SIL
OFL licenses ship in `public/fonts/` and the static export. API types in `generated/contracts.ts` come from backend schemas through `pnpm contracts`; builds regenerate them and `pnpm contracts:check` checks currentness. They are structural types, not evidence validation. Never edit them by hand.

- **Design:** [design.md](../design.md) and the visual reference [design/study-finding.html](../design/study-finding.html).
- **Tasks:** M5.1–M5.8.
- **Acceptance:** [M5.1 record](../docs/results/2026-10-06-m5.1-notes.md), including
  actual 1440/390 Day/Night screenshots. This does not close the separate saved
  HTML report screenshot gate or the full workbench accessibility pass.
