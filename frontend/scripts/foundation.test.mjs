import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { tokens, renderTokens } from "./tokens.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const surfaces = ["desk", "sheet", "raised", "well", "cite", "carmine-wash", "blue-wash", "ochre-wash"];
const foregrounds = ["ink", "graphite", "pencil", "carmine", "blue", "ochre", "umber"];

function luminance(hex) {
  const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  const linear = rgb.map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}
function ratio(a, b) {
  const [lo, hi] = [luminance(a), luminance(b)].sort((x, y) => x - y);
  return (hi + 0.05) / (lo + 0.05);
}

test("unrounded text and information-line contrasts meet the unchanged AA gates", () => {
  assert.equal(ratio("#000000", "#ffffff"), 21);
  assert.equal(ratio("#000000", "#000000"), 1);
  for (const [theme, colors] of Object.entries(tokens.themes)) {
    for (const foreground of foregrounds) for (const surface of surfaces) {
      assert.ok(ratio(colors[foreground], colors[surface]) >= 4.5, `${theme} ${foreground}/${surface}`);
    }
    for (const [foreground, backgrounds] of [["blue-line", ["desk", "sheet"]], ["control-rule", ["well", "sheet"]]]) {
      for (const background of backgrounds) assert.ok(ratio(colors[foreground], colors[background]) >= 3, `${theme} ${foreground}/${background}`);
    }
  }
});

test("tokens preserve the design palette and generated CSS is current", () => {
  const design = readFileSync(resolve(root, "../design.md"), "utf8");
  const rows = [...design.matchAll(/^\| `([a-z-]+)`[^|]*\| (#[a-fA-F0-9]{6}) \| (#[a-fA-F0-9]{6}) \|/gm)];
  assert.equal(rows.length, Object.keys(tokens.themes.day).length);
  for (const [, name, day, night] of rows) {
    assert.equal(tokens.themes.day[name], day);
    assert.equal(tokens.themes.night[name], night);
  }
  assert.equal(readFileSync(resolve(root, "app/tokens.css"), "utf8"), renderTokens());
});

function sources(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap(item => item.isDirectory()
    ? sources(resolve(folder, item.name)) : [resolve(folder, item.name)]);
}
test("components use color tokens and text-safe rendering", () => {
  for (const path of [...sources(resolve(root, "app")), ...sources(resolve(root, "components"))]) {
    if (path.endsWith("tokens.css")) continue;
    const code = readFileSync(path, "utf8");
    assert.doesNotMatch(code, /#[a-fA-F0-9]{3,8}\b|\b(?:rgb|hsl)a?\(/, path);
    assert.doesNotMatch(code, /dangerouslySetInnerHTML/, path);
  }
});
