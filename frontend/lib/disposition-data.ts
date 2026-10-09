import type { CaseDetail, DispositionDecision, DispositionUpdate } from "../generated/contracts";
import schema from "../generated/disposition-decision.schema.json" with { type: "json" };
import { structuralMatches, validRunId } from "./run-metadata.ts";

export class DispositionError extends Error {}

export function validDispositionHistory(detail:CaseDetail):boolean {
  const history=detail.disposition_history??[];const f=detail.finding;
  let state=history[0]?.previous_disposition??f.disposition??"open";let timestamp=0;
  for(const [index,d] of history.entries()){
    const time=Date.parse(d.recorded_at);
    if(!structuralMatches(d,schema)||d.run_id!==f.run_id||d.finding_id!==f.id||d.snapshot_id!==f.snapshot_id
      ||d.expected_version!==index||d.version!==index+1||d.previous_disposition!==state||d.disposition===state
      ||(state!=="open"&&d.disposition!=="open")||!Number.isFinite(time)||time<timestamp
      ||((d.disposition==="resolved")!==!!d.resolution_commit)
      ||d.original_finding_sha256!==history[0]!.original_finding_sha256||!d.reason.trim()||!d.actor.trim()
      ||/[\x00-\x1f]/.test(d.reason+d.actor))return false;
    state=d.disposition;timestamp=time;
  }
  return !history.length||(f.disposition===state&&f.disposition_reason===history.at(-1)!.reason);
}

export function dispositionIntent(detail:CaseDetail,disposition:DispositionUpdate["disposition"],reason:string,actor:string,commit:string):DispositionUpdate{
  const f=detail.finding;const previous=f.disposition??"open";
  if(!validDispositionHistory(detail)||disposition===previous||(previous!=="open"&&disposition!=="open"))throw new DispositionError("Refresh the case before changing its disposition.");
  if(!reason.trim()||reason.trim().length>1000||!actor.trim()||actor.trim().length>100||/[\x00-\x1f]/.test(reason+actor))throw new DispositionError("Enter a one-line reason and reviewer name.");
  if(disposition==="resolved"&&!/^[0-9a-f]{40}$/.test(commit))throw new DispositionError("Link the full 40-character commit hash before marking resolved.");
  return {snapshot_id:f.snapshot_id,expected_version:detail.disposition_history?.length??0,previous_disposition:previous,disposition,reason:reason.trim(),actor:actor.trim(),resolution_commit:disposition==="resolved"?commit:null};
}

export function applyDecision(detail:CaseDetail,value:unknown,intent:DispositionUpdate):CaseDetail{
  if(!structuralMatches(value,schema))throw new DispositionError("The decision response cannot be read. Refresh to check whether it was saved.");
  const decision=value as DispositionDecision;
  if(decision.run_id!==detail.run.id||decision.finding_id!==detail.finding.id||decision.snapshot_id!==intent.snapshot_id
    ||decision.expected_version!==intent.expected_version||decision.version!==intent.expected_version+1
    ||decision.previous_disposition!==intent.previous_disposition||decision.disposition!==intent.disposition
    ||(decision.resolution_commit??null)!==(intent.resolution_commit??null))throw new DispositionError("The response differs from this reviewer decision. Refresh its saved state.");
  const view:CaseDetail={...detail,finding:{...detail.finding,disposition:decision.disposition,disposition_reason:decision.reason},disposition_history:[...(detail.disposition_history??[]),decision]};
  if(!validDispositionHistory(view))throw new DispositionError("The saved reviewer history is inconsistent. Refresh the case.");
  return view;
}

export async function saveDecision(detail:CaseDetail,intent:DispositionUpdate,signal:AbortSignal,request:typeof fetch=fetch):Promise<CaseDetail>{
  if(!validRunId(detail.run.id))throw new DispositionError("Use a saved review.");
  const path=`/api/runs/${encodeURIComponent(detail.run.id)}/findings/${encodeURIComponent(detail.finding.id)}/disposition`;
  let response:Response;
  try{response=await request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(intent),signal,credentials:"same-origin",cache:"no-store",redirect:"error"});}
  catch{throw new DispositionError("Save was not acknowledged. Refresh before trying again; it may already be recorded.");}
  if(!response.ok){await response.body?.cancel();throw new DispositionError(response.status===409?"Another decision changed this case, or its history is full. Refresh before trying again.":response.status===401?"Open the one-time terminal link to restore this browser session.":"Decision could not be acknowledged. Refresh its saved state before trying again.");}
  // Reuse the bounded case response reader without a second network request.
  const {readCaseRecord}=await import("./case-data.ts");
  const value=await readCaseRecord(path,signal,async()=>response);
  if(signal.aborted)throw new DispositionError("Save canceled. Refresh to check whether it was recorded.");
  return applyDecision(detail,value,intent);
}
