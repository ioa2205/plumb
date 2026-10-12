import { test } from "node:test";
import assert from "node:assert/strict";
import { buildWebsiteSetup, emptySetup } from "../lib/website-setup.ts";

const draft = () => ({...emptySetup(), address: "https://owned.example", purpose: "Check our synthetic accounts", authorizedBy: "Owner", authorization: "Ticket 17", confirmed: true});
const build = value => buildWebsiteSetup(value, new Date("2026-10-12T00:00:00Z"), "a".repeat(32));

test("human fields produce a read-only expiring plan request without secrets or implicit origins", () => {
  const request = build(draft());
  assert.equal(request.confirmed_authority, true);
  assert.deepEqual(request.scope.allowed_actions, ["read", "report"]);
  assert.deepEqual(request.scope.targets, [{origin: "https://owned.example", paths: ["/"]}]);
  assert.equal(request.scope.expires_at, "2026-10-12T04:00:00.000Z");
  assert.equal(request.scope.mode, "external");
  assert.equal(JSON.stringify(request).includes("password"), false);
});

test("explicit accounts, sign-up effects and owner markers stay in the exact confirmed scope", () => {
  const value = draft();
  value.accounts = [{id: "owner", label: "Owner test", role: "customer", username: "owner-test", existing: true, email: ""}, {id: "other", label: "Other test", role: "customer", username: "new-test", existing: false, email: "new@example.test"}];
  value.loginSuccessPath = "/home"; value.signupSuccessText = "Synthetic account created";
  value.objects = [{path: "/items/17", label: "Synthetic receipt", marker: "SYNTHETIC-17", owner: "owner", rule: "Only owner may read this receipt."}];
  const scope = build(value).scope;
  assert.deepEqual(scope.allowed_actions, ["read", "report", "sign_in", "sign_up", "compare"]);
  assert.equal(scope.accounts[1].secret_ref, `acct-${"a".repeat(32)}-2`);
  assert.equal(scope.objects[0].marker, "SYNTHETIC-17");
  assert.deepEqual(scope.rules[0].allowed_account_ids, ["owner"]);
  assert.equal(scope.signup.sends_messages, false);
});

test("missing authorization, unapproved paths, credential URLs and incomplete object controls are refused", () => {
  const invalid = [
    {confirmed: false}, {authorizedBy: ""}, {authorization: ""}, {address: "http://owned.example"},
    {address: "https://user:secret@owned.example"}, {address: "https://owned.example?token=secret"},
    {paths: "/allowed", start: "/outside"}, {paths: "/../escape"}, {paths: "/%2fescape"},
    {otherOrigins: "https://owned.example"}, {questions: "61"}, {requests: "0"},
    {accounts: [{id: "x", label: "X", role: "user", username: "x", existing: true, email: ""}]},
    {objects: [{path: "/items/17", label: "Receipt", marker: "", owner: "x", rule: "Owner only"}]},
  ];
  for (const patch of invalid) assert.throws(() => build({...draft(), ...patch}));
});
