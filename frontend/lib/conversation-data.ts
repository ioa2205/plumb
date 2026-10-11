import type { ConversationAsk, ConversationCreate, ConversationView } from "../generated/contracts";
import schema from "../generated/conversation-view.schema.json" with { type: "json" };
import { structuralMatches } from "./run-metadata.ts";

export const MAX_CONVERSATION_BYTES = 1024 * 1024;
export class ConversationReadError extends Error {}
const identifier = /^conversation-[0-9a-f]{32}$/;
const targetIdentifier = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/;
const validId = (value: string) => identifier.exec(value)?.[0] === value;
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);

function validTarget(value: unknown): value is ConversationCreate {
  return isRecord(value) && Object.keys(value).every(key => ["target_kind", "target_id"].includes(key))
    && typeof value.target_kind === "string" && ["inspection", "review", "assessment"].includes(value.target_kind) && typeof value.target_id === "string"
    && targetIdentifier.exec(value.target_id)?.[0] === value.target_id
    && (value.target_kind !== "inspection" || /^inspect-[0-9a-f]{32}$/.exec(value.target_id)?.[0] === value.target_id);
}
function validAsk(value: unknown): value is ConversationAsk {
  return isRecord(value) && Object.keys(value).every(key => ["prompt", "profile", "max_seconds"].includes(key))
    && typeof value.prompt === "string" && !!value.prompt.trim() && value.prompt.length <= 4096
    && (value.profile === undefined || typeof value.profile === "string" && value.profile.length <= 96 && /^(auto|[a-z][a-z0-9._-]{0,95})$/.exec(value.profile)?.[0] === value.profile)
    && (value.max_seconds === undefined || typeof value.max_seconds === "number" && Number.isSafeInteger(value.max_seconds) && value.max_seconds >= 1 && value.max_seconds <= 300);
}
function sourcePath(value: string): boolean {
  return !!value && !/[\\\u0000-\u001f:]/u.test(value) && !value.startsWith("/") && !value.includes("//")
    && !value.split("/").some(part => [".", ".."].includes(part));
}

export function parseConversation(value: unknown, target: ConversationCreate, id?: string): ConversationView {
  if (!validTarget(target) || id !== undefined && !validId(id) || !structuralMatches(value, schema)) throw new ConversationReadError("The local conversation cannot be read.");
  const view = value as ConversationView;
  if (view.target_id !== target.target_id || view.target_kind !== target.target_kind || id !== undefined && view.conversation_id !== id) throw new ConversationReadError("Conversation belongs to different evidence.");
  for (const turn of view.turns ?? []) {
    const refs = (turn.evidence ?? []).map(item => item.reference_id);
    if (new Set(refs).size !== refs.length) throw new ConversationReadError("Conversation contains duplicated evidence references.");
    for (const item of turn.evidence ?? []) {
      const source = item.source != null; const observation = item.observation != null;
      if (source === observation || (target.target_kind === "assessment") !== observation) throw new ConversationReadError("Conversation citation kind does not match the loaded evidence.");
      if (item.source && (!sourcePath(item.source.path) || item.source.end_line < item.source.start_line || item.quote.split("\n").length !== item.source.end_line - item.source.start_line + 1)) throw new ConversationReadError("Conversation source citation has an invalid exact range or path.");
    }
  }
  return view;
}

async function verifyConversationHashes(view: ConversationView): Promise<void> {
  for (const turn of view.turns ?? []) for (const item of turn.evidence ?? []) {
    const expected = item.observation?.sha256 ?? item.source?.content_sha256;
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(item.quote));
    const actual = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
    if (expected !== actual) throw new ConversationReadError("Conversation quote does not match its exact evidence hash.");
  }
}

export async function conversationRequest(target: ConversationCreate, path: string, body: ConversationAsk | ConversationCreate | null | undefined, signal: AbortSignal, id?: string, request: typeof fetch = fetch): Promise<ConversationView> {
  if (!validTarget(target)) throw new ConversationReadError("Invalid local conversation target.");
  const resource = /^\/api\/conversations\/(conversation-[0-9a-f]{32})(?:\/(ask|cancel))?$/.exec(path);
  const create = path === "/api/conversations";
  const exactResource = !!resource && resource[0] === path && typeof id === "string" && id === resource[1] && validId(id);
  const method = create || resource?.[2] ? "POST" : "GET";
  const allowed = create ? id === undefined && validTarget(body) && body.target_id === target.target_id && body.target_kind === target.target_kind
    : exactResource && (resource?.[2] === "ask" ? validAsk(body) : resource?.[2] === "cancel" ? body === null : body === undefined);
  if (!allowed) throw new ConversationReadError("Invalid local conversation path, identity or request type.");
  let response: Response;
  try {response = await request(path, {method, headers: {"content-type": "application/json"}, ...(body != null ? {body: JSON.stringify(body)} : {}), signal, credentials: "same-origin", cache: "no-store", redirect: "error"});}
  catch {throw new ConversationReadError("Plumb cannot be reached. Check its terminal and browser session, then try again.");}
  if (!response.ok || response.redirected) throw new ConversationReadError("Local question refused. Check the current Plumb session, selected evidence, model readiness and turn limit.");
  if (!response.body || !/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type")?.trim() ?? "")) throw new ConversationReadError("Unreadable conversation response.");
  const length = response.headers.get("content-length");
  if (length && /^\d+$/.test(length) && Number(length) > MAX_CONVERSATION_BYTES) {await response.body.cancel().catch(() => {}); throw new ConversationReadError("Conversation exceeds the workbench limit.");}
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {const {done, value} = await reader.read(); if (done) break; size += value.byteLength; if (size > MAX_CONVERSATION_BYTES) throw new ConversationReadError("Conversation exceeds the workbench limit."); chunks.push(value);}
  } catch (error) {throw error instanceof ConversationReadError ? error : new ConversationReadError("The conversation transfer stopped. Load its saved turns again.");}
  finally {await reader.cancel().catch(() => {}); reader.releaseLock();}
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.byteLength;}
  let value: unknown;
  try {value = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));}
  catch {throw new ConversationReadError("Unreadable conversation response.");}
  const view = parseConversation(value, target, id); await verifyConversationHashes(view); return view;
}
