import type { CaseDetail, CitedExcerpt, FindingPage, PeerExcerpt } from "../generated/contracts";
import caseSchema from "../generated/case-detail.schema.json" with { type: "json" };
import pageSchema from "../generated/finding-page.schema.json" with { type: "json" };
import excerptSchema from "../generated/cited-excerpt.schema.json" with { type: "json" };
import peerExcerptSchema from "../generated/peer-excerpt.schema.json" with { type: "json" };
import { peerCitations, validPeer } from "./peer-data.ts";
import { parseRun, structuralMatches, validRunId } from "./run-metadata.ts";
import { validChangeEvidence } from "./change-data.ts";
import { observed } from "./proof-data.ts";
import { validDispositionHistory } from "./disposition-data.ts";
export { observed } from "./proof-data.ts";

const idPattern=new RegExp(caseSchema.properties.finding.$ref ? caseSchema.$defs.Finding.properties.id.pattern : "(?!)");
export const MAX_CASE_BYTES=512*1024;
export class CaseReadError extends Error {}
export function validFindingId(id:string):boolean { return idPattern.exec(id)?.[0]===id; }
export function selectedFinding(search:string):string|null {
  const ids=new URLSearchParams(search).getAll("finding");
  if(!ids.length) return null;
  if(ids.length !== 1 || !validFindingId(ids[0]!)) throw new CaseReadError("Use one valid finding ID from this run.");
  return ids[0]!;
}
export function caseDestination(run:string,id:string):string {
  if(!validRunId(run) || !validFindingId(id)) throw new CaseReadError("Invalid case selection.");
  return `/findings/?${new URLSearchParams({run,finding:id})}`;
}
export function parsePage(value:unknown,runId:string,offset:number):FindingPage {
  if(!structuralMatches(value,pageSchema)) throw new CaseReadError("The finding list cannot be read. Open its saved report.");
  const page=value as FindingPage; const run=parseRun(page.run,runId); const end=offset+page.findings.length;
  if(page.offset !== offset || page.total !== (run.finding_ids?.length||0)
    || page.next_offset !== (end<page.total ? end : null)
    || page.findings.some((finding,index)=>finding.id !== run.finding_ids?.[offset+index] || finding.run_id !== run.id || finding.snapshot_id !== run.snapshot_id)) throw new CaseReadError("The finding list is inconsistent. Open its saved report.");
  return page;
}
export function parseCase(value:unknown,runId:string,findingId:string):CaseDetail {
  if(!validFindingId(findingId) || !structuralMatches(value,caseSchema)) throw new CaseReadError("This case cannot be read. Open its saved report.");
  const detail=value as CaseDetail; const run=parseRun(detail.run,runId); const f=detail.finding; const change=detail.suggested_change;
  const proposal=detail.proposal;
  if(!validDispositionHistory(detail))throw new CaseReadError("This reviewer history does not match the saved case.");
  if(proposal&&(proposal.finding_id!==f.id||proposal.snapshot_id!==f.snapshot_id||f.conclusion!=="supported"
    ||((proposal.status==="proposed")!==!!proposal.change)
    ||proposal.change&&JSON.stringify(proposal.change)!==JSON.stringify(change??null)
    ||((proposal.probe_status==="available")!==!!proposal.probe_spec)
    ||(proposal.probe_spec&&(proposal.probe_spec.finding_id!==f.id||!proposal.adapter_manifest_sha256))))throw new CaseReadError("This proposal has inconsistent evidence links.");
  const probeIds=[...(f.probe_run_ids||[]),...(change?.replay_probe_run_ids||[])];
  if(f.id !== findingId || f.run_id !== run.id || f.snapshot_id !== run.snapshot_id || !run.finding_ids?.includes(f.id)
    || (typeof detail.peer_comparison==="object"&&!validPeer(detail.peer_comparison,f))
    || (!!change !== !!f.suggested_change_id) || (change && (change.id !== f.suggested_change_id || change.finding_id !== f.id))
    || new Set(detail.probe_runs.map(p=>p.id)).size !== detail.probe_runs.length || new Set(probeIds).size !== detail.probe_runs.length
    || detail.probe_runs.some(p=>p.finding_id !== f.id || !probeIds.includes(p.id)
      || (p.snapshot_role === "vulnerable" && (p.snapshot_id !== run.snapshot_id || !f.probe_run_ids?.includes(p.id)))
      || (p.snapshot_role === "patched" && !change?.replay_probe_run_ids?.includes(p.id)))
    || !validChangeEvidence(f,change,detail.probe_runs)
    || f.exhibits.some(e=>e.span.snapshot_id !== run.snapshot_id)
    || new Set(f.exhibits.map(e=>e.tag)).size !== f.exhibits.length) throw new CaseReadError("This case has inconsistent evidence links. Open its saved report.");
  return detail;
}
export function parseExcerpt(value:unknown,detail:CaseDetail,tag:string,offset:number):CitedExcerpt {
  if(!structuralMatches(value,excerptSchema)) throw new CaseReadError("This excerpt cannot be read.");
  const result=value as CitedExcerpt; const exhibit=detail.finding.exhibits.find(e=>e.tag===tag); const span=exhibit?.span;
  if(!span || result.run_id !== detail.run.id || result.finding_id !== detail.finding.id || result.snapshot_id !== detail.run.snapshot_id
    || result.exhibit.tag !== tag || result.exhibit.role !== exhibit.role || result.exhibit.gloss !== exhibit.gloss
    || result.exhibit.span.path !== span.path || result.exhibit.span.snapshot_id !== span.snapshot_id
    || result.exhibit.span.content_sha256 !== span.content_sha256 || result.exhibit.span.start_line !== span.start_line || result.exhibit.span.end_line !== span.end_line
    || result.start_line !== span.start_line+offset || result.end_line < result.start_line || result.end_line>span.end_line
    || result.lines.length !== result.end_line-result.start_line+1 || result.next_offset !== (result.end_line<span.end_line ? result.end_line-span.start_line+1 : null)) throw new CaseReadError("This excerpt does not match the selected citation.");
  return result;
}

