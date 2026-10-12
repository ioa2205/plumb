import type { ChatAsk, ChatCreate, ChatView, SavedResults } from "../generated/contracts";
import schema from "../generated/chat-view.schema.json" with { type: "json" };
import savedSchema from "../generated/saved-results.schema.json" with { type: "json" };
import { structuralMatches } from "./run-metadata.ts";
import { LocalReadError, localJson } from "./local-json.ts";

export const MAX_CHAT_BYTES = 2 * 1024 * 1024;
export class ChatReadError extends LocalReadError {}
type Turn = NonNullable<ChatView["turns"]>[number];
export type ChatPart = NonNullable<Turn["parts"]>[number];
export type ChatIntent = Turn["intent"];

const identifier = /^chat-[0-9a-f]{32}$/;
const targetIdentifier = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/;
const intents = ["general_question", "creative_writing", "explain_result", "general_and_result", "review_folder", "test_website", "about_plumb", "unclear"];
export const validChatId = (value: string) => identifier.exec(value)?.[0] === value;
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);

function validSelection(value: unknown): value is ChatCreate {
  if (!isRecord(value) || !Object.keys(value).every(key => ["target_kind", "target_id"].includes(key))) return false;
  if (value.target_kind == null && value.target_id == null) return true;
  return typeof value.target_kind === "string" && ["inspection", "review", "assessment", "website"].includes(value.target_kind)
    && typeof value.target_id === "string" && targetIdentifier.exec(value.target_id)?.[0] === value.target_id;
}
function validAsk(value: unknown): value is ChatAsk {
  return isRecord(value) && Object.keys(value).every(key => ["prompt", "profile", "max_seconds", "choice"].includes(key))
    && typeof value.prompt === "string" && !!value.prompt.trim() && value.prompt.length <= 4096
    && (value.profile === undefined || typeof value.profile === "string" && /^(auto|[a-z][a-z0-9._-]{0,95})$/.exec(value.profile)?.[0] === value.profile)
    && (value.max_seconds === undefined || typeof value.max_seconds === "number" && Number.isSafeInteger(value.max_seconds) && value.max_seconds >= 1 && value.max_seconds <= 600)
    && (value.choice === undefined || value.choice === null || typeof value.choice === "string" && intents.includes(value.choice));
}

/** A general part never carries evidence; a cited part always does; nothing was run or approved. */
export function parseChat(value: unknown, id?: string): ChatView {
  if (id !== undefined && !validChatId(id) || !structuralMatches(value, schema)) throw new ChatReadError("This chat cannot be read.");
  const view = value as ChatView;
  if (id !== undefined && view.chat_id !== id) throw new ChatReadError("This chat belongs to a different record.");
  for (const turn of view.turns ?? []) {
    if (turn.authorization_granted || turn.actions_executed || turn.finding_created) throw new ChatReadError("A chat turn may not grant, run or conclude anything.");
    for (const part of turn.parts ?? []) {
      const evidence = part.evidence ?? [];
      if ((part.kind === "cited") !== (evidence.length > 0)) throw new ChatReadError("Only a cited part carries evidence, and it always does.");
      if (new Set(evidence.map(item => item.reference_id)).size !== evidence.length) throw new ChatReadError("A cited part repeats an evidence reference.");
      for (const item of evidence) if ((item.source != null) === (item.observation != null)) throw new ChatReadError("An evidence item has exactly one kind of citation.");
    }
    if (turn.task && (turn.task.authorization_granted || turn.task.started)) throw new ChatReadError("A proposal starts nothing.");
  }
  return view;
}

async function verifyQuotes(view: ChatView): Promise<void> {
  for (const turn of view.turns ?? []) for (const part of turn.parts ?? []) for (const item of part.evidence ?? []) {
    const expected = item.observation?.sha256 ?? item.source?.content_sha256;
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(item.quote));
    const actual = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
    if (expected !== actual) throw new ChatReadError("A quote does not match its exact evidence hash.");
  }
}

export async function chatRequest(path: string, body: ChatAsk | ChatCreate | null | undefined, signal: AbortSignal, id?: string, request: typeof fetch = fetch): Promise<ChatView> {
  const resource = /^\/api\/chats\/(chat-[0-9a-f]{32})(?:\/(ask|cancel|select))?$/.exec(path);
  const create = path === "/api/chats";
  const exact = !!resource && resource[0] === path && typeof id === "string" && id === resource[1] && validChatId(id);
  const action = resource?.[2];
  const allowed = create ? id === undefined && validSelection(body)
    : exact && (action === "ask" ? validAsk(body) : action === "select" ? validSelection(body) : action === "cancel" ? body === null : body === undefined);
  if (!allowed) throw new ChatReadError("Invalid chat path, identity or request.");
  const view = parseChat(await localJson(path, create || action ? "POST" : "GET", body, signal, MAX_CHAT_BYTES, request), id);
  await verifyQuotes(view);
  return view;
}

export async function savedResults(signal: AbortSignal, request: typeof fetch = fetch): Promise<SavedResults> {
  const value = await localJson("/api/chats/saved-results", "GET", undefined, signal, 64 * 1024, request);
  if (!structuralMatches(value, savedSchema)) throw new ChatReadError("The list of saved results cannot be read.");
  return value as SavedResults;
}

export function selectedChat(search: string): string | null {
  const values = new URLSearchParams(search).getAll("chat");
  if (!values.length) return null;
  if (values.length !== 1 || !validChatId(values[0]!)) throw new ChatReadError("Use one valid chat ID.");
  return values[0]!;
}

const rungs: Record<Turn["intent_rung"], string> = {
  code: "decided by code",
  model: "decided by the local model",
  model_reordered: "decided by the local model on a second, independent try",
  user: "your choice",
  stop: "not decided",
};
export const rungWords = (rung: Turn["intent_rung"]): string => rungs[rung];

const headings: Record<ChatPart["kind"], string> = {
  general: "General answer",
  guidance: "From reviewed guidance",
  cited: "From the selected result",
  notice: "Note",
};
export const partHeading = (part: ChatPart): string => headings[part.kind] + (part.complete === false ? " · stopped at its length limit" : "");
