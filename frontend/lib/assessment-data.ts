import type { AccessExpectation, AssessmentAnswer, AssessmentChecklist, AssessmentScope, AssessmentView, ComparisonRequest, EvidenceImportRequest, LabCollectionImportRequest, ObservationComparison, ObservedMap, PrivateReportRequest, ReportPreview, ScopeCreate, TaskResolveRequest } from "../generated/contracts";
import scopeSchema from "../generated/assessment-scope.schema.json" with { type: "json" };
import viewSchema from "../generated/assessment-view.schema.json" with { type: "json" };
import answerSchema from "../generated/assessment-answer.schema.json" with { type: "json" };
import mapSchema from "../generated/observed-map.schema.json" with { type: "json" };
import checklistSchema from "../generated/assessment-checklist.schema.json" with { type: "json" };
import comparisonSchema from "../generated/observation-comparison.schema.json" with { type: "json" };
import reportSchema from "../generated/report-preview.schema.json" with { type: "json" };
import { structuralMatches } from "./run-metadata.ts";

export const MAX_ASSESSMENT_BYTES = 4 * 1024 * 1024;
export const MAX_IMPORT_BYTES = 2 * 1024 * 1024;
export class AssessmentReadError extends Error {}
const idPattern = new RegExp(scopeSchema.properties.assessment_id.pattern);
export function validAssessmentId(id: string): boolean { return idPattern.exec(id)?.[0] === id; }
export function selectedAssessment(search: string): string | null {
  const ids = new URLSearchParams(search).getAll("assessment");
  if (!ids.length) return null;
  if (ids.length !== 1 || !validAssessmentId(ids[0]!)) throw new AssessmentReadError("Enter one assessment ID from a saved local assessment.");
  return ids[0]!;
}
export function parseScope(value: unknown): AssessmentScope {
  if (!structuralMatches(value, scopeSchema)) throw new AssessmentReadError("The scope does not match the assessment contract. Check its IDs, authority, paths, roles and budgets.");
  const scope = value as AssessmentScope;
  if (!validAssessmentId(scope.assessment_id) || scope.external_access_enabled !== false) throw new AssessmentReadError("This scope cannot enable external website access.");
  if (scope.authority.granted_by.startsWith("Replace with") || scope.authority.reference.startsWith("Replace with")) throw new AssessmentReadError("Replace the example's authority fields with the actual authorizing person and explicit limits before confirming it.");
  return scope;
}
type Citation = NonNullable<AssessmentAnswer["citations"]>[number];
export function citationsResolve(citations: ReadonlyArray<Citation>, view: AssessmentView): boolean {
  return citations.every(citation => {
    const artifact = view.artifacts?.find(item => item.artifact_id === citation.artifact_id);
    return !!artifact && Object.hasOwn(artifact.fields, citation.field);
  });
}
export async function verifyCitationHashes(citations: ReadonlyArray<Citation>, view: AssessmentView): Promise<void> {
  if (!citationsResolve(citations, view)) throw new AssessmentReadError("An evidence citation does not resolve to its saved field.");
  const matches = await Promise.all(citations.map(async citation => {
    const artifact = view.artifacts!.find(item => item.artifact_id === citation.artifact_id)!;
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(artifact.fields[citation.field]!));
    return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("") === citation.sha256;
  }));
  if (matches.some(value => !value)) throw new AssessmentReadError("A cited evidence field no longer matches its saved hash.");
}
export function parseAssessment(value: unknown, id: string): AssessmentView {
  if (!validAssessmentId(id) || !structuralMatches(value, viewSchema)) throw new AssessmentReadError("The assessment record cannot be read. Check its ID and local backend.");
  const view = value as AssessmentView;
  const artifactIds = (view.artifacts ?? []).map(item => item.artifact_id);
  if (view.scope.assessment_id !== id || new Set(artifactIds).size !== artifactIds.length
      || view.artifacts?.some(item => item.assessment_id !== id || Object.values(item.fields).some(field => typeof field !== "string"))
      || view.answers?.some(answer => answer.task.target_id !== id || !citationsResolve(answer.citations ?? [], view))
      || view.comparisons?.some(comparison => !citationsResolve(comparison.citations ?? [], view))
      || !!view.stopped !== !!view.stop_reason) throw new AssessmentReadError("The assessment has inconsistent evidence or stop state. Read the local saved record.");
  return view;
}
function parseBound<T>(value: unknown, schema: unknown, id: string): T {
  if (!validAssessmentId(id) || !structuralMatches(value, schema) || !value || typeof value !== "object" || !("assessment_id" in value) || value.assessment_id !== id) throw new AssessmentReadError("Plumb returned a mismatched assessment record.");
  return value as T;
}
export function parseAnswer(value: unknown, view: AssessmentView): AssessmentAnswer {
  if (!structuralMatches(value, answerSchema)) throw new AssessmentReadError("The resolved task cannot be read.");
  const answer = value as AssessmentAnswer;
  if (answer.task.target_id !== view.scope.assessment_id || !citationsResolve(answer.citations ?? [], view)) throw new AssessmentReadError("The answer does not cite this assessment's saved evidence.");
  return answer;
}
export function parseObservedMap(value: unknown, view: AssessmentView): ObservedMap {
  const map = parseBound<ObservedMap>(value, mapSchema, view.scope.assessment_id);
  if (map.endpoints?.some(endpoint => !citationsResolve(endpoint.citations, view))) throw new AssessmentReadError("The map has unresolved evidence citations.");
  return map;
}
export function parseChecklist(value: unknown, id: string): AssessmentChecklist { return parseBound<AssessmentChecklist>(value, checklistSchema, id); }
export function parseReportPreview(value: unknown, view: AssessmentView): ReportPreview {
  if (!structuralMatches(value, reportSchema)) throw new AssessmentReadError("The private report preview cannot be read.");
  const preview = value as ReportPreview;
  if (preview.report.assessment_id !== view.scope.assessment_id || preview.report.claims.some(claim => !citationsResolve(claim.citations, view)) || preview.report.comparisons.some(comparison => !citationsResolve(comparison.citations ?? [], view))) throw new AssessmentReadError("The report has mismatched or unresolved evidence. Check the saved local assessment.");
  return preview;
}
function endpoint(id: string, suffix = ""): string {
  if (!validAssessmentId(id)) throw new AssessmentReadError("Enter a valid saved assessment ID first.");
  return `/api/assessments/${encodeURIComponent(id)}${suffix}`;
}
const post = (body: unknown): RequestInit => ({method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
export async function readAssessmentJson(path: string, signal: AbortSignal, init: RequestInit = {}, request: typeof fetch = fetch): Promise<unknown> {
  const parts = /^\/api\/assessments\/([^/]+)(?:\/(imports|expectations|prompt|map|checklist|comparisons|report|analyze|collections\/import|actions\/(?:preview|run)))?$/.exec(path);
  const job = /^\/api\/assessment-jobs\/([^/]+)(?:\/cancel)?$/.exec(path);
  let permitted = path === "/api/assessments" || path === "/api/projects/prompt";
  try { permitted ||= !!parts && validAssessmentId(decodeURIComponent(parts[1]!)) && ![".", ".."].includes(parts[1]!) || !!job && validAssessmentId(decodeURIComponent(job[1]!)) && ![".", ".."].includes(job[1]!); } catch { permitted = false; }
  if (!permitted) throw new AssessmentReadError("Only the local assessment API can be called.");
  let response: Response;
  try { response = await request(path, {...init, signal, credentials: "same-origin", cache: "no-store", redirect: "error"}); }
  catch { throw new AssessmentReadError("Plumb cannot be reached. Check its terminal and browser session, then try again."); }
  if (response.status === 401 || response.status === 403) throw new AssessmentReadError("Open the one-time Plumb link printed in the terminal to connect this browser session.");
  if (response.status === 409) throw new AssessmentReadError("The assessment is stopped, expired or another worker is running. Check the local saved scope and status.");
  if (!response.ok) throw new AssessmentReadError("This action was refused or could not complete. Check the scope, sanitized input and saved assessment in the terminal.");
  if (!response.body || !response.headers.get("content-type")?.startsWith("application/json")) throw new AssessmentReadError("Plumb returned an unreadable assessment record.");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) { const {done, value} = await reader.read(); if (done) break; size += value.byteLength; if (size > MAX_ASSESSMENT_BYTES) throw new AssessmentReadError("The assessment is too large for the workbench. Read its private local report."); chunks.push(value); }
  } catch (error) { throw error instanceof AssessmentReadError ? error : new AssessmentReadError("The assessment transfer stopped. Try loading it again."); }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes)); }
  catch { throw new AssessmentReadError("Plumb returned an unreadable assessment record."); }
}
async function verifiedView(value: unknown, id: string): Promise<AssessmentView> {
  const view = parseAssessment(value, id);
  await verifyCitationHashes([...(view.answers ?? []).flatMap(answer => answer.citations ?? []), ...(view.comparisons ?? []).flatMap(comparison => comparison.citations ?? [])], view);
  return view;
}
export async function fetchAssessment(id: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentView> { return verifiedView(await readAssessmentJson(endpoint(id), signal, {}, request), id); }
export async function createAssessment(scope: AssessmentScope, confirmed: boolean, signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentView> {
  if (!confirmed) throw new AssessmentReadError("Confirm the recorded authority before creating the scope.");
  const body: ScopeCreate = {scope: parseScope(scope), confirmed_authority: true};
  return verifiedView(await readAssessmentJson("/api/assessments", signal, post(body), request), scope.assessment_id);
}
export async function importEvidence(view: AssessmentView, payload: string, review: EvidenceImportRequest["review"], signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentView> {
  if (!payload.trim() || new TextEncoder().encode(payload).byteLength > MAX_IMPORT_BYTES || !review.confirmed_sanitized || !review.reviewed_by.trim()) throw new AssessmentReadError("Import a bounded attachment only after a named human review of its sanitization.");
  return verifiedView(await readAssessmentJson(endpoint(view.scope.assessment_id, "/imports"), signal, post({payload, review} satisfies EvidenceImportRequest), request), view.scope.assessment_id);
}
export async function importReviewedCollection(view: AssessmentView, previewSha256: string, review: EvidenceImportRequest["review"], signal: AbortSignal, request: typeof fetch = fetch, prepareWebsiteComparisons = false): Promise<AssessmentView> {
  if (!/^[0-9a-f]{64}$/.test(previewSha256) || !review.confirmed_sanitized || !review.reviewed_by.trim()) throw new AssessmentReadError("Review the sanitized collected observations before importing the saved lab trace.");
  const input: LabCollectionImportRequest = {preview_sha256: previewSha256, review, ...(prepareWebsiteComparisons ? {prepare_website_comparisons: true} : {})};
  return verifiedView(await readAssessmentJson(endpoint(view.scope.assessment_id, "/collections/import"), signal, post(input), request), view.scope.assessment_id);
}
export async function resolveAssessmentTask(view: AssessmentView, input: TaskResolveRequest, signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentAnswer> {
  if (!input.prompt.trim() || input.prompt.length > 4096 || input.evidence_ids?.some(id => !view.artifacts?.some(artifact => artifact.artifact_id === id))) throw new AssessmentReadError("Enter a bounded prompt and select artifacts from this saved assessment.");
  const answer = parseAnswer(await readAssessmentJson(endpoint(view.scope.assessment_id, "/prompt"), signal, post(input), request), view);
  await verifyCitationHashes(answer.citations ?? [], view); return answer;
}
export async function fetchAssessmentMap(view: AssessmentView, signal: AbortSignal, request: typeof fetch = fetch): Promise<ObservedMap> { const map = parseObservedMap(await readAssessmentJson(endpoint(view.scope.assessment_id, "/map"), signal, {}, request), view); await verifyCitationHashes((map.endpoints ?? []).flatMap(endpoint => endpoint.citations), view); return map; }
export async function fetchAssessmentChecklist(id: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentChecklist> { return parseChecklist(await readAssessmentJson(endpoint(id, "/checklist"), signal, {}, request), id); }
export async function saveExpectation(view: AssessmentView, expectation: AccessExpectation, signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentView> { return verifiedView(await readAssessmentJson(endpoint(view.scope.assessment_id, "/expectations"), signal, post(expectation), request), view.scope.assessment_id); }
export async function compareObservations(view: AssessmentView, input: ComparisonRequest, signal: AbortSignal, request: typeof fetch = fetch): Promise<ObservationComparison> {
  const result = await readAssessmentJson(endpoint(view.scope.assessment_id, "/comparisons"), signal, post(input), request);
  if (!structuralMatches(result, comparisonSchema)) throw new AssessmentReadError("The comparison cannot be read.");
  const comparison = result as ObservationComparison;
  if (!citationsResolve(comparison.citations ?? [], view)) throw new AssessmentReadError("The comparison has unresolved evidence citations.");
  await verifyCitationHashes(comparison.citations ?? [], view);
  return comparison;
}
export async function fetchAssessmentReport(view: AssessmentView, signal: AbortSignal, exportRequest?: PrivateReportRequest, request: typeof fetch = fetch): Promise<ReportPreview> {
  if (exportRequest && (!exportRequest.review.confirmed_sanitized || !exportRequest.review.reviewed_by.trim() || !/^[0-9a-f]{64}$/.test(exportRequest.preview_sha256))) throw new AssessmentReadError("Review this exact sanitized preview before saving a private report.");
  const preview = parseReportPreview(await readAssessmentJson(endpoint(view.scope.assessment_id, "/report"), signal, exportRequest ? post(exportRequest) : {}, request), view);
  if (exportRequest && preview.preview_sha256 !== exportRequest.preview_sha256) throw new AssessmentReadError("The report changed after human review. Read and review the new preview before exporting.");
  await verifyCitationHashes([...preview.report.claims.flatMap(claim => claim.citations), ...preview.report.comparisons.flatMap(comparison => comparison.citations ?? [])], view);
  return preview;
}
