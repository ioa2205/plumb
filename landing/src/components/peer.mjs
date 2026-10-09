// @ts-check
// The peer check: the codebase compared with itself. Rows, guards and exclusions come from
// the saved report; only the column wording is ours.

import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { glyph, pencilMark } from './glyphs.mjs';

const COLUMN_LABELS = {
  authenticated: { en: 'Signed in', uz: 'Tizimga kirgan' },
  owner: { en: 'Belongs to caller', uz: 'So‘rovchiniki' },
  role: { en: 'Staff role', uz: 'Xodim roli' },
};

/** "/orders/{order_id}/receipt" with a line-break opportunity after each slash. */
function route(/** @type {string} */ path) {
  return path
    .split('/')
    .slice(1)
    .map((segment) => html`/<wbr>${segment}`);
}

/** The last word of the route the peer check singled out, e.g. "receipt". */
export const deviantName = (/** @type {any} */ peer) =>
  peer.rows.find((/** @type {any} */ row) => row.subject).route.split('/').pop();

export function peerClaim(/** @type {any} */ peer) {
  // The Uzbek sentence names the route in Uzbek, so it must be the route it names.
  holds(deviantName(peer) === 'receipt', 'the route singled out is the receipt route');
  return t(
    html`A practice app loads an order in ${peer.compared} comparable places. ${peer.deviation.peers_applying} of them check that the order belongs to the person asking. <em>The ${deviantName(peer)} route doesn’t.</em>`,
    html`Sinov ilovasida buyurtma ${peer.compared} ta o‘xshash joyda yuklanadi. Ulardan ${peer.deviation.peers_applying} tasi buyurtma so‘rayotgan odamniki ekanini tekshiradi. <em>Chek manzili tekshirmaydi.</em>`,
  );
}

/**
 * @param {any} peer
 * @param {object} [options]
 * @param {string[]} [options.columns] guard kinds to show; defaults to every recorded column
 * @param {boolean} [options.animate] draw the red-pencil mark once on load
 * @param {boolean} [options.compact] leave out file locations, for the short form on the overview
 */
export function peerTable(peer, { columns = peer.columns, animate = false, compact = false } = {}) {
  const { deviation } = peer;
  const rows = peer.rows.filter((/** @type {any} */ row) => !row.excluded);
  const applied = t('applied', 'qo‘llangan');
  const absent = t('not applied', 'qo‘llanmagan');
  const outlier = t(
    `not applied, while ${deviation.peers_applying} of ${deviation.peers_total} peers apply it`,
    `qo‘llanmagan, holbuki ${deviation.peers_total} ta o‘xshash joydan ${deviation.peers_applying} tasida bor`,
  );

  return html`<table class="peer${animate ? ' is-drawn' : ''}${compact ? ' is-compact' : ''}">
  <caption class="sr-only">${t('Checks applied at each place that loads an order', 'Buyurtma yuklanadigan har bir joyda qo‘llangan tekshiruvlar')}</caption>
  <thead><tr>
    <th scope="col">${t('Where an order is loaded', 'Buyurtma yuklanadigan joy')}</th>
    ${columns.map((key) => {
      const label = COLUMN_LABELS[/** @type {keyof typeof COLUMN_LABELS} */ (key)];
      return html`<th scope="col">${t(label.en, label.uz)}</th>`;
    })}
  </tr></thead>
  <tbody>
    ${rows.map(
      (/** @type {any} */ row) => html`<tr${row.subject ? html` class="dev"` : ''}>
      <th scope="row"><span class="site"><span class="verb">${row.method}</span>${route(row.route)}</span>${row.subject ? html`<span class="this">${t('this one', 'mana shu')}</span>` : ''}${compact ? '' : html`<span class="where">${row.handler.path}:${row.handler.line}</span>`}</th>
      ${columns.map((key) => {
        if (row.applied.includes(key)) return html`<td>${glyph('dot', applied)}</td>`;
        if (row.subject && key === deviation.missing) {
          return html`<td><span class="mark">${glyph('ring', outlier)}${pencilMark}</span></td>`;
        }
        return html`<td class="off">${glyph('ring', absent)}</td>`;
      })}
    </tr>`,
    )}
  </tbody>
</table>`;
}

/** Sites left out of the comparison, each with the reason the report recorded. */
export function peerExclusions(/** @type {any} */ peer) {
  const rows = peer.rows.filter((/** @type {any} */ row) => row.excluded);
  return html`<ul class="quiet-list">
    ${rows.map(
      (/** @type {any} */ row) =>
        html`<li><span class="fact">${row.method} ${row.route}</span><span class="small" lang="en">${row.excluded}</span></li>`,
    )}
  </ul>`;
}
