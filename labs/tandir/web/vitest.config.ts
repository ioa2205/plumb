import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@": here("./"),
      // Next.js resolves `server-only` itself; outside Next it would throw on import.
      "server-only": here("./tests/support/empty.ts"),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    globalSetup: ["tests/support/seed.ts"],
    setupFiles: ["tests/support/next-mocks.ts"],
    pool: "forks",
    testTimeout: 20000,
  },
});
