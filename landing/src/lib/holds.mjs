// @ts-check
// Sentences on the site are written by hand; the facts inside them are not allowed to drift.
// Wherever prose depends on a recorded value, the page asserts it here and the build fails
// if a later record says otherwise.

/** @param {unknown} condition @param {string} claim the sentence that depends on it */
export function holds(condition, claim) {
  if (!condition) throw new Error(`The site says "${claim}", but the saved records do not.`);
}
