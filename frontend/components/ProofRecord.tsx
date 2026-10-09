import type { ProbeRun } from "../generated/contracts";
import { observed, proofAnchor } from "../lib/proof-data";
import styles from "./CaseFile.module.css";

const words=(value:string)=>value.replaceAll("_"," ");
export function ProofRecord({probe}:{probe:ProbeRun}) {
  return <section id={proofAnchor(probe.id)} tabIndex={-1} className={styles.probe} aria-label={`${words(probe.snapshot_role)} snapshot proof`}>
    <p className={styles.probeLabel}><strong>{words(probe.snapshot_role)} snapshot · {words(probe.outcome)}</strong><code title={probe.snapshot_id}>{probe.snapshot_id.slice(0,12)}</code></p>
    <table className={styles.proof}><caption>{words(probe.runner)} · {probe.id}</caption><thead><tr><th scope="col">Step</th><th scope="col">As</th><th scope="col">Expected if safe</th><th scope="col">Observed</th></tr></thead><tbody>{probe.steps.map((step,i)=><tr key={i} className={step.role==="attack"&&observed(step)==="allowed" ? styles.exposed : ""}><th scope="row">{words(step.role)}</th><td>{step.principal}</td><td>{words(step.expected_if_safe)}</td><td><strong>{step.status==null ? "No response" : `HTTP ${step.status}`}</strong><br />Marker {step.marker_present==null ? "unknown" : step.marker_present ? "present" : "absent"}{step.role!=="setup"&&<> · {observed(step)==="unknown" ? "access unresolved" : observed(step)}</>}{step.error&&<p>{step.error}</p>}</td></tr>)}</tbody></table>
    <details><summary>Requests and recorded conditions</summary><ol>{probe.steps.map((step,i)=><li key={i}><code>{step.method} {step.path}</code> as {step.principal}</li>)}</ol><p>Finished {probe.finished_at}. Runner manifest <code>{probe.runner_manifest_sha256}</code>.</p></details>
  </section>;
}
