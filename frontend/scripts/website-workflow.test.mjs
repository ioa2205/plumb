import { test } from "node:test";
import assert from "node:assert/strict";
import { approvedWebsiteUrl, websiteScope, createWebsiteAssessment, OWNED_WEBSITE_ORIGIN } from "../lib/website-workflow.ts";

const signal = () => new AbortController().signal;
const now = new Date("2026-10-11T00:00:00Z");
const scope = () => websiteScope("Synthetic owner", "Explicit owned-lab testing approval", 18, 600, 1, "fixed-fixture", now);

test("URL scope preserves named authority, isolated accounts, explicit actions and lifetime budget", () => {
  const value = scope();
  assert.equal(value.origin, OWNED_WEBSITE_ORIGIN);
  assert.equal(value.external_access_enabled, false);
  assert.deepEqual(value.accounts.map(item => item.account_id), ["alice", "bob"]);
  assert.deepEqual(value.allowed_paths, ["/health", "/auth/login", "/orders"]);
  assert.equal(value.allowed_actions.length, 8);
  assert.equal(value.budget.max_requests, 18);
  assert.equal(value.budget.max_seconds, 600);
  assert.equal(Date.parse(value.expires_at) - Date.parse(value.authority.granted_at), 3_600_000);
  assert.ok(value.stop_conditions.some(item => item.includes("personal information")));
});

test("external, encoded, alternate loopback and extra-path URL inputs are refused before any request", () => {
  for (const value of ["https://external.invalid", "http://localhost:8701", "http://127.0.0.1:8701@external.invalid", `${OWNED_WEBSITE_ORIGIN}/orders?next=external`, `${OWNED_WEBSITE_ORIGIN}/%6frders`, `${OWNED_WEBSITE_ORIGIN}/orders/../health`, `${OWNED_WEBSITE_ORIGIN}/orders/1042/receipt`]) assert.throws(() => approvedWebsiteUrl(value), /disabled/);
  for (const value of [OWNED_WEBSITE_ORIGIN, `${OWNED_WEBSITE_ORIGIN}/`, `${OWNED_WEBSITE_ORIGIN}/orders`]) assert.equal(approvedWebsiteUrl(value), value);
  for (const args of [["", "reference", 18, 600, 1], ["owner", "", 18, 600, 1], ["owner", "reference", 17, 600, 1], ["owner", "reference", 31, 600, 1], ["owner", "reference", 18, 3601, 1], ["owner", "reference", 18, 600, 25]]) assert.throws(() => websiteScope(...args, "fixture", now));
});

test("URL creation needs separate scope and owner-policy approvals and emits only the local API call", async () => {
  let calls = 0;
  const value = scope();
  const request = async (url, options) => {
    calls++;
    assert.equal(url, "/api/assessments/website");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.redirect, "error");
    const input = JSON.parse(options.body);
    assert.equal(input.url, OWNED_WEBSITE_ORIGIN);
    assert.equal(input.expected_owner_only, true);
    assert.equal(input.confirmed_authority, true);
    assert.deepEqual(input.scope, value);
    const expectations = ["receipt", "invoice"].map(endpoint => ({expectation_id: `website-owner-${endpoint}`, path: `/orders/{order_id}/${endpoint}`, object_id: value.synthetic_objects[0].object_id, allowed_account_ids: ["alice"], statement: "Owner only", declared_by: "Synthetic owner", basis: "Declared lab policy"}));
    return Response.json({scope: value, artifacts: [], expectations, comparisons: [], answers: [], analyses: [], stopped: false, stop_reason: null, spent_requests: 0, spent_seconds: 0});
  };
  await assert.rejects(createWebsiteAssessment(OWNED_WEBSITE_ORIGIN, value, false, true, "Policy", signal(), request), /Approve/);
  await assert.rejects(createWebsiteAssessment(OWNED_WEBSITE_ORIGIN, value, true, false, "Policy", signal(), request), /Approve/);
  await assert.rejects(createWebsiteAssessment(OWNED_WEBSITE_ORIGIN, value, true, true, "", signal(), request), /Approve/);
  await assert.rejects(createWebsiteAssessment("https://external.invalid", value, true, true, "Policy", signal(), request), /disabled/);
  assert.equal(calls, 0);
  const result = await createWebsiteAssessment(OWNED_WEBSITE_ORIGIN, value, true, true, "Policy", signal(), request);
  assert.equal(calls, 1);
  assert.equal(result.expectations.length, 2);
});
