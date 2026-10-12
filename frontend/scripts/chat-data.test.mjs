import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chatRequest, parseChat, partHeading, rungWords, savedResults, selectedChat, MAX_CHAT_BYTES } from "../lib/chat-data.ts";

const fixture = () => JSON.parse(readFileSync(new URL("./fixtures/chat-views.json", import.meta.url), "utf8")).view;
const id = fixture().chat_id; const other = "chat-" + "d".repeat(32);
const signal = () => new AbortController().signal;
const json = value => Response.json(value);

test("a chat needs no target and keeps general and cited parts apart", () => {
  const view = parseChat(fixture(), id);
  assert.equal(view.turns.length, 4);
  const [general, proposal, mixed, unclear] = view.turns;
  assert.equal(general.parts[0].kind, "general"); assert.equal(general.parts[0].evidence.length, 0);
  assert.equal(proposal.task.kind, "website_setup"); assert.equal(proposal.task.started, false);
  assert.deepEqual(mixed.parts.map(part => part.kind), ["general", "cited"]);
  assert.equal(mixed.parts[1].evidence[0].reference_id, "R001");
  assert.equal(unclear.choices.length, 2);
  assert.equal(rungWords(mixed.intent_rung), "decided by the local model on a second, independent try");
  assert.equal(partHeading(general.parts[0]), "General answer");
  assert.equal(partHeading({...general.parts[0], complete: false}), "General answer · stopped at its length limit");
  const empty = {...fixture(), target_kind: null, target_id: null, target_label: null, turns: []};
  assert.equal(parseChat(empty, id).turns.length, 0);
});

test("a general part with evidence, an uncited cited part or a turn that claims an action is refused", () => {
  const change = edit => {const view = fixture(); edit(view); return view;};
  const evidence = fixture().turns[2].parts[1].evidence;
  for (const view of [
    change(v => {v.turns[0].parts[0].evidence = evidence;}),
    change(v => {v.turns[2].parts[1].evidence = [];}),
    change(v => {v.turns[2].parts[1].evidence = [evidence[0], evidence[0]];}),
    change(v => {v.turns[0].actions_executed = true;}),
    change(v => {v.turns[0].authorization_granted = true;}),
    change(v => {v.turns[0].finding_created = true;}),
    change(v => {v.turns[1].task.started = true;}),
    change(v => {v.turns[1].task.authorization_granted = true;}),
    change(v => {v.chat_id = other;}),
    change(v => {v.unexpected = "field";}),
    change(v => {v.turns[0].intent = "delete_everything";}),
  ]) assert.throws(() => parseChat(view, id));
});

test("chat transport uses exact local paths, same-origin requests and verifies cited quotes", async () => {
  const requests = [];
  const request = async (path, options) => {requests.push({path, options}); return json(fixture());};
  await chatRequest(`/api/chats/${id}`, undefined, signal(), id, request);
  await chatRequest(`/api/chats/${id}/ask`, {prompt: "What is SQL injection?", max_seconds: 300}, signal(), id, request);
  await chatRequest(`/api/chats/${id}/ask`, {prompt: "hmm", choice: "general_question"}, signal(), id, request);
  await chatRequest(`/api/chats/${id}/select`, {target_kind: "website", target_id: "journey-" + "a".repeat(32)}, signal(), id, request);
  await chatRequest(`/api/chats/${id}/select`, {}, signal(), id, request);
  await chatRequest(`/api/chats/${id}/cancel`, null, signal(), id, request);
  assert.deepEqual(requests.map(item => item.options.method), ["GET", "POST", "POST", "POST", "POST", "POST"]);
  for (const {options} of requests) {assert.equal(options.credentials, "same-origin"); assert.equal(options.cache, "no-store"); assert.equal(options.redirect, "error");}
  const created = await chatRequest("/api/chats", {}, signal(), undefined, async () => json({...fixture(), turns: []}));
  assert.equal(created.chat_id, id);
  const tampered = fixture(); tampered.turns[2].parts[1].evidence[0].quote = "404";
  await assert.rejects(chatRequest(`/api/chats/${id}`, undefined, signal(), id, async () => json(tampered)), /exact evidence hash/);
});

test("chat refuses unanchored paths, wrong identities and wrong bodies before any request", async () => {
  let calls = 0; const forbidden = async () => {calls++; throw new Error("unexpected request");};
  const root = `/api/chats/${id}`;
  for (const [path, body, identity] of [
    ["https://external.invalid/api/chats", {}, undefined], ["/api/chats/", {}, undefined], ["/api/chats-extra", {}, undefined],
    [root + "?x=1", undefined, id], [root + "/../ask", {prompt: "x"}, id], [root + "/ask/", {prompt: "x"}, id], [root, undefined, other],
    [root + "/ask", {prompt: ""}, id], [root + "/ask", {prompt: "x", choice: "approve_all"}, id], [root + "/ask", {prompt: "x", max_seconds: 9000}, id],
    [root + "/ask", {prompt: "x", run: true}, id], [root + "/cancel", {}, id], [root + "/select", {target_kind: "website"}, id],
    [root + "/select", {target_kind: "computer", target_id: "x"}, id], ["/api/chats", {target_kind: "review", target_id: "../x"}, undefined],
    [root + "/approve", null, id],
  ]) await assert.rejects(chatRequest(path, body, signal(), identity, forbidden));
  assert.equal(calls, 0);
});

test("refusals, wrong media types and oversized responses are not shown as a chat", async () => {
  const refused = async () => new Response(JSON.stringify({detail: "Chat request refused. Check the message for secrets."}), {status: 409, headers: {"content-type": "application/json"}});
  await assert.rejects(chatRequest("/api/chats", {}, signal(), undefined, refused), /Check the message for secrets/);
  await assert.rejects(chatRequest("/api/chats", {}, signal(), undefined, async () => new Response("<html>", {headers: {"content-type": "text/html"}})), /cannot read/);
  await assert.rejects(chatRequest("/api/chats", {}, signal(), undefined, async () => new Response("{}", {headers: {"content-type": "application/json", "content-length": String(MAX_CHAT_BYTES + 1)}})), /limit/);
  await assert.rejects(chatRequest("/api/chats", {}, signal(), undefined, async () => {throw new TypeError("offline");}), /cannot be reached/);
  const results = await savedResults(signal(), async () => json({results: [{target_kind: "review", target_id: "review-" + "a".repeat(32), label: "Review of shop, 11 October 2026"}]}));
  assert.equal(results.results[0].label, "Review of shop, 11 October 2026");
  await assert.rejects(savedResults(signal(), async () => json({results: [{target_kind: "review"}]})));
});

test("the chat in the address bar is one valid identifier or nothing", () => {
  assert.equal(selectedChat(""), null); assert.equal(selectedChat(`?chat=${id}`), id);
  for (const search of ["?chat=x", `?chat=${id}&chat=${other}`, "?chat=../secrets", `?chat=${id}%0A`]) assert.throws(() => selectedChat(search));
});
