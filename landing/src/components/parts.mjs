// @ts-check
// Small pieces shared by pages. `fact` marks text copied from a saved record: on this site
// the monospaced face means "recorded", never "typed by hand".

import { html, raw } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { tone } from '../lib/tone.mjs';
import { gauge, glyph } from './glyphs.mjs';

export const fact = (/** @type {unknown} */ value) => html`<span class="fact">${value}</span>`;

/** A source line on a sheet saying which record the sheet shows. */
export const stamp = (/** @type {unknown} */ value) => html`<p class="stamp">${value}</p>`;

let commandCount = 0;

/**
 * A command to type, with a copy button that appears when scripts run. Each argument is kept
 * whole when the line wraps, so an option such as --family is never split at its hyphens.
 */
export function command(/** @type {string} */ text) {
  commandCount += 1;
  const id = `cmd-${commandCount}`;
  const lines = text.split('\n').map((line, index) => {
    const words = line.split(' ').map((word, position) => html`${position ? ' ' : ''}<span class="arg">${word}</span>`);
    return html`${index ? '\n' : ''}${words}`;
  });
  return html`<div class="cmd"><pre><code id="${id}">${lines}</code></pre><button class="btn copy" type="button" data-copy="${id}" data-done="${t('Copied', 'Nusxalandi')}" hidden>${t('Copy', 'Nusxalash')}</button></div>`;
}

/** A block of plain text to copy whole, such as a message for an AI agent. */
export function copyBlock(/** @type {string} */ text, /** @type {string} */ label) {
  commandCount += 1;
  const id = `cmd-${commandCount}`;
  return html`<div class="cmd copy-block"><p class="copy-label">${label}</p><pre lang="en"><code id="${id}">${text}</code></pre><button class="btn copy" type="button" data-copy="${id}" data-done="${t('Copied', 'Nusxalandi')}" hidden>${t('Copy', 'Nusxalash')}</button></div>`;
}

const CONCLUSIONS = {
  supported: { glyph: 'dot', en: 'Supported', uz: 'Tasdiqlandi' },
  rejected: { glyph: 'slash', en: 'Rejected', uz: 'Rad etildi' },
  inconclusive: { glyph: 'half', en: 'Inconclusive', uz: 'Noaniq' },
};
const SEVERITY = {
  critical: { level: 4, en: 'Critical severity', uz: 'O‘ta yuqori xavf' },
  high: { level: 3, en: 'High severity', uz: 'Yuqori xavf' },
  medium: { level: 2, en: 'Medium severity', uz: 'O‘rtacha xavf' },
  low: { level: 1, en: 'Low severity', uz: 'Past xavf' },
};
const RUNTIME = {
  not_attempted: { en: 'not attempted', uz: 'o‘tkazilmagan' },
  reproduced: { en: 'reproduced', uz: 'takrorlandi' },
  not_reproduced: { en: 'not reproduced', uz: 'takrorlanmadi' },
};

/**
 * The status line of a finding. Source conclusion and runtime verification are separate
 * dimensions and are always shown as separate items.
 */
export function verdict(/** @type {any} */ finding) {
  const conclusion = CONCLUSIONS[/** @type {keyof typeof CONCLUSIONS} */ (finding.conclusion)];
  const severity = SEVERITY[/** @type {keyof typeof SEVERITY} */ (finding.severity)];
  const runtime = RUNTIME[/** @type {keyof typeof RUNTIME} */ (finding.runtime_verification)];
  const unproven = finding.runtime_verification === 'not_attempted';
  return html`<ul class="verdict" aria-label="${t(`Status of ${finding.display_id}`, `${finding.display_id} holati`)}">
    <li class="verdict-main${finding.conclusion === 'supported' ? ' is-gap' : ''}">${glyph(/** @type {any} */ (conclusion.glyph))}<span class="sr-only">${t('Source conclusion: ', 'Koddan chiqarilgan xulosa: ')}</span>${t(conclusion.en, conclusion.uz)}<span class="verdict-kind">${t('from the source', 'kod bo‘yicha')}</span></li>
    ${severity ? html`<li>${gauge(severity.level)}${t(severity.en, severity.uz)}</li>` : ''}
    <li${unproven ? raw(' class="unproven"') : ''}>${t('Runtime check', 'Jonli sinov')}: ${t(runtime.en, runtime.uz)}</li>
  </ul>`;
}

