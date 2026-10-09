// @ts-check
// Passes one message from the contact form to the site owner's Telegram and keeps nothing.
//
// This is plain logic with no server attached: the deployed function (api/message.js) and
// the local preview server both call `receive` with a body they have already parsed.
// The bot token and chat ID come from the environment and are never written to a response
// or a log.

export const LIMITS = { messageMin: 10, messageMax: 2000, name: 80, reply: 120 };

// A light brake on floods. It lives in memory, so it resets whenever the function instance
// is recycled and is not shared between instances. It keeps accidents and casual abuse away
// from the owner's phone; it is not a guarantee.
const WINDOW_MS = 10 * 60 * 1000;
const PER_SENDER = 3;
const PER_INSTANCE = 30;
const MAX_SENDERS = 500;

/** @type {Map<string, number[]>} */
const bySender = new Map();
/** @type {number[]} */
let everyone = [];

export function resetLimits() {
  bySender.clear();
  everyone = [];
}

/** @returns {boolean} true when this sender may send now; records the attempt if so */
function admit(/** @type {string} */ sender, /** @type {number} */ now) {
  const recent = (/** @type {number[]} */ times) => times.filter((time) => now - time < WINDOW_MS);
  everyone = recent(everyone);
  const mine = recent(bySender.get(sender) ?? []);
  if (mine.length >= PER_SENDER || everyone.length >= PER_INSTANCE) return false;
  mine.push(now);
  everyone.push(now);
  if (bySender.size >= MAX_SENDERS) bySender.clear();
  bySender.set(sender, mine);
  return true;
}

/** One line of text: trimmed, with control characters and line breaks removed. */
const line = (/** @type {unknown} */ value) =>
  typeof value === 'string' ? value.replace(/[\u0000-\u001f\u007f]+/g, ' ').trim() : '';

/** Free text: trimmed, line breaks kept, other control characters removed. */
const text = (/** @type {unknown} */ value) =>
  typeof value === 'string'
    ? value.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b-\u001f\u007f]+/g, '').trim()
    : '';

const first = (/** @type {string | string[] | undefined} */ value) => (Array.isArray(value) ? value[0] : value) ?? '';

/** What the owner reads. Plain text only: nothing a sender types is treated as formatting. */
export function compose(/** @type {{ message: string, name: string, reply: string, language: string }} */ entry) {
  return [
    'Plumb site: new message',
    `From: ${entry.name || 'not given'}`,
    `Reply to: ${entry.reply || 'not given'}`,
    `Page language: ${entry.language}`,
    '',
    entry.message,
  ].join('\n');
}

/**
 * @param {object} request
 * @param {string} request.method
 * @param {Record<string, string | string[] | undefined>} request.headers lower-case names
 * @param {unknown} request.fields the parsed body: an object of strings
 * @param {Record<string, string | undefined>} request.env
 * @param {typeof fetch} [request.send] replaced in tests
 * @param {number} [request.now]
 * @param {boolean} [request.preview] local preview without credentials: accept, do not send
 * @returns {Promise<{ status: number, headers: Record<string, string>, body: string }>}
 */
export async function receive({ method, headers, fields, env, send = fetch, now = Date.now(), preview = false }) {
  const type = first(headers['content-type']).split(';')[0].trim().toLowerCase();
  const asJson = type === 'application/json';
  const values = fields && typeof fields === 'object' ? /** @type {Record<string, unknown>} */ (fields) : {};
  const language = values.lang === 'uz' ? 'uz' : 'en';

  /** A script gets JSON; a plain form post is sent on to a page that says what happened. */
  const reply = (/** @type {number} */ status, /** @type {{ ok: boolean, error?: string, preview?: boolean }} */ result) => {
    if (asJson || status === 405 || status === 415) {
      return {
        status,
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...(status === 405 ? { Allow: 'POST' } : {}) },
        body: JSON.stringify(result),
      };
    }
    const prefix = language === 'uz' ? '/uz' : '';
    return {
      status: 303,
      headers: { Location: `${prefix}/contact/${result.ok ? 'sent' : 'not-sent'}`, 'Cache-Control': 'no-store' },
      body: '',
    };
  };

  if (method !== 'POST') return reply(405, { ok: false, error: 'method' });
  if (!asJson && type !== 'application/x-www-form-urlencoded') return reply(415, { ok: false, error: 'type' });

  // Only this site's own pages may post here.
  const origin = first(headers.origin);
  const site = first(headers['sec-fetch-site']);
  let sameOrigin = site === '' || site === 'same-origin';
  if (origin) {
    try {
      sameOrigin = new URL(origin).host === first(headers.host);
    } catch {
      sameOrigin = false;
    }
  }
  if (!sameOrigin) return reply(403, { ok: false, error: 'forbidden' });

  // The form has a field people cannot see. Whatever fills it in is not a person; it is
  // told the message went through and nothing is sent.
  if (line(values.website)) return reply(200, { ok: true });

  const entry = { message: text(values.message), name: line(values.name), reply: line(values.reply), language };
  const valid =
    entry.message.length >= LIMITS.messageMin &&
    entry.message.length <= LIMITS.messageMax &&
    entry.name.length <= LIMITS.name &&
    entry.reply.length <= LIMITS.reply;
  if (!valid) return reply(400, { ok: false, error: 'invalid' });

  const token = env.TELEGRAM_BOT_TOKEN;
  const chat = env.TELEGRAM_CHAT_ID;
  // A local preview without credentials sends nothing, so it has nothing to slow down.
  if ((!token || !chat) && preview) return reply(200, { ok: true, preview: true });

  const sender = first(headers['x-forwarded-for']).split(',')[0].trim() || 'unknown';
  if (!admit(sender, now)) return reply(429, { ok: false, error: 'rate_limited' });
  if (!token || !chat) return reply(503, { ok: false, error: 'not_configured' });

  try {
    const response = await send(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chat, text: compose(entry), link_preview_options: { is_disabled: true } }),
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) return reply(502, { ok: false, error: 'delivery_failed' });
  } catch {
    return reply(502, { ok: false, error: 'delivery_failed' });
  }
  return reply(200, { ok: true });
}
