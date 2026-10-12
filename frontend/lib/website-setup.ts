import type { JourneyCreate } from "../generated/contracts";

export type SetupAccount = {id: string; label: string; role: string; username: string; existing: boolean; email: string};
export type SetupObject = {path: string; label: string; marker: string; owner: string; rule: string};
export type SetupDraft = {
  name: string; address: string; otherOrigins: string; paths: string; start: string; purpose: string;
  authorizedBy: string; authorization: string; confirmed: boolean; publicValues: string;
  accounts: SetupAccount[]; objects: SetupObject[];
  loginPath: string; loginSuccessPath: string; loginSuccessText: string;
  signupPath: string; signupSuccessPath: string; signupSuccessText: string; signupEffects: string; sendsMessages: boolean;
  hours: string; requests: string; seconds: string; megabytes: string; questions: string;
};

export const emptySetup = (): SetupDraft => ({
  name: "", address: "", otherOrigins: "", paths: "/", start: "/", purpose: "",
  authorizedBy: "", authorization: "", confirmed: false, publicValues: "", accounts: [], objects: [],
  loginPath: "/login", loginSuccessPath: "", loginSuccessText: "",
  signupPath: "/signup", signupSuccessPath: "", signupSuccessText: "", signupEffects: "Creates one synthetic account.", sendsMessages: false,
  hours: "4", requests: "300", seconds: "900", megabytes: "20", questions: "24",
});

const required = (value: string, label: string, max = 300): string => {
  const text = value.trim();
  if (!text || text.length > max) throw new Error(`${label} is required and must fit within ${max} characters.`);
  return text;
};
const lines = (value: string): string[] => value.split(/[\n,]/).map(item => item.trim()).filter(Boolean);
function origin(value: string): string {
  let url: URL;
  try {url = new URL(value.includes("://") ? value : `https://${value}`);} catch {throw new Error("Enter a valid HTTPS website address.");}
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) throw new Error("Use HTTPS without credentials, a query or a fragment.");
  return url.origin;
}
function path(value: string): string {
  const text = value.trim();
  if (!text.startsWith("/") || text.includes("\\") || text.includes("?") || text.includes("#") || text.includes("%") || text.includes("//") || text.split("/").some(item => item === "." || item === "..") || /[\s\x00-\x1f]/.test(text)) throw new Error("Paths must start with / and contain no query, fragment, encoded or relative segments.");
  return required(text, "Path", 512);
}
function number(value: string, label: string, min: number, max: number): number {
  const parsed = Number(value);
  if (!value.trim() || !Number.isInteger(parsed) || parsed < min || parsed > max) throw new Error(`${label} must be a whole number from ${min} to ${max}.`);
  return parsed;
}

