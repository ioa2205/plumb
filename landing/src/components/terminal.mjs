// @ts-check
// What Plumb printed in the terminal during the recorded review, line by line. Runs of
// identical lines are shown once with a count, and a few long stretches are left out with a
// note saying how many lines went and what they were. Counts, notes and numbered markers are
// set in the page's own face, so they never read as output.

import { DATA_FOLDER } from '../../scripts/extract.mjs';
import { commandLine, day } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { lang, t } from '../lib/lang.mjs';

/** A recorded line, with the laptop's data folder shown as a labelled placeholder. */
function recorded(/** @type {string} */ line) {
  const parts = line.split(DATA_FOLDER);
  return parts.map(
    (part, index) =>
      html`${index ? html`<span class="ph" lang="${lang()}" title="${t('The laptop’s data folder, left out', 'Noutbukdagi ma’lumotlar papkasi yo‘li ko‘rsatilmagan')}">${t('data folder', 'ma’lumotlar papkasi')}</span>` : ''}${part}`,
  );
}

/**
 * @param {object} options
 * @param {string} options.title
 * @param {string} options.command what was typed
 * @param {string[]} options.lines what was printed
 * @param {{ from: number, to: number, note: string }[]} [options.cuts] inclusive ranges left out
 * @param {Record<number, number>} [options.markers] line index -> marker number
 */
export function terminal({ title, command, lines, cuts = [], markers = {} }) {
  /** @type {unknown[]} */
  const rows = [];
  let index = 0;
  while (index < lines.length) {
    const cut = cuts.find((entry) => entry.from === index);
    if (cut) {
      const count = cut.to - cut.from + 1;
      rows.push(html`<span class="tl cut" lang="${lang()}"><span class="tk"></span><span class="tt">${t(`… ${count} lines left out: ${cut.note}`, `… ${count} qator tushirib qoldirilgan: ${cut.note}`)}</span></span>`);
      index = cut.to + 1;
      continue;
    }
    let run = 1;
    while (index + run < lines.length && lines[index + run] === lines[index] && !Object.hasOwn(markers, index + run)) run += 1;
    const marker = markers[index];
    rows.push(
      html`<span class="tl"><span class="tk">${marker ? html`<span class="callout">${marker}</span>` : ''}</span><span class="tt">${recorded(lines[index])}${run > 1 ? html`<span class="times" lang="${lang()}">× ${run}</span>` : ''}</span></span>`,
    );
    index += run;
  }
  return html`<figure class="term">
  <figcaption class="term-bar"><span class="term-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>${title}</span></figcaption>
  <pre class="term-body" lang="en"><span class="tl prompt"><span class="tk"></span><span class="tt"><span class="ps">PS&gt;</span> ${command}</span></span>${rows}</pre>
</figure>`;
}

/**
 * The recorded review, shortened the same way wherever it is shown: the long list of the
 * app's addresses and the run's closing list of limits are cut after their first entries.
 * @param {any} run the run record
 * @param {Record<string, number>} [mark] which lines get numbered markers, by name
 */
export function reviewConsole(run, mark = {}) {
  /** @type {string[]} */
  const lines = run.console;
  const find = (/** @type {(line: string) => boolean} */ test, from = 0) => {
    const found = lines.findIndex((line, position) => position >= from && test(line));
    holds(found >= 0, 'the recorded console has the expected shape');
    return found;
  };
  const flows = find((line) => /^Showing \d+ of \d+ entry flows:$/.test(line));
  const overviewOnly = find((line) => line.startsWith('Overview only;'), flows);
  const preparing = find((line) => line.startsWith('Preparing the queue'), overviewOnly);
  const firstLimit = find((line) => line.startsWith('Limit: '));
  const saved = find((line) => line.startsWith('Saved '), firstLimit);
  holds(lines.slice(flows + 1, overviewOnly).every((line) => / \| /.test(line)), 'the address list is one address per line');
  holds(lines.slice(firstLimit, saved).every((line) => line.startsWith('Limit: ')), 'the limits run until the saved report');
  const shownFlows = 3;

  /** @type {Record<string, number>} */
  const at = {
    map: 0,
    run: find((line) => line.startsWith('Run: ')),
    questions: find((line) => /^\s+\w+: answered$/.test(line)),
    receipt: find((line) => line.startsWith('F-01: ')),
    invoice: find((line) => line.startsWith('F-02: ')),
    summary: find((line) => line.startsWith('Source conclusions: ')),
    saved,
  };
  return terminal({
    title: t(
      `PowerShell · recorded on ${day(run.started_at)}`,
      `PowerShell · ${day(run.started_at)} kuni yozib olingan`,
    ),
    command: commandLine(run.command),
    lines,
    cuts: [
      {
        from: flows + 1 + shownFlows,
        to: overviewOnly - 1,
        note: t('more addresses of the app, one per line', 'ilovaning boshqa manzillari, har biri alohida qatorda'),
      },
      {
        from: overviewOnly + 1,
        to: preparing - 1,
        note: t('which parts of Plumb have and have not been evaluated', 'Plumbning qaysi qismlari baholangan va qaysilari baholanmagan'),
      },
      {
        from: firstLimit + 1,
        to: saved - 1,
        note: t('more limits the run states about itself', 'tekshiruv o‘zi haqida aytgan boshqa cheklovlar'),
      },
    ],
    markers: Object.fromEntries(Object.entries(mark).map(([name, number]) => [at[name], number])),
  });
}
