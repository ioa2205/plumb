// @ts-check
// The recorded collection, request by request: who asked, what was asked, what came back.
// Every row is one planned action of the saved collection record and its saved answer. The
// words beside an answer compare it with what the plan itself declares a safe app would do.
// With scripts, the rows arrive one at a time when the list scrolls into view; without them,
// or when the reader asks for less motion, the whole list is simply there.

import { day, int, seconds } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { pencilMark } from './glyphs.mjs';

const NAMES = { alice: 'Alice', bob: 'Bob' };

/** The person a request was sent as: an initial and a name. Alice owns the order. */
export function who(/** @type {string | null} */ account) {
  if (!account) return html`<span class="tr-who is-none">${t('no account', 'hisobsiz')}</span>`;
  const name = NAMES[/** @type {keyof typeof NAMES} */ (account)];
  return html`<span class="tr-who is-${account}"><i aria-hidden="true">${name[0]}</i>${name}</span>`;
}

/** What "safe" means for one request, as the plan declares it. */
function expectation(/** @type {any} */ collection, /** @type {any} */ action) {
  return collection.expectations.find(
    (/** @type {any} */ entry) => entry.account === action.account && entry.method === action.method && entry.template === action.template,
  );
}

/** How one row reads: its kind, what came back, and the remark beside it. */
function reading(/** @type {any} */ collection, /** @type {any} */ action) {
  if (action.purpose === 'readiness') {
    return { kind: 'setup', answer: t('Is the app up? The reply is not kept.', 'Ilova ishlayaptimi? Javob saqlanmaydi.'), note: '' };
  }
  if (action.purpose === 'authenticate') {
    return { kind: 'setup', answer: t('Signs in. The reply is not kept as evidence.', 'Hisobga kiradi. Javob dalil sifatida saqlanmaydi.'), note: '' };
  }
  if (action.purpose === 'create_synthetic') {
    return { kind: 'setup', status: action.status, answer: t('A made-up test order is created.', 'Sinov uchun soxta buyurtma yaratiladi.'), note: '' };
  }
  const expected = expectation(collection, action);
  holds(expected, 'every recorded read has a declared expectation');
  const gotData = action.status === 200 && action.marker_present === true;
  if (expected.expected_if_safe === 'denied' && gotData) {
    return {
      kind: 'leak',
      status: action.status,
      answer: t('Alice’s order comes back.', 'Alice’ning buyurtmasi qaytadi.'),
      note: t('Bob does not own this order. A safe app refuses here.', 'Bu buyurtma Bob’niki emas. Xavfsiz ilova bu yerda rad etadi.'),
    };
  }
  if (expected.expected_if_safe === 'denied') {
    holds(action.status === 404 && action.marker_present === false && action.detail, 'the protected address refused the other account');
    return {
      kind: 'refused',
      status: action.status,
      detail: action.detail,
      answer: '',
      note: t('Refused, as it should be.', 'Rad etildi, shunday bo‘lishi kerak ham.'),
    };
  }
  holds(gotData, 'the owner received her own order');
  return { kind: 'own', status: action.status, answer: t('Her own order comes back.', 'O‘zining buyurtmasi qaytadi.'), note: '' };
}

/**
 * @param {any} collection the extracted collection record
 * @param {object} [options]
 * @param {(action: any) => boolean} [options.only] show a selection of the recorded rows
 * @param {string} [options.title]
 * @param {boolean} [options.totals] close with the recorded totals
 */
export function tape(collection, { only, title, totals = false } = {}) {
  const leaks = collection.actions.filter((/** @type {any} */ action) => action.purpose === 'read' && reading(collection, action).kind === 'leak');
  holds(leaks.length === 1 && leaks[0].account === 'bob' && /\/receipt$/.test(leaks[0].path), 'one recorded reply went to the wrong person: Bob got the receipt');
  const rows = collection.actions
    .map((/** @type {any} */ action, /** @type {number} */ index) => ({ action, number: index + 1 }))
    .filter((/** @type {any} */ row) => !only || only(row.action));

  return html`<figure class="tape" data-tape>
  <figcaption class="tape-bar">
    <span>${title ?? t(`Requests to the practice app · recorded on ${day(collection.recorded_at)}`, `Sinov ilovasiga so‘rovlar · ${day(collection.recorded_at)} kuni yozib olingan`)}</span>
    <button class="btn tape-replay" type="button" data-tape-replay hidden>${t('Play again', 'Qayta ko‘rsatish')}</button>
  </figcaption>
  <ol class="tape-rows">
    ${rows.map((/** @type {any} */ row) => {
      const { action, number } = row;
      const read = reading(collection, action);
      const status = read.status
        ? read.kind === 'leak'
          ? html`<span class="tr-status mark">${action.status}${pencilMark}</span>`
          : html`<span class="tr-status">${action.status}</span>`
        : '';
      return html`<li class="tr is-${read.kind}">
      <span class="tr-n" aria-hidden="true">${number}</span>
      ${who(action.account)}
      <code class="tr-req" lang="en"><b>${action.method}</b> ${action.path}</code>
      <span class="tr-ans">${status}${read.detail ? html` <span class="fact" lang="en">${read.detail}</span>` : ''}${read.answer ? html` ${read.answer}` : ''}</span>
      ${read.note ? html`<span class="tr-note">${read.note}</span>` : ''}
    </li>`;
    })}
  </ol>
  ${totals
    ? html`<p class="tape-foot">${t(
        html`<span class="fact">${collection.requests}</span> requests · <span class="fact">${int(collection.bytes_received)}</span> bytes received · <span class="fact">${seconds(Number(collection.seconds.toFixed(2)))} s</span> from start to finish`,
        html`<span class="fact">${collection.requests}</span> ta so‘rov · <span class="fact">${int(collection.bytes_received)}</span> bayt qabul qilingan · boshidan oxirigacha <span class="fact">${seconds(Number(collection.seconds.toFixed(2)))} s</span>`,
      )}</p>`
    : ''}
</figure>`;
}

/** The three rows that tell the story: Bob and Alice ask for the receipt, Bob asks for the invoice. */
export function storyRows(/** @type {any} */ collection) {
  const refusal = collection.actions.find((/** @type {any} */ action) => action.account === 'bob' && /\/invoice$/.test(action.path));
  holds(refusal && refusal.status === 404, 'Bob was refused the invoice');
  return (/** @type {any} */ action) => action.purpose === 'read' && (/\/receipt$/.test(action.path) || action === refusal);
}
