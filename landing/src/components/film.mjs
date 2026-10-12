// @ts-check
// Plumb in four chapters, drawn so that someone who has never read code can follow it: the
// mistake, how Plumb finds it, how it checks itself, and the report. With scripts and motion
// allowed, the chapters play one after another like a short film, with a caption for each
// beat. Without scripts, or when the reader asks for less motion, the same four drawings are
// laid out as panels with all their captions, so nothing is lost.
//
// Nothing here is typed by hand: names, orders and addresses are the practice app's own
// sample data, the counts and the code lines come from the recorded review, and the builds
// stop if the records stop saying what the drawings show.
//
// How a beat is marked: an element with data-from="2" appears at the chapter's second beat,
// and one with data-to="2" leaves after it. The stage is sized in em from its own width, so
// it scales as a picture would.

import { day, longDay } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html, raw } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { glyph } from './glyphs.mjs';

const PENCIL = 'M151 6C94 1 17 7 7 28c-7 21 53 29 122 27 70-2 108-12 107-29C235 9 182 3 118 5';
const folderIcon = raw('<svg class="s-ico" viewBox="0 0 20 16" aria-hidden="true"><path d="M1.5 3.2c0-.9.7-1.7 1.7-1.7h4l1.9 2.2h7.7c.9 0 1.7.8 1.7 1.7v7.4c0 .9-.8 1.7-1.7 1.7H3.2c-1 0-1.7-.8-1.7-1.7z"/></svg>');
const chipIcon = raw('<svg class="s-ico" viewBox="0 0 20 20" aria-hidden="true"><rect x="5" y="5" width="10" height="10" rx="1.6"/><path d="M8 2v3M12 2v3M8 15v3M12 15v3M2 8h3M2 12h3M15 8h3M15 12h3"/></svg>');
const laptopIcon = raw('<svg class="s-ico is-wide" viewBox="0 0 28 20" aria-hidden="true"><rect x="5" y="2.5" width="18" height="11.5" rx="1.6"/><path d="M1.5 17.5h25"/></svg>');

/** Three marks in a row: the three separate judgments behind every answer. */
const marks = (/** @type {'dot' | 'half' | 'slash'} */ name) => html`${glyph(name)}${glyph(name)}${glyph(name)}`;

/** A receipt as the practice app's receipt address returns it. */
function receipt(/** @type {any} */ order, /** @type {import('../lib/html.mjs').Markup | string} */ attributes, circled = false) {
  const items = order.items.map((/** @type {any} */ item, /** @type {number} */ index) => html`${index ? ' · ' : ''}${item.quantity} × ${item.name}`);
  return html`<div class="s-receipt"${attributes}>
        <p class="s-k">${t(`Receipt · order ${order.id}`, `Chek · ${order.id}-buyurtma`)}</p>
        <p class="s-name" lang="en">${circled
          ? html`<span class="s-circled">${order.customer.name}<svg class="s-pencil" data-from="3" viewBox="0 0 240 60" preserveAspectRatio="none"><path pathLength="1" d="${PENCIL}"/></svg></span>`
          : order.customer.name}</p>
        <p class="s-addr" lang="en">${order.address}</p>
        <p class="s-addr" lang="en">${items}</p>
      </div>`;
}

/**
 * @param {any} record the extracted record
 */
