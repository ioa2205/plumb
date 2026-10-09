import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { generate } from "./tokens.mjs";
import { exportPolicy } from "./export-policy.mjs";
import { generateContracts } from "./contracts.mjs";

if (process.argv[2] === "build") { generate(); generateContracts(); }
const require = createRequire(import.meta.url);
const result = spawnSync(process.execPath, [require.resolve("next/dist/bin/next"), ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
});
if (result.status === 0 && process.argv[2] === "build") {
  const files = exportPolicy(fileURLToPath(new URL("../out/", import.meta.url)));
  console.log(`Export policy recorded for ${Object.keys(files).length} files.`);
}
process.exit(result.status ?? 1);
