// @ts-check
// Checks on the built site: that it says only what the saved records say, publishes nothing
// private, honours its own content-security policy, has no broken internal links, keeps its
// two languages in step, and passes messages on safely.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { before, beforeEach, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { LIMITS, compose, receive, resetLimits } from '../server/message.mjs';
import { escape, html, raw } from '../src/lib/html.mjs';
import { holds } from '../src/lib/holds.mjs';
import { AGENT_RULES, AGENT_RULES_FOR_FILE, guide } from '../src/lib/guide.mjs';
import { localPath, setLang, t } from '../src/lib/lang.mjs';
import { tone } from '../src/lib/tone.mjs';
import { build } from './build.mjs';
import { PRIVATE_PATTERNS, PRIVATE_WORDS_LOADED } from './private.mjs';

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(LANDING, 'dist');
const record = JSON.parse(readFileSync(join(LANDING, 'src/data/record.json'), 'utf8'));
const site = JSON.parse(readFileSync(join(LANDING, 'src/data/site.json'), 'utf8'));
const config = JSON.parse(readFileSync(join(LANDING, 'vercel.json'), 'utf8'));
const sha256 = (/** @type {string | Buffer} */ data) => createHash('sha256').update(data).digest('hex');

/** @param {string} directory @returns {string[]} */
function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

/** Pages written by this site, as opposed to the saved report published unchanged. */
const pages = () =>
  files(DIST).filter((path) => extname(path) === '.html' && !relative(DIST, path).startsWith('saved-report'));
const name = (/** @type {string} */ path) => relative(DIST, path).replace(/\\/g, '/');
const isUzbek = (/** @type {string} */ path) => name(path).startsWith('uz/');

/** @type {{ path: string, output: string, language: string, listed: boolean }[]} */
let built = [];

before(async () => {
  built = await build();
});

test('the committed data still matches the saved records', { skip: !existsSync(join(LANDING, '../docs/results')) }, () => {
  execFileSync(process.execPath, [join(LANDING, 'scripts/extract.mjs'), '--check'], { stdio: 'pipe' });
});

test('the published reports are the saved files, byte for byte', () => {
  for (const file of record.run.saved_reports) {
    const data = readFileSync(join(DIST, 'saved-report', file.name));
    assert.equal(sha256(data), file.sha256, file.name);
    assert.equal(data.length, file.bytes, file.name);
  }
});

test('quoted code hashes to the value the report cites', () => {
  for (const [key, excerpt] of Object.entries(record.excerpts)) {
    assert.equal(sha256(excerpt.lines.join('\n')), excerpt.sha256, key);
    assert.equal(excerpt.lines.length, excerpt.end - excerpt.start + 1, key);
  }
});

test('source conclusions and runtime labels stay separate in the record', () => {
  const [receipt, invoice] = record.run.findings;
  assert.equal(receipt.conclusion, 'supported');
  assert.equal(invoice.conclusion, 'rejected');
  for (const finding of record.run.findings) {
    assert.equal(finding.runtime_verification, 'not_attempted');
    assert.equal(finding.judgments.length, 3);
  }
  assert.equal(record.run.target_code_executed, false);
  assert.notEqual(record.runtime.replay.review_id, record.run.id);
});