/** Build the existing backend contract from human fields; creating it grants no permission to run. */
export function buildWebsiteSetup(draft: SetupDraft, now = new Date(), id = crypto.randomUUID().replaceAll("-", "")): JourneyCreate {
  if (!draft.confirmed) throw new Error("Confirm the exact addresses, actions and authorization before saving a plan.");
  const main = origin(draft.address);
  const origins = [main, ...lines(draft.otherOrigins).map(origin)];
  const paths = lines(draft.paths).map(path);
  if (!paths.length || paths.length > 40 || new Set(paths).size !== paths.length || origins.length > 8 || new Set(origins).size !== origins.length) throw new Error("List distinct approved addresses and paths, with at most eight addresses and forty paths.");
  const inside = (value: string) => paths.some(prefix => prefix === "/" || value === prefix || value.startsWith(prefix.replace(/\/$/, "") + "/"));
  const checkedPath = (value: string) => {const result = path(value); if (!inside(result)) throw new Error(`${result} is outside your approved paths.`); return result;};
  const accounts = draft.accounts.map((account, index) => {
    const accountId = required(account.id, "Account ID", 128);
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(accountId)) throw new Error("Account IDs use letters, numbers, dots, underscores, colons or hyphens.");
    return {account_id: accountId, label: required(account.label || accountId, "Account label"), role: required(account.role || "user", "Account role"), username: required(account.username, "Test-account username", 128), secret_ref: `acct-${id}-${index + 1}`, provisioned: account.existing, contact_email: account.email.trim() || null};
  });
  if (accounts.length > 6 || new Set(accounts.map(account => account.account_id)).size !== accounts.length) throw new Error("Use at most six distinct test accounts.");
  const accountIds = new Set(accounts.map(account => account.account_id));
  const objects = draft.objects.map((object, index) => {
    if (!accountIds.has(object.owner)) throw new Error("Each synthetic object must belong to one listed test account.");
    const marker = required(object.marker, "Unique synthetic object marker", 128);
    if (marker.length < 6) throw new Error("A synthetic object marker needs at least six characters.");
    return {object_id: `object-${index + 1}`, path: checkedPath(object.path), kind: required(object.label, "Object description"), owner_account_id: object.owner, marker, synthetic: true as const};
  });
  if (objects.length > 20 || objects.length && accounts.length < 2) throw new Error("Comparisons need at least two test accounts and at most twenty synthetic objects.");
  const rules = objects.map((object, index) => ({rule_id: `rule-${index + 1}`, object_id: object.object_id, statement: required(draft.objects[index]!.rule, "Owner's access rule", 1024), allowed_account_ids: [object.owner_account_id], declared_by: required(draft.authorizedBy, "Who authorized the test"), basis: required(draft.authorization, "Authorization reference", 1024)}));
  const existing = accounts.some(account => account.provisioned);
  const creating = accounts.some(account => !account.provisioned);
  if (existing && !draft.loginSuccessPath.trim() && !draft.loginSuccessText.trim()) throw new Error("Give a page path or text that confirms successful sign-in.");
  if (creating && !draft.signupSuccessPath.trim() && !draft.signupSuccessText.trim()) throw new Error("Give a page path or text that confirms the synthetic account was created.");
  const allowed: NonNullable<JourneyCreate["scope"]["allowed_actions"]>[number][] = ["read", "report"];
  if (existing) allowed.push("sign_in");
  if (creating) allowed.push("sign_up");
  if (objects.length) allowed.push("compare");
  const publicValues = lines(draft.publicValues).map(value => required(value, "Known public value"));
  if (publicValues.length > 20) throw new Error("List at most twenty known public values.");
  return {
    confirmed_authority: true,
    scope: {
      scope_id: `scope-${id}`, website_id: `website-${id}`, name: required(draft.name || main, "Website name"), mode: "external",
      targets: origins.map(address => ({origin: address, paths})), start_path: checkedPath(draft.start), purpose: required(draft.purpose, "Purpose", 1024),
      authority: {granted_by: required(draft.authorizedBy, "Who authorized the test"), reference: required(draft.authorization, "Authorization reference", 1024), granted_at: now.toISOString()},
      accounts, objects, rules, allowed_actions: allowed,
      login: existing ? {path: checkedPath(draft.loginPath), success_path: draft.loginSuccessPath.trim() ? checkedPath(draft.loginSuccessPath) : null, success_text: draft.loginSuccessText.trim() || null} : null,
      signup: creating ? {path: checkedPath(draft.signupPath), success_path: draft.signupSuccessPath.trim() ? checkedPath(draft.signupSuccessPath) : null, success_text: draft.signupSuccessText.trim() || null, approved_side_effects: [required(draft.signupEffects, "Approved sign-up effects")], sends_messages: draft.sendsMessages} : null,
      expires_at: new Date(now.getTime() + number(draft.hours, "Scope duration in hours", 1, 168) * 3600000).toISOString(),
      budget: {max_requests: number(draft.requests, "Requests", 1, 2000), max_seconds: number(draft.seconds, "Seconds", 1, 7200), max_bytes: number(draft.megabytes, "Megabytes", 1, 256) * 1024 * 1024, max_model_questions: number(draft.questions, "Model questions", 0, 60)},
      stop_conditions: ["Unexpected personal data appears.", "An action leaves the approved scope or plan.", "The site shows signs of harm to real users or data."], public_values: publicValues, confirmed_targets: true,
    },
  };
}
