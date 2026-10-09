// @ts-check
// What must never reach the public site.
//
// The general patterns are written here. Words that would identify the owner (account and
// folder names, an address) are kept in landing/.private-words, one regular expression per
// line, and that file is never committed: publishing this code must not publish the very
// words it guards against. Without the file only the general patterns apply.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const FILE = join(resolve(dirname(fileURLToPath(import.meta.url)), '..'), '.private-words');

const GENERAL = [
  /\b[A-Za-z]:\\{1,2}[\w .()-]+\\/, // absolute Windows paths, raw or JSON-escaped
  /[\\/]Users[\\/]/i,
  /plumb-data/i,
];

const words = existsSync(FILE)
  ? readFileSync(FILE, 'utf8')
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#'))
  : [];

/** True when the local word list was found, so a check can say how much it covered. */
export const PRIVATE_WORDS_LOADED = words.length > 0;

export const PRIVATE_PATTERNS = [...GENERAL, ...words.map((word) => new RegExp(word, 'i'))];