test('the second profile is stated as one run on one laptop, done from source', () => {
  const cpu = record.cpu_profile;
  assert.equal(cpu.from_source, true, 'the one run was typed in a source checkout, not in the download');
  assert.equal(cpu.same_computer_as_recorded_run, true);
  assert.equal(cpu.first_use_check.outcome, 'passed');
  assert.deepEqual(cpu.review.findings.map((/** @type {any} */ finding) => finding.conclusion), ['supported', 'rejected']);
  // The record says its timings are not comparable, so none of them is extracted.
  assert.doesNotMatch(JSON.stringify(cpu), /elapsed|seconds/);

  const text = (/** @type {string} */ path) => readFileSync(path, 'utf8').replace(/<[^>]+>/g, '');
  const named = [...pages(), join(DIST, 'agent-install.md')].filter((path) => text(path).includes(cpu.id));
  assert.ok(named.length >= 9, 'the overview, both install pages and the limits page name the profile in both languages');
  for (const path of named) {
    // Wherever the profile is named, the same page says no other computer has been tried.
    assert.match(
      text(path),
      isUzbek(path) ? /kompyuterda (?:esa |hali hech narsa )?sinab ko‘rilmagan/ : /(?:not|Nothing has) been tried on (?:any other|a second) computer/,
      `${name(path)}: names ${cpu.id} without saying it is untried elsewhere`,
    );
    // The models have not been compared: no page may rank them.
    assert.doesNotMatch(text(path), /more accurate|finds more|better model|aniqroq model|yaxshiroq model/i, `${name(path)}: ranks the models`);
  }
  // The fixed label is Plumb's own, shown as recorded in both languages.
  for (const page of ['install/index.html', 'uz/install/index.html']) {
    assert.ok(text(join(DIST, page)).includes(record.other_models_label), `${page}: the label for other models`);
  }
});

test('the download is the package its saved checks describe, and is not said to have run a review', { skip: !site.download }, () => {
  const { download, cpu_profile: cpu } = record;
  // One package: the link, the name and the fingerprint on the page all belong to it.
  assert.ok(site.download.endsWith(`/${download.name}`), 'site.json links the package the records describe');
  const install = readFileSync(join(DIST, 'install/index.html'), 'utf8');
  assert.ok(install.includes(`href="${site.download}"`) && install.includes(download.archive_sha256), 'the install page links it and shows its whole fingerprint');

  // What its checks recorded: the same code as the source, and no model loaded.
  assert.equal(download.investigator_same_as_source, true, 'its investigator is the one in the source code');
  assert.equal(download.same_investigator_as_cpu_profile_run, true, 'and the one that completed the processor-only review');
  assert.ok(download.has_cpu_profile && download.has_calibrate_command && download.first_use_check_importable, `it has ${cpu.id} and its first-use check`);
  assert.ok(download.doctor_advises_on_models && download.setup_takes_model && download.knows_pattern_scanner, 'it has the model advice, --model and the pattern scanner');
  assert.equal(download.model_loaded, false, 'its checks loaded no model');
  assert.equal(download.downloaded_or_installed, false, 'its checks downloaded and installed nothing');
  assert.equal(download.clean_user_profile, false, 'a fresh Windows account was not tried');
  assert.equal(download.developer_tools_on_path, false);
  // It is no longer the investigator of the recorded test, file for file, and the pages must not say so.
  const since = download.since_recorded_test;
  assert.equal(since.same + since.changed.length + since.added.length, download.investigator_files);
  assert.ok(since.changed.length > 0 && since.added.includes('backend/cpu_profile.py'), 'the investigator changed after the recorded test');

  const text = (/** @type {string} */ path) => readFileSync(path, 'utf8').replace(/<[^>]+>/g, '');
  // Near the download, in both languages: no review with the model yet, and tried on one laptop only.
  for (const [page, noReview, oneLaptop] of [
    ['index.html', /has not yet run a review with the AI model/, /only been tried on the laptop it was built on/],
    ['install/index.html', /has not yet run a review with the AI model/, /A fresh Windows account and other computers have not been tested/],
    ['evidence/index.html', /this package has not run a review/, /A clean account and a second computer are untested/],
    ['uz/index.html', /SI modeli bilan hali birorta ham tekshiruv o‘tkazmagan/, /faqat o‘zi yig‘ilgan noutbukda sinab ko‘rilgan/],
    ['uz/install/index.html', /SI modeli bilan hali birorta ham tekshiruv o‘tkazmagan/, /Yangi Windows hisobi va boshqa kompyuterlarda sinab ko‘rilmagan/],
    ['uz/evidence/index.html', /bu to‘plam hali birorta ham tekshiruv o‘tkazmagan/, /Yangi hisobda va ikkinchi kompyuterda sinab ko‘rilmagan/],
  ]) {
    assert.match(text(join(DIST, /** @type {string} */ (page))), /** @type {RegExp} */ (noReview), `${page}: says the download has run no review`);
    assert.match(text(join(DIST, /** @type {string} */ (page))), /** @type {RegExp} */ (oneLaptop), `${page}: says where the download was tried`);
  }
  // Nothing still describes the earlier package, which was older than the source.
  for (const path of [...pages(), join(DIST, 'agent-install.md')]) {
    assert.doesNotMatch(
      text(path),
      /older than the source|download is older|not equal today|lacks one safety fix|only profile in the download|built before this fix|investigator from the recorded test/i,
      `${name(path)}: describes the earlier package`,
    );
    assert.doesNotMatch(
      text(path),
      /manba kodidan eskiroq|to‘plam eskiroq|teng emas|xavfsizlikka oid bitta tuzatish yo‘q|tuzatishdan oldin yig‘ilgan|sinovdagi tekshiruvchining o‘zi/i,
      `${name(path)}: describes the earlier package`,
    );
  }
});

