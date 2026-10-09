import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, rmdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { exportPolicy, manifestName, scriptHashes } from "./export-policy.mjs";

test("build policy preserves exact script content and excludes external script tags", () => {
  const text = "\n console.log('Ⅰ ≠ 1');\n";
  const expected = `sha256-${createHash("sha256").update(text).digest("base64")}`;
  assert.deepEqual(scriptHashes(`<script>${text}</script><script src="/_next/static/app.js"></script>`), [expected]);
  assert.deepEqual(scriptHashes(`<script>${text.replaceAll("\n", "\r\n")}</script>`), [expected]);
  assert.notDeepEqual(scriptHashes(`<script>${text.trim()}</script>`), [expected]);
});

test("inline styling and event attributes refuse rather than weaken the policy", () => {
  for (const html of ['<span style="color:red">x</span>', '<button onclick="x()">x</button>', '<style>body{}</style>']) {
    assert.throws(() => scriptHashes(html), /inline/);
  }
});

test("manifested exports include only regular supported assets and omit Next's styled error page", () => {
  const root = mkdtempSync(join(tmpdir(), "plumb-export-test-"));
  try {
    writeFileSync(join(root, "index.html"), "<html><script>console.log('sample')</script></html>");
    writeFileSync(join(root, "404.html"), '<span style="color:red">Not served</span>');
    const files = exportPolicy(root);
    assert.deepEqual(Object.keys(files), ["index.html"]);
    assert.deepEqual(JSON.parse(readFileSync(join(root, manifestName), "utf8")).files, files);
    assert.deepEqual(exportPolicy(root), files); // rebuilding the manifest is deterministic
    writeFileSync(join(root, "private.env"), "not an export asset");
    assert.throws(() => exportPolicy(root), /Unsupported/);
  } finally {
    for (const name of ["index.html", "404.html", manifestName, "private.env"]) {
      rmSync(join(root, name), {force:true});
    }
    rmdirSync(root);
  }
});
