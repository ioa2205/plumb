// @ts-check
// Captures a region of a locally served page with headless Chrome, for looking at the result
// before calling UI work done (CLAUDE.md). Chrome on Windows will not lay out narrower than
// about 500 px, so every capture goes through a harness page holding an <iframe> of the
// wanted width; the preview server must run with --allow-framing.
//
//   node scripts/shots.mjs recorded-run --width 390 --theme night --y 1200 --height 900
//
// Output: shots/<page>-<width>-<theme>-<y>.png (ignored by Git).

import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SHOTS = join(LANDING, 'shots');
const CHROME = process.env.CHROME_BINARY ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

// Pages are named without a leading slash ("home" for the overview): Git Bash rewrites
// arguments that look like absolute paths.
const [pageName = 'home', ...rest] = process.argv.slice(2);
const page = pageName === 'home' ? '/' : `/${pageName}`;
const option = (/** @type {string} */ name, /** @type {string} */ fallback) => {
  const index = rest.indexOf(`--${name}`);
  return index >= 0 ? rest[index + 1] : fallback;
};
const origin = option('origin', 'http://127.0.0.1:4174');
const width = Number(option('width', '1440'));
const theme = option('theme', 'day');
const y = Number(option('y', '0'));
const height = Number(option('height', '1000'));
const total = Number(option('total', '12000'));

mkdirSync(SHOTS, { recursive: true });
const name = `${pageName.replace(/\//g, '-')}-${width}-${theme}-${y}`;
const harness = join(SHOTS, `_${name}.html`);
const output = join(SHOTS, `${name}.png`);

writeFileSync(
  harness,
  `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;overflow:hidden;background:#888}` +
    `iframe{display:block;border:0;width:${width}px;height:${total}px;margin-top:-${y}px;` +
    // An embedded page takes its preferred colour scheme from the embedding element.
    `color-scheme:${theme === 'night' ? 'dark' : 'light'}}</style>` +
    `<iframe src="${origin}${page}"></iframe>`,
);

const result = spawnSync(
  CHROME,
  [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--no-first-run',
    '--force-device-scale-factor=1',
    `--user-data-dir=${join(SHOTS, '_profile')}`,
    `--window-size=${Math.max(width, 500)},${height}`,
    // Captures show the settled page: the one animation is drawn in its final state.
    '--force-prefers-reduced-motion',
    '--timeout=4000',
    `--screenshot=${output}`,
    pathToFileURL(harness).href,
  ],
  { encoding: 'utf8', timeout: 90_000 },
);
if (result.status !== 0) {
  console.error(result.stderr || result.error);
  process.exit(1);
}
console.log(output);