export function parsePeerExcerpt(value:unknown,detail:CaseDetail,site:string,citation:number,offset:number):PeerExcerpt {
  if(!structuralMatches(value,peerExcerptSchema))throw new CaseReadError("This peer citation cannot be read.");
  const result=value as PeerExcerpt;const peer=detail.peer_comparison;
  const row=typeof peer==="object" ? peer.rows.find(r=>r.site.id===site) : undefined;
  const span=row ? peerCitations(row)[citation] : undefined;
  if(!span||result.run_id!==detail.run.id||result.finding_id!==detail.finding.id||result.site_id!==site||result.citation!==citation
    ||result.span.path!==span.path||result.span.snapshot_id!==span.snapshot_id||result.span.content_sha256!==span.content_sha256
    ||result.span.start_line!==span.start_line||result.span.end_line!==span.end_line||result.start_line!==span.start_line+offset
    ||result.end_line<result.start_line||result.end_line>span.end_line||result.lines.length!==result.end_line-result.start_line+1
    ||result.next_offset!==(result.end_line<span.end_line ? result.end_line-span.start_line+1 : null))throw new CaseReadError("This excerpt does not match the selected peer citation.");
  return result;
}

export async function readCaseRecord(path:string,signal:AbortSignal,request:typeof fetch):Promise<unknown> {
  let response:Response;
  try { response=await request(path,{signal,credentials:"same-origin",cache:"no-store",redirect:"error"}); }
  catch { throw new CaseReadError("Plumb cannot be reached. Check that the backend is running."); }
  if(response.status===401) throw new CaseReadError("Open the one-time Plumb link printed in the terminal to start this browser session.");
  if(response.status===404) throw new CaseReadError("No saved case matches this selection. A run still in progress may not have a report yet.");
  if(!response.ok) throw new CaseReadError("Plumb cannot read this saved case safely. Its report is preserved.");
  if(!response.body || !response.headers.get("content-type")?.startsWith("application/json")) throw new CaseReadError("Plumb did not return a readable case.");
  const reader=response.body.getReader(); const chunks:Uint8Array[]=[];let size=0;
  try {
    while(true) { const {done,value}=await reader.read();if(done)break;size+=value.byteLength;
      if(size>MAX_CASE_BYTES) {await reader.cancel();throw new CaseReadError("This saved case is too large to display. Open its report.");} chunks.push(value); }
  } catch(error) { throw error instanceof CaseReadError ? error : new CaseReadError("The case transfer stopped. Try again."); }
  finally { reader.releaseLock(); }
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  try {return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));}
  catch {throw new CaseReadError("This saved case cannot be read. Open its report.");}
}
function base(run:string):string {
  if(!validRunId(run))throw new CaseReadError("Use a valid recorded run ID.");
  return `/api/runs/${encodeURIComponent(run)}/findings`;
}
export async function fetchPage(run:string,offset:number,signal:AbortSignal,request:typeof fetch=fetch):Promise<FindingPage> {
  if(!Number.isSafeInteger(offset)||offset<0||offset>1_000_000)throw new CaseReadError("Invalid finding page.");
  return parsePage(await readCaseRecord(`${base(run)}?offset=${offset}&limit=20`,signal,request),run,offset);
}
export async function fetchCase(run:string,finding:string,signal:AbortSignal,request:typeof fetch=fetch):Promise<CaseDetail> {
  if(!validFindingId(finding))throw new CaseReadError("Use a finding from this run.");
  return parseCase(await readCaseRecord(`${base(run)}/${encodeURIComponent(finding)}`,signal,request),run,finding);
}
export async function fetchExcerpt(detail:CaseDetail,tag:string,offset:number,signal:AbortSignal,request:typeof fetch=fetch):Promise<CitedExcerpt> {
  if(!detail.finding.exhibits.some(e=>e.tag===tag && e.role!=="developer_note") || !Number.isSafeInteger(offset) || offset<0 || offset>1_000_000) throw new CaseReadError("Use a cited code exhibit from this case.");
  return parseExcerpt(await readCaseRecord(`${base(detail.run.id)}/${encodeURIComponent(detail.finding.id)}/exhibits/${encodeURIComponent(tag)}?offset=${offset}&lines=80`,signal,request),detail,tag,offset);
}
export async function fetchPeerExcerpt(detail:CaseDetail,site:string,citation:number,offset:number,signal:AbortSignal,request:typeof fetch=fetch):Promise<PeerExcerpt> {
  const peer=detail.peer_comparison;const row=typeof peer==="object" ? peer.rows.find(r=>r.site.id===site) : undefined;
  if(!row||!Number.isSafeInteger(citation)||!peerCitations(row)[citation]||!Number.isSafeInteger(offset)||offset<0||offset>1_000_000)throw new CaseReadError("Use a recorded peer citation from this case.");
  return parsePeerExcerpt(await readCaseRecord(`${base(detail.run.id)}/${encodeURIComponent(detail.finding.id)}/peers/${encodeURIComponent(site)}/citations/${citation}?offset=${offset}&lines=80`,signal,request),detail,site,citation,offset);
}
export function proofSummary(detail:CaseDetail):string|null {
  const probe=detail.probe_runs.find(p=>p.snapshot_role==="vulnerable");
  if(!probe)return null;
  const attack=probe.steps.find(s=>s.role==="attack"&&observed(s)==="allowed");
  const control=probe.steps.find(s=>s.role==="control"&&observed(s)==="allowed");
  if(probe.outcome==="reproduced"&&attack&&control) return `In the recorded test, ${attack.principal}'s attack request returned the victim marker. ${control.principal}'s legitimate-user control also succeeded.`;
  if(probe.outcome==="not_reproduced"&&control)return `The recorded attack did not expose the victim marker under the tested conditions. ${control.principal}'s legitimate-user control succeeded.`;
  return "The recorded runtime observations did not settle this case. Read the steps and conditions below.";
}
