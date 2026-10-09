import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

export const manifestName = "plumb-export.json";
const extensions = new Set(["html", "txt", "js", "css", "woff", "woff2", "svg", "png", "jpg", "jpeg", "ico", "json"]);
const digest = bytes => createHash("sha256").update(bytes).digest("hex");

/** Only compiler-owned HTML. The backend independently parses and checks it too. */
export function scriptHashes(html) {
  if (/<[^>]+\s(?:style|on[\w-]+)\s*=/i.test(html)) {
    throw new Error("Export contains inline styles or event handlers; use classes and React handlers.");
  }
  if (/<style\b/i.test(html)) throw new Error("Export contains an inline stylesheet; use CSS files.");
  const hashes = [];
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)) {
    if (/\bsrc\s*=/i.test(match[1])) continue;
    const text = match[2].replace(/\r\n?/g, "\n");
    hashes.push(`sha256-${createHash("sha256").update(text, "utf8").digest("base64")}`);
  }
  return [...new Set(hashes)].sort();
}

export function exportPolicy(root) {
  const files = {};
  function visit(folder) {
    for (const name of readdirSync(folder).sort()) {
      const path = join(folder, name);
      const rel = relative(root, path).replaceAll("\\", "/");
      if (rel === manifestName || rel === `${manifestName}.tmp`) continue;
      // Next's generated error documents have inline styles. The API supplies
      // its own plain refusal/404 responses; these documents are never served.
      if (rel === "404.html" || rel.startsWith("404/") || rel.startsWith("_not-found/")) continue;
      const info = lstatSync(path);
      if (info.isSymbolicLink()) throw new Error("Export may not include links.");
      if (info.isDirectory()) { visit(path); continue; }
      if (!info.isFile() || info.nlink !== 1 || info.size > 8 * 1024 ** 2) throw new Error("Export file fails its type/size/link limit.");
      if (!extensions.has(name.split(".").at(-1))) throw new Error("Unsupported export asset type.");
      if (!/^[A-Za-z0-9_./-]+$/.test(rel) || rel.split("/").some(part => part.startsWith("."))) throw new Error("Unsafe export name.");
      const bytes = readFileSync(path);
      files[rel] = { sha256: digest(bytes), bytes: bytes.length, script_hashes: rel.endsWith(".html") ? scriptHashes(bytes.toString("utf8")) : [] };
    }
  }
  visit(root);
  const target = join(root, manifestName);
  writeFileSync(`${target}.tmp`, `${JSON.stringify({ version: 1, files }, null, 2)}\n`);
  renameSync(`${target}.tmp`, target);
  return files;
}
