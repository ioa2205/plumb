import type { ReviewRun, RunComparison, RunHistory } from "../generated/contracts";
import historySchema from "../generated/run-history.schema.json" with { type: "json" };
import comparisonSchema from "../generated/run-comparison.schema.json" with { type: "json" };
import { parseRun, structuralMatches, validRunId } from "./run-metadata.ts";
import { readView } from "./review-data.ts";

export type ComparisonGroup=RunComparison["group"];
export const groups:readonly ComparisonGroup[]=["new","still_present","no_longer_observed","not_reviewed"];
export const groupLabels:Record<ComparisonGroup,string>={new:"New",still_present:"Still present",no_longer_observed:"No longer observed",not_reviewed:"Not reviewed this time"};
export class HistoryReadError extends Error {}
export function earlierRun(search:string,after:string|null):string|null{
  const values=new URLSearchParams(search).getAll("before");
  if(!values.length)return null;
  if(values.length!==1||!validRunId(values[0]!))throw new HistoryReadError("Use one valid earlier run ID.");
  return values[0]===after?null:values[0]!;
}
const page=(rows:readonly unknown[],total:number,offset:number,next:number|null)=>(!rows.length||offset+rows.length<=total)&&next===(offset+rows.length<total?offset+rows.length:null);
const validOffset=(n:number)=>Number.isSafeInteger(n)&&n>=0&&n<=1_000_000;
export function parseHistory(value:unknown,offset:number):RunHistory{
  if(!structuralMatches(value,historySchema))throw new HistoryReadError("Recorded history cannot be read.");
  const p=value as RunHistory;
  if(p.offset!==offset||!page(p.runs,p.total,p.offset,p.next_offset)||new Set(p.runs.map(r=>r.id)).size!==p.runs.length)throw new HistoryReadError("Recorded history has inconsistent pages.");
  for(const run of p.runs)parseRun(run,run.id);
  return p;
}
export async function fetchHistory(offset:number,signal:AbortSignal,request:typeof fetch=fetch):Promise<RunHistory>{
  if(!validOffset(offset))throw new HistoryReadError("Invalid history page.");
  return parseHistory(await readView(`/api/runs?offset=${offset}`,signal,request),offset);
}
export function parseComparison(value:unknown,before:string,after:string,group:ComparisonGroup,offset:number,policyOffset:number):RunComparison{
  if(!structuralMatches(value,comparisonSchema))throw new HistoryReadError("The saved comparison cannot be read.");
  const p=value as RunComparison;parseRun(p.before,before);parseRun(p.after,after);
  if(before===after||Date.parse(p.after.created_at)<Date.parse(p.before.created_at)||p.group!==group||p.offset!==offset||p.policy_offset!==policyOffset
    ||Object.keys(p.counts).length!==groups.length||groups.some(g=>!Number.isSafeInteger(p.counts[g])||(p.counts[g]??-1)<0)
    ||!page(p.rows,p.counts[group]!,p.offset,p.next_offset)||!page(p.policies,p.policies_total,p.policy_offset,p.policy_next_offset)
    ||new Set(p.rows.map(r=>r.id)).size!==p.rows.length)throw new HistoryReadError("The comparison has inconsistent run identities or counts.");
  for(const row of p.rows){
    if(row.group!==group||(group==="new"?(!!row.before||!row.after):!row.before)
      ||(["still_present","no_longer_observed"].includes(group)&&!row.after)
      ||(group==="no_longer_observed"&&row.after?.conclusion!=="rejected")
      ||(["new","still_present"].includes(group)&&row.after?.conclusion==="rejected"))throw new HistoryReadError("A comparison group differs from its recorded conclusions.");
    for(const [f,run] of [[row.before,p.before],[row.after,p.after]] as const)if(f&&(!(run.finding_ids??[]).includes(f.id)||(f.location&&f.location.snapshot_id!==run.snapshot_id)))throw new HistoryReadError("A compared finding belongs to another run.");
  }
  for(const drift of p.policies)for(const [count,run] of [[drift.before,p.before],[drift.after,p.after]] as const)if(count&&(count.applying>count.total||count.citations.some(c=>c.span.snapshot_id!==run.snapshot_id)))throw new HistoryReadError("Policy observations differ from their source or cohort.");
  return p;
}
export async function fetchComparison(before:string,after:string,group:ComparisonGroup,offset:number,policyOffset:number,signal:AbortSignal,request:typeof fetch=fetch):Promise<RunComparison>{
  if(!validRunId(before)||!validRunId(after)||before===after||!groups.includes(group)||!validOffset(offset)||!validOffset(policyOffset))throw new HistoryReadError("Choose two distinct recorded runs and a valid comparison page.");
  const params=new URLSearchParams({before,group,offset:String(offset),policy_offset:String(policyOffset)});
  return parseComparison(await readView(`/api/runs/${encodeURIComponent(after)}/compare?${params}`,signal,request),before,after,group,offset,policyOffset);
}
export function durationLabel(run:ReviewRun):string{
  if(!run.started_at||!run.finished_at)return run.started_at?"Ongoing or paused":"Not recorded";
  const seconds=(Date.parse(run.finished_at)-Date.parse(run.started_at))/1000;
  if(!Number.isFinite(seconds)||seconds<0)return "Invalid recorded timing";
  return seconds<60?`${seconds.toFixed(1)} s`:`${(seconds/60).toFixed(1)} min`;
}
