import type { AssessmentJob, AssessmentView, LabActionPreview, LabActionPreviewRequest, LabActionRunRequest, ObservationAnalysisRequest } from "../generated/contracts";
import jobSchema from "../generated/assessment-job.schema.json" with { type: "json" };
import previewSchema from "../generated/lab-action-preview.schema.json" with { type: "json" };
import { structuralMatches } from "./run-metadata.ts";
import { AssessmentReadError, readAssessmentJson, validAssessmentId } from "./assessment-data.ts";
import { validProfile } from "./model-choices.ts";

const post = (body: unknown): RequestInit => ({method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
function endpoint(id: string, suffix: string): string {if (!validAssessmentId(id)) throw new AssessmentReadError("Open a saved assessment first."); return `/api/assessments/${encodeURIComponent(id)}${suffix}`;}
export function parseAssessmentJob(value: unknown, id: string): AssessmentJob {
  if (!structuralMatches(value, jobSchema)) throw new AssessmentReadError("The local worker status cannot be read.");
  const job = value as AssessmentJob; const finished = ["completed", "canceled", "failed"].includes(job.state);
  if (job.assessment_id !== id || !validAssessmentId(job.job_id) || finished !== !!job.ended_at || !finished && job.result != null) throw new AssessmentReadError("The local worker status has inconsistent identity or lifecycle.");
  return job;
}
export function parseLabPreview(value: unknown, view: AssessmentView): LabActionPreview {
  if (!structuralMatches(value, previewSchema)) throw new AssessmentReadError("The owned-lab action preview cannot be read.");
  const preview = value as LabActionPreview; const actions = preview.preview.actions; const ids = actions.map(action => action.action_id);
  const attempts = actions.reduce((total, action) => total + (action.max_attempts ?? 1), 0);
  if (preview.preview.assessment_id !== view.scope.assessment_id || new Set(ids).size !== ids.length || ![6, 9].includes(actions.length)
      || attempts > (view.scope.budget?.max_requests ?? 3) || preview.preview.max_requests !== attempts || preview.preview.max_requests > (view.scope.budget?.max_requests ?? 3)
      || actions.some(action => !action.path.startsWith("/") || action.path.startsWith("//") || action.path.includes("\\") || action.path.includes("..") || /[\u0000-\u001f]/u.test(action.path))
      || Date.parse(preview.preview.expires_at) > Date.parse(view.scope.expires_at)) throw new AssessmentReadError("The action preview does not match this owned-lab scope and budget.");
  return preview;
}
export async function startObservationAnalysis(view: AssessmentView, comparisonId: string, signal: AbortSignal, request: typeof fetch = fetch, profile = "auto"): Promise<AssessmentJob> {
  if (!validProfile(profile)) throw new AssessmentReadError("Choose a registered local model profile.");
  if (!view.comparisons?.some(item => item.comparison_id === comparisonId)) throw new AssessmentReadError("Select a saved comparison from this assessment.");
  const input: ObservationAnalysisRequest = {comparison_id: comparisonId, profile};
  const job = parseAssessmentJob(await readAssessmentJson(endpoint(view.scope.assessment_id, "/analyze"), signal, post(input), request), view.scope.assessment_id);
  if (job.action !== "analyze") throw new AssessmentReadError("The worker did not start the selected analysis."); return job;
}
export async function prepareLabActions(view: AssessmentView, paired: boolean, signal: AbortSignal, request: typeof fetch = fetch): Promise<LabActionPreview> {
  const input: LabActionPreviewRequest = {paired};
  return parseLabPreview(await readAssessmentJson(endpoint(view.scope.assessment_id, "/actions/preview"), signal, post(input), request), view);
}
export async function runLabActions(view: AssessmentView, preview: LabActionPreview, approved: boolean, approvedBy: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentJob> {
  if (!approved || !approvedBy.trim() || approvedBy.length > 256 || Date.parse(preview.preview.expires_at) <= Date.now()) throw new AssessmentReadError("Review the current exact action preview and name its approving person before running it.");
  parseLabPreview(preview, view);
  const now = new Date();
  const input: LabActionRunRequest = {preview_sha256: preview.preview_sha256, permission: {preview_sha256: preview.preview_sha256, approved_action_ids: preview.preview.actions.map(action => action.action_id), approved_by: approvedBy.trim(), granted_at: now.toISOString(), expires_at: preview.preview.expires_at, reviewed_preview: true}};
  const job = parseAssessmentJob(await readAssessmentJson(endpoint(view.scope.assessment_id, "/actions/run"), signal, post(input), request), view.scope.assessment_id);
  if (job.action !== "collect") throw new AssessmentReadError("The worker did not start the reviewed lab collection."); return job;
}
export async function readAssessmentJob(id: string, assessmentId: string, signal: AbortSignal, cancel = false, request: typeof fetch = fetch): Promise<AssessmentJob> {
  if (!validAssessmentId(id) || !validAssessmentId(assessmentId)) throw new AssessmentReadError("Open a valid local worker status first.");
  const job = parseAssessmentJob(await readAssessmentJson(`/api/assessment-jobs/${encodeURIComponent(id)}${cancel ? "/cancel" : ""}`, signal, cancel ? post({}) : {}, request), assessmentId);
  if (job.job_id !== id) throw new AssessmentReadError("The worker status returned a different job."); return job;
}
