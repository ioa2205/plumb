import type { CapabilityTable } from "../generated/contracts";
import schema from "../generated/capability-table.schema.json" with { type: "json" };
import { structuralMatches } from "./run-metadata.ts";

export function validateCapabilities(value:unknown,snapshot:string|null,languages?:Readonly<Record<string,number>>,frameworks?:Readonly<Record<string,number>>):void {
  if(value==null)return; // Legacy saved records did not record capability observations.
  if(!structuralMatches(value,schema))throw new Error("The capability record cannot be read.");
  const p=value as CapabilityTable;
  const seen=new Set<string>();
  if(p.snapshot_id!==snapshot)throw new Error("Capabilities belong to a different snapshot.");
  for(const row of p.rows){
    const key=`${row.category}:${row.name}`;
    if(seen.has(key))throw new Error("Duplicate capability scope.");seen.add(key);
    const units=row.units??null;
    for(const [level,count] of [[row.parsed,row.parsed_units??null],[row.indexed,row.indexed_units??null]] as const){
      if(units===null?(count!==null||!["unverified","not_applicable"].includes(level)):
        (snapshot===null||count===null||count>units||level!==(units===0?"unverified":count===units?"observed":"partial")))throw new Error("Capability observations disagree with their denominator.");
    }
    const inventory=row.category==="language"?languages:row.category==="framework"?frameworks:undefined;
    if(inventory&&units!==(inventory[row.name]??0))throw new Error("Capability scope disagrees with source inventory.");
  }
}
