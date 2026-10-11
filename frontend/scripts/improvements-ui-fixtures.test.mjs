import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { conversationFixtures } from "./improvements-ui-fixtures.mjs";
import { parseConversation } from "../lib/conversation-data.ts";
import { parseReadiness } from "../lib/setup-data.ts";
import { validateModelCatalog } from "../lib/model-choices.ts";

const read = name => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const setup = read("setup-views");
const modelFixture = read("improvements-models");
const inspection = {...setup.inspection, inspection_id: "inspect-" + "a".repeat(32)};
const saved = read("archived-peer-case");
const assessment = read("assessment-views").view;
const codePages = read("code-pages");
const digest = value => createHash("sha256").update(value).digest("hex");

for (const target of [{target_kind: "inspection", target_id: inspection.inspection_id}, {target_kind: "review", target_id: saved.run.id}, {target_kind: "assessment", target_id: assessment.scope.assessment_id}]) {
  test(`appearance conversation ${target.target_kind} binds fixture questions and follow-ups to exact saved evidence`, () => {
    const api = conversationFixtures({inspection, saved, assessment, codePages});
    const initial = parseConversation(api("/api/conversations", "POST", target), target);
    assert.equal(initial.state, "idle"); assert.equal(initial.turns.length, 0);
    const path = `/api/conversations/${initial.conversation_id}/ask`;
    api(path, "POST", {prompt: "What does this evidence establish?"});
    const final = parseConversation(api(path, "POST", {prompt: "What remains unknown?"}), target, initial.conversation_id);
    assert.equal(final.turns.length, 2); assert.equal(final.state, "completed");
    assert.deepEqual(final.turns[0].evidence, final.turns[1].evidence);
    assert.match(final.turns[0].answer, /Synthetic UI answer; no inference/);
    for (const turn of final.turns) {
      assert.equal(turn.authorization_granted, false); assert.equal(turn.actions_executed, false); assert.equal(turn.verdict_changed, false);
      assert.equal(turn.evidence_sha256, digest(JSON.stringify(turn.evidence)));
      assert.ok(turn.unknowns.length);
      for (const item of turn.evidence) {
        if (item.observation) {
          const artifact = assessment.artifacts.find(artifact => artifact.artifact_id === item.observation.artifact_id);
          assert.equal(item.quote, artifact.fields[item.observation.field]);
          assert.equal(item.observation.sha256, digest(item.quote));
        } else {
          const page = codePages.find(page => page.citation.content_sha256 === item.source.content_sha256 && page.citation.snapshot_id === item.source.snapshot_id);
          assert.equal(item.quote, page.lines.slice(item.source.start_line - page.start_line, item.source.end_line - page.start_line + 1).join("\n"));
        }
      }
    }
    assert.equal(api("/api/conversations", "POST", {...target, target_id: "different-target"}), null);
  });
}

test("model appearance fixture preserves exact pins, saved memory and honest quality labels", () => {
  assert.match(modelFixture.label, /Synthetic/);
  const catalog = validateModelCatalog(modelFixture.catalog);
  const readiness = parseReadiness({...setup.readiness, model_catalog: catalog});
  assert.equal(catalog.available_ram_bytes, readiness.available_ram_bytes);
  assert.equal(catalog.model_loaded, false); assert.equal(catalog.downloads_started, false);
  for (const model of catalog.models) {
    const pin = setup.setup_preview.doctor.model_candidates.find(pin => pin.id === model.model_id);
    assert.equal(model.size_bytes, pin.size_bytes);
    assert.equal(model.requires_download_approval, pin.requires_download_approval);
    for (const profile of model.profiles) {
      assert.equal(profile.launch_available, false);
      assert.equal(profile.automatic_eligible, profile.quality_records.length > 0);
      if (profile.quality_state === "untested") assert.equal(profile.first_use_check, "pending");
    }
  }
  assert.ok(catalog.models.some(model => !model.profiles.length && model.unavailable_reason));
});