/**
 * A cited code excerpt, shown exactly as the frozen source has it.
 * @param {any} excerpt
 * @param {object} options
 * @param {string} options.gloss why this exhibit matters, in one sentence
 * @param {'access' | 'guard'} [options.mark] which recorded line range gets a margin bar
 */
export function exhibit(excerpt, { gloss, mark }) {
  const range = mark ? excerpt[mark] : null;
  const kind = mark === 'access' ? 'flag' : 'cite';
  const lines = excerpt.lines.map((/** @type {string} */ line, /** @type {number} */ index) => {
    const number = excerpt.start + index;
    const marked = range && number >= range.start && number <= range.end;
    return html`<span class="l${marked ? ` ${kind}` : ''}"><span class="n">${number}</span><span class="t">${tone(line)}</span></span>`;
  });
  return html`<figure class="exhibit">
  <figcaption><span class="tag">${excerpt.tag.replace('/', ' ')}</span><span class="path">${excerpt.path}</span><span class="lines">${excerpt.start}–${excerpt.end}</span><span class="gloss">${gloss}</span></figcaption>
  <pre class="code">${lines}</pre>
</figure>`;
}

/**
 * A picture of the saved report in the reader's theme, linking to the report itself. The
 * pictures are captures of the published file (scripts/report-images.mjs), never mock-ups.
 * @param {'summary' | 'finding'} name
 * @param {string} alt
 * @param {[number, number]} size
 */
export function reportShot(name, alt, [width, height]) {
  const image = (/** @type {string} */ theme) =>
    html`<img class="only-${theme}" src="/shots/report-${name}-${theme}.webp" alt="${alt}" width="${width}" height="${height}" loading="lazy" decoding="async">`;
  return html`<a class="shot" href="/saved-report/report.html">${image('day')}${image('night')}</a>`;
}

/** What one recorded request returned, in words. */
function observed(/** @type {any} */ step) {
  const bad = step.role === 'attack' && step.marker_present;
  const body = step.marker_present
    ? t('Alice’s data in the reply', 'javobda Alice’ning ma’lumotlari bor')
    : t('no order data', 'buyurtma ma’lumoti yo‘q');
  return html`<span class="${bad ? 'out-bad' : 'out-ok'}">${fact(step.status)} · ${body}</span>`;
}

/**
 * Recorded requests against the bundled practice app.
 * @param {{ label: string, steps: any[], outcome: string }[]} groups
 */
export function probeTable(groups) {
  const attackWords = t('Bob asks for Alice’s order', 'Bob Alice’ning buyurtmasini so‘raydi');
  const controlWords = t('Alice asks for her own order', 'Alice o‘z buyurtmasini so‘raydi');
  const outcomeWords = t('Recorded outcome', 'Yozib olingan natija');
  const outcomes = {
    reproduced: t('Reproduced', 'Xato takrorlandi'),
    not_reproduced: t('Not reproduced', 'Xato takrorlanmadi'),
    fixed: t('No longer reproduced', 'Tuzatishdan keyin takrorlanmadi'),
  };
  return html`<table class="plain stack">
  <caption class="sr-only">${t('What each recorded request returned', 'Yozib olingan har bir so‘rovga kelgan javob')}</caption>
  <thead><tr><th scope="col">${t('Tested', 'Nima sinaldi')}</th><th scope="col">${attackWords}</th><th scope="col">${controlWords}</th><th scope="col">${outcomeWords}</th></tr></thead>
  <tbody>
    ${groups.map((group) => {
      const attack = group.steps.find((step) => step.role === 'attack');
      const control = group.steps.find((step) => step.role === 'control');
      return html`<tr>
        <th scope="row">${group.label}</th>
        <td data-label="${attackWords}">${observed(attack)}</td>
        <td data-label="${controlWords}">${observed(control)}</td>
        <td data-label="${outcomeWords}">${outcomes[/** @type {keyof typeof outcomes} */ (group.outcome)]}</td>
      </tr>`;
    })}
  </tbody>
</table>`;
}
