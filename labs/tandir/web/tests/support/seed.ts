import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { TestProject } from "vitest/node";

declare module "vitest" {
  export interface ProvidedContext {
    seededDataDir: string;
  }
}

const apiDir = fileURLToPath(new URL("../../../api", import.meta.url));

// Seed one lab data directory with the API lab's own seed; each test copies it.
export default function setup(project: TestProject): () => void {
  const dataDir = mkdtempSync(path.join(tmpdir(), "tandir-web-seed-"));
  execFileSync("uv", ["run", "--frozen", "python", "-m", "tandir", "--seed-only"], {
    cwd: apiDir,
    env: { ...process.env, TANDIR_DATA_DIR: dataDir },
    stdio: "inherit",
  });
  project.provide("seededDataDir", dataDir);
  return () => rmSync(dataDir, { recursive: true, force: true });
}
