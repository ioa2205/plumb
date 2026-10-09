import type { ReviewRun } from "../generated/contracts";
import styles from "./SetupPanel.module.css";

type Condition=NonNullable<ReviewRun["conditions"]>[number];
const labels:Record<Condition["kind"],string>={setup_required:"Setup required",model_too_large:"Model too large for free memory",runner_unavailable:"Runner unavailable",stale_source:"Stale source",unsupported_framework:"Unsupported framework",unreadable_file:"Unreadable file",partial_coverage:"Partial coverage"};
const actions:Record<Condition["kind"],string>={setup_required:"Check local setup before investigating.",model_too_large:"Check current readiness again after freeing memory.",runner_unavailable:"Use static evidence; runtime verification requires an approved isolated runner.",stale_source:"Review current files before treating changed source as checked.",unsupported_framework:"Read scope; unsupported flows remain unknown.",unreadable_file:"Check file permissions, then inspect again.",partial_coverage:"Read scope and pending, excluded and unsupported counts."};
export function Conditions({conditions}:{conditions:readonly Condition[]}){
  if(!conditions.length)return null;
  return <ul className={styles.conditions} aria-label="Conditions needing attention">{conditions.map((c,i)=><li key={`${c.kind}:${i}`}><strong>{labels[c.kind]}</strong><p>{c.message}</p><p>{c.action||actions[c.kind]}</p></li>)}</ul>;
}
