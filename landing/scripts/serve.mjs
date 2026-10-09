// @ts-check
// Serves dist/ on the loopback interface the way the deployment will: same response
// headers (read from vercel.json), directory indexes without trailing slashes, and the
// 404 page. For local preview only.
//
//   node scripts/serve.mjs [--port 4173] [--allow-framing]
//
// The contact form posts to /api/message, handled here by the same code as the deployment.
// Without TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment a message is accepted
// and not sent on, and the page says so.
//
// --allow-framing drops the two headers that forbid embedding, so a narrow <iframe> can be
// used to inspect phone layouts. Never needed outside local checks.

import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { receive } from '../server/message.mjs';

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(LANDING, 'dist');
const HOST = '127.0.0.1';

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.sarif': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
};

const argument = (/** @type {string} */ name) => {
  const index = process.argv.indexOf(name);
  return index > 0 ? process.argv[index + 1] : undefined;
};
const port = Number(argument('--port') ?? 4173);
const allowFraming = process.argv.includes('--allow-framing');

const config = JSON.parse(readFileSync(join(LANDING, 'vercel.json'), 'utf8'));
const rules = config.headers.map((/** @type {any} */ rule) => ({
  pattern: new RegExp(`^${rule.source}$`),
  headers: rule.headers,
}));

/** @param {string} pathname */
function headersFor(pathname) {
  /** @type {Record<string, string>} */
  const headers = {};
  for (const rule of rules) {
    if (!rule.pattern.test(pathname)) continue;
    for (const { key, value } of rule.headers) headers[key] = value;
  }
  if (allowFraming) {
    delete headers['X-Frame-Options'];
    if (headers['Content-Security-Policy']) {
      headers['Content-Security-Policy'] = headers['Content-Security-Policy'].replace(/;?\s*frame-ancestors [^;]+/, '');
    }
  }
  return headers;
}

/** @param {string} pathname @returns {string | null} a file inside dist, or null */
function fileFor(pathname) {
  const target = normalize(join(DIST, decodeURIComponent(pathname)));
  if (target !== DIST && !target.startsWith(DIST + sep)) return null;
  if (existsSync(target) && statSync(target).isFile()) return target;
  const index = join(target, 'index.html');
  return existsSync(index) ? index : null;
}

/** The contact form's endpoint, with the body read and parsed the way the host does it. */
async function message(/** @type {import('node:http').IncomingMessage} */ request, /** @type {import('node:http').ServerResponse} */ response) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 16384) {
      response.writeHead(413).end();
      return;
    }
    chunks.push(chunk);
  }
  const body = Buffer.concat(chunks).toString('utf8');
  const type = String(request.headers['content-type'] ?? '').split(';')[0].trim();
  let fields;
  try {
    fields = type === 'application/json' ? JSON.parse(body) : Object.fromEntries(new URLSearchParams(body));
  } catch {
    fields = undefined;
  }
  const result = await receive({ method: request.method ?? 'GET', headers: request.headers, fields, env: process.env, preview: true });
  if (result.body.includes('"preview":true')) console.log('Contact form: a message arrived and was not sent on (no Telegram credentials in this preview).');
  response.writeHead(result.status, { ...headersFor('/api/message'), ...result.headers });
  response.end(result.body);
}

const server = createServer((request, response) => {
  const { pathname } = new URL(request.url ?? '/', `http://${HOST}`);
  if (pathname === '/api/message') {
    message(request, response).catch(() => response.writeHead(500).end());
    return;
  }
  if (pathname.length > 1 && pathname.endsWith('/')) {
    response.writeHead(308, { Location: pathname.slice(0, -1) });
    response.end();
    return;
  }
  const file = fileFor(pathname);
  const served = file ?? join(DIST, '404.html');
  response.writeHead(file ? 200 : 404, {
    'Content-Type': TYPES[/** @type {keyof typeof TYPES} */ (extname(served))] ?? 'application/octet-stream',
    ...headersFor(pathname),
  });
  createReadStream(served).pipe(response);
});

server.listen(port, HOST, () => {
  console.log(`Plumb landing preview: http://${HOST}:${port}/${allowFraming ? '  (framing allowed)' : ''}`);
});
