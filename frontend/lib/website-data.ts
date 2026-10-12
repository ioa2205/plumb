import type { HumanAuthInput, HumanAuthView, JourneyApprove, JourneyCreate, JourneyList, JourneyRun, JourneyView, WebsiteReadiness } from "../generated/contracts";
import viewSchema from "../generated/journey-view.schema.json" with { type: "json" };
import listSchema from "../generated/journey-list.schema.json" with { type: "json" };
import readinessSchema from "../generated/website-readiness.schema.json" with { type: "json" };
import humanViewSchema from "../generated/human-auth-view.schema.json" with { type: "json" };
import humanInputSchema from "../generated/human-auth-input.schema.json" with { type: "json" };
import { structuralMatches } from "./run-metadata.ts";
import { LocalReadError, localBody, localJson } from "./local-json.ts";

export const MAX_JOURNEY_BYTES = 8 * 1024 * 1024;
export const MAX_REPORT_BYTES = 2 * 1024 * 1024;
export const MAX_HUMAN_BYTES = 6 * 1024 * 1024;
export class WebsiteReadError extends LocalReadError {}
export type Step = NonNullable<JourneyView["steps"]>[number];
export type Finding = NonNullable<JourneyView["findings"]>[number];
export type LiveHumanAuthView = HumanAuthView & Required<Pick<HumanAuthView, "width" | "height" | "ready">>;
type FixtureCreate = {variant: "open" | "defended"};

const identifier = /^journey-[0-9a-f]{32}$/;
export const validJourneyId = (value: string) => identifier.exec(value)?.[0] === value;
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);

/** Structure, identity, and the two things a page must never show wrongly: supported without three readings, a secret. */
export function parseJourney(value: unknown, id?: string): JourneyView {
  if (id !== undefined && !validJourneyId(id) || !structuralMatches(value, viewSchema)) throw new WebsiteReadError("This website test cannot be read.");
  const view = value as JourneyView;
  if (id !== undefined && view.journey_id !== id) throw new WebsiteReadError("This website test belongs to a different record.");
  const checks = new Map((view.checks ?? []).map(check => [check.check_id, check]));
  const evidence = new Set((view.evidence ?? []).map(item => item.evidence_id));
  for (const finding of view.findings ?? []) {
    const check = checks.get(finding.check_id);
    if (!check || check.comparison !== "candidate") throw new WebsiteReadError("A finding has no completed comparison behind it.");
    if (finding.conclusion === "supported" && check.judged !== "supported") throw new WebsiteReadError("A supported finding lacks its three agreeing readings.");
    if (!(finding.evidence ?? []).every(item => evidence.has(item.evidence_id))) throw new WebsiteReadError("A finding cites evidence this record does not hold.");
  }
  if ((view.scope.accounts ?? []).some(account => "password" in account)) throw new WebsiteReadError("A website record may not carry a password.");
  return view;
}

function validApprove(value: unknown): value is JourneyApprove {
  return isRecord(value) && Object.keys(value).every(key => ["plan_sha256", "approved_by", "reviewed_plan", "step_ids"].includes(key))
    && typeof value.plan_sha256 === "string" && /^[0-9a-f]{64}$/.test(value.plan_sha256)
    && typeof value.approved_by === "string" && !!value.approved_by.trim() && value.approved_by.length <= 300 && value.reviewed_plan === true
    && (value.step_ids === undefined || value.step_ids === null || Array.isArray(value.step_ids) && value.step_ids.every(item => typeof item === "string"));
}
function validRun(value: unknown): value is JourneyRun {
  const text = (item: unknown) => isRecord(item) && Object.values(item).every(entry => typeof entry === "string" && entry.length <= 1024);
  return isRecord(value) && Object.keys(value).every(key => ["profile", "use_model", "secrets", "answers"].includes(key))
    && (value.profile === undefined || typeof value.profile === "string") && (value.use_model === undefined || typeof value.use_model === "boolean")
    && (value.secrets === undefined || text(value.secrets)) && (value.answers === undefined || text(value.answers));
}

export async function websiteRequest(path: string, body: JourneyApprove | JourneyRun | JourneyCreate | FixtureCreate | null | undefined, signal: AbortSignal, request: typeof fetch = fetch): Promise<JourneyView> {
  const resource = /^\/api\/websites\/(journey-[0-9a-f]{32})(?:\/(approve|run|stop|revoke))?$/.exec(path);
  const action = resource?.[2];
  const allowed = path === "/api/websites/fixture" ? isRecord(body) && Object.keys(body).length === 1 && ["open", "defended"].includes(String((body as FixtureCreate).variant))
    : path === "/api/websites" ? isRecord(body) && (body as {confirmed_authority?: unknown}).confirmed_authority === true && isRecord((body as {scope?: unknown}).scope)
    : !!resource && resource[0] === path && (action === "approve" ? validApprove(body) : action === "run" ? validRun(body) : action ? body === null : body === undefined);
  if (!allowed) throw new WebsiteReadError("Invalid website path or request.");
  const post = path === "/api/websites/fixture" || path === "/api/websites" || !!action;
  return parseJourney(await localJson(path, post ? "POST" : "GET", body, signal, MAX_JOURNEY_BYTES, request), resource?.[1]);
}

export async function websiteList(signal: AbortSignal, request: typeof fetch = fetch): Promise<JourneyList> {
  const value = await localJson("/api/websites", "GET", undefined, signal, 20 * MAX_JOURNEY_BYTES, request);
  if (!structuralMatches(value, listSchema)) throw new WebsiteReadError("The saved website tests cannot be read.");
  return value as JourneyList;
}

