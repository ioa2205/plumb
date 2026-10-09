// @ts-check
// The flaw Plumb looks for, drawn so anyone can see it: one customer changes a number in the
// address and gets another customer's receipt. Names, addresses and items are the practice
// app's own sample data, read from its seed file; the receipt shows only the fields the
// receipt route really returns. The recorded runtime test is cited for what really happened.

import { day } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { pencilWide } from './glyphs.mjs';

/** One browser frame showing a receipt. */
function frame(/** @type {any} */ order, /** @type {string} */ viewer, /** @type {{ leak?: boolean, from?: number }} */ { leak = false, from } = {}) {
  const items = order.items.map((/** @type {any} */ item, /** @type {number} */ index) => html`${index ? ' · ' : ''}${item.quantity} × ${item.name}`);
  const name = html`<span class="paper-name">${leak ? html`<span class="circled">${order.customer.name}${pencilWide}</span>` : order.customer.name}</span>`;
  const who = html`${name}<span class="paper-addr">${order.address}</span>`;
  return html`<div class="frame${leak ? ' is-leak' : ''}">
    <p class="bar"><span class="bar-app">Tandir</span><span class="bar-url">/orders/<b${leak ? html` class="changed" title="${t(`was ${from}`, `avval ${from} edi`)}"` : ''}>${order.id}</b>/receipt</span><span class="bar-who">${t(`Signed in as ${viewer}`, `Hisob: ${viewer}`)}</span></p>
    <div class="paper">
      <p class="paper-k">${t(`Receipt · order ${order.id}`, `Chek · ${order.id}-buyurtma`)}</p>
      <p class="paper-who" lang="en">${who}</p>
      <p class="paper-items" lang="en">${items}</p>
    </div>
  </div>`;
}

/**
 * @param {any} sample the practice app's sample customers and the receipt's fields
 * @param {any} probe the recorded runtime test of the receipt route
 */
export function leak(sample, probe) {
  const { victim, intruder, receipt_fields: fields } = sample;
  const attack = probe.steps.find((/** @type {any} */ step) => step.role === 'attack');
  holds(['customer_name', 'delivery_address', 'items'].every((field) => fields.includes(field)), 'a receipt carries the name, the address and the items');
  holds(probe.outcome === 'reproduced' && attack.principal === 'bob' && attack.status === 200 && attack.marker_present, 'Bob received Alice’s data in the recorded test');
  const viewer = intruder.customer.name.split(' ')[0];
  const victimName = victim.customer.name.split(' ')[0];

  return html`<figure class="leak" aria-labelledby="leak-cap">
  <ol class="leak-steps">
    <li>
      ${frame(intruder, viewer)}
      <p class="leak-cap"><span class="callout">1</span><span>${t(
        `${viewer} is signed in and opens his own receipt.`,
        `${viewer} o‘z hisobiga kirib, o‘z chekini ochadi.`,
      )}</span></p>
    </li>
    <li>
      ${frame(victim, viewer, { leak: true, from: intruder.id })}
      <p class="leak-cap"><span class="callout">2</span><span>${t(
        html`He changes <b>${intruder.id}</b> to <b>${victim.id}</b> in the address. The app now shows <em>${victimName}’s name, home address and order</em>.`,
        html`U manzildagi <b>${intruder.id}</b> ni <b>${victim.id}</b> ga o‘zgartiradi. Endi ilova unga <em>${victimName}’ning ismi, uy manzili va buyurtmasini</em> ko‘rsatadi.`,
      )}</span></p>
    </li>
  </ol>
  <figcaption class="small" id="leak-cap">${t(
    `Drawn with the practice app’s own sample customers. A recorded test on ${day(probe.at)} sent this kind of request for real: when ${viewer} asked for an order of ${victimName}’s, the reply contained her data.`,
    `Rasm sinov ilovasining o‘z namunaviy mijozlari asosida chizilgan. ${day(probe.at)} kuni yozib olingan sinovda xuddi shunday so‘rov haqiqatan yuborilgan: ${viewer} ${victimName}’ning buyurtmasini so‘raganda, javobda ${victimName}’ning ma’lumotlari kelgan.`,
  )}</figcaption>
</figure>`;
}
