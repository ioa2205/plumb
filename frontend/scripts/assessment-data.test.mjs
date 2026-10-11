import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseAssessment, parseScope, parseAnswer, parseObservedMap, parseChecklist, parseReportPreview, selectedAssessment, createAssessment, fetchAssessment, importEvidence, resolveAssessmentTask, fetchAssessmentReport, verifyCitationHashes, MAX_IMPORT_BYTES, MAX_ASSESSMENT_BYTES, readAssessmentJson, importReviewedCollection } from "../lib/assessment-data.ts";
import { parseAssessmentJob, parseLabPreview, runLabActions, readAssessmentJob } from "../lib/assessment-jobs.ts";
import { parseSourcePrompt, resolveSourcePrompt } from "../lib/setup-data.ts";
import { parseSavedAnswer, askSavedFinding } from "../lib/saved-answer-data.ts";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/assessment-views.json", import.meta.url), "utf8"));
const saved = JSON.parse(readFileSync(new URL("./fixtures/archived-peer-case.json", import.meta.url), "utf8"));
const inspection = {...JSON.parse(readFileSync(new URL("./fixtures/setup-views.json", import.meta.url), "utf8")).inspection, inspection_id: "inspect-" + "a".repeat(32)};
const signal = () => new AbortController().signal;
const clone = value => structuredClone(value);
const view = fixture.view;
const assessmentId = view.scope.assessment_id;

test("synthetic imported observations keep scope, fields, context, plans and report limits", async () => {
  assert.match(fixture.label, /Synthetic/);
  assert.equal(parseScope(view.scope).external_access_enabled, false);
  assert.equal(parseAssessment(view, assessmentId).scope.assessment_id, assessmentId);
  assert.equal(parseAnswer(fixture.answer, view).task.authorization_granted, false);
  assert.equal(parseObservedMap(fixture.map, view).collection_performed, false);
  assert.equal(parseChecklist(fixture.checklist, assessmentId).execution_status, "plan_only");
  const report = parseReportPreview(fixture.preview, view);
  assert.equal(report.report.runtime_verification, "not_attempted");
  assert.equal(report.submitted, false);
  assert.equal(fixture.comparison.conclusion, "candidate");
  await verifyCitationHashes(fixture.answer.citations, view);
  await verifyCitationHashes(fixture.comparison.citations, view);
  for (const claim of fixture.preview.report.claims) await verifyCitationHashes(claim.citations, view);
});

test("forged assessment scope, artifact identity, active evidence and citations fail closed", async () => {
  for (const change of [value => value.scope.assessment_id = "another", value => value.artifacts[0].assessment_id = "another", value => value.artifacts.push(value.artifacts[0]), value => value.artifacts[0].execution_status = "reproduced", value => value.scope.external_access_enabled = true, value => value.answers[0].task.authorization_granted = true, value => value.stopped = true]) {
    const value = clone(view); change(value); assert.throws(() => parseAssessment(value, assessmentId));
  }
  const answer = clone(fixture.answer); answer.citations[0].field = "invented.field"; assert.throws(() => parseAnswer(answer, view));
  const badHash = clone(fixture.answer.citations); badHash[0].sha256 = "0".repeat(64); await assert.rejects(verifyCitationHashes(badHash, view), /hash/);
  const report = clone(fixture.preview); report.report.runtime_verification = "reproduced"; assert.throws(() => parseReportPreview(report, view));
  const map = clone(fixture.map); map.collection_performed = true; assert.throws(() => parseObservedMap(map, view));
  for (const value of ["?assessment=../escape", "?assessment=x&assessment=y", "?assessment=", "?assessment=%3Cscript%3E"]) assert.throws(() => selectedAssessment(value));
  assert.equal(selectedAssessment(""), null); assert.equal(selectedAssessment(`?assessment=${assessmentId}`), assessmentId);
});