test('the package steps are the source steps with the package’s own launcher', () => {
  const { steps, packageSteps } = guide(record, site);
  const text = (/** @type {string} */ path) =>
    readFileSync(join(DIST, path), 'utf8').replace(/<[^>]+>/g, '').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
  assert.deepEqual(packageSteps.map((step) => step.id), ['preview', 'install', 'inspect', 'doctor', 'calibrate', 'review', 'report']);
  for (const step of packageSteps) {
    const source = /** @type {import('../src/lib/guide.mjs').Step} */ (steps.find((entry) => entry.id === step.id));
    assert.equal(step.detail, source.detail, `${step.id}: said the same way`);
    const pairs = [...(step.commands ?? []), ...(step.otherCommands ?? [])].map((line, index) => [line, [...(source.commands ?? []), ...(source.otherCommands ?? [])][index]]);
    for (const [line, from] of pairs) {
      assert.match(line, /^\.\\plumb\.cmd /, `${step.id}: typed with the package launcher`);
      assert.equal(line.replace(/^\.\\plumb\.cmd /, '').replace('.\\app\\labs\\tandir', 'labs/tandir'), from.replace(/^uv run (?:--locked )?plumb /, ''), `${step.id}: the same command`);
      for (const page of ['install/index.html', 'uz/install/index.html']) assert.ok(text(page).includes(line), `${page}: ${line}`);
    }
  }
  // Plumb picks the profile for the computer it is on: no step names one. (The recorded
  // console, shown as recorded, still carries the option the recorded command had.)
  for (const step of [...steps, ...packageSteps]) {
    for (const line of [...(step.commands ?? []), ...(step.otherCommands ?? [])]) assert.doesNotMatch(line, /--profile/, `${step.id}: names a profile`);
  }
});

test('nothing private is published', () => {
  // The owner's name and contact details are public because the owner put them in
  // site.json. They may appear exactly as written there and nowhere else.
  const chosen = [site.author, site.repository, site.download, ...site.contact.flatMap((/** @type {any} */ entry) => [entry.href, entry.value])]
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);
  // The owner's own words come from landing/.private-words, which is never committed.
  if (!PRIVATE_WORDS_LOADED) console.log('note: landing/.private-words not found; checking the general patterns only');
  const forbidden = PRIVATE_PATTERNS;
  for (const path of files(DIST).filter((file) => !/\.(woff2|png|webp)$/.test(file))) {
    const content = chosen.reduce((text, value) => text.split(value).join(''), readFileSync(path, 'utf8'));
    for (const pattern of forbidden) {
      assert.doesNotMatch(content, pattern, `${name(path)} matches ${pattern}`);
    }
  }
  // The records themselves never carry them.
  for (const pattern of forbidden) assert.doesNotMatch(JSON.stringify(record), pattern);
});

