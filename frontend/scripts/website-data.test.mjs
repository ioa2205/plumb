import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { activityCounts, parseJourney, rungWords, selectedJourney, statusWords, stepWords, waitWords, websiteList, websiteReadiness, websiteReport, websiteRequest, MAX_REPORT_BYTES } from "../lib/website-data.ts";

const fixtures = () => JSON.parse(readFileSync(new URL("./fixtures/website-views.json", import.meta.url), "utf8"));
const id = fixtures().done.journey_id; const other = "journey-" + "d".repeat(32);
const signal = () => new AbortController().signal;
const json = value => Response.json(value);

test("a real practice-site journey is read with its plan, activity and exact counts", () => {
  const {planned, waiting, done} = fixtures();
  const first = parseJourney(planned, id);
  assert.equal(statusWords(first), "Waiting for your approval");
  assert.deepEqual(activityCounts(first), {done: 0, steps: 13, pages: 0, checks: 0, supported: 0, leads: 0, blocked: 0});
  assert.match(waitWords(first), /^The local model may be asked up to \d+ closed questions: up to about \d+ minutes\. That wait is an upper limit, not a measurement on this computer\.$/);
  assert.equal(first.plan.steps.filter(step => step.state_changing).length, 1);
  const paused = parseJourney(waiting, id);
  assert.equal(statusWords(paused), "Paused"); assert.equal(paused.waiting.length, 1);
  assert.equal(paused.waiting[0].choices.some(choice => choice.label === "display_name"), true);
  const view = parseJourney(done, id);
  assert.equal(statusWords(view), "Finished");
  const counts = activityCounts(view);
  assert.equal(counts.done, counts.steps); assert.equal(counts.checks, 4);
  // No model ran for this fixture, so the complete comparisons stay leads.
  assert.equal(counts.supported, 0); assert.equal(counts.leads, 2); assert.ok(counts.blocked > 0);
  assert.equal(view.findings.every(item => item.explanation_source === "code"), true);
  assert.equal(stepWords(view.steps[0]), "Done"); assert.equal(rungWords("model_reordered"), "local model, second independent try");
  assert.equal(JSON.stringify(view).includes("Fx-"), false);  // no fixture password in the record
});

test("a finding without its comparison, readings or evidence is refused", () => {
  const change = edit => {const view = fixtures().done; edit(view); return view;};
  for (const view of [
    change(v => {v.findings[0].conclusion = "supported";}),
    change(v => {v.findings[0].check_id = "check-missing";}),
    change(v => {v.checks.find(c => c.check_id === v.findings[0].check_id).comparison = "protected";}),
    change(v => {v.findings[0].evidence[0].evidence_id = "E999";}),
    change(v => {v.scope.accounts[0].password = "x";}),
    change(v => {v.journey_id = other;}),
    change(v => {v.status = "unstoppable";}),
    change(v => {delete v.plan_sha256;}),
  ]) assert.throws(() => parseJourney(view, id));
});

test("website transport keeps scope, approval and run as three separate requests", async () => {
  const requests = []; const {planned, done} = fixtures();
  const request = async (path, options) => {requests.push({path, method: options.method, body: options.body && JSON.parse(options.body), options}); return json(path.endsWith("fixture") ? planned : done);};
  const created = await websiteRequest("/api/websites/fixture", {variant: "open"}, signal(), request);
  const root = `/api/websites/${id}`;
  await websiteRequest(`${root}/approve`, {plan_sha256: created.plan_sha256, approved_by: "Reviewer", reviewed_plan: true}, signal(), request);
  await websiteRequest(`${root}/run`, {use_model: false, secrets: {}, answers: {"field:/join:name": "display_name"}}, signal(), request);
  await websiteRequest(root, undefined, signal(), request);
  await websiteRequest(`${root}/stop`, null, signal(), request);
  await websiteRequest(`${root}/revoke`, null, signal(), request);
  assert.deepEqual(requests.map(item => item.method), ["POST", "POST", "POST", "GET", "POST", "POST"]);
  assert.equal(requests[1].body.plan_sha256, planned.plan_sha256);
  for (const {options} of requests) {assert.equal(options.credentials, "same-origin"); assert.equal(options.cache, "no-store"); assert.equal(options.redirect, "error");}
});

test("website requests with a wrong path, a missing confirmation or an unreviewed approval never leave", async () => {
  let calls = 0; const forbidden = async () => {calls++; throw new Error("unexpected request");};
  const root = `/api/websites/${id}`; const hash = "a".repeat(64);
  for (const [path, body] of [
    ["https://external.invalid/api/websites", {scope: {}, confirmed_authority: true}], ["/api/websites/", undefined], [root + "/", undefined],
    [root + "?x=1", undefined], [root + "/../run", {}], [root + "/delete", null], [root + "/run/", {}],
    ["/api/websites", {scope: {}, confirmed_authority: false}], ["/api/websites", {scope: {}}], ["/api/websites/fixture", {variant: "production"}],
    ["/api/websites/fixture", {variant: "open", origin: "https://x"}],
    [root + "/approve", {plan_sha256: hash, approved_by: "R", reviewed_plan: false}], [root + "/approve", {plan_sha256: "short", approved_by: "R", reviewed_plan: true}],
    [root + "/approve", {plan_sha256: hash, approved_by: " ", reviewed_plan: true}], [root + "/approve", {plan_sha256: hash, approved_by: "R", reviewed_plan: true, widen: true}],
    [root + "/run", {use_model: "yes"}], [root + "/run", {secrets: {a: 5}}], [root + "/run", {targets: ["https://x"]}], [root + "/stop", {}], [root, {}],
  ]) await assert.rejects(websiteRequest(path, body, signal(), forbidden));
  assert.equal(calls, 0);
});

test("lists, readiness and the private report are bounded and typed", async () => {
  const {done} = fixtures();
  const list = await websiteList(signal(), async () => json({journeys: [done]}));
  assert.equal(list.journeys[0].journey_id, id);
  await assert.rejects(websiteList(signal(), async () => json({journeys: [{journey_id: id}]})));
  const ready = await websiteReadiness(signal(), async () => json({browser_ready: true, browser_note: "ok", external_ready: false, external_note: "Run: plumb website qualify"}));
  assert.equal(ready.external_ready, false);
  await assert.rejects(websiteReadiness(signal(), async () => json({browser_ready: "yes"})));
  const markdown = async () => new Response("# Private website test report\n", {headers: {"content-type": "text/markdown; charset=utf-8"}});
  assert.equal(await websiteReport(id, signal(), markdown), "# Private website test report\n");
  await assert.rejects(websiteReport("journey-nope", signal(), markdown));
  await assert.rejects(websiteReport(id, signal(), async () => json({})), /cannot read/);
  await assert.rejects(websiteReport(id, signal(), async () => new Response("x", {headers: {"content-type": "text/markdown", "content-length": String(MAX_REPORT_BYTES + 1)}})), /limit/);
  const refused = async () => new Response(JSON.stringify({detail: "Approve the plan first, or this test has already ended"}), {status: 409, headers: {"content-type": "application/json"}});
  await assert.rejects(websiteRequest(`/api/websites/${id}/run`, {}, signal(), refused), /Approve the plan first/);
});

test("the website test in the address bar is one valid identifier or nothing", () => {
  assert.equal(selectedJourney(""), null); assert.equal(selectedJourney(`?journey=${id}`), id);
  for (const search of ["?journey=x", `?journey=${id}&journey=${other}`, "?journey=../x"]) assert.throws(() => selectedJourney(search));
});