export async function websiteReadiness(signal: AbortSignal, request: typeof fetch = fetch): Promise<WebsiteReadiness> {
  const value = await localJson("/api/websites/readiness", "GET", undefined, signal, 16 * 1024, request);
  if (!structuralMatches(value, readinessSchema)) throw new WebsiteReadError("Readiness cannot be read.");
  return value as WebsiteReadiness;
}

export async function websiteReport(id: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<string> {
  if (!validJourneyId(id)) throw new WebsiteReadError("Invalid website test.");
  return localBody(`/api/websites/${id}/report`, "GET", undefined, signal, MAX_REPORT_BYTES, "markdown", request);
}

/** A live, private browser view is ephemeral. Null is absence, never proof of successful sign-in. */
export function parseHumanAuth(value: unknown): LiveHumanAuthView | null {
  if (value === null) return null;
  if (!structuralMatches(value, humanViewSchema)) throw new WebsiteReadError("The private sign-in view cannot be read.");
  const view = value as HumanAuthView;
  if (!/^[0-9a-f]{32}$/.test(view.view_id) || view.view_id.length !== 32 || view.ready !== true || view.width === undefined || view.height === undefined) throw new WebsiteReadError("The private sign-in view cannot be read.");
  if (!view.screenshot_png.startsWith("iVBORw0KGgo") || !/^[A-Za-z0-9+/]+={0,2}$/.test(view.screenshot_png) || view.screenshot_png.length % 4 !== 0) throw new WebsiteReadError("The private sign-in picture cannot be read.");
  return view as LiveHumanAuthView;
}

export async function websiteHuman(id: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<LiveHumanAuthView | null> {
  if (!validJourneyId(id)) throw new WebsiteReadError("Invalid website test.");
  return parseHumanAuth(await localJson(`/api/websites/${id}/human`, "GET", undefined, signal, MAX_HUMAN_BYTES, request));
}

export async function websiteHumanInput(id: string, input: HumanAuthInput, signal: AbortSignal, request: typeof fetch = fetch): Promise<LiveHumanAuthView | null> {
  if (!validJourneyId(id) || !structuralMatches(input, humanInputSchema)) throw new WebsiteReadError("Invalid private sign-in action.");
  const coordinates = input.x !== undefined && input.x !== null || input.y !== undefined && input.y !== null;
  const text = input.text !== undefined && input.text !== null;
  if (!/^[0-9a-f]{32}$/.test(input.view_id) || input.view_id.length !== 32) throw new WebsiteReadError("Invalid private sign-in action.");
  if (input.kind === "pointer" ? !Number.isInteger(input.x) || !Number.isInteger(input.y) || Number(input.x) >= 1280 || Number(input.y) >= 900 || text : coordinates) throw new WebsiteReadError("Invalid private sign-in action.");
  if (input.kind === "text" ? !text || !input.text : text) throw new WebsiteReadError("Invalid private sign-in action.");
  if (text && /[\r\n\0]/.test(input.text!)) throw new WebsiteReadError("Invalid private sign-in action.");
  return parseHumanAuth(await localJson(`/api/websites/${id}/human`, "POST", input, signal, MAX_HUMAN_BYTES, request));
}

export function selectedJourney(search: string): string | null {
  const values = new URLSearchParams(search).getAll("journey");
  if (!values.length) return null;
  if (values.length !== 1 || !validJourneyId(values[0]!)) throw new WebsiteReadError("Use one valid website test ID.");
  return values[0]!;
}

const statuses: Record<JourneyView["status"] & string, string> = {
  planned: "Waiting for your approval", approved: "Approved, not started", running: "Running", paused: "Paused",
  stopped: "Stopped", handoff: "Waiting for a person", done: "Finished", failed: "Stopped on an error",
};
export const statusWords = (view: JourneyView): string => statuses[view.status ?? "planned"];

const stepStates: Record<NonNullable<Step["state"]>, string> = {
  planned: "Not started", attempted: "Started", completed: "Done", uncertain: "Uncertain", blocked: "Could not run", skipped: "Skipped",
};
export const stepWords = (step: Step): string => stepStates[step.state ?? "planned"];

const rungs: Record<string, string> = {code: "code", model: "local model", model_reordered: "local model, second independent try", user: "you", stop: "not decided"};
export const rungWords = (rung: string): string => rungs[rung] ?? "not decided";

/** Counts with true denominators only; nothing is estimated here. */
export function activityCounts(view: JourneyView): {done: number; steps: number; pages: number; checks: number; supported: number; leads: number; blocked: number} {
  const steps = view.steps ?? []; const findings = view.findings ?? [];
  return {
    done: steps.filter(step => step.state === "completed").length, steps: steps.length, pages: (view.pages ?? []).length, checks: (view.checks ?? []).length,
    supported: findings.filter(item => item.conclusion === "supported").length, leads: findings.filter(item => item.conclusion === "candidate").length,
    blocked: (view.blocked ?? []).reduce((sum, row) => sum + (row.count ?? 1), 0),
  };
}

export function waitWords(view: JourneyView): string {
  const plan = view.plan; const seconds = plan.expected_model_seconds;
  const time = seconds >= 90 ? `up to about ${Math.round(seconds / 60)} minute${Math.round(seconds / 60) === 1 ? "" : "s"}` : `about ${Math.round(seconds)} seconds`;
  const unmeasured = plan.unmeasured_question_types ?? [];
  return `The local model may be asked up to ${plan.model_questions} closed question${plan.model_questions === 1 ? "" : "s"}: ${time}.`
    + (unmeasured.length ? " That wait is an upper limit, not a measurement on this computer." : "");
}