test('pages need no inline style or script, and load nothing from other servers', () => {
  for (const path of pages()) {
    const page = readFileSync(path, 'utf8');
    assert.doesNotMatch(page, /\sstyle="/, `${name(path)}: inline style attribute`);
    assert.doesNotMatch(page, /<style[\s>]/, `${name(path)}: inline stylesheet`);
    assert.doesNotMatch(page, /<script(?![^>]*\ssrc=)[^>]*>/, `${name(path)}: inline script`);
    assert.doesNotMatch(page, /\son[a-z]+="/, `${name(path)}: inline event handler`);
    for (const [, tag, url] of page.matchAll(/<(\w+)[^>]*\s(?:src|href|action)="(https?:[^"]+)"/g)) {
      assert.ok(tag === 'a' || (tag === 'link' && site.url && url.startsWith(site.url)), `${name(path)}: <${tag}> loads ${url}`);
    }
  }
});

test('the policy lets the form reach this site and nothing else', () => {
  const policy = config.headers
    .flatMap((/** @type {any} */ rule) => rule.headers)
    .filter((/** @type {any} */ header) => header.key === 'Content-Security-Policy')
    .map((/** @type {any} */ header) => header.value);
  const [pagesPolicy] = policy;
  assert.match(pagesPolicy, /default-src 'none'/);
  assert.match(pagesPolicy, /connect-src 'self'(;|$)/);
  assert.match(pagesPolicy, /form-action 'self'(;|$)/);
  for (const value of policy) assert.doesNotMatch(value, /https?:|\*/, 'no other origin is allowed');
  const contact = readFileSync(join(DIST, 'contact/index.html'), 'utf8');
  assert.match(contact, /<form[^>]*method="post"[^>]*action="\/api\/message"/);
});

test('every page has one heading, a title, a description and its language', () => {
  for (const path of pages()) {
    const page = readFileSync(path, 'utf8');
    assert.equal((page.match(/<h1[\s>]/g) ?? []).length, 1, `${name(path)}: h1 count`);
    assert.match(page, /<title>[^<]{10,}<\/title>/, `${name(path)}: title`);
    assert.match(page, /<meta name="description" content="[^"]{50,}">/, `${name(path)}: description`);
    assert.match(page, new RegExp(`<html lang="${isUzbek(path) ? 'uz' : 'en'}">`), `${name(path)}: language`);
    assert.doesNotMatch(page, /\bundefined\b|\bNaN\b|\[object Object\]/, `${name(path)}: unrendered value`);
  }
});

test('the two languages have the same pages and stay inside their own language', () => {
  const english = built.filter((entry) => entry.language === 'en' && entry.path !== '/404').map((entry) => entry.path);
  const uzbek = built.filter((entry) => entry.language === 'uz').map((entry) => entry.path);
  assert.deepEqual(uzbek, english.map((path) => localPath(path, 'uz')));

  for (const path of pages().filter(isUzbek)) {
    const page = readFileSync(path, 'utf8');
    // Uzbek spelling uses ‘ and ’. A straight apostrophe inside a word is a typing slip.
    const text = page.replace(/<pre[\s\S]*?<\/pre>|<[^>]+>|lang="en">[\s\S]*?<\//g, ' ');
    assert.doesNotMatch(text, /[a-z](?:'|&#39;)[a-z]/i, `${name(path)}: straight apostrophe in Uzbek text`);
    for (const [tag, href] of [...page.matchAll(/<a\b[^>]*\shref="(\/[^"]*)"/g)].map((match) => [match[0], match[1]])) {
      if (tag.includes('hreflang=')) continue;
      const root = href.split(/[#?]/)[0].split('/')[1] ?? '';
      const shared = ['fonts', 'saved-report', 'assets'].includes(root);
      assert.ok(shared || root === 'uz', `${name(path)}: links out of Uzbek to ${href}`);
    }
    // The same record feeds both, so the same sections must exist in both.
    const twin = readFileSync(join(DIST, name(path).slice(3)), 'utf8');
    const ids = (/** @type {string} */ markup) => [...markup.matchAll(/\sid="([a-z][\w-]*)"/g)].map((match) => match[1]).filter((id) => !id.startsWith('cmd-'));
    assert.deepEqual(ids(page), ids(twin), `${name(path)}: sections differ from the English page`);
  }
});

test('every page offers both languages and the day/night switch', () => {
  for (const path of pages()) {
    const page = readFileSync(path, 'utf8');
    assert.match(page, /<details class="lang" data-lang-menu>/, `${name(path)}: language menu`);
    for (const language of ['en', 'uz']) {
      assert.match(page, new RegExp(`<a hreflang="${language}" lang="${language}" href="[^"]+"`), `${name(path)}: ${language} link`);
    }
    assert.match(page, /<button class="theme-switch" type="button" role="switch" aria-checked="false" data-theme-switch/, `${name(path)}: theme switch`);
  }
});

test('the agent instructions carry the same rules and commands as the pages', () => {
  const file = readFileSync(join(DIST, 'agent-install.md'), 'utf8');
  const text = (/** @type {string} */ path) =>
    readFileSync(join(DIST, path), 'utf8').replace(/<[^>]+>/g, '').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
  const install = text('install/index.html');
  const agentPage = text('install/agent/index.html');
  for (const rule of AGENT_RULES_FOR_FILE) assert.ok(file.includes(rule), `file rule: ${rule}`);
  for (const rule of AGENT_RULES) assert.ok(agentPage.includes(rule), `message rule: ${rule}`);
  for (const command of [
    'uv sync --locked',
    'uv run --locked plumb setup',
    'uv run --locked plumb setup --install --inspect-only',
    'uv run --locked plumb setup --install --approve-large-downloads',
    'uv run plumb inspect labs/tandir',
    'uv run plumb doctor',
  ]) {
    assert.ok(file.includes(command), `file: ${command}`);
    assert.ok(install.includes(command), `install page: ${command}`);
    assert.ok(agentPage.includes(command), `agent page: ${command}`);
  }
  assert.doesNotMatch(file, /o‘|g‘|’ning\b/, 'the file is in English');
  assert.match(text('uz/install/agent/index.html'), /Explain everything to me in Uzbek\./);
  assert.doesNotMatch(agentPage, /Explain everything to me in Uzbek\./);
});

test('wording must exist in both languages', () => {
  setLang('uz');
  assert.equal(t('yes', 'ha'), 'ha');
  assert.throws(() => t('yes', /** @type {any} */ (undefined)), /missing Uzbek/);
  setLang('en');
  assert.equal(t('yes', 'ha'), 'yes');
});

test('internal links and fragments resolve', () => {
  /** @param {string} path site path @returns {string | null} */
  const target = (path) => {
    const direct = join(DIST, path);
    if (existsSync(direct) && statSync(direct).isFile()) return direct;
    const index = join(DIST, path, 'index.html');
    return existsSync(index) ? index : null;
  };
  for (const path of pages()) {
    const page = readFileSync(path, 'utf8');
    for (const [, href] of page.matchAll(/\s(?:href|src)="(\/[^"]*)"/g)) {
      const [pathname, fragment] = href.split('?')[0].split('#');
      const file = target(pathname);
      assert.ok(file, `${name(path)} links to missing ${href}`);
      if (fragment) {
        assert.match(readFileSync(file, 'utf8'), new RegExp(`\\sid="${fragment}"`), `${href}: no such fragment`);
      }
    }
  }
});

test('colour literals live only in the generated tokens', () => {
  const css = readFileSync(join(LANDING, 'src/styles/site.css'), 'utf8');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/);
  for (const path of files(join(LANDING, 'src')).filter((file) => file.endsWith('.mjs'))) {
    assert.doesNotMatch(readFileSync(path, 'utf8'), /#[0-9a-fA-F]{6}\b/, relative(LANDING, path));
  }
});

test('recorded text can only appear as text', () => {
  assert.equal(html`<p>${'<script>alert(1)</script>'}</p>`.toString(), '<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>');
  assert.equal(html`${raw('<b>')}${['<', html`<i>`]}`.toString(), '<b>&lt;<i>');
  assert.equal(escape(`"'&`), '&quot;&#39;&amp;');
  assert.equal(tone('    return "<x>"').toString(), '    <span class="k">return</span> <span class="s">&quot;&lt;x&gt;&quot;</span>');
});

test('prose that contradicts the record stops the build', () => {
  assert.throws(() => holds(false, 'the moon is cheese'), /saved records do not/);
  assert.doesNotThrow(() => holds(true, 'anything'));
});

test('a release build refuses to publish without contact details and a public address', async () => {
  const ready = site.contact.length > 0 && site.author && /^https:\/\//.test(site.url);
  if (ready) {
    await assert.doesNotReject(build({ release: true }));
  } else {
    await assert.rejects(build({ release: true }), /release build/);
  }
  await build();
});

// ---------- the message endpoint ----------

const env = { TELEGRAM_BOT_TOKEN: '123:test-token', TELEGRAM_CHAT_ID: '42' };
const json = { 'content-type': 'application/json', host: 'plumb.example', origin: 'https://plumb.example', 'x-forwarded-for': '203.0.113.7' };
const good = { message: 'Does Plumb read TypeScript too?', name: 'Dilnoza', reply: 'dilnoza@example.org', lang: 'en', website: '' };

/** A stand-in for Telegram that records what it was sent. */
function telegram(ok = true) {
  /** @type {{ url: string, body: any }[]} */
  const calls = [];
  const send = /** @type {typeof fetch} */ (async (url, options) => {
    calls.push({ url: String(url), body: JSON.parse(String(options?.body)) });
    return /** @type {Response} */ ({ ok });
  });
  return { calls, send };
}

beforeEach(() => resetLimits());

test('a message is passed on once, as plain text, to the owner only', async () => {
  const { calls, send } = telegram();
  const result = await receive({ method: 'POST', headers: json, fields: good, env, send });
  assert.equal(result.status, 200);
  assert.deepEqual(JSON.parse(result.body), { ok: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://api.telegram.org/bot123:test-token/sendMessage');
  assert.equal(calls[0].body.chat_id, '42');
  assert.equal(calls[0].body.parse_mode, undefined, 'nothing a sender types is treated as formatting');
  assert.equal(calls[0].body.text, compose({ message: good.message, name: good.name, reply: good.reply, language: 'en' }));
  assert.doesNotMatch(result.body + JSON.stringify(result.headers), /test-token|"42"/, 'credentials never leave');
});

test('messages that are too short, too long or malformed are refused before anything is sent', async () => {
  const { calls, send } = telegram();
  const attempt = (/** @type {unknown} */ fields) => receive({ method: 'POST', headers: json, fields, env, send });
  for (const fields of [
    { ...good, message: 'short' },
    { ...good, message: 'x'.repeat(LIMITS.messageMax + 1) },
    { ...good, name: 'n'.repeat(LIMITS.name + 1) },
    { ...good, reply: 'r'.repeat(LIMITS.reply + 1) },
    { ...good, message: 42 },
    { name: 'no message' },
    undefined,
    'a string body',
  ]) {
    const result = await attempt(fields);
    assert.equal(result.status, 400);
    assert.equal(JSON.parse(result.body).error, 'invalid');
  }
  assert.equal(calls.length, 0);
});

test('other methods, other content types and other sites are refused', async () => {
  const { calls, send } = telegram();
  assert.equal((await receive({ method: 'GET', headers: json, fields: good, env, send })).status, 405);
  assert.equal((await receive({ method: 'POST', headers: { ...json, 'content-type': 'text/plain' }, fields: good, env, send })).status, 415);
  assert.equal((await receive({ method: 'POST', headers: { ...json, origin: 'https://elsewhere.example' }, fields: good, env, send })).status, 403);
  assert.equal((await receive({ method: 'POST', headers: { ...json, origin: 'not a url' }, fields: good, env, send })).status, 403);
  const crossSite = { 'content-type': 'application/json', host: 'plumb.example', 'sec-fetch-site': 'cross-site' };
  assert.equal((await receive({ method: 'POST', headers: crossSite, fields: good, env, send })).status, 403);
  assert.equal(calls.length, 0);
});

test('a filled hidden field is answered politely and sent nowhere', async () => {
  const { calls, send } = telegram();
  const result = await receive({ method: 'POST', headers: json, fields: { ...good, website: 'https://spam.example' }, env, send });
  assert.deepEqual(JSON.parse(result.body), { ok: true });
  assert.equal(calls.length, 0);
});

test('one sender is slowed down, and the brake eases with time', async () => {
  const { calls, send } = telegram();
  const at = (/** @type {number} */ now) => receive({ method: 'POST', headers: json, fields: good, env, send, now });
  for (let index = 0; index < 3; index += 1) assert.equal((await at(1000 + index)).status, 200);
  const fourth = await at(2000);
  assert.equal(fourth.status, 429);
  assert.equal(JSON.parse(fourth.body).error, 'rate_limited');
  assert.equal(calls.length, 3);
  assert.equal((await at(2000 + 11 * 60 * 1000)).status, 200);
});

test('without credentials the endpoint says so, and a failed delivery is reported as failed', async () => {
  const { calls, send } = telegram();
  const missing = await receive({ method: 'POST', headers: json, fields: good, env: {}, send });
  assert.equal(missing.status, 503);
  assert.equal(JSON.parse(missing.body).error, 'not_configured');
  const preview = await receive({ method: 'POST', headers: json, fields: good, env: {}, send, preview: true });
  assert.deepEqual(JSON.parse(preview.body), { ok: true, preview: true });
  assert.equal(calls.length, 0);

  resetLimits();
  const refused = await receive({ method: 'POST', headers: json, fields: good, env, send: telegram(false).send });
  assert.equal(refused.status, 502);
  const broken = /** @type {typeof fetch} */ (async () => {
    throw new Error('network down: https://api.telegram.org/bot123:test-token/sendMessage');
  });
  const failed = await receive({ method: 'POST', headers: json, fields: good, env, send: broken });
  assert.equal(failed.status, 502);
  assert.doesNotMatch(failed.body, /test-token/);
});

test('without scripts the form is sent on to a page in the reader’s language', async () => {
  const { send } = telegram();
  const form = { ...json, 'content-type': 'application/x-www-form-urlencoded; charset=UTF-8' };
  const sent = await receive({ method: 'POST', headers: form, fields: { ...good, lang: 'uz' }, env, send });
  assert.equal(sent.status, 303);
  assert.equal(sent.headers.Location, '/uz/contact/sent');
  const failed = await receive({ method: 'POST', headers: form, fields: { ...good, message: 'no' }, env, send });
  assert.equal(failed.headers.Location, '/contact/not-sent');
  for (const location of ['/uz/contact/sent', '/contact/not-sent', '/contact/sent', '/uz/contact/not-sent']) {
    assert.ok(existsSync(join(DIST, location, 'index.html')), `${location} exists`);
  }
});

test('control characters and line breaks cannot forge the header of a message', async () => {
  const { calls, send } = telegram();
  await receive({ method: 'POST', headers: json, fields: { ...good, name: 'Eve\nReply to: someone else', message: 'First line\r\nsecond line\u0000 here' }, env, send });
  const [header, from] = calls[0].body.text.split('\n');
  assert.equal(header, 'Plumb site: new message');
  assert.equal(from, 'From: Eve Reply to: someone else');
  assert.ok(calls[0].body.text.endsWith('First line\nsecond line here'));
});
