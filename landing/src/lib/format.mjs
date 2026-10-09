// @ts-check
// How recorded values are written out. Formatting never rounds a value into a different claim:
// byte counts keep two decimals of decimal gigabytes, the unit Plumb's own messages use.
// In Uzbek the same digits are written with a decimal comma and spaced thousands.

import { lang } from './lang.mjs';

const uz = () => lang() === 'uz';
const grouped = (/** @type {number} */ value) => {
  const text = value.toLocaleString('en-US');
  return uz() ? text.replace(/,/g, ' ') : text;
};
const decimal = (/** @type {number} */ value, /** @type {number} */ places) => {
  const text = value.toFixed(places);
  return uz() ? text.replace('.', ',') : text;
};

export const int = grouped;

export const gb = (/** @type {number} */ bytes) => `${decimal(bytes / 1e9, 2)} GB`;

export const mb = (/** @type {number} */ bytes) => `${decimal(bytes / 1e6, 1)} MB`;

export const kb = (/** @type {number} */ bytes) => `${grouped(Math.round(bytes / 1e3))} kB`;

/** A recorded number of seconds, such as 921.547, with the decimal mark of the language. */
export const seconds = (/** @type {number} */ value) => (uz() ? String(value).replace('.', ',') : String(value));

export const shortHash = (/** @type {string} */ hash, length = 12) => hash.slice(0, length);

/** "review-ee4171c3…bc63": enough of a run ID to recognise it. */
export const shortRun = (/** @type {string} */ id) => `${id.slice(0, 15)}…${id.slice(-4)}`;

const DAY = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC',
  day: 'numeric',
  month: 'short',
  year: 'numeric',
});
const LONG_DAY = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});
const TIME = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});
const UZ_MONTHS = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'];
const two = (/** @type {number} */ value) => String(value).padStart(2, '0');

/** "8 Oct 2026", or "08.10.2026" in Uzbek. Dates are read in UTC, as the records store them. */
export function day(/** @type {string} */ iso) {
  const date = new Date(iso);
  if (!uz()) return DAY.format(date);
  return `${two(date.getUTCDate())}.${two(date.getUTCMonth() + 1)}.${date.getUTCFullYear()}`;
}

/** "8 October 2026", or "2026-yil 8-oktabr" in Uzbek. */
export function longDay(/** @type {string} */ iso) {
  const date = new Date(iso);
  if (!uz()) return LONG_DAY.format(date);
  return `${date.getUTCFullYear()}-yil ${date.getUTCDate()}-${UZ_MONTHS[date.getUTCMonth()]}`;
}

export const time = (/** @type {string} */ iso) => TIME.format(new Date(iso));

/** 921.547 -> "15 min 22 s" */
export function minutes(/** @type {number} */ value) {
  const whole = Math.round(value);
  return uz()
    ? `${Math.floor(whole / 60)} daqiqa ${whole % 60} soniya`
    : `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

/** A PowerShell command line from recorded arguments. */
export function commandLine(/** @type {string[]} */ argv, program = '.\\plumb.cmd') {
  const quoted = argv.map((arg) => (/[{}\s]/.test(arg) ? `'${arg}'` : arg));
  return [program, ...quoted].join(' ');
}