test("only bounded same-origin local API traffic is emitted; private errors remain private", async () => {
  let calls = 0;
  const request = async (url, options) => {calls++; assert.equal(url, `/api/assessments/${assessmentId}`); assert.equal(options.credentials, "same-origin"); assert.equal(options.redirect, "error"); assert.equal(options.cache, "no-store"); return Response.json(view);};
  assert.equal((await fetchAssessment(assessmentId, signal(), request)).scope.assessment_id, assessmentId);
  for (const path of ["https://example.invalid/", "/api/assessments/../report", "/api/assessments/%2E%2E/report", "/api/assessments/test?url=https://other.invalid", "/api/runs/secret"]) await assert.rejects(readAssessmentJson(path, signal(), {}, request));
  assert.equal(calls, 1);
  for (const status of [401, 403, 409, 422, 500]) await assert.rejects(fetchAssessment(assessmentId, signal(), async () => new Response("private sensitive server detail", {status})), error => !error.message.includes("private sensitive"));
  await assert.rejects(fetchAssessment(assessmentId, signal(), async () => {throw new Error("private transport");}), error => !error.message.includes("private transport"));
  await assert.rejects(fetchAssessment(assessmentId, signal(), async () => new Response("x".repeat(MAX_ASSESSMENT_BYTES + 1), {headers: {"content-type": "application/json"}})), /too large/);
  await assert.rejects(fetchAssessment(assessmentId, signal(), async () => Response.json({...view, scope: {...view.scope, assessment_id: "another"}})), /inconsistent/);
});

test("scope creation/import/export need separate authority and named attachment review", async () => {
  let calls = 0; const reviewed = {reviewed_by: "Synthetic reviewer", confirmed_sanitized: true, reviewed_at: new Date().toISOString()};
  const request = async (url, options) => {calls++; const input = JSON.parse(options.body); if (url === "/api/assessments") {assert.deepEqual(input, {scope: view.scope, confirmed_authority: true}); return Response.json(view);} assert.deepEqual(input.review, reviewed); return Response.json(url.endsWith("/report") ? fixture.preview : view);};
  await assert.rejects(createAssessment(view.scope, false, signal(), request));
  await createAssessment(view.scope, true, signal(), request);
  await assert.rejects(importEvidence(view, "{}", {...reviewed, confirmed_sanitized: false}, signal(), request));
  await assert.rejects(importEvidence(view, "x".repeat(MAX_IMPORT_BYTES + 1), reviewed, signal(), request));
  await importEvidence(view, "{}", reviewed, signal(), request);
  await fetchAssessmentReport(view, signal(), {review:reviewed,preview_sha256:fixture.preview.preview_sha256}, request);
  await assert.rejects(fetchAssessmentReport(view, signal(), {review:reviewed,preview_sha256:fixture.preview.preview_sha256}, async () => Response.json({...fixture.preview, preview_sha256: "0".repeat(64)})), /changed after human review/);
  await importReviewedCollection(view, "a".repeat(64), reviewed, signal(), request);
  assert.equal(calls, 4);
});

test("prompt tasks cite current artifacts and cannot invent targets or authority", async () => {
  let calls = 0;
  const input = {prompt: "What evidence is missing?", evidence_ids: ["E-owner", "E-other"], budget: view.scope.budget};
  const request = async (url, options) => {calls++; assert.equal(url, `/api/assessments/${assessmentId}/prompt`); assert.deepEqual(JSON.parse(options.body), input); return Response.json(fixture.answer);};
  await resolveAssessmentTask(view, input, signal(), request);
  await assert.rejects(resolveAssessmentTask(view, {...input, evidence_ids: ["E-invented"]}, signal(), request));
  assert.equal(calls, 1);
  const result = clone(fixture.answer); result.task.target_id = "another"; await assert.rejects(resolveAssessmentTask(view, input, signal(), async () => Response.json(result)));
});

test("source prompt resolution uses the inspected target and refuses stale routes", async () => {
  const resolution = {target_id: inspection.inspection_id, task_id: "source-task-" + "b".repeat(24), prompt: "Review this project for order ownership problems", families: ["authorization"], resources: ["Order"], routes: [], limit: 2, status: "resolved", clarification: null, authorization_granted: false, network_activity: false};
  assert.equal(parseSourcePrompt(resolution, inspection).limit, 2);
  for (const change of [{target_id: "another"}, {routes: ["/invented"]}, {network_activity: true}, {authorization_granted: true}]) assert.throws(() => parseSourcePrompt({...resolution, ...change}, inspection));
  await resolveSourcePrompt(inspection, resolution.prompt, 2, signal(), async (url, options) => {assert.equal(url, "/api/projects/prompt"); assert.equal(options.redirect, "error"); assert.deepEqual(JSON.parse(options.body), {inspection_id: inspection.inspection_id, prompt: resolution.prompt, limit: 2}); return Response.json(resolution);});
});