export function film(record) {
  const { run, excerpts, runtime, sample } = record;
  const { victim, intruder, receipt_fields: fields } = sample;
  const [flawed, cleared] = run.findings;
  const { peer } = run;
  const compared = peer.rows.filter((/** @type {any} */ row) => !row.excluded);
  const subject = compared.findIndex((/** @type {any} */ row) => row.subject);
  const handler = excerpts.receipt_handler;
  const attack = runtime.receipt.steps.find((/** @type {any} */ step) => step.role === 'attack');
  const viewer = intruder.customer.name.split(' ')[0];
  const owner = victim.customer.name.split(' ')[0];

  holds(['customer_name', 'delivery_address', 'items'].every((field) => fields.includes(field)), 'a receipt carries the name, the address and the items');
  holds(runtime.receipt.outcome === 'reproduced' && attack.principal === 'bob' && attack.status === 200 && attack.marker_present, 'Bob received Alice’s data in the recorded test');
  holds(compared.length === peer.compared && subject >= 0 && compared[subject].route === flawed.route, 'the receipt is the one compared place that stands out');
  holds(compared.filter((/** @type {any} */ row) => row.applied.includes('owner')).length === peer.deviation.peers_applying && peer.deviation.peers_applying === peer.compared - 1, 'every other compared place checks the owner');
  holds(handler.access.start === handler.access.end && handler.access.start >= handler.start && handler.access.start + 2 <= handler.end, 'one cited line loads the order');
  holds(flawed.conclusion === 'supported' && flawed.judgments.length === 3 && flawed.judgments.every((/** @type {any} */ entry) => entry.interpretation === 'none_found'), 'three judgments found nothing that protects the receipt');
  holds(cleared.conclusion === 'rejected' && cleared.judgments.length === 3 && cleared.judgments.every((/** @type {any} */ entry) => entry.interpretation === 'scoped_elsewhere') && cleared.guards.some((/** @type {any} */ guard) => guard.kind === 'owner' && !guard.where.startsWith(handler.path)), 'the invoice was cleared by a check in another file');
  holds(flawed.runtime_verification === 'not_attempted' && run.target_code_executed === false, 'the report says no live test was attempted');
  holds(cleared.route === flawed.route.replace('receipt', 'invoice'), 'the two addresses differ only in their last word');

  // The dot row: eleven places across a stage 250 units wide (ten units to one em).
  const step = 18.5;
  const first = (250 - (compared.length - 1) * step) / 2;
  const x = (/** @type {number} */ index) => Number((first + index * step).toFixed(2));
  const codeFrom = handler.access.start - handler.start;
  const code = handler.lines.slice(codeFrom, codeFrom + 3).map((/** @type {string} */ line) => line.replace(/^ {4}/, ''));
  const address = (/** @type {unknown} */ digit) => html`/orders/${digit}/receipt`;

  const chapters = [
    {
      name: t('The mistake', 'Xato'),
      captions: [
        t(`${viewer} signs in to a bakery app and opens his own receipt: order ${intruder.id}.`, `${viewer} nonvoyxona ilovasiga kirib, o‘z chekini ochadi: ${intruder.id}-buyurtma.`),
        t('He changes one digit in the address.', 'U manzildagi bitta raqamni o‘zgartiradi.'),
        t(`The app hands him ${owner}’s name, home address and order.`, `Ilova unga ${owner}’ning ismi, uy manzili va buyurtmasini ko‘rsatadi.`),
      ],
      stage: html`<div class="stage s1">
    <div class="s-browser">
      <p class="s-bar" lang="en"><span class="s-app">Tandir</span><span class="s-url">${address(html`<b class="s-digit"><i data-to="1">${intruder.id}</i><i data-from="2">${victim.id}</i></b>`)}</span><span class="s-who"><i>${viewer[0]}</i>${viewer}</span></p>
      <div class="s-desk">
        ${receipt(intruder, raw(' data-to="2"'))}
        ${receipt(victim, raw(' data-from="3"'), true)}
      </div>
    </div>
  </div>`,
    },
    {
      name: t('Plumb finds it', 'Plumb uni topadi'),
      captions: [
        t(`Point Plumb at the code. It finds every place that hands out an order: ${peer.compared} here.`, `Plumbga kodni ko‘rsating. U buyurtma beriladigan har bir joyni topadi: bu yerda ${peer.compared} ta.`),
        t(`${peer.deviation.peers_applying} of them check whose order it is. One does not.`, `Ularning ${peer.deviation.peers_applying} tasi buyurtma kimniki ekanini tekshiradi. Bittasi tekshirmaydi.`),
        t('Plumb points to the exact line: the order is loaded by its number alone.', 'Plumb aynan qaysi qator ekanini ko‘rsatadi: buyurtma faqat raqami bo‘yicha yuklanadi.'),
      ],
      stage: html`<div class="stage s2">
    <p class="s-chip" lang="en">${folderIcon}tandir/ · ${t(`${run.overview.included_files} files`, `${run.overview.included_files} ta fayl`)}</p>
    <div class="s-code" data-from="3" lang="en">
      ${code.map((/** @type {string} */ line, /** @type {number} */ index) => html`<p class="s-line${index ? '' : ' is-hit'}"><span class="s-n">${handler.access.start + index}</span><code>${line}</code></p>`)}
      <p class="s-path">${handler.path}</p>
    </div>
    <svg class="s-over" viewBox="0 0 250 230">
      <g class="s-found" data-to="1">${compared.map((/** @type {any} */ row, /** @type {number} */ index) => html`<circle cx="${x(index)}" cy="56" r="4"/>`)}</g>
      <g class="s-judged" data-from="2">${compared.map((/** @type {any} */ row, /** @type {number} */ index) =>
        index === subject ? html`<circle class="is-gap" cx="${x(index)}" cy="56" r="5.6"/>` : html`<circle cx="${x(index)}" cy="56" r="6.5"/>`)}
        <text class="s-label" x="${x(subject) + 11}" y="79">${t('receipt', 'chek')}</text>
      </g>
      <g transform="translate(${x(subject)} 0)"><g class="s-plumb" data-from="2"><path class="s-string" d="M0 -300V27"/><path class="s-weight" d="M0 26 5.2 34 0 47.5-5.2 34z"/></g></g>
    </svg>
  </div>`,
    },
    {
      name: t('It checks itself', 'O‘zini tekshiradi'),
      captions: [
        t('First, Plumb looks for a check it may have missed.', 'Avval Plumb o‘zi payqamay qolgan tekshiruvni qidiradi.'),
        t('A small AI model on your laptop judges the evidence three times. None finds a protection.', 'Noutbukingizdagi kichik SI modeli dalillarga uch marta baho beradi. Birortasi himoya topmaydi.'),
        t('The invoice looks the same, but a check in another file protects it. Plumb clears it.', 'Hisob-faktura ham xuddi shunday ko‘rinadi, lekin uni boshqa fayldagi tekshiruv himoya qiladi. Plumb uni oqlaydi.'),
      ],
      stage: html`<div class="stage s3">
    <p class="s-chip" data-from="2">${chipIcon}${t('AI model · on this laptop', 'SI modeli · shu noutbukda')}</p>
    <div class="s-case is-flaw">
      <p class="s-route" lang="en">${flawed.route}</p>
      <p class="s-verdict"><span class="s-marks"><span data-to="1">${marks('half')}</span><span data-from="2">${marks('dot')}</span></span><b class="s-word" data-from="2">${t('Supported', 'Tasdiqlandi')}</b></p>
      <p class="s-gloss"><span data-to="1">${t('Does anything protect it?', 'Uni biror narsa himoya qiladimi?')}</span><span data-from="2">${t('Nothing protects it.', 'Uni hech narsa himoya qilmaydi.')}</span></p>
    </div>
    <div class="s-case is-clear" data-from="3">
      <p class="s-route" lang="en">${cleared.route}</p>
      <p class="s-verdict"><span class="s-marks"><span>${marks('slash')}</span></span><b class="s-word">${t('Rejected', 'Rad etildi')}</b></p>
      <p class="s-gloss"><span>${t('Protected in another file.', 'Boshqa faylda himoyalangan.')}</span></p>
    </div>
  </div>`,
    },
    {
      name: t('You get a report', 'Hisobot olasiz'),
      captions: [
        t('You get a report: the place, the file, the line, the evidence.', 'Sizga hisobot beriladi: joy, fayl, qator va dalillar.'),
        t('It also says what it did not check, so you know how far to trust it.', 'Unda nima tekshirilmagani ham yozilgan, shuning uchun unga qanchalik ishonish mumkinligini bilasiz.'),
        t('All of it ran on one laptop.', 'Hammasi bitta noutbukda bajarildi.'),
      ],
      stage: html`<div class="stage s4">
    <div class="s-report">
      <p class="s-r-head" lang="en"><span class="s-tag">${flawed.display_id}</span>${flawed.title}</p>
      <p class="s-route" lang="en">${flawed.route}</p>
      <p class="s-r-verdict">${glyph('dot')}${t('Supported', 'Tasdiqlandi')}</p>
      <p class="s-route" lang="en">${handler.path}:${handler.access.start}</p>
      <p class="s-r-unknown" data-from="2">${glyph('half')}<span>${t('Not checked: a live test', 'Tekshirilmagan: jonli sinov')}</span></p>
    </div>
    <p class="s-local" data-from="3">${laptopIcon}${t('Saved on this laptop', 'Shu noutbukda saqlandi')}</p>
  </div>`,
    },
  ];

  return html`<div class="film" id="film" data-film>
  <ol class="film-list">
    ${chapters.map((chapter, index) => html`<li class="chapter" data-chapter>
      <h3 class="chapter-head"><button type="button" class="chapter-go" data-film-go disabled><span class="chapter-n" aria-hidden="true">${index + 1}</span><span class="chapter-label">${chapter.name}</span></button></h3>
      <div class="chapter-text">
        <p class="chapter-name" aria-hidden="true">${chapter.name}</p>
        <ol class="captions">
          ${chapter.captions.map((caption) => html`<li>${caption}</li>`)}
        </ol>
      </div>
      <div class="stage-box" aria-hidden="true">
  ${chapter.stage}
      </div>
    </li>`)}
  </ol>
  <div class="film-rail" aria-hidden="true"><svg class="film-bob" viewBox="0 0 14 20"><path d="M7 0 12.4 8 7 20 1.6 8z"/></svg></div>
  <p class="film-controls" data-film-controls hidden>
    <button class="btn film-btn" type="button" data-film-toggle data-pause="${t('Pause', 'To‘xtatish')}" data-play="${t('Play', 'Davom ettirish')}">${t('Pause', 'To‘xtatish')}</button>
    <button class="btn film-btn" type="button" data-film-replay>${t('Play again', 'Boshidan ko‘rish')}</button>
  </p>
  <p class="small film-note">${t(
    `${viewer}’s request was also sent for real on ${day(runtime.receipt.at)}: the reply held ${owner}’s data.`,
    `${day(runtime.receipt.at)} kuni alohida sinovda ${viewer}’ning so‘rovi haqiqatan yuborilgan: javobda ${owner}’ning ma’lumotlari kelgan.`,
  )}</p>
</div>`;
}
