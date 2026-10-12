/** One bounded, same-origin read of JSON or text from the local Plumb API. Nothing is cached. */

export class LocalReadError extends Error {}

export async function localBody(path: string, method: "GET" | "POST", body: unknown, signal: AbortSignal, limit: number, kind: "json" | "markdown", request: typeof fetch = fetch): Promise<string> {
  let response: Response;
  try {response = await request(path, {method, headers: {"content-type": "application/json"}, ...(body !== undefined && body !== null ? {body: JSON.stringify(body)} : {}), signal, credentials: "same-origin", cache: "no-store", redirect: "error"});}
  catch {throw new LocalReadError("Plumb cannot be reached. Check its terminal and this browser session, then try again.");}
  if (!response.ok || response.redirected) {
    let detail = "";
    try {const value: unknown = await response.json(); if (value && typeof value === "object" && typeof (value as {detail?: unknown}).detail === "string") detail = (value as {detail: string}).detail.slice(0, 300);} catch {detail = "";}
    throw new LocalReadError(detail || "Plumb refused this request. Check the current session and try again.");
  }
  const type = response.headers.get("content-type")?.trim() ?? "";
  const expected = kind === "json" ? /^application\/json(?:\s*;|$)/i : /^text\/markdown(?:\s*;|$)/i;
  if (!response.body || !expected.test(type)) throw new LocalReadError("Plumb sent a response this page cannot read.");
  const length = response.headers.get("content-length");
  if (length && /^\d+$/.test(length) && Number(length) > limit) {await response.body.cancel().catch(() => {}); throw new LocalReadError("The response exceeds this page's limit.");}
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {const {done, value} = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) throw new LocalReadError("The response exceeds this page's limit."); chunks.push(value);}
  } catch (error) {throw error instanceof LocalReadError ? error : new LocalReadError("The transfer stopped. Load the saved record again.");}
  finally {await reader.cancel().catch(() => {}); reader.releaseLock();}
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.byteLength;}
  try {return new TextDecoder("utf-8", {fatal: true}).decode(bytes);}
  catch {throw new LocalReadError("Plumb sent a response this page cannot read.");}
}

export async function localJson(path: string, method: "GET" | "POST", body: unknown, signal: AbortSignal, limit: number, request: typeof fetch = fetch): Promise<unknown> {
  const text = await localBody(path, method, body, signal, limit, "json", request);
  try {return JSON.parse(text);}
  catch {throw new LocalReadError("Plumb sent a response this page cannot read.");}
}
