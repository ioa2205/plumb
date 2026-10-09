// @ts-check
// Pictures of the saved report, taken from the report itself, for the pages that show what
// Plumb's output looks like. The report is published unchanged under /saved-report/; these
// are captures of that file in both themes, never a mock-up.
//
//   node scripts/serve.mjs                  (in another terminal)
//   node scripts/report-images.mjs          writes public/shots/report-*.webp
//
// Needs Google Chrome. Run it again whenever the saved report changes.

import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(LANDING, 'public/shots');
const ORIGIN = process.env.PLUMB_PREVIEW ?? 'http://127.0.0.1:4173';
const CHROME = process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9336;
const WIDTH = 1180;

const wait = (/** @type {number} */ ms) => new Promise((done) => setTimeout(done, ms));
const profile = mkdtempSync(join(tmpdir(), 'plumb-report-images-'));
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });

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
  const evaluate = async (/** @type {string} */ expression) =>
    (await call('Runtime.evaluate', { expression, returnByValue: true })).result.result.value;

  await call('Page.enable');
  mkdirSync(OUT, { recursive: true });
  for (const [theme, scheme] of [['day', 'light'], ['night', 'dark']]) {
    await call('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: 900, deviceScaleFactor: 1, mobile: false });
    await call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
    await call('Page.navigate', { url: `${ORIGIN}/saved-report/report.html` });
    await wait(1200);
    // The summary: title, verdict counts, the findings list and the reviewed scope.
    // The first finding: its status, what Plumb looked for, and the proof it does not have.
    const regions = await evaluate(`(() => {
      const box = (element) => { const r = element.getBoundingClientRect(); return { top: r.top + scrollY, bottom: r.bottom + scrollY, left: r.left, right: r.right }; };
      const card = (element) => element.closest('section, article, header, div');
      const title = box(card(document.querySelector('h1')));
      const scope = box(document.querySelector('#scope'));
      const heading = [...document.querySelectorAll('h2')].find((h) => h.textContent.trim() === 'Order access: owner check');
      const finding = box(heading.closest('article, section'));
      const proof = [...document.querySelectorAll('h3')].find((h) => h.textContent.trim() === 'Proof');
      const proofEnd = box(proof.closest('section')).bottom;
      return {
        summary: { x: title.left - 16, y: title.top - 16, width: title.right - title.left + 32, height: scope.bottom - title.top + 32 },
        finding: { x: finding.left - 16, y: finding.top - 16, width: finding.right - finding.left + 32, height: proofEnd - finding.top + 40 },
      };
    })()`);
    for (const [name, clip] of Object.entries(regions)) {
      const rounded = Object.fromEntries(Object.entries(clip).map(([key, value]) => [key, Math.round(/** @type {number} */ (value))]));
      const shot = await call('Page.captureScreenshot', { format: 'webp', quality: 84, captureBeyondViewport: true, clip: { ...rounded, scale: 1 } });
      const file = join(OUT, `report-${name}-${theme}.webp`);
      writeFileSync(file, Buffer.from(shot.result.data, 'base64'));
      console.log(`${file.slice(LANDING.length + 1)}  ${rounded.width}x${rounded.height}`);
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
