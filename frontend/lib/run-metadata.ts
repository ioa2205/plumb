import type { ReviewRun } from "../generated/contracts";
import schemaJson from "../generated/review-run.schema.json" with { type: "json" };

type Schema = {
  $ref?: string; $defs?: Record<string, Schema>; type?: string; enum?: unknown[]; const?: unknown;
  anyOf?: Schema[]; properties?: Record<string, Schema>; required?: string[];
  additionalProperties?: boolean | Schema; items?: Schema; pattern?: string; format?: string;
  minimum?: number; maximum?: number; minLength?: number; maxLength?: number;
  minItems?: number; maxItems?: number;
};
const schema = schemaJson as Schema;
const runPattern = new RegExp(schemaJson.properties.id.pattern);
export const MAX_RUN_BYTES = 256 * 1024;
export class RunReadError extends Error {}

// This is the bounded structural projection used by the header, not an evidence validator.
function matches(value: unknown, node: Schema, depth = 0, root: Schema = schema): boolean {
  if(depth > 32) return false;
  if(node.$ref) {
    const name = node.$ref.replace(/^#\/\$defs\//, "");
    const definition = root.$defs?.[name];
    return node.$ref === `#/$defs/${name}` && !!definition && matches(value,definition,depth+1,root);
  }
  if(node.anyOf) return node.anyOf.some(item => matches(value,item,depth+1,root));
  if(node.enum && !node.enum.includes(value)) return false;
  if(Object.hasOwn(node,"const") && value !== node.const) return false;
  switch(node.type) {
    case "null": return value === null;
    case "boolean": return typeof value === "boolean";
    case "string": return typeof value === "string"
      && (node.minLength === undefined || value.length >= node.minLength)
      && (node.maxLength === undefined || value.length <= node.maxLength)
      && (!node.pattern || new RegExp(node.pattern).test(value))
      && (!node.format || (Number.isFinite(Date.parse(value)) && (node.format !== "date-time" || /T.*(?:Z|[+-]\d\d:\d\d)$/.test(value))));
    case "integer": case "number": return typeof value === "number" && Number.isFinite(value)
      && (node.type !== "integer" || Number.isSafeInteger(value))
      && (node.minimum === undefined || value >= node.minimum)
      && (node.maximum === undefined || value <= node.maximum);
    case "array": return Array.isArray(value) && value.length <= 4096
      && (node.minItems === undefined || value.length >= node.minItems)
      && (node.maxItems === undefined || value.length <= node.maxItems)
      && !!node.items && value.every(item => matches(item,node.items!,depth+1,root));
    case "object": {
      if(!value || typeof value !== "object" || Array.isArray(value)) return false;
      const data = value as Record<string,unknown>;
      if(node.required?.some(key => !Object.hasOwn(data,key))) return false;
      return Object.entries(data).every(([key,item]) => {
        const child = node.properties?.[key];
        return child ? matches(item,child,depth+1,root) : node.additionalProperties !== false;
      });
    }
    default: return false;
  }
}

export function structuralMatches(value: unknown, input: unknown): boolean {
  const root=input as Schema;
  return matches(value,root,0,root);
}

export function validRunId(id: string): boolean { return runPattern.exec(id)?.[0] === id; }

export function selectedRun(search: string): string | null {
  const values = new URLSearchParams(search).getAll("run");
  if(!values.length) return null;
  if(values.length !== 1 || !validRunId(values[0]!)) throw new Error("Use one valid run ID from a review.");
  return values[0]!;
}

export function runDestination(path: string, id: string | null): string {
  if(!["/","/review/","/findings/","/runs/"].includes(path)) throw new Error("Unknown workbench destination");
  if(id === null) return path;
  if(!validRunId(id)) throw new Error("Invalid run ID");
  return `${path}?${new URLSearchParams({run:id})}`;
}

export function parseRun(value: unknown, requested: string): ReviewRun {
  if(!validRunId(requested) || !matches(value,schema)) throw new Error("This run record cannot be read. Open its saved report or recheck the run ID.");
  const run = value as ReviewRun;
  const coverage = run.coverage;
  const active = run.lifecycle === "running" || run.lifecycle === "paused";
  const ended = ["canceled","failed","completed"].includes(run.lifecycle);
  if(run.id !== requested || active !== !!run.stage || ended !== !!run.finished_at
    || (coverage && [coverage.total,coverage.completed,coverage.pending,coverage.excluded,coverage.unsupported].some(x=>x===undefined))
    || (coverage && coverage.completed!+coverage.pending!+coverage.excluded!+coverage.unsupported! !== coverage.total)) {
    throw new Error("This run record is inconsistent. Open its saved report or recheck the run ID.");
  }
  return run;
}

export function runLabel(run: ReviewRun): string {
  if(run.run_type === "live") return "Live";
  const date = new Intl.DateTimeFormat("en-GB",{dateStyle:"medium",timeStyle:"short",timeZone:"UTC"}).format(new Date(run.created_at));
  return `${run.run_type === "saved" ? "Saved run" : "Replay of saved run"} · ${date} UTC`;
}

export function lifecycleLabel(run: ReviewRun): string {
  const labels = {queued:"Queued",running:"Running",paused:"Paused at checkpoint",canceled:"Canceled",failed:"Failed",completed:"Completed"};
  return labels[run.lifecycle];
}

export async function fetchRun(id: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<ReviewRun> {
  if(!validRunId(id)) throw new RunReadError("Use the run ID printed by a review.");
  let response: Response;
  try { response = await request(`/api/runs/${encodeURIComponent(id)}`,{signal,credentials:"same-origin",cache:"no-store",redirect:"error"}); }
  catch { throw new RunReadError("Plumb cannot be reached. Start the backend and open its one-time browser link, then try again."); }
  if(response.status === 401) throw new RunReadError("Open the one-time Plumb link printed in the terminal to start this browser session.");
  if(response.status === 404) throw new RunReadError("No recorded run has this ID. Copy the ID printed by a review.");
  if(!response.ok) throw new RunReadError("Plumb cannot read this run right now. Its saved report is still available.");
  if(!response.headers.get("content-type")?.startsWith("application/json") || !response.body) throw new RunReadError("Plumb did not return a readable run record.");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while(true) {
      const {done,value} = await reader.read(); if(done) break;
      size += value.byteLength;
      if(size > MAX_RUN_BYTES) { await reader.cancel(); throw new RunReadError("This run record is too large to display. Open its saved report."); }
      chunks.push(value);
    }
  } catch(error) { throw error instanceof RunReadError ? error : new RunReadError("The run transfer stopped before it finished. Try opening the run again."); }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for(const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.byteLength; }
  try { return parseRun(JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)),id); }
  catch { throw new RunReadError("This run record cannot be read. Open its saved report or recheck the run ID."); }
}
