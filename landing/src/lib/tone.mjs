// @ts-check
// Python excerpts are drawn in weight and tone, not hue (design.md §5): keywords heavier,
// decorators quieter, string literals in umber. Everything is emitted as escaped text.

import { Markup, escape } from './html.mjs';

const TOKEN =
  /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|\b(def|class|if|elif|else|is|in|or|and|not|None|True|False|raise|return|for|import|from)\b/g;

/** @param {string} line */
export function tone(line) {
  const decorator = line.match(/^(\s*)(@[\w.]+)(.*)$/);
  if (decorator) {
    const [, indent, name, rest] = decorator;
    return new Markup(`${escape(indent)}<span class="d">${escape(name)}</span>${tokens(rest)}`);
  }
  return new Markup(tokens(line));
}

/** @param {string} text */
function tokens(text) {
  let out = '';
  let last = 0;
  for (const match of text.matchAll(TOKEN)) {
    out += escape(text.slice(last, match.index));
    out += match[1]
      ? `<span class="s">${escape(match[1])}</span>`
      : `<span class="k">${escape(match[2])}</span>`;
    last = match.index + match[0].length;
  }
  return out + escape(text.slice(last));
}