test("local worker states, exact action previews, explicit permission and cancellation stay separate", async () => {
  const job = {job_id: "job-synthetic", assessment_id: assessmentId, action: "collect", state: "running", created_at: "2026-10-10T00:00:00Z", ended_at: null, result: null, message: "Synthetic local worker fixture"};
  assert.equal(parseAssessmentJob(job, assessmentId).state, "running");
  for (const change of [{assessment_id: "another"}, {state: "completed"}, {result: {claim: "unrun"}}, {ended_at: "2026-10-10T00:00:01Z"}]) assert.throws(() => parseAssessmentJob({...job, ...change}, assessmentId));
  assert.equal(parseLabPreview(fixture.lab_preview, view).preview.actions.length, 9);
  assert.equal(fixture.lab_preview.preview.actions.reduce((total, action) => total + action.max_attempts, 0), 12);
  const overBudget = {...view, scope: {...view.scope, budget: {...view.scope.budget, max_requests: 11}}};
  assert.throws(() => parseLabPreview(fixture.lab_preview, overBudget), /budget/);
  for (const change of [value => value.preview.assessment_id = "another", value => value.preview.actions[0].path = "//escape.invalid", value => value.preview.actions.push(value.preview.actions[0]), value => value.preview.max_requests += 1, value => value.preview.external_access_enabled = true]) {const value = clone(fixture.lab_preview); change(value); assert.throws(() => parseLabPreview(value, view));}
  let calls = 0;
  const request = async (url, options) => {calls++; assert.equal(url, `/api/assessments/${assessmentId}/actions/run`); const input = JSON.parse(options.body); assert.equal(input.permission.reviewed_preview, true); assert.equal(input.permission.preview_sha256, fixture.lab_preview.preview_sha256); assert.deepEqual(input.permission.approved_action_ids, fixture.lab_preview.preview.actions.map(action => action.action_id)); return Response.json(job);};
  await assert.rejects(runLabActions(view, fixture.lab_preview, false, "Owner", signal(), request));
  await runLabActions(view, fixture.lab_preview, true, "Owner", signal(), request); assert.equal(calls, 1);
  await readAssessmentJob(job.job_id, assessmentId, signal(), true, async (url, options) => {assert.equal(url, "/api/assessment-jobs/job-synthetic/cancel"); assert.equal(options.method, "POST"); assert.deepEqual(JSON.parse(options.body), {}); return Response.json(job);});
});

test("saved follow-up answers preserve the selected finding, source hash and recorded verdict", async () => {
  const result = {run_id: saved.run.id, prompt: `Explain ${saved.finding.display_id}`, finding: saved.finding, report_path: "Synthetic saved path", limitations: saved.limitations, generated_by: "saved_evidence", network_activity: false, authorization_granted: false};
  assert.equal(parseSavedAnswer(result, saved).finding.conclusion, saved.finding.conclusion);
  for (const change of [{run_id: "another"}, {authorization_granted: true}, {network_activity: true}, {finding: {...saved.finding, conclusion: "rejected"}}, {finding: {...saved.finding, unknowns: ["Invented certainty"]}}, {finding: {...saved.finding, snapshot_id: "0".repeat(64)}}]) assert.throws(() => parseSavedAnswer({...result, ...change}, saved));
  await askSavedFinding(saved, result.prompt, signal(), async (url, options) => {assert.equal(url, `/api/runs/${saved.run.id}/ask`); assert.equal(options.redirect, "error"); return Response.json(result);});
  for (const status of [401, 403, 422, 500]) await assert.rejects(askSavedFinding(saved, result.prompt, signal(), async () => new Response("private secret", {status})), error => !error.message.includes("private secret"));
});
