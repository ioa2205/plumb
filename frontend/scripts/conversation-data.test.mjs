import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { conversationFixtures } from "./improvements-ui-fixtures.mjs";
import { conversationRequest, parseConversation, MAX_CONVERSATION_BYTES } from "../lib/conversation-data.ts";

const read = name => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const inspection = {...read("setup-views").inspection, inspection_id: "inspect-" + "a".repeat(32)};
const saved = read("archived-peer-case"); const assessment = read("assessment-views").view;
const codePages = read("code-pages");
const targets = [{target_kind: "inspection", target_id: inspection.inspection_id}, {target_kind: "review", target_id: saved.run.id}, {target_kind: "assessment", target_id: assessment.scope.assessment_id}];
const id = "conversation-" + "b".repeat(32); const otherId = "conversation-" + "c".repeat(32);
const signal = () => new AbortController().signal;
const response = value => Response.json(value);
function fixture(target = targets[0]) {
  const api = conversationFixtures({inspection, saved, assessment, codePages});
  const view = api("/api/conversations", "POST", target);
  return api(`/api/conversations/${view.conversation_id}/ask`, "POST", {prompt: "Explain this evidence and its limitations"});
}

for (const target of targets) test(`conversation transport preserves exact ${target.target_kind} evidence and local request policy`, async () => {
  const api = conversationFixtures({inspection, saved, assessment, codePages}); const requests = [];
  const request = async (path, options) => {requests.push({path, options}); return response(api(path, options.method, options.body ? JSON.parse(options.body) : undefined));};
  const initial = await conversationRequest(target, "/api/conversations", target, signal(), undefined, request);
  const path = `/api/conversations/${initial.conversation_id}`;
  const answered = await conversationRequest(target, `${path}/ask`, {prompt: "Explain this evidence", profile: "auto", max_seconds: 300}, signal(), initial.conversation_id, request);
  assert.equal(answered.turns.length, 1);
  await conversationRequest(target, path, undefined, signal(), initial.conversation_id, request);
  const canceled = await conversationRequest(target, `${path}/cancel`, null, signal(), initial.conversation_id, request);
  assert.equal(canceled.state, "canceled"); assert.deepEqual(requests.map(item => item.options.method), ["POST", "POST", "GET", "POST"]);
  for (const {options} of requests) {assert.equal(options.credentials, "same-origin"); assert.equal(options.cache, "no-store"); assert.equal(options.redirect, "error"); assert.ok(options.signal);}
});

test("conversation rejects unanchored routes, mismatched identities and wrong method bodies before fetch", async () => {
  const root = `/api/conversations/${id}`; let calls = 0; const forbidden = async () => {calls++; throw new Error("Unexpected network request");};
  const invalid = [
    ["https://external.invalid/api/conversations", targets[0], undefined],
    ["/api/conversations-extra", targets[0], undefined], ["/api/conversations/", targets[0], undefined],
    [root + "?id=another", undefined, id], [root + "#details", undefined, id], [root + "\n", undefined, id],
    [root + "/../ask", {prompt: "question"}, id], [root + "/ask/", {prompt: "question"}, id],
    [root.replace("conversation-", "conversation-%62"), undefined, id], [root + "/export", null, id],
    [root, undefined, otherId], [root, undefined, undefined], [root, null, id], [root, {prompt: "question"}, id],
    [root + "/ask", undefined, id], [root + "/ask", null, id], [root + "/ask", targets[0], id],
    [root + "/cancel", undefined, id], [root + "/cancel", {prompt: "question"}, id],
    ["/api/conversations", undefined, undefined], ["/api/conversations", targets[0], id],
    ["/api/conversations", targets[1], undefined], ["/api/conversations", {...targets[0], authorized: true}, undefined],
  ];
  for (const [path, body, expectedId] of invalid) await assert.rejects(conversationRequest(targets[0], path, body, signal(), expectedId, forbidden));
  for (const body of [{prompt: "   "}, {prompt: "x".repeat(4097)}, {prompt: "question", max_seconds: 301}, {prompt: "question", max_seconds: 1.5}, {prompt: "question", max_seconds: 0}, {prompt: "question", profile: "../../../model"}, {prompt: "question", profile: "auto\n"}, {prompt: "question", action: "collect"}]) await assert.rejects(conversationRequest(targets[0], root + "/ask", body, signal(), id, forbidden));
  for (const target of [{target_kind: "remote", target_id: inspection.inspection_id}, {...targets[0], target_id: "inspect-../escape"}, {...targets[1], target_id: "../run"}, {...targets[2], target_id: "assess-ui-synthetic\n"}]) await assert.rejects(conversationRequest(target, "/api/conversations", target, signal(), undefined, forbidden));
  assert.equal(calls, 0);
});

