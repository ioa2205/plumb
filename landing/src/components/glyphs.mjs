// @ts-check
// The product's mark grammar (design.md §7): filled = established, ring = absent,
// half = undecided, slashed ring = rejected. Every glyph is paired with a word.

import { html, raw } from '../lib/html.mjs';

export const sprite = raw(
  '<svg class="sprite" width="0" height="0" aria-hidden="true">' +
    '<symbol id="g-dot" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.6" fill="currentColor"/></symbol>' +
    '<symbol id="g-ring" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.1" fill="none" stroke="currentColor" stroke-width="1.5"/></symbol>' +
    '<symbol id="g-half" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.1" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 1.9a4.1 4.1 0 0 1 0 8.2z" fill="currentColor"/></symbol>' +
    '<symbol id="g-slash" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.1" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M2.6 9.4 9.4 2.6" stroke="currentColor" stroke-width="1.5"/></symbol>' +
    '</svg>',
);

/**
 * @param {'dot' | 'ring' | 'half' | 'slash'} name
 * @param {string} [label] spoken label; omit when a visible word sits next to the glyph
 */
export function glyph(name, label) {
  return label
    ? html`<svg class="g" role="img" aria-label="${label}"><use href="#g-${name}"/></svg>`
    : html`<svg class="g" aria-hidden="true"><use href="#g-${name}"/></svg>`;
}

/** The plumb-bob mark: a line ending in a solid bob. */
export const bob = raw(
  '<svg class="bob" viewBox="0 0 10 22" aria-hidden="true"><path d="M5 0v12" stroke="currentColor" stroke-width="1.6"/><path d="M5 11.5 8.6 16 5 21.5 1.4 16z" fill="currentColor"/></svg>',
);

/** The same mark at the foot of a plumb line, where the result hangs. */
export const bobEnd = raw(
  '<svg class="bob-foot" viewBox="0 0 14 30" aria-hidden="true"><path d="M7 0v15" stroke="currentColor" stroke-width="1.6"/><path d="M7 13.5 12 20 7 28.5 2 20z" fill="currentColor"/></svg>',
);

/** The red-pencil mark: a hand-drawn ellipse around the one thing out of true. */
export const pencilMark = raw(
  '<svg class="pencil" viewBox="0 0 46 30" aria-hidden="true"><path d="M27 4.2C17 2.6 5.4 6.4 4.3 14.6 3.3 22.3 14.2 27 25 25.9c10.4-1 17.2-6.3 16.7-12.6C41.2 6.6 31.7 2.4 20.6 4.1"/></svg>',
);

/** The same mark drawn around a wider block of text; it stretches to the block it circles. */
export const pencilWide = raw(
  '<svg class="pencil-wide" viewBox="0 0 240 60" preserveAspectRatio="none" aria-hidden="true"><path pathLength="1" d="M151 6C94 1 17 7 7 28c-7 21 53 29 122 27 70-2 108-12 107-29C235 9 182 3 118 5"/></svg>',
);

/** Severity gauge: four ticks, `level` of them filled. */
export function gauge(/** @type {number} */ level) {
  const ticks = [1, 2, 3, 4].map((tick) => (tick <= level ? '<i class="on"></i>' : '<i></i>')).join('');
  return raw(`<span class="gauge" aria-hidden="true">${ticks}</span>`);
}
