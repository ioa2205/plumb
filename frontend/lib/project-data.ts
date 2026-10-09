import type { ProjectPage, ProjectPageSchema, ProjectExcerpt, ProjectRule, PolicyInput, BoundPolicy } from "../generated/contracts";
import boundSchema from "../generated/bound-policy.schema.json" with { type: "json" };
export type ProjectCitation=ProjectPageSchema.ProjectCitation;
export type ProjectFlow=ProjectPageSchema.ProjectFlow;
import pageSchema from "../generated/project-page.schema.json" with { type: "json" };
import ruleSchema from "../generated/project-rule.schema.json" with { type: "json" };
import excerptSchema from "../generated/project-excerpt.schema.json" with { type: "json" };
import { structuralMatches, validRunId } from "./run-metadata.ts";
import { readView } from "./review-data.ts";
import { validateCapabilities } from "./capability-data.ts";

export class ProjectReadError extends Error {}
export type ProjectOffsets={offset:number;scope_offset:number;policy_offset:number};
export const firstProjectPage:ProjectOffsets={offset:0,scope_offset:0,policy_offset:0};
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
const validId=(id:string)=>/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.exec(id)?.[0]===id;
function base(id:string){if(!validRunId(id))throw new ProjectReadError("Select a recorded run to read its frozen project.");return `/api/runs/${encodeURIComponent(id)}/project`;}
function pages(rows:readonly unknown[],total:number,offset:number,next:number|null){return (!rows.length||offset+rows.length<=total)&&next===(offset+rows.length<total?offset+rows.length:null);}
export function parseProject(value:unknown,id:string,snapshot:string,offsets:ProjectOffsets):ProjectPage{
  if(!structuralMatches(value,pageSchema))throw new ProjectReadError("The frozen project record cannot be read.");
  const p=value as ProjectPage;
  validateCapabilities(p.capabilities,p.snapshot_id,p.languages,p.frameworks);
  const nodes=p.flows.flatMap(f=>[f.entry,...f.guards,...f.data]);
  const citations=[...nodes.map(n=>n.citation),...p.rules.flatMap(r=>r.citations)];
  if(p.run_id!==id||p.snapshot_id!==snapshot||Object.entries(offsets).some(([key,n])=>p[key as keyof ProjectOffsets]!==n)
    ||!pages(p.flows,p.flows_total,p.offset,p.next_offset)||!pages(p.exclusions,p.excluded_files,p.scope_offset,p.scope_next_offset)||!pages(p.rules,p.rules_total,p.policy_offset,p.policy_next_offset)
    ||Object.values(p.exclusion_reasons).reduce((a,b)=>a+b,0)!==p.excluded_files
    ||[...Object.values(p.languages),...Object.values(p.frameworks),...Object.values(p.resources),...Object.values(p.exclusion_reasons)].some(n=>n<0)
    ||citations.some(c=>c.span.snapshot_id!==snapshot||c.span.end_line<c.span.start_line)
    ||p.flows.some(f=>{const ids=new Set([f.entry,...f.guards,...f.data].map(n=>n.id));return f.guards.length>f.guards_total||f.data.length>f.data_total||ids.size!==1+f.guards.length+f.data.length||f.links.some(e=>!ids.has(e.source)||!ids.has(e.target));})
    ||p.rules.some(r=>r.source_run_id!==id||r.sites_applying>r.sites_total||!same(r.citations.map(c=>c.span),r.assertion.evidence)
      ||(r.assertion.status==="confirmed")!==!!(r.assertion.confirmed_by&&r.assertion.confirmed_at))
    ||(p.bound_policies??[]).some(p=>p.snapshot_id!==snapshot||p.sites.some(s=>s.snapshot_id!==snapshot||s.span.snapshot_id!==snapshot||s.resource!==p.assertion.resource)))throw new ProjectReadError("The project record has inconsistent source or scope.");
  return p;
}
export async function fetchProject(id:string,snapshot:string,offsets:ProjectOffsets,signal:AbortSignal,request:typeof fetch=fetch):Promise<ProjectPage>{
  if(Object.values(offsets).some(n=>!Number.isSafeInteger(n)||n<0||n>1_000_000))throw new ProjectReadError("Invalid project page.");
  const params=new URLSearchParams(Object.entries(offsets).map(([key,n])=>[key,String(n)]));
  return parseProject(await readView(`${base(id)}?${params}`,signal,request),id,snapshot,offsets);
}
export function parseProjectExcerpt(value:unknown,id:string,citation:ProjectCitation,offset:number):ProjectExcerpt{
  if(!structuralMatches(value,excerptSchema))throw new ProjectReadError("The frozen project source cannot be read.");
  const p=value as ProjectExcerpt;const span=citation.span;
  if(p.run_id!==id||!same(p.citation,citation)||p.offset!==offset||p.start_line!==span.start_line+offset||p.end_line!==p.start_line+p.lines.length-1||p.end_line>span.end_line
    ||p.next_offset!==(p.end_line<span.end_line?offset+p.lines.length:null))throw new ProjectReadError("The source page differs from its frozen citation.");
  return p;
}
export async function fetchProjectExcerpt(id:string,citation:ProjectCitation,offset:number,signal:AbortSignal,request:typeof fetch=fetch):Promise<ProjectExcerpt>{
  if(!validId(citation.id)||!Number.isSafeInteger(offset)||offset<0||offset>1_000_000)throw new ProjectReadError("Invalid project citation.");
  return parseProjectExcerpt(await readView(`${base(id)}/citations/${encodeURIComponent(citation.id)}?offset=${offset}`,signal,request),id,citation,offset);
}
export function parseConfirmedRule(value:unknown,proposal:ProjectRule):ProjectRule{
  if(!structuralMatches(value,ruleSchema))throw new ProjectReadError("The rule confirmation cannot be read. Refresh to check its saved status.");
  const rule=value as ProjectRule;
  const normalized={...rule,assertion:{...rule.assertion,status:proposal.assertion.status,confirmed_by:proposal.assertion.confirmed_by,confirmed_at:proposal.assertion.confirmed_at}};
  if(rule.assertion.status!=="confirmed"||!rule.assertion.confirmed_by||!rule.assertion.confirmed_at||!same(normalized,proposal))throw new ProjectReadError("The confirmation differs from the proposed source-bound rule.");
  return rule;
}
export async function confirmProjectRule(proposal:ProjectRule,signal:AbortSignal,request:typeof fetch=fetch):Promise<ProjectRule>{
  if(!validId(proposal.assertion.id))throw new ProjectReadError("Invalid rule identifier.");
  const path=`${base(proposal.source_run_id)}/rules/${encodeURIComponent(proposal.assertion.id)}/confirm`;
  let response:Response;
  try{response=await request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({proposal_sha256:proposal.proposal_sha256}),signal,credentials:"same-origin",cache:"no-store",redirect:"error"});}
  catch{throw new ProjectReadError("Confirmation was not acknowledged. Refresh before trying again; it may already be saved.");}
  if(response.status===409){await response.body?.cancel();throw new ProjectReadError("This rule changed. Refresh the project before confirming it.");}
  return parseConfirmedRule(await readView(path,signal,async()=>response),proposal);
}

