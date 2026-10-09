// @ts-check
// The deployed endpoint behind the contact form. Vercel has already parsed the body; the
// logic and its checks live in server/message.mjs.
//
// Needs two environment variables in the deployment, and nothing in this repository:
//   TELEGRAM_BOT_TOKEN   from @BotFather
//   TELEGRAM_CHAT_ID     the owner's chat with that bot

import { receive } from '../server/message.mjs';

/** @param {any} request @param {any} response */
export default async function handler(request, response) {
  let fields;
  try {
    fields = request.body;
  } catch {
    fields = undefined; // a body that does not parse is treated as an empty one
  }
  const result = await receive({
    method: request.method ?? 'GET',
    headers: request.headers,
    fields,
    env: process.env,
  });
  response.statusCode = result.status;
  for (const [name, value] of Object.entries(result.headers)) response.setHeader(name, value);
  response.end(result.body);
}
