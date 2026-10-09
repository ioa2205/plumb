import type { ProbeRun, ProbeRunSchema } from "../generated/contracts";

export function observed(step:ProbeRunSchema.ProbeStep):"allowed"|"denied"|"unknown" {
  if(step.status==null || step.marker_present==null)return "unknown";
  if(step.status>=200 && step.status<300)return step.marker_present ? "allowed" : "denied";
  return [401,403,404].includes(step.status) && !step.marker_present ? "denied" : "unknown";
}
/** Mirrors the backend's observation rule; a failed control or timeout is never a fix. */
export function probeOutcome(probe:ProbeRun):ProbeRunSchema.ProbeOutcome {
  const attacks=probe.steps.filter(s=>s.role==="attack"),controls=probe.steps.filter(s=>s.role==="control");
  if(!attacks.length||!controls.length||controls.some(s=>observed(s)!=="allowed")||attacks.some(s=>observed(s)==="unknown"))return "inconclusive";
  const exposed=attacks.some(s=>observed(s)==="allowed");
  return probe.snapshot_role==="vulnerable" ? exposed ? "reproduced" : "not_reproduced" : exposed ? "not_fixed" : "fixed";
}
export function proofAnchor(id:string):string {return `proof-${id}`;}