export async function declareProjectRule(id:string,input:PolicyInput,signal:AbortSignal,request:typeof fetch=fetch):Promise<BoundPolicy>{
  const path=`${base(id)}/rules`;
  let response:Response;
  try{response=await request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input),signal,credentials:"same-origin",cache:"no-store",redirect:"error"});}
  catch{throw new ProjectReadError("Rule save was not acknowledged. Refresh before trying again.");}
  if(response.status===409){await response.body?.cancel();throw new ProjectReadError("Rule source changed or its accesses are unrelated. Refresh and revalidate it.");}
  const value=await readView(path,signal,async()=>response);
  if(!structuralMatches(value,boundSchema))throw new ProjectReadError("The saved rule cannot be read. Refresh its status.");
  const p=value as BoundPolicy;
  if(p.snapshot_id!==input.snapshot_id||p.source_run_id!==id||p.assertion.status!=="declared"||p.assertion.statement!==input.statement||p.assertion.author!==input.author||p.assertion.kind!==(input.required_guard??"unknown")||!same(p.forbidden_fields,input.forbidden_fields??[])||!same(p.sites.map(s=>s.id).sort(),[...input.site_ids].sort())||p.sites.some(s=>s.snapshot_id!==input.snapshot_id||s.resource!==p.assertion.resource))throw new ProjectReadError("Saved rule differs from the submitted requirement.");
  return p;
}
