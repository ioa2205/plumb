// @ts-check
// A small HTML template tag. Interpolated values are escaped unless they are already
// markup produced by `html` or explicitly marked with `raw`, so text copied from saved
// records and source files can only ever appear as text.

export class Markup {
  /** @param {string} value */
  constructor(value) {
    this.value = value;
  }
  toString() {
    return this.value;
  }
}

/** @param {unknown} value */
export function escape(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** @param {unknown} value @returns {string} */
function render(value) {
  if (value === null || value === undefined || value === false || value === true) return '';
  if (value instanceof Markup) return value.value;
  if (Array.isArray(value)) return value.map(render).join('');
  return escape(value);
}

/** @param {TemplateStringsArray} strings @param {...unknown} values */
export function html(strings, ...values) {
  let out = '';
  strings.forEach((part, index) => {
    out += part;
    if (index < values.length) out += render(values[index]);
  });
  return new Markup(out);
}

/** Markup written by hand in this repository; never use it for recorded or source text. */
export const raw = (/** @type {string} */ value) => new Markup(value);
