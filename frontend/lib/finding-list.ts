import type { FindingList, FindingListSchema } from "../generated/contracts";
import schema from "../generated/finding-list.schema.json" with { type:"json" };
import { parseRun, structuralMatches } from "./run-metadata.ts";
import { readView, ReviewError, runPath } from "./review-data.ts";

export type FindingFilters={family:FindingListSchema.Family|"";severity:FindingListSchema.Severity|"";runtime_verification:FindingListSchema.RuntimeVerification|"";disposition:FindingListSchema.Disposition|""};
export const emptyFilters:FindingFilters={family:"",severity:"",runtime_verification:"",disposition:""};
export const conclusionOrder=["supported","inconclusive","candidate","rejected"] as const;
export const filterOptions={family:schema.$defs.Family.enum,severity:schema.$defs.Severity.enum,runtime_verification:schema.$defs.RuntimeVerification.enum,disposition:schema.$defs.Disposition.enum};
export function parseFindingList(value:unknown,id:string,offset:number,filters:FindingFilters):FindingList{
  if(!structuralMatches(value,schema))throw new ReviewError("This finding list cannot be read.");
  const list=value as FindingList;const run=parseRun(list.run,id);const end=offset+list.findings.length;
  const observed=list.supplementary;
  if(observed&&(observed.run_id!==id||observed.snapshot_id!==run.snapshot_id
    ||new Set(observed.signals?.map(s=>s.id)).size!==(observed.signals?.length??0)
    ||observed.signals?.some(s=>s.source.snapshot_id!==run.snapshot_id)
    ||((observed.pack_sha256===null)!==(observed.pack_date===null))
    ||(observed.status==="not_run"&&observed.signals?.length)))throw new ReviewError("These security signals have inconsistent records.");
  if(list.offset!==offset||list.next_offset!==(end<list.total?end:null)||list.total>(run.finding_ids?.length||0)
    ||(list.findings.length>0&&end>list.total)
    ||Object.keys(list.counts).length!==4||conclusionOrder.some(c=>!Number.isSafeInteger(list.counts[c])||list.counts[c]!<0)
    ||Object.values(list.counts).reduce((n,v)=>n+v,0)!==list.total
    ||new Set(list.findings.map(f=>f.id)).size!==list.findings.length
    ||list.findings.some((f,i)=>!run.finding_ids?.includes(f.id)||(f.location&&f.location.snapshot_id!==run.snapshot_id)
      ||Object.entries(filters).some(([key,v])=>v&&f[key as keyof FindingFilters]!==v)
      ||(i>0&&conclusionOrder.indexOf(list.findings[i-1]!.conclusion)>conclusionOrder.indexOf(f.conclusion))))throw new ReviewError("This finding list has inconsistent records.");
  return list;
}
export async function fetchFindingList(id:string,offset:number,filters:FindingFilters,signal:AbortSignal,request:typeof fetch=fetch):Promise<FindingList>{
  if(!Number.isSafeInteger(offset)||offset<0||offset>1_000_000)throw new ReviewError("Invalid findings page.");
  const query=new URLSearchParams({offset:String(offset)});for(const [key,value] of Object.entries(filters))if(value)query.set(key,value);
  return parseFindingList(await readView(`${runPath(id)}/finding-list?${query}`,signal,request),id,offset,filters);
}
