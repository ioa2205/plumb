// @ts-check
// Two languages, one set of pages. Each page is rendered once per language: `t` picks the
// wording, and everything copied from a saved record stays exactly as it was recorded.
//
// Uzbek is written with ‘ (o‘, g‘) and ’ (tutuq belgisi). The self-hosted Latin subset of
// the typeface has those two marks and does not have U+02BB / U+02BC.

export const LANGS = /** @type {const} */ (['en', 'uz']);
export const LANG_NAMES = { en: 'English', uz: 'O‘zbekcha' };
/** Round flags in public/flags, shown beside each language's own name in the switcher. */
export const LANG_FLAGS = { en: '/flags/en.svg', uz: '/flags/uz.svg' };

/** @typedef {(typeof LANGS)[number]} Lang */

/** @type {Lang} */
let current = 'en';

/** Rendering is synchronous and one page at a time, so one module-level language is enough. */
export function setLang(/** @type {Lang} */ language) {
  if (!LANGS.includes(language)) throw new Error(`unknown language: ${language}`);
  current = language;
}

export const lang = () => current;

/**
 * The wording for the language being rendered.
 * @template A, B
 * @param {A} en
 * @param {B} uz
 * @returns {A | B}
 */
export function t(en, uz) {
  if (uz === undefined || uz === null) throw new Error(`missing Uzbek wording for: ${String(en).slice(0, 60)}`);
  return current === 'uz' ? uz : en;
}

/** "/contact" in English, "/uz/contact" in Uzbek. */
export const localPath = (/** @type {string} */ path, /** @type {Lang} */ language = current) =>
  language === 'en' ? path : path === '/' ? '/uz' : `/uz${path}`;