test("conversation parsing rejects wrong targets, duplicated refs and mixed citation kinds", () => {
  const source = fixture(); const observed = fixture(targets[2]);
  const rejected = [
    value => value.target_id = "another-target", value => value.target_kind = "assessment",
    value => value.turns[0].evidence[0].source = null,
    value => value.turns[0].evidence[0].observation = observed.turns[0].evidence[0].observation,
    value => value.turns[0].evidence[0] = observed.turns[0].evidence[0],
    value => value.turns[0].evidence.push(value.turns[0].evidence[0]),
    value => value.turns[0].evidence[0].source.end_line = 1,
    value => value.turns[0].evidence[0].source.path = "../secret.py",
    value => value.turns[0].evidence[0].source.path = "C:/private.py",
    value => value.turns[0].evidence[0].source.path = "api\\private.py",
    value => value.turns[0].evidence[0].quote += "\nextra line",
    value => value.turns[0].actions_executed = true,
  ];
  for (const mutate of rejected) {const value = structuredClone(source); mutate(value); assert.throws(() => parseConversation(value, targets[0]));}
  const value = structuredClone(observed); value.turns[0].evidence[0] = source.turns[0].evidence[0];
  assert.throws(() => parseConversation(value, targets[2]));
  assert.throws(() => parseConversation(source, targets[0], id));
});

test("conversation transport verifies quote hashes and rejects identity-swapped responses", async () => {
  for (const target of targets) {
    const view = fixture(target); const path = `/api/conversations/${view.conversation_id}`;
    const quoteChanged = structuredClone(view); quoteChanged.turns[0].evidence[0].quote = quoteChanged.turns[0].evidence[0].quote.replace(/[^\n]/, "X");
    await assert.rejects(conversationRequest(target, path, undefined, signal(), view.conversation_id, async () => response(quoteChanged)), /exact evidence hash/);
    const switched = {...view, conversation_id: otherId};
    await assert.rejects(conversationRequest(target, path, undefined, signal(), view.conversation_id, async () => response(switched)), /different evidence/);
  }
});

test("conversation stream stops at byte bound and cancels its reader", async () => {
  let canceled = 0; let pulls = 0;
  const stream = new ReadableStream({pull(controller) {pulls++; controller.enqueue(new Uint8Array(65536));}, cancel() {canceled++;}});
  await assert.rejects(conversationRequest(targets[0], "/api/conversations", targets[0], signal(), undefined, async () => new Response(stream, {headers: {"content-type": "application/json"}})), /exceeds/);
  assert.equal(canceled, 1); assert.ok(pulls <= MAX_CONVERSATION_BYTES / 65536 + 2); assert.equal(stream.locked, false);
});

test("conversation byte limit counts multibyte UTF-8 rather than characters", async () => {
  const text = JSON.stringify("é".repeat(MAX_CONVERSATION_BYTES / 2));
  assert.ok(text.length < MAX_CONVERSATION_BYTES); assert.ok(new TextEncoder().encode(text).byteLength > MAX_CONVERSATION_BYTES);
  await assert.rejects(conversationRequest(targets[0], "/api/conversations", targets[0], signal(), undefined, async () => new Response(text, {headers: {"content-type": "application/json"}})), /exceeds/);
});

test("declared oversized conversation cancels before reading its stream", async () => {
  let canceled = false;
  const stream = new ReadableStream({cancel() {canceled = true;}});
  await assert.rejects(conversationRequest(targets[0], "/api/conversations", targets[0], signal(), undefined, async () => new Response(stream, {headers: {"content-type": "application/json", "content-length": String(MAX_CONVERSATION_BYTES + 1)}})), /exceeds/);
  assert.equal(canceled, true); assert.equal(stream.locked, false);
});

test("unreadable, invalid UTF-8, interrupted and unsuccessful conversation responses stop safely", async () => {
  const cases = [
    async () => new Response("{}", {status: 409}), async () => new Response(null, {status: 204}),
    async () => new Response("{}", {headers: {"content-type": "application/jsonp"}}),
    async () => new Response("{", {headers: {"content-type": "application/json"}}),
    async () => new Response(new Uint8Array([0xc3, 0x28]), {headers: {"content-type": "application/json"}}),
    async () => new Response(new ReadableStream({start(controller) {controller.error(new Error("Private error body"));}}), {headers: {"content-type": "application/json"}}),
    async () => {throw new Error("Private transport details");},
  ];
  for (const request of cases) await assert.rejects(conversationRequest(targets[0], "/api/conversations", targets[0], signal(), undefined, request), error => !error.message.includes("Private"));
});
