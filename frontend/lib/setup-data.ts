import type { InspectionView, SetupReadiness, LaunchRequest, ReviewRun, SourceCheck } from "../generated/contracts";
import inspectionSchema from "../generated/inspection-view.schema.json" with { type: "json" };
import readinessSchema from "../generated/setup-readiness.schema.json" with { type: "json" };
import sourceSchema from "../generated/source-check.schema.json" with { type: "json" };
import { parseRun, structuralMatches, validRunId } from "./run-metadata.ts";
import { validateCapabilities } from "./capability-data.ts";

export class SetupReadError extends Error {}
export function validLocalFolder(folder:string):boolean {
  return folder.length>0&&folder.length<=4096&&!/[\u0000-\u001f]/u.test(folder)
    &&(/^[a-z]:[\\/]/i.test(folder)||/^\/(?!\/)/.test(folder))
    &&!/^([a-z]:[\\/]|\/)$/i.test(folder);
}
export function reviewCommand(folder:string):string {
  if(!validLocalFolder(folder))throw new SetupReadError("Use an absolute local project folder.");
  return `uv run plumb review '${folder.replaceAll("'","''")}'`;
}
export function parseReadiness(value:unknown):SetupReadiness {
  if(!structuralMatches(value,readinessSchema))throw new SetupReadError("Readiness cannot be read.");
  const p=value as SetupReadiness;
  validateCapabilities(p.capabilities,null);
  const fits=p.available_ram_bytes>=p.required_ram_bytes&&p.available_vram_bytes!==null&&p.available_vram_bytes>=p.required_vram_bytes;
  if(p.memory_fit!==fits||p.requires_large_download_approval!==(p.missing_download_bytes>500_000_000)
    ||p.ready&&!(p.inspect_ready&&p.measured_host&&p.model_verified&&p.runtime_verified&&fits))throw new SetupReadError("Readiness disagrees with measured prerequisites.");
  return p;
}
export function parseInspection(value:unknown):InspectionView {
  if(!structuralMatches(value,inspectionSchema))throw new SetupReadError("The inspected source record cannot be read.");
  const p=value as InspectionView;
  validateCapabilities(p.capabilities,p.snapshot_id,p.languages,p.frameworks);
  if(p.entries_total<p.entries.length||new Set(p.entries.map(e=>e.id)).size!==p.entries.length
    ||p.entries.some(e=>e.snapshot_id!==p.snapshot_id||e.span.snapshot_id!==p.snapshot_id)
    ||[p.languages,p.frameworks,p.resources,p.exclusion_reasons].some(counts=>Object.values(counts).some(n=>n<0))
    ||Object.values(p.exclusion_reasons).reduce((a,b)=>a+b,0)!==p.excluded_files
    ||Object.values(p.frameworks).reduce((a,b)=>a+b,0)!==p.entries_total)throw new SetupReadError("The inspection has inconsistent scope or citations.");
  return p;
}
async function read(path:string,signal:AbortSignal,init:RequestInit,request:typeof fetch):Promise<unknown> {
  let response:Response;
  try{response=await request(path,{...init,signal,credentials:"same-origin",cache:"no-store",redirect:"error"});}
  catch{throw new SetupReadError("Plumb cannot be reached. Check its terminal, then try again.");}
  if(response.status===401||response.status===403)throw new SetupReadError("Open the one-time Plumb link printed in the terminal to connect this browser session.");
  if(response.status===409)throw new SetupReadError("Another review is running. Read its saved results and try after it stops.");
  if(!response.ok)throw new SetupReadError("This check could not complete. Check the absolute local folder, separate data storage and plumb setup in the terminal.");
  if(!response.body||!response.headers.get("content-type")?.startsWith("application/json"))throw new SetupReadError("Plumb returned an unreadable setup record.");
  const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>512*1024)throw new SetupReadError("The setup record is too large. Read the terminal summary.");chunks.push(value);}}
  catch(error){throw error instanceof SetupReadError?error:new SetupReadError("The setup transfer stopped. Try again.");}
  finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  try{return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));}catch{throw new SetupReadError("Plumb returned an unreadable setup record.");}
}
export async function fetchReadiness(signal:AbortSignal,request:typeof fetch=fetch):Promise<SetupReadiness>{return parseReadiness(await read("/api/setup",signal,{},request));}
export async function inspectFolder(folder:string,authorized:boolean,signal:AbortSignal,request:typeof fetch=fetch):Promise<InspectionView>{
  if(!authorized||!validLocalFolder(folder))throw new SetupReadError("Confirm authorization and enter an absolute local project folder.");
  return parseInspection(await read("/api/projects/inspect",signal,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({folder,authorized:true})},request));
}

