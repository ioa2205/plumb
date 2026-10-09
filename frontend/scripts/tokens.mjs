import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
export const tokens = JSON.parse(readFileSync(resolve(root, "tokens.json"), "utf8"));

function properties(values) {
  return Object.entries(values).map(([key, value]) => `  --${key}: ${value};`).join("\n");
}

export function renderTokens() {
  const common = properties(tokens.common);
  const day = properties(tokens.themes.day);
  const night = properties(tokens.themes.night);
  const swatches = Object.keys(tokens.themes.day).map(name => `.token-swatch[data-token="${name}"] { background-color: var(--${name}); }`).join("\n");
  return `/* Generated from tokens.json; do not edit. */\n:root {\n${common}\n${day}\n  color-scheme: light;\n}\n@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="day"]) {\n${night}\n    color-scheme: dark;\n  }\n}\n:root[data-theme="night"] {\n${night}\n  color-scheme: dark;\n}\n${swatches}\n`;
}

export function generate() {
  const target = resolve(root, "app/tokens.css");
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, renderTokens());
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) generate();
