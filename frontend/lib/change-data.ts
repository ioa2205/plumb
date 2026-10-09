import type { CaseDetail, ProbeRun, SuggestedChange, SuggestedChangeSchema } from "../generated/contracts";
import caseSchema from "../generated/case-detail.schema.json" with { type: "json" };
import { structuralMatches } from "./run-metadata.ts";
import { probeOutcome } from "./proof-data.ts";

export type ChangeFinding=Pick<CaseDetail["finding"],"id"|"snapshot_id"|"probe_run_ids"|"suggested_change_id">;
const changeSchema={...caseSchema.$defs.SuggestedChange,$defs:caseSchema.$defs};
const probeSchema={...caseSchema.$defs.ProbeRun,$defs:caseSchema.$defs};
/** Preserve exact saved association and verify claims against recorded observations. */
export function validChangeEvidence(finding:ChangeFinding,change:SuggestedChange|null|undefined,probes:readonly ProbeRun[]):boolean {
  if((change==null)!=(finding.suggested_change_id==null)||change&&(!structuralMatches(change,changeSchema)||change.id!==finding.suggested_change_id||change.finding_id!==finding.id))return false;
  const baseline=finding.probe_run_ids??[],replay=change?.replay_probe_run_ids??[];
  if(new Set(baseline).size!==baseline.length||new Set(replay).size!==replay.length||baseline.some(id=>replay.includes(id)))return false;
  const ids=[...baseline,...replay];
  if(new Set(probes.map(p=>p.id)).size!==probes.length||ids.length!==probes.length)return false;
  for(const p of probes) {
    if(!structuralMatches(p,probeSchema)||p.finding_id!==finding.id||!ids.includes(p.id)||p.outcome!==probeOutcome(p)
      ||!Number.isFinite(Date.parse(p.started_at))||!Number.isFinite(Date.parse(p.finished_at))||Date.parse(p.finished_at)<Date.parse(p.started_at)
      ||p.steps.some(s=>s.role==="attack"&&s.expected_if_safe!=="denied"||s.role==="control"&&s.expected_if_safe!=="allowed"))return false;
    if(p.snapshot_role==="vulnerable" ? !baseline.includes(p.id)||p.snapshot_id!==finding.snapshot_id : !replay.includes(p.id)||p.snapshot_id===finding.snapshot_id)return false;
  }
  if(!change)return true;
  if(change.snapshot_id&&change.snapshot_id!==finding.snapshot_id)return false;
  if(change.source_edits?.length) {
    const scope=change.source_scope;
    if(!scope||scope.snapshot_id!==finding.snapshot_id||change.files.length!==1||change.files[0]!==scope.path
      ||new Set(change.source_edits.map(e=>e.source.start_line)).size!==change.source_edits.length
      ||change.source_edits.some(e=>e.source.snapshot_id!==finding.snapshot_id||e.source.path!==scope.path
        ||e.source.start_line!==e.source.end_line||e.source.start_line<scope.start_line||e.source.end_line>scope.end_line
        ||(e.action==="delete"?e.code!=="":!e.code.trim())))return false;
  } else if(change.snapshot_id||change.source_scope)return false;
  if(!`\n${change.diff}`.includes("\n--- ")||!change.diff.includes("\n+++ "))return false;
  const status=change.status??"proposed",patched=probes.filter(p=>replay.includes(p.id));
  if(status==="proposed")return replay.length===0;
  if(!patched.length)return false;
  const comparable=(p:ProbeRun)=>probes.some(b=>baseline.includes(b.id)&&b.outcome==="reproduced"&&b.runner===p.runner&&b.runner_manifest_sha256===p.runner_manifest_sha256&&Date.parse(b.finished_at)<=Date.parse(p.started_at));
  // The backend allows an inconclusive historical attempt beside a successful replay.
  if(status==="replayed_fixed")return patched.some(p=>p.outcome==="fixed"&&comparable(p))&&!patched.some(p=>p.outcome==="not_fixed");
  if(status==="replayed_not_fixed")return patched.some(p=>p.outcome==="not_fixed"&&comparable(p));
  return status==="replay_failed"&&(patched.some(p=>p.outcome==="inconclusive")||!patched.some(comparable));
}

const states:Record<SuggestedChangeSchema.ChangeStatus,{title:string;explanation:string;tone:"proposed"|"ink"|"risk"|"attention"}>={
  proposed:{title:"Proposed, not applied",explanation:"No patched-snapshot replay was recorded. The suggestion has not changed your project.",tone:"proposed"},
  replayed_fixed:{title:"Fixed in disposable replay",explanation:"A recorded replay denied the attack while legitimate-user controls still succeeded. This result applies to the tested patched snapshot.",tone:"ink"},
  replayed_not_fixed:{title:"Attack still succeeds in replay",explanation:"The patched snapshot still exposed the victim marker while legitimate-user controls succeeded. The recorded change did not fix the tested attack.",tone:"risk"},
  replay_failed:{title:"Replay inconclusive",explanation:"The recorded attempts did not establish a before-and-after fix. Failed controls, server errors and timeouts do not prove safety.",tone:"attention"},
};
export function changeState(change:SuggestedChange) {return states[change.status??"proposed"];}
export function diffPage(diff:string,offset:number) {
  const lines=diff.split("\n");if(!Number.isSafeInteger(offset)||offset<0||offset>=lines.length)throw Error("Invalid diff page");
  return {lines:lines.slice(offset,offset+80),total:lines.length,next:offset+80<lines.length?offset+80:null};
}
export function diffTone(line:string):"deletion"|"addition"|"context" {
  return line.startsWith("-")&&!line.startsWith("--- ") ? "deletion" : line.startsWith("+")&&!line.startsWith("+++ ") ? "addition" : "context";
}
