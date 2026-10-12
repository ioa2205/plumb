// @ts-check
// Pictures of Plumb's browser workbench, cut from the captures its own view check makes.
// They show the real screens with the check's display fixtures loaded: a saved run replayed,
// and stand-in conversation answers that the screens themselves label as synthetic. Nothing
// is drawn or retouched here; each picture is a region of one capture.
//
//   pnpm --dir frontend build && node frontend/scripts/assessment-ui-images.mjs   (makes the captures)
//   node landing/scripts/workbench-images.mjs                                     (writes public/shots/workbench-*.webp)
//
// Needs Google Chrome. The captures must be the ones the saved check describes: their sizes
// are compared with docs/results/2026-10-11-improvements-ui-checks.json before anything is cut.

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO = resolve(LANDING, '..');
const CAPTURES = join(REPO, 'tmp/improvements-ui-shots');
const OUT = join(LANDING, 'public/shots');
const CHROME = process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9337;

/** Which region of which capture becomes which picture. All captures are 1440 px wide. */
export const REGIONS = [
  { name: 'case', screen: 'saved-followup', x: 0, y: 0, width: 1440, height: 1000 },
  { name: 'ask', screen: 'source-prompt', x: 236, y: 1524, width: 1056, height: 1062 },
  { name: 'assess', screen: 'website-url', x: 236, y: 162, width: 1056, height: 1300 },
];

const wait = (/** @type {number} */ ms) => new Promise((done) => setTimeout(done, ms));

async function main() {
  const check = JSON.parse(readFileSync(join(REPO, 'docs/results/2026-10-11-improvements-ui-checks.json'), 'utf8'));
  if (check.passed !== true) throw new Error('the saved workbench view check did not pass');

  const profile = mkdtempSync(join(tmpdir(), 'plumb-workbench-images-'));
  const harness = join(profile, 'crop.html');
  const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars', '--allow-file-access-from-files', `--remote-debugging-port=${PORT}`, `--user-data-dir=${join(profile, 'chrome')}`, 'about:blank'], { stdio: 'ignore' });
  try {
    /** @type {any} */
    let target;
    for (let attempt = 0; attempt < 60 && !target; attempt += 1) {
      await wait(250);
      try {
        target = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find((/** @type {any} */ entry) => entry.type === 'page');
      } catch {}
    }
    if (!target) throw new Error('Chrome did not start');
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((done) => socket.addEventListener('open', done));
    let id = 0;
    const pending = new Map();
    socket.addEventListener('message', (event) => {
      const data = JSON.parse(String(event.data));
      if (data.id && pending.has(data.id)) pending.get(data.id)(data);
    });
    const call = (/** @type {string} */ method, params = {}) =>
      new Promise((/** @type {(value: any) => void} */ done) => {
        id += 1;
        pending.set(id, done);
        socket.send(JSON.stringify({ id, method, params }));
      });

    await call('Page.enable');
    await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    mkdirSync(OUT, { recursive: true });
    for (const region of REGIONS) {
      for (const theme of ['day', 'night']) {
        const file = `${region.screen}-1440-${theme}.png`;
        const source = join(CAPTURES, file);
        if (!existsSync(source)) throw new Error(`${file} is missing; make the captures first (see the top of this file)`);
        const sample = check.samples.find((/** @type {any} */ entry) => entry.file === file);
        if (!sample) throw new Error(`${file} is not in the saved check`);
        writeFileSync(harness, `<!doctype html><meta charset="utf-8"><body style="margin:0"><img style="display:block" src="${pathToFileURL(source).href}">`);
        await call('Page.navigate', { url: pathToFileURL(harness).href });
        await wait(900);
        const size = (await call('Runtime.evaluate', { expression: 'JSON.stringify([document.images[0].naturalWidth, document.images[0].naturalHeight])', returnByValue: true })).result.result.value;
        const [width, height] = JSON.parse(size);
        if (width !== sample.width || height !== sample.height) throw new Error(`${file} is ${width}x${height}; the saved check recorded ${sample.width}x${sample.height}`);
        const reply = await call('Page.captureScreenshot', {
          format: 'webp',
          quality: 84,
          captureBeyondViewport: true,
          clip: { x: region.x, y: region.y, width: region.width, height: region.height, scale: 1 },
        });
        const output = join(OUT, `workbench-${region.name}-${theme}.webp`);
        writeFileSync(output, Buffer.from(reply.result.data, 'base64'));
        console.log(`${output} (${region.width}x${region.height} of ${file})`);
      }
    }
    socket.close();
  } finally {
    chrome.kill();
    await wait(500);
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {}
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
