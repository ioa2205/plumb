// @ts-check
// Builds the static site into dist/. No dependencies and no network: pages are plain
// modules in src/pages that turn the extracted record into HTML.
//
//   node scripts/build.mjs             build for preview
//   node scripts/build.mjs --release   also require what a public deployment needs

import { createHash } from 'node:crypto';
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { agentFile } from '../src/lib/guide.mjs';
import { LANGS, localPath, setLang } from '../src/lib/lang.mjs';

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(LANDING, 'src');
const DIST = join(LANDING, 'dist');

const read = (/** @type {string} */ path) => readFileSync(join(SRC, path), 'utf8');
const version = (/** @type {string} */ content) =>
  createHash('sha256').update(content).digest('hex').slice(0, 10);

/** @param {string} path site path such as "/contact" @param {string} content */
function write(path, content) {
  const target = join(DIST, path);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, content);
}

export async function build({ release = false } = {}) {
  const record = JSON.parse(read('data/record.json'));
  const site = JSON.parse(read('data/site.json'));
  site.url = site.url.replace(/\/$/, '');

  if (release) {
    // A public deployment must not ship an empty contact page or relative social links.
    if (site.contact.length === 0) throw new Error('release build: src/data/site.json has no contact details');
    if (!site.author) throw new Error('release build: src/data/site.json has no author');
    if (!/^https:\/\//.test(site.url)) throw new Error('release build: src/data/site.json needs the public https URL');
  }

  rmSync(DIST, { recursive: true, force: true });
  cpSync(join(LANDING, 'public'), DIST, { recursive: true });

  const tokens = read('styles/tokens.css');
  const css = `${tokens}\n${read('styles/site.css')}`;
  const js = read('scripts/site.js');
  write('assets/site.css', css);
  write('assets/site.js', js);

  const desk = [...tokens.matchAll(/--desk: (#[0-9A-Fa-f]{6});/g)].map((match) => match[1]);
  /** @type {import('../src/components/layout.mjs').PageContext} */
  const context = {
    record,
    site,
    assets: { css: `/assets/site.css?v=${version(css)}`, js: `/assets/site.js?v=${version(js)}` },
    themeColor: { day: desk[0], night: desk[1] },
  };

  const modules = [];
  for (const file of readdirSync(join(SRC, 'pages')).filter((name) => name.endsWith('.mjs')).sort()) {
    modules.push(await import(pathToFileURL(join(SRC, 'pages', file)).href));
  }

  // Every page is rendered once per language. The 404 page answers for both and is written once.
  const pages = [];
  for (const language of LANGS) {
    setLang(language);
    for (const module of modules) {
      if (module.path === '/404' && language !== 'en') continue;
      const local = localPath(module.path, language);
      const output = module.path === '/404' ? '404.html' : local === '/' ? 'index.html' : `${local.slice(1)}/index.html`;
      write(output, module.render(context).toString());
      pages.push({ path: local, output, language, listed: module.listed !== false });
    }
  }
  setLang('en');
  // Plain instructions for AI coding agents, in English, linked from the agent page.
  write('agent-install.md', agentFile(record, site));

  const listed = pages.filter((entry) => entry.listed).map((entry) => entry.path);
  write('robots.txt', `User-agent: *\nAllow: /\n${site.url ? `Sitemap: ${site.url}/sitemap.xml\n` : ''}`);
  if (site.url) {
    const urls = listed.map((path) => `  <url><loc>${site.url}${path === '/' ? '/' : path}</loc></url>`).join('\n');
    write('sitemap.xml', `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`);
  }
  return pages;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const pages = await build({ release: process.argv.includes('--release') });
  console.log(`Built ${pages.length} pages into dist/: ${pages.map((entry) => entry.path).join(' ')}`);
}
