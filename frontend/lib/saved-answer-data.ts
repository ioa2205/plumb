import type { CaseDetail, SavedAnswerRequest, SavedFindingAnswer } from "../generated/contracts";
import schema from "../generated/saved-finding-answer.schema.json" with { type: "json" };
import { structuralMatches, validRunId } from "./run-metadata.ts";

export class SavedAnswerError extends Error {}
export function parseSavedAnswer(value: unknown, detail: CaseDetail): SavedFindingAnswer {
  if (!structuralMatches(value, schema)) throw new SavedAnswerError("The saved evidence answer cannot be read.");
  const answer = value as SavedFindingAnswer;
  if (answer.run_id !== detail.run.id || answer.finding.id !== detail.finding.id || answer.finding.snapshot_id !== detail.run.snapshot_id
      || answer.finding.conclusion !== detail.finding.conclusion || answer.finding.runtime_verification !== detail.finding.runtime_verification
      || answer.finding.title !== detail.finding.title || answer.finding.lede !== detail.finding.lede
      || JSON.stringify(answer.finding.gaps ?? []) !== JSON.stringify(detail.finding.gaps ?? []) || JSON.stringify(answer.finding.unknowns ?? []) !== JSON.stringify(detail.finding.unknowns ?? [])
      || answer.finding.exhibits.length !== detail.finding.exhibits.length
      || answer.finding.exhibits.some(exhibit => !detail.finding.exhibits.some(saved => saved.tag === exhibit.tag && saved.span.content_sha256 === exhibit.span.content_sha256 && saved.span.path === exhibit.span.path && saved.span.start_line === exhibit.span.start_line && saved.span.end_line === exhibit.span.end_line))) throw new SavedAnswerError("The answer does not match this saved finding and its evidence.");
  return answer;
}
export async function askSavedFinding(detail: CaseDetail, prompt: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<SavedFindingAnswer> {
  if (!validRunId(detail.run.id) || !prompt.trim() || prompt.length > 4096) throw new SavedAnswerError("Enter a bounded question about this saved finding.");
  const body: SavedAnswerRequest = {prompt: prompt.trim()}; let response: Response;
  try {response = await request(`/api/runs/${encodeURIComponent(detail.run.id)}/ask`, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body), signal, credentials: "same-origin", cache: "no-store", redirect: "error"});}
  catch {throw new SavedAnswerError("Plumb cannot be reached. Check its terminal and current browser session.");}
  if (response.status === 401 || response.status === 403) throw new SavedAnswerError("Open the one-time Plumb browser link printed in the terminal.");
  if (!response.ok) throw new SavedAnswerError("Name this saved finding and ask to explain its evidence or limitations. Check that the saved report remains available.");
  if (!response.body || !response.headers.get("content-type")?.startsWith("application/json")) throw new SavedAnswerError("Plumb returned an unreadable saved answer.");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {while (true) {const {done, value} = await reader.read(); if (done) break; size += value.byteLength; if (size > 1024 * 1024) throw new SavedAnswerError("This answer exceeds the workbench limit. Read its saved report."); chunks.push(value);}}
  catch (error) {throw error instanceof SavedAnswerError ? error : new SavedAnswerError("The saved answer transfer stopped. Try again.");}
  finally {await reader.cancel().catch(() => {}); reader.releaseLock();}
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.byteLength;}
  try {return parseSavedAnswer(JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes)), detail);}
  catch (error) {throw error instanceof SavedAnswerError ? error : new SavedAnswerError("The saved evidence answer cannot be read.");}
}
