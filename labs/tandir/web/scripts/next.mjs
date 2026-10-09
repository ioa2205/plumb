// Runs the Next.js CLI with telemetry switched off: the lab never phones home.
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const bin = require.resolve("next/dist/bin/next");
const result = spawnSync(process.execPath, [bin, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: {
    ...process.env,
    NEXT_TELEMETRY_DISABLED: "1",
    // node:sqlite still prints an ExperimentalWarning on Node 24.
    NODE_OPTIONS: `${process.env.NODE_OPTIONS ?? ""} --disable-warning=ExperimentalWarning`.trim(),
  },
});
process.exit(result.status ?? 1);
