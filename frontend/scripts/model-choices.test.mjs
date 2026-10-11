import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateModelCatalog, validProfile, profileChoice } from "../lib/model-choices.ts";
import { parseReadiness, launchReview } from "../lib/setup-data.ts";

const actual = JSON.parse(readFileSync(new URL("./fixtures/setup-views.json", import.meta.url), "utf8"));
const profile = {profile_id: "cpu-8k", backend: "cpu", hardware_compatible: true, memory_fit: true, required_ram_bytes: 2436385888, required_vram_bytes: 0, available_vram_bytes: null, runtime_verified: true, runtime_compatible: true, first_use_check: "pending", launch_available: true, automatic_eligible: true, quality_state: "recorded_scoped", quality_records: [{path: "docs/results/2026-10-10-a1-cpu-profile-review/report.json", sha256: "a".repeat(64)}], quality_note: "Historical scoped source evidence only; web-observation acceptance unmet.", conditions: []};
const catalog = {checked_at: "2026-10-11T00:00:00Z", selected_profile: "cpu-8k", recommended_profile: "cpu-8k", selection_basis: "Recorded scoped evidence plus hardware fit; no size ranking", available_ram_bytes: 3000000000, available_vram_bytes: null, models: [{model_id: "qwen3.5-2b-q4_k_m", family: "Qwen3.5-2B", quantization: "Q4_K_M", size_bytes: 1396198496, verified_installed: true, requires_download_approval: true, profiles: [profile], unavailable_reason: null}], model_loaded: false, downloads_started: false};

test("catalog preserves separate hardware, first-use and recorded quality facts", () => {
  assert.equal(validateModelCatalog(catalog).models[0].profiles[0].first_use_check, "pending");
  assert.equal(parseReadiness({...actual.readiness, model_catalog: catalog}).model_catalog.recommended_profile, "cpu-8k");
  assert.equal(profileChoice(catalog, "cpu-8k").quality_state, "recorded_scoped");
  assert.equal(profileChoice(catalog, "larger-is-better"), null);
  for (const value of [null, 1, "../escape", "bad\nprofile", "$(execute)", "A".repeat(129)]) assert.equal(validProfile(value), false);
});

test("forged automatic qualification, memory fit or first-use cannot enable launch", () => {
  const changed = updates => ({...catalog, models: [{...catalog.models[0], profiles: [{...profile, ...updates}]}]});
  for (const value of [changed({quality_state: "untested"}), changed({memory_fit: false}), changed({first_use_check: "failed"}), changed({runtime_compatible: false}), changed({quality_records: []}), {...catalog, available_ram_bytes: 1}, {...catalog, recommended_profile: "unknown"}]) assert.throws(() => validateModelCatalog(value));
  const untested = changed({automatic_eligible: false, quality_state: "untested", quality_records: []});
  assert.throws(() => validateModelCatalog(untested));
  assert.equal(validateModelCatalog({...untested, recommended_profile: null}).models[0].profiles[0].quality_state, "untested");
});

test("selected model profile reaches the review request without model downloads", async () => {
  const inspection = {...actual.inspection, inspection_id: "inspect-" + "a".repeat(32)};
  const body = {inspection_id: inspection.inspection_id, authorized: true, limit: 1, families: ["authorization"], resources: [], routes: [], profile: "cpu-8k-qwen3.5-0.8b-q4_k_m"};
  const run = {id: "review-" + "b".repeat(32), snapshot_id: inspection.snapshot_id, run_type: "live", lifecycle: "queued", created_at: "2026-10-11T00:00:00Z", coverage: {total: 1, pending: 1, completed: 0, excluded: 0, unsupported: 0}};
  let calls = 0;
  const request = async (url, options) => {calls++; assert.equal(url, "/api/projects/review"); assert.equal(JSON.parse(options.body).profile, body.profile); return Response.json(run);};
  assert.equal((await launchReview(inspection, body, new AbortController().signal, request)).id, run.id);
  await assert.rejects(launchReview(inspection, {...body, profile: "../bad"}, new AbortController().signal, request));
  assert.equal(calls, 1);
});
