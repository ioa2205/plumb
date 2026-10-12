import { test } from "node:test";
import assert from "node:assert/strict";
import { parseHumanAuth, websiteHuman, websiteHumanInput, MAX_HUMAN_BYTES } from "../lib/website-data.ts";

const id = `journey-${"a".repeat(32)}`;
const viewId = "b".repeat(32);
const signal = () => new AbortController().signal;
const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Zra0AAAAASUVORK5CYII=";
const view = () => ({view_id: viewId, step_id: "signin-owner", account_id: "owner", label: "Owner test", challenge: "one_time_code", question: "Complete this sign-in challenge.", screenshot_png: png, width: 1280, height: 900, ready: true});

test("a private human view needs an exact live nonce, bounded dimensions and PNG-only content", () => {
  assert.equal(parseHumanAuth(null), null);
  assert.deepEqual(parseHumanAuth(view()), view());
  for (const change of [
    {view_id: `${viewId}\n`}, {view_id: "short"}, {ready: false}, {width: undefined}, {height: undefined},
    {width: 1281}, {height: 901}, {width: 0}, {challenge: "unknown"}, {screenshot_png: "javascript:alert(1)"},
    {screenshot_png: png + "\n"}, {screenshot_png: png.slice(0, -1)}, {screenshot_png: "iVBORw0KGgo" + "a".repeat(4 * 1024 * 1024)},
    {password: "not allowed"},
  ]) assert.throws(() => parseHumanAuth({...view(), ...change}));
});

test("human events stay on one authenticated, uncached local route and carry only the person event", async () => {
  const events = [
    {kind: "pointer", x: 1279, y: 899}, {kind: "text", text: "synthetic-code"},
    {kind: "submit"}, {kind: "completed"}, {kind: "pause"}, {kind: "refresh"},
  ];
  const requests = [];
  const request = async (path, options) => {
    requests.push({path, options});
    return Response.json(options.method === "POST" && JSON.parse(options.body).kind === "pause" ? null : view());
  };
  assert.equal((await websiteHuman(id, signal(), request)).view_id, viewId);
  for (const event of events) {
    const result = await websiteHumanInput(id, {view_id: viewId, ...event}, signal(), request);
    assert.equal(result === null, event.kind === "pause");
  }
  assert.equal(requests[0].options.method, "GET");
  assert.equal(requests[0].options.body, undefined);
  for (const [index, event] of events.entries()) {
    assert.equal(requests[index + 1].options.method, "POST");
    assert.deepEqual(JSON.parse(requests[index + 1].options.body), {view_id: viewId, ...event});
  }
  for (const {path, options} of requests) {
    assert.equal(path, `/api/websites/${id}/human`);
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.redirect, "error");
    assert.equal(options.cache, "no-store");
  }
});

test("malformed or mixed human events never make a request", async () => {
  let calls = 0;
  const request = async () => {calls++; return Response.json(view());};
  const invalid = [
    {kind: "pointer", x: 1280, y: 0}, {kind: "pointer", x: 0, y: 900}, {kind: "pointer", x: -1, y: 0},
    {kind: "pointer", x: 1.5, y: 0}, {kind: "pointer", x: 0}, {kind: "pointer", x: 0, y: 0, text: "x"},
    {kind: "text"}, {kind: "text", text: ""}, {kind: "text", text: "x".repeat(1025)},
    {kind: "text", text: "first\nsecond"}, {kind: "text", text: "first\rsecond"}, {kind: "text", text: "a\0b"},
    {kind: "text", text: "x", x: 0}, {kind: "submit", x: 0}, {kind: "completed", text: "x"},
    {kind: "command", text: "script"}, {kind: "pause", origin: "https://outside.invalid"},
    {kind: "refresh", view_id: `${viewId}\n`}, {kind: "refresh", view_id: "short"},
  ];
  for (const input of invalid) await assert.rejects(websiteHumanInput(id, {view_id: viewId, ...input}, signal(), request));
  await assert.rejects(websiteHuman("journey-invalid", signal(), request));
  await assert.rejects(websiteHumanInput("https://outside.invalid", {view_id: viewId, kind: "refresh"}, signal(), request));
  assert.equal(calls, 0);
});

test("private view reads refuse oversized, redirected and non-JSON responses", async () => {
  await assert.rejects(websiteHuman(id, signal(), async () => new Response("{}", {headers: {"content-type": "application/json", "content-length": String(MAX_HUMAN_BYTES + 1)}})), /limit/);
  await assert.rejects(websiteHuman(id, signal(), async () => new Response("<html></html>", {headers: {"content-type": "text/html"}})), /cannot read/);
  await assert.rejects(websiteHuman(id, signal(), async () => new Response(null, {status: 302, headers: {location: "https://outside.invalid"}})), /refused/);
});