const inspectionId=(value:string)=>/^inspect-[0-9a-f]{32}$/.test(value);
const post=(body:unknown):RequestInit=>({method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)});
function liveRun(value:unknown):ReviewRun {
  if(!value||typeof value!=="object"||!("id" in value)||typeof value.id!=="string")throw new SetupReadError("The started review cannot be read. Open Runs before trying again.");
  const run=parseRun(value,value.id);
  if(run.run_type!=="live")throw new SetupReadError("The response did not identify a live review.");
  return run;
}
export async function launchReview(inspection:InspectionView,body:LaunchRequest,signal:AbortSignal,request:typeof fetch=fetch):Promise<ReviewRun>{
  const allowed=["authorization","injection","path_traversal","nextjs_exposure"];
  if(!inspection.inspection_id||!inspectionId(body.inspection_id)||body.inspection_id!==inspection.inspection_id||body.authorized!==true||!Number.isInteger(body.limit??5)||(body.limit??5)<1||(body.limit??5)>20
    ||!body.families?.length||new Set(body.families).size!==body.families.length||body.families.some(f=>!allowed.includes(f))
    ||[...(body.resources??[]),...(body.routes??[])].some(s=>!s.length||s.length>256||/[\u0000-\u001f]/u.test(s))
    ||body.resources?.length&&body.families.some(f=>f!=="authorization"))throw new SetupReadError("Inspect an authorized folder and select valid review scope first.");
  const run=liveRun(await read("/api/projects/review",signal,post(body),request));
  if(run.snapshot_id!==inspection.snapshot_id)throw new SetupReadError("The started review does not match the inspected snapshot. Open Runs before retrying.");
  return run;
}
export async function resumeReview(id:string,signal:AbortSignal,request:typeof fetch=fetch):Promise<ReviewRun>{
  if(!validRunId(id))throw new SetupReadError("Open a recorded run first.");
  const run=liveRun(await read(`/api/runs/${encodeURIComponent(id)}/resume`,signal,post({limit:5}),request));
  if(run.id!==id)throw new SetupReadError("Resume returned a different review. Open Runs before retrying.");
  return run;
}
export function parseSourceCheck(value:unknown,id:string,snapshot:string):SourceCheck{
  if(!structuralMatches(value,sourceSchema))throw new SetupReadError("The source observation cannot be read.");
  const p=value as SourceCheck;const measured=p.state==="current"||p.state==="changed";
  const counts=[p.changed_files??null,p.added_files??null,p.removed_files??null];
  if(p.run_id!==id||p.snapshot_id!==snapshot||measured!==counts.every(n=>n!==null)
    ||measured!==(p.current_snapshot_id!=null&&p.excluded_scope_changed!=null)
    ||!measured&&[...counts,p.current_snapshot_id??null,p.excluded_scope_changed??null].some(n=>n!==null)
    ||measured&&(p.state==="changed")!==(counts.some(n=>!!n)||!!p.excluded_scope_changed)
    ||p.state==="current"&&p.current_snapshot_id!==p.snapshot_id)throw new SetupReadError("The source observation has inconsistent identity or counts.");
  return p;
}
export async function checkSource(id:string,snapshot:string,signal:AbortSignal,request:typeof fetch=fetch):Promise<SourceCheck>{
  if(!validRunId(id)||! /^[0-9a-f]{64}$/.test(snapshot))throw new SetupReadError("Open a recorded run first.");
  return parseSourceCheck(await read(`/api/runs/${encodeURIComponent(id)}/source-check`,signal,post({}),request),id,snapshot);
}
