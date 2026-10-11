import type { AssessmentScope, AssessmentView, WebsiteScopeCreate } from "../generated/contracts";
import { AssessmentReadError, parseAssessment, parseScope, readAssessmentJson } from "./assessment-data.ts";

export const OWNED_WEBSITE_ORIGIN = "http://127.0.0.1:8701";
export function approvedWebsiteUrl(value: string): string {
  if (![OWNED_WEBSITE_ORIGIN, `${OWNED_WEBSITE_ORIGIN}/`, `${OWNED_WEBSITE_ORIGIN}/orders`].includes(value)) throw new AssessmentReadError("External website collection is disabled. Use the exact owned Tandir URL http://127.0.0.1:8701.");
  return value;
}
export function websiteScope(author: string, reference: string, requests: number, seconds: number, hours: number, identity: string, now = new Date()): AssessmentScope {
  if (!author.trim() || !reference.trim() || !Number.isInteger(requests) || requests < 18 || requests > 30 || !Number.isInteger(seconds) || seconds < 180 || seconds > 3600 || !Number.isInteger(hours) || hours < 1 || hours > 24) throw new AssessmentReadError("Name the authorizing person and reference, then choose a bounded collection and analysis budget and expiry.");
  return parseScope({scope_id: `scope-${identity}`, assessment_id: `website-${identity}`, application_id: "owned-tandir", application_name: "Owned Tandir website · synthetic assessment", origin: OWNED_WEBSITE_ORIGIN, allowed_paths: ["/health", "/auth/login", "/orders"], allowed_actions: ["read", "compare", "plan", "report", "analyze", "collect", "authenticate", "create_synthetic"], accounts: [{account_id: "alice", role: "customer", label: "Synthetic owner Alice"}, {account_id: "bob", role: "customer", label: "Synthetic other customer Bob"}], synthetic_objects: [{object_id: `order-${identity}`, owner_account_id: "alice", kind: "Order", synthetic: true, synthetic_marker: `TANDIR-FAKE-WEB-${identity}`}], authority: {granted_by: author.trim(), reference: reference.trim(), granted_at: now.toISOString()}, expires_at: new Date(now.getTime() + hours * 3_600_000).toISOString(), budget: {max_requests: requests, max_seconds: seconds}, stop_conditions: ["Unexpected sensitive or real personal information", "Origin, path or redirect leaves approved scope", "Cancellation, expiry or budget exhausted"], external_access_enabled: false});
}
export async function createWebsiteAssessment(url: string, scope: AssessmentScope, confirmed: boolean, ownerOnly: boolean, basis: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<AssessmentView> {
  if (!confirmed || !ownerOnly || !basis.trim()) throw new AssessmentReadError("Approve the explicit scope and separately declare the expected owner access and its basis.");
  const input: WebsiteScopeCreate = {url: approvedWebsiteUrl(url), scope: parseScope(scope), confirmed_authority: true, expected_owner_only: true, expectation_basis: basis.trim()};
  const result = parseAssessment(await readAssessmentJson("/api/assessments/website", signal, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(input)}, request), scope.assessment_id);
  if (result.scope.origin !== OWNED_WEBSITE_ORIGIN || !result.expectations?.some(item => item.expectation_id === "website-owner-receipt") || !result.expectations.some(item => item.expectation_id === "website-owner-invoice")) throw new AssessmentReadError("The local website scope did not preserve both prior access declarations.");
  return result;
}
