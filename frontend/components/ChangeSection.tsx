"use client";

import { useState } from "react";
import type { FixProposal, ProbeRun, SuggestedChange } from "../generated/contracts";
import { changeState, diffPage, diffTone, validChangeEvidence, type ChangeFinding } from "../lib/change-data";
import { proofAnchor } from "../lib/proof-data";
import styles from "./CaseFile.module.css";

/** Saved records only. No edit, apply, recheck or arbitrary target execution action. */
export function ChangeSection({finding,change,proposal,probes,linkToProof=true}:{finding:ChangeFinding;change?:SuggestedChange|null;proposal?:FixProposal|null;probes:readonly ProbeRun[];linkToProof?:boolean}) {
  const [position,setPosition]=useState({diff:change?.diff??"",offset:0});
  if(!validChangeEvidence(finding,change,probes))return <p className={styles.replayCondition}>Change evidence is inconsistent. Open the saved report to inspect its records.</p>;
  if(!change)return <div><p>No suggested change was saved for this case.</p>{proposal&&<p>Proposal {proposal.status}: {proposal.reason} Regression specification: {proposal.probe_reason}</p>}</div>;
  const offset=position.diff===change.diff ? position.offset : 0;
  const state=changeState(change),page=diffPage(change.diff,offset);
  const replay=probes.filter(p=>change.replay_probe_run_ids?.includes(p.id));
  return <div>
    <p className={state.tone==="proposed" ? styles.proposed : state.tone==="risk" ? styles.risk : state.tone==="attention" ? styles.replayCondition : styles.replayState}>{state.title}</p>
    <p>{state.explanation}</p>
    {replay.length>0&&<p>Only the disposable replay copy was patched. Your project has not been changed, and the finding disposition is unchanged.</p>}
    <p>{change.intent}</p>
    {proposal&&<div><p>General proposal {proposal.status}: {proposal.reason}</p>{!proposal.change&&<p>This recorded change was supplied by the separate bundled replay.</p>}<p>Regression specification {proposal.probe_status}: {proposal.probe_reason}</p>{proposal.probe_spec&&<details><summary>Declarative regression requests · not executed</summary><pre>{JSON.stringify(proposal.probe_spec,null,2)}</pre><p>Adapter manifest <code>{proposal.adapter_manifest_sha256}</code></p></details>}</div>}
    <details className={styles.changeRecord}><summary>Change and replay records</summary>
      <p>Change <code>{change.id}</code> · finding <code>{finding.id}</code></p>
      <p>Files in the recorded diff:</p><ul>{change.files.map(file=><li key={file}><code>{file}</code></li>)}</ul>
      <p>Original snapshot <code>{finding.snapshot_id}</code></p>
      <ul>{probes.map(probe=><li key={probe.id}>{probe.snapshot_role==="patched" ? "Patched replay" : "Original proof"} · {linkToProof ? <a href={`#${proofAnchor(probe.id)}`}>{probe.id}</a> : <code>{probe.id}</code>} · {probe.outcome.replaceAll("_"," ")}<p>Snapshot <code>{probe.snapshot_id}</code></p></li>)}</ul>
    </details>
    <pre className={styles.diff} aria-label="Recorded proposed diff"><code>{page.lines.map((line,i)=><span key={offset+i} className={diffTone(line)==="deletion" ? styles.deletion : diffTone(line)==="addition" ? styles.addition : ""}>{line}{offset+i<page.total-1 ? "\n" : ""}</span>)}</code></pre>
    <p className={styles.note} role="status">Recorded diff lines {offset+1}–{Math.min(offset+80,page.total)} of {page.total}. Deletions are red; additions use bold ink.</p>
    {(offset>0||page.next!==null)&&<div className={styles.codeActions} role="group" aria-label="Recorded diff pages"><button className={styles.action} type="button" aria-disabled={offset===0} onClick={()=>{if(offset>0)setPosition({diff:change.diff,offset:Math.max(0,offset-80)});}}>Previous diff lines</button><button className={styles.action} type="button" aria-disabled={page.next===null} onClick={()=>{if(page.next!==null)setPosition({diff:change.diff,offset:page.next});}}>Next diff lines</button></div>}
    <p>Use the recorded attack and legitimate-user control as regression cases. A replay does not establish whole-project safety.</p>
  </div>;
}
