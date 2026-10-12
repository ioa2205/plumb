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
import { render as installPage } from '../src/pages/install.mjs';
import { render as assessmentPage } from '../src/pages/web-assessment.mjs';
import { render as homePage } from '../src/pages/index.mjs';
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
  assert.equal(download.same_investigator_as_cpu_profile_run, false, 'the investigator has changed since the processor-only review');
  assert.ok(download.has_cpu_profile && download.has_calibrate_command && download.first_use_check_importable, `it has ${cpu.id} and its first-use check`);
  assert.ok(download.doctor_advises_on_models && download.setup_takes_model && download.knows_pattern_scanner, 'it has the model advice, --model and the pattern scanner');
  assert.equal(download.model_loaded, false, 'its checks loaded no model');
  assert.equal(download.downloaded_or_installed, false, 'its checks downloaded and installed nothing');
  assert.equal(download.clean_user_profile, false, 'a fresh Windows account was not tried');
  assert.equal(download.developer_tools_on_path, false);
  assert.equal(download.features.security_card_count, 3);
  assert.equal(download.features.security_card_license_present, true);
  assert.equal(download.features.baseline_default_preserved, true);
  assert.equal(download.features.website_missing_runner_refused, true);
  assert.equal(download.features.external_testing_enabled, false);
  assert.equal(download.features.external_scope_and_qualification_required, true);
  assert.equal(download.pinned_browser_checked, true);
  assert.equal(download.owned_website_completed, true);
  assert.equal(download.external_website_tested, false);
  assert.equal(download.model_planning_qualified, false);
  assert.equal(record.observation_comparison.acceptance_met, false);
  assert.equal(record.observation_comparison.completed_analyses_inconclusive, true);
  // It is no longer the investigator of the recorded test, file for file, and the pages must not say so.
  const since = download.since_recorded_test;
  assert.equal(since.same + since.changed.length + since.added.length, download.investigator_files);
  assert.ok(since.changed.length > 0 && since.added.includes('backend/cpu_profile.py'), 'the investigator changed after the recorded test');

  const text = (/** @type {string} */ path) => readFileSync(path, 'utf8').replace(/<[^>]+>/g, '');
  // Near the download, in both languages: no review with the model yet, and tried on one laptop only.
  for (const [page, noReview, oneLaptop] of [
    ['what-it-does/index.html', /has not yet run a review with the AI model/, /only been tried on the laptop it was built on/],
    ['install/index.html', /has not yet run a review with the AI model/, /A fresh Windows account and other computers have not been tested/],
    ['evidence/index.html', /this package has not run a review/, /A clean account and a second computer are untested/],
    ['uz/what-it-does/index.html', /SI modeli bilan hali birorta ham tekshiruv o‘tkazmagan/, /faqat o‘zi yig‘ilgan noutbukda sinab ko‘rilgan/],
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
      /investigator is the one that completed|investigator files are the ones that completed|tekshiruvchisi.+tekshiruvni bajargan kodning o‘zi|ta fayli faqat protsessorda o‘tkazilgan tekshiruvni bajargan fayllarning o‘zi/i,
      `${name(path)}: attributes an earlier model review to the current package`,
    );
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

test('the package page refuses changed safety defaults and inherited model acceptance', () => {
  const context = () => ({
    record: structuredClone(record), site,
    assets: { css: '/assets/site.css', js: '/assets/site.js' },
    themeColor: { day: '', night: '' },
  });
  assert.doesNotThrow(() => installPage(context()));
  const external = context();
  external.record.download.features.external_testing_enabled = true;
  assert.throws(() => installPage(external), /saved records do not/);
  const noBoundary = context();
  noBoundary.record.download.features.external_scope_and_qualification_required = false;
  assert.throws(() => installPage(noBoundary), /saved records do not/);
  const historical = context();
  historical.record.download.same_investigator_as_cpu_profile_run = true;
  assert.throws(() => installPage(historical), /saved records do not/);
  const claimed = context();
  claimed.record.observation_comparison.acceptance_met = true;
  assert.throws(() => installPage(claimed), /saved records do not/);
});

test('recorded local collection stays distinct from qualified and approved website tests', () => {
  const { collection, observation_comparison: comparison } = record;
  // What the records say.
  assert.equal(collection.external_access, false);
  assert.equal(collection.loopback_only, true);
  assert.equal(collection.human_review, 'pending');
  assert.equal(collection.imported, false);
  assert.equal(collection.model_loaded, false);
  assert.equal(collection.runtime_verification, 'not_attempted');
  assert.equal(collection.actions.length, collection.requests);
  assert.equal(comparison.acceptance_met, false);
  for (const condition of comparison.conditions) {
    assert.equal(condition.conclusion, 'inconclusive', `${condition.case} / ${condition.approach}`);
    assert.equal(condition.correct, false);
  }
  assert.equal(comparison.conditions.length + comparison.unrun, comparison.planned);

  const text = (/** @type {string} */ path) => readFileSync(join(DIST, path), 'utf8').replace(/<[^>]+>/g, '');
  // The older collection is local; the separate adapter still needs qualification and permission.
  for (const page of ['index.html', 'how-it-works/index.html', 'web-assessment/index.html', 'evidence/index.html']) {
    assert.match(text(page), /Testing another website requires a network boundary check on this computer and your approved scope and plan/, `${page}: qualification and scope are required`);
    assert.match(text(page), /No external website has been tested/, `${page}: no external acceptance claimed`);
    assert.match(text(`uz/${page}`), /Boshqa saytni sinash uchun shu kompyuterda tarmoq chegarasi tekshiruvi hamda siz tasdiqlagan qamrov va reja kerak/, `uz/${page}: qualification and scope are required`);
    assert.match(text(`uz/${page}`), /Tashqi sayt sinab ko‘rilmagan/, `uz/${page}: no external acceptance claimed`);
  }
  // The model's standing on this evidence is stated where the feature is introduced.
  assert.match(text('index.html'), /its AI model has not settled a case yet/);
  assert.match(text('uz/index.html'), /hali birorta holat bo‘yicha aniq xulosaga kelmagan/);
  assert.match(text('web-assessment/index.html'), /the AI model has not reached a verdict yet/);
  assert.match(text('uz/web-assessment/index.html'), /SI modeli hali aniq xulosaga kelmagan/);
  // An observation is never dressed as a source finding or a runtime check.
  for (const page of ['web-assessment/index.html', 'uz/web-assessment/index.html']) {
    assert.doesNotMatch(text(page), /Runtime check: reproduced|Jonli sinov: takrorlandi|from the source\b/i, `${page}: observation shown as another kind of evidence`);
  }

  // The request list is the recorded one: every row, in order, with the recorded status.
  const tidy = (/** @type {string} */ markup) => markup.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  const page = readFileSync(join(DIST, 'web-assessment/index.html'), 'utf8');
  const rows = [...page.matchAll(/<li class="tr is-\w+">([\s\S]*?)<\/li>/g)].map((match) => tidy(match[1]));
  assert.equal(rows.length, collection.actions.length, 'one row per recorded request');
  collection.actions.forEach((/** @type {any} */ action, /** @type {number} */ index) => {
    assert.ok(rows[index].includes(`${action.method} ${action.path}`), `row ${index + 1}: ${action.method} ${action.path}`);
    if (action.status) assert.ok(rows[index].includes(String(action.status)), `row ${index + 1}: status ${action.status}`);
  });
  const explained = readFileSync(join(DIST, 'how-it-works/index.html'), 'utf8');
  assert.equal([...explained.matchAll(/<li class="tr is-\w+">/g)].length, 3, 'the page on how it works shows three of the recorded rows');
});

test('the web-assessment page refuses a record that says more than was recorded', () => {
  const context = () => ({
    record: structuredClone(record), site,
    assets: { css: '/assets/site.css', js: '/assets/site.js' },
    themeColor: { day: '', night: '' },
  });
  assert.doesNotThrow(() => assessmentPage(context()));
  const external = context();
  external.record.collection.external_access = true;
  assert.throws(() => assessmentPage(external), /saved records do not/);
  const verdict = context();
  verdict.record.observation_comparison.conditions[1].conclusion = 'supported';
  assert.throws(() => assessmentPage(verdict), /saved records do not/);
  const reviewed = context();
  reviewed.record.collection.human_review = 'reviewed';
  assert.throws(() => assessmentPage(reviewed), /saved records do not/);
  const exported = context();
  exported.record.report_drafts.published = true;
  assert.throws(() => assessmentPage(exported), /saved records do not/);
});

test('the model list and the workbench pictures are shown as recorded', () => {
  const { console_records: consoles, workbench_views: views } = record;
  const text = (/** @type {string} */ path) =>
    readFileSync(join(DIST, path), 'utf8').replace(/<[^>]+>/g, '').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
  for (const page of ['install/index.html', 'uz/install/index.html']) {
    for (const line of consoles.models.lines) assert.ok(text(page).includes(line.trim()), `${page}: ${line.trim().slice(0, 50)}`);
  }
  // Only the default model has a recorded result; the others are untested and not installed.
  assert.equal(consoles.models.list[0].quality, 'recorded_scoped');
  for (const entry of consoles.models.list.slice(1)) {
    assert.equal(entry.quality, 'untested', entry.id);
    assert.equal(entry.installed, false, entry.id);
  }
  // The pictures are cut from captures made with stand-in content, and the pages say so.
  assert.equal(views.fresh_model_acceptance, false);
  assert.equal(views.signed_in_acceptance, false);
  for (const name of ['case', 'ask', 'assess']) {
    for (const theme of ['day', 'night']) assert.ok(existsSync(join(DIST, `shots/workbench-${name}-${theme}.webp`)), `workbench-${name}-${theme}.webp`);
  }
  assert.match(text('what-it-does/index.html'), /The answer text in this picture is a stand-in/);
  assert.match(text('uz/what-it-does/index.html'), /Bu rasmdagi javob matni namuna/);
  assert.match(text('what-it-does/index.html'), /a full walk-through in a signed-in browser has not been completed/);
});

test('the walk-through on the front page is drawn from the record and complete without scripts', () => {
  const { run, excerpts, sample } = record;
  const handler = excerpts.receipt_handler;
  for (const path of ['index.html', 'uz/index.html']) {
    const page = readFileSync(join(DIST, path), 'utf8');
    const chapters = [...page.matchAll(/<li class="chapter" data-chapter>([\s\S]*?)<\/li>\s*(?=<li class="chapter"|<\/ol>\s*<div class="film-rail")/g)].map((match) => match[1]);
    assert.equal(chapters.length, 4, `${path}: four chapters`);
    for (const chapter of chapters) {
      // Every caption is in the page itself, so the story is whole before any script runs.
      assert.equal([...chapter.matchAll(/<li>[^<]/g)].length, 3, `${path}: three captions per chapter`);
      assert.match(chapter, /<button type="button" class="chapter-go" data-film-go disabled>/, `${path}: chapter buttons wait for the script`);
      assert.match(chapter, /<div class="stage-box" aria-hidden="true">/, `${path}: the drawing is not read out twice`);
    }
    // The drawings carry recorded values, not typed ones.
    assert.equal([...page.matchAll(/<g class="s-judged"[\s\S]*?<\/g>/g)][0][0].match(/<circle/g)?.length, run.peer.compared, `${path}: one mark per compared place`);
    assert.equal([...page.matchAll(/<circle class="is-gap"/g)].length, 1, `${path}: one place stands out`);
    assert.ok(page.includes(`<span class="s-n">${handler.access.start}</span><code>${handler.lines[handler.access.start - handler.start].trim()}</code>`), `${path}: the cited line as recorded`);
    assert.ok(page.includes(sample.victim.customer.name) && page.includes(sample.victim.address), `${path}: the practice app’s own sample customer`);
    assert.ok(page.includes(`${handler.path}:${handler.access.start}`), `${path}: the report names the file and line`);
  }
  // The film refuses a record that no longer says what its drawings show.
  const context = () => ({
    record: structuredClone(record), site,
    assets: { css: '/assets/site.css', js: '/assets/site.js' },
    themeColor: { day: '', night: '' },
  });
  assert.doesNotThrow(() => homePage(context()));
  const guessed = context();
  guessed.record.run.findings[0].judgments[1].interpretation = 'scoped_elsewhere';
  assert.throws(() => homePage(guessed), /saved records do not/);
  const harmless = context();
  harmless.record.runtime.receipt.outcome = 'not_reproduced';
  assert.throws(() => homePage(harmless), /saved records do not/);
  const tested = context();
  tested.record.run.findings[0].runtime_verification = 'reproduced';
  assert.throws(() => homePage(tested), /saved records do not/);
});

test('the front page stays short, and what it used to carry lives on the deeper pages', () => {
  const words = (/** @type {string} */ path) => {
    const page = readFileSync(join(DIST, path), 'utf8');
    const main = page.slice(page.indexOf('<main'), page.indexOf('</main>'));
    // The drawings are pictures; what counts is what a visitor has to read.
    return main.replace(/<div class="stage-box"[\s\S]*?<\/div>\s*<\/li>/g, ' ').replace(/<svg[\s\S]*?<\/svg>/g, ' ').replace(/<[^>]+>/g, ' ').split(/\s+/).filter(Boolean).length;
  };
  // A newcomer reads the front page in about three minutes. Detail belongs behind it.
  assert.ok(words('index.html') <= 600, `the front page has ${words('index.html')} words`);
  assert.ok(words('uz/index.html') <= 600, `the Uzbek front page has ${words('uz/index.html')} words`);
  const text = (/** @type {string} */ path) => readFileSync(join(DIST, path), 'utf8').replace(/<[^>]+>/g, '');
  assert.match(text('how-it-works/index.html'), /How reading the code works, in four steps/);
  assert.match(text('how-it-works/index.html'), /Words used on this site/);
  assert.match(text('what-it-does/index.html'), /Everything Plumb can do today/);
  assert.match(text('what-it-does/index.html'), /Can I use it today\?/);
  // Each deeper page opens with its three-line summary, and the two recorded cases point at each other.
  for (const path of ['how-it-works', 'what-it-does', 'recorded-run', 'web-assessment', 'evidence', 'install']) {
    assert.equal([...readFileSync(join(DIST, path, 'index.html'), 'utf8').matchAll(/<div class="in-short">[\s\S]*?<\/ul>/g)].map((match) => match[0].match(/<li>/g)?.length)[0], 3, `${path}: three lines in short`);
  }
  assert.match(readFileSync(join(DIST, 'recorded-run/index.html'), 'utf8'), /<a href="\/web-assessment"/);
  assert.match(readFileSync(join(DIST, 'web-assessment/index.html'), 'utf8'), /<a href="\/recorded-run"/);
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
