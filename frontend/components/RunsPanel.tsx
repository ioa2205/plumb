"use client";

import { useEffect, useState } from "react";
import type { ReviewRun, RunComparison, RunHistory } from "../generated/contracts";
import { durationLabel, earlierRun, fetchComparison, fetchHistory, groupLabels, groups, type ComparisonGroup } from "../lib/history-data";
import { lifecycleLabel, runDestination, validRunId } from "../lib/run-metadata";
import { Sheet, useSelectedRun } from "./Workbench";
import styles from "./RunsPanel.module.css";

export function RunsPanel(){const {id,selectionRevision}=useSelectedRun();return <RunsSession key={`${id}:${selectionRevision}`} />;}
function RunsSession(){
  const {id,run}=useSelectedRun();const [history,setHistory]=useState<RunHistory|null>(null);const [offset,setOffset]=useState(0);const [revision,setRevision]=useState(0);const [message,setMessage]=useState("");
  const [beforeInput,setBeforeInput]=useState("");const [before,setBefore]=useState<string|null>(null);const [comparison,setComparison]=useState<RunComparison|null>(null);const [comparisonMessage,setComparisonMessage]=useState("");
  const [group,setGroup]=useState<ComparisonGroup>("new");const [rowOffset,setRowOffset]=useState(0);const [policyOffset,setPolicyOffset]=useState(0);
  useEffect(()=>{try{const earlier=earlierRun(window.location.search,id);if(earlier){setBeforeInput(earlier);if(id)setBefore(earlier);}}catch(error){setComparisonMessage(error instanceof Error?error.message:"The earlier selection cannot be read.");}},[id]);
  useEffect(()=>{const controller=new AbortController();let active=true;const timer=setTimeout(()=>controller.abort(),15000);setMessage("Reading recorded history…");
    fetchHistory(offset,controller.signal).then(p=>{if(active){setHistory(p);setMessage("");}}).catch(error=>{if(active)setMessage(controller.signal.aborted?"History lookup timed out. Try again.":error instanceof Error?error.message:"History cannot be read.");}).finally(()=>clearTimeout(timer));
    return()=>{active=false;clearTimeout(timer);controller.abort();};
  },[offset,revision]);
  useEffect(()=>{if(!before||!id)return;const controller=new AbortController();let active=true;const timer=setTimeout(()=>controller.abort(),15000);setComparisonMessage("Reading saved comparison…");
    fetchComparison(before,id,group,rowOffset,policyOffset,controller.signal).then(p=>{if(active){setComparison(p);setComparisonMessage("");}}).catch(error=>{if(active)setComparisonMessage(controller.signal.aborted?"Comparison lookup timed out. Saved reports remain available.":error instanceof Error?error.message:"Saved runs cannot be compared.");}).finally(()=>clearTimeout(timer));
    return()=>{active=false;clearTimeout(timer);controller.abort();};
  },[before,id,group,rowOffset,policyOffset,revision]);
  return <Sheet title="Recorded runs" description="Read previous investigations, compare their observations and inspect the settings saved with each run. Opening history starts no model.">
    <p role="status">{message}</p><button className={styles.control} onClick={()=>setRevision(n=>n+1)}>Refresh history</button>
    {history&&<HistoryView history={history} earlierId={beforeInput.trim()} onPage={setOffset} onEarlier={value=>{setBeforeInput(value);setBefore(null);setComparison(null);setComparisonMessage("Earlier run selected. Open the later run to compare.");const url=new URL(window.location.href);url.searchParams.set("before",value);window.history.replaceState(null,"",url);}} />}
    <section className={styles.section} aria-labelledby="compare-title"><h2 id="compare-title">Compare saved observations</h2><p>The run opened above is the later review. Select an earlier review from history or paste its ID. Scope and unresolved correspondence stay visible.</p>
      <form className={styles.form} onSubmit={event=>{event.preventDefault();const value=beforeInput.trim();if(!id||!validRunId(value)||value===id){setComparisonMessage("Open the later run, then choose a different earlier run.");return;}setRowOffset(0);setPolicyOffset(0);setBefore(value);setComparison(null);setRevision(n=>n+1);}}>
        <label>Earlier run ID<input value={beforeInput} onChange={e=>setBeforeInput(e.target.value)} autoComplete="off" spellCheck={false} maxLength={128} required /></label>
        <p>Later run: <code>{id??"Open a run from history first"}</code></p><button className={styles.control} type="submit">Compare runs</button>
      </form><p role="status">{comparisonMessage}</p>
      {comparison&&<ComparisonView comparison={comparison} onGroup={value=>{setGroup(value);setRowOffset(0);}} onPage={setRowOffset} onPolicyPage={setPolicyOffset} />}
    </section>
    <section className={styles.section} aria-labelledby="reproduce-title"><h2 id="reproduce-title">Reproducibility record</h2>{run?<Reproducibility run={run} />:<p>Open a run from history to read its recorded model, toolchain and snapshot. Missing fields stay marked as not recorded.</p>}</section>
  </Sheet>;
}

export function HistoryView({history,onPage,onEarlier,earlierId=""}:{history:RunHistory;onPage?:(n:number)=>void;onEarlier?:(id:string)=>void;earlierId?:string}){
  return <section className={styles.section} aria-labelledby="history-title"><h2 id="history-title">History</h2>
    {history.runs.length?<><p role="status">{history.offset+1}–{history.offset+history.runs.length} of {history.total} recorded runs · newest first.</p><div className={styles.tableWrap} tabIndex={0} role="region" aria-label="Recorded run history; scroll horizontally if needed"><table className={styles.history}><caption>Saved review settings and results</caption><thead><tr><th scope="col">Run and date (UTC)</th><th scope="col">Snapshot</th><th scope="col">Type and status</th><th scope="col">Recorded model</th><th scope="col">Duration</th><th scope="col">Actions</th></tr></thead><tbody>{history.runs.map(run=><tr key={run.id}>
      <th scope="row"><code>{run.id}</code><time dateTime={run.created_at}>{new Date(run.created_at).toISOString().slice(0,19).replace("T"," ")} UTC</time></th><td><code title={run.snapshot_id}>{run.snapshot_id.slice(0,12)}</code></td><td>{run.run_type} · {lifecycleLabel(run)}</td><td>{run.model?.id??"Not recorded"}<small>{run.model?.quantization??""}</small></td><td>{durationLabel(run)}</td><td><a className={styles.linkControl} aria-label={`Open run ${run.id}`} href={runDestination("/runs/",run.id)+(validRunId(earlierId)&&earlierId!==run.id?`&${new URLSearchParams({before:earlierId})}`:"")}>Open run</a>{onEarlier&&<button className={styles.linkControl} aria-label={`Use run ${run.id} as earlier`} onClick={()=>onEarlier(run.id)}>Use as earlier</button>}</td>
    </tr>)}</tbody></table></div></>:<p>{history.total?"No runs on this page.":<>No reviews have been recorded. <a href="/">Open a project and run a review</a>, then return here for its saved results.</>}</p>}
    {onPage&&<div className={styles.controls}><button className={styles.control} aria-disabled={history.offset===0} onClick={()=>{if(history.offset)onPage(Math.max(0,history.offset-20));}}>Previous runs</button><button className={styles.control} aria-disabled={history.next_offset===null} onClick={()=>{if(history.next_offset!==null)onPage(history.next_offset);}}>Next runs</button></div>}
  </section>;
}

export function Reproducibility({run}:{run:ReviewRun}){
  const values=[
    ["Run",run.id],["Run type",run.run_type],["Created (UTC)",new Date(run.created_at).toISOString()],
    ["Model",run.model?.id],["Model file SHA256",run.model?.file_sha256],["Quantization",run.model?.quantization],
    ["llama.cpp release",run.toolchain?.llama_cpp_release],["llama.cpp build",run.toolchain?.llama_cpp_build],
    ["Inference backend",run.toolchain?.backend],["Opengrep version",run.toolchain?.opengrep_version],
    ["Opengrep rules SHA256",run.toolchain?.opengrep_rules_sha256],["Knowledge-pack date",run.toolchain?.knowledge_pack_date],
    ["Snapshot SHA256",run.snapshot_id],
  ];return <><p>Values saved with this review; they do not describe the current machine or establish model quality.</p><dl className={styles.record}>{values.map(([label,value])=><div key={label}><dt>{label}</dt><dd><code>{value??"Not recorded"}</code></dd></div>)}</dl><p>{run.coverage?.completed??0} of {run.coverage?.total??0} checks processed; {run.coverage?.pending??0} pending, {run.coverage?.excluded??0} excluded, {run.coverage?.unsupported??0} unsupported.</p></>;
}

export function ComparisonView({comparison:p,onGroup,onPage,onPolicyPage}:{comparison:RunComparison;onGroup?:(g:ComparisonGroup)=>void;onPage?:(n:number)=>void;onPolicyPage?:(n:number)=>void}){
  const shown=(f:NonNullable<RunComparison["rows"][number]["before"]>,run:ReviewRun)=><div><a href={`/findings/?${new URLSearchParams({run:run.id,finding:f.id})}`}><strong>{f.display_id} · {f.title}</strong></a><p>{f.conclusion} · {f.runtime_verification.replaceAll("_"," ")}</p>{f.location&&<code>{f.location.path}:{f.location.start_line}</code>}</div>;
  return <div><p><code>{p.before.id}</code> → <code>{p.after.id}</code>. No longer observed means an explicit later source rejection; it does not establish a runtime fix.</p>
    <div className={styles.controls} role="group" aria-label="Comparison groups">{groups.map(g=><button key={g} className={styles.control} aria-pressed={p.group===g} onClick={()=>onGroup?.(g)}>{groupLabels[g]} · {p.counts[g]}</button>)}</div>
    <h3>{groupLabels[p.group]}</h3>{p.rows.length?<ul className={styles.comparisons}>{p.rows.map(row=><li key={row.id}><div className={styles.pair}><section><h4>Earlier</h4>{row.before?shown(row.before,p.before):<p>No matched earlier concern recorded.</p>}</section><section><h4>Later</h4>{row.after?shown(row.after,p.after):<p>Correspondence or a completed later judgment is unavailable.</p>}</section></div><p className={styles.reason}>{row.reason}</p></li>)}</ul>:<p>No records in this comparison group. Review coverage and the other groups before drawing a conclusion.</p>}
    {onPage&&<div className={styles.controls}><button className={styles.control} aria-disabled={p.offset===0} onClick={()=>{if(p.offset)onPage(Math.max(0,p.offset-20));}}>Previous comparisons</button><button className={styles.control} aria-disabled={p.next_offset===null} onClick={()=>{if(p.next_offset!==null)onPage(p.next_offset);}}>Next comparisons</button></div>}
    <section className={styles.section} aria-labelledby="drift-title"><h3 id="drift-title">Policy observations</h3><p>Recorded guard counts, independent of human-confirmed rules. Missing or changed peer cohorts are marked explicitly.</p>
      {p.policies.length?<ul className={styles.comparisons}>{p.policies.map(d=><li key={`${d.resource}:${d.kind}`}><strong>{d.resource} · {d.kind}</strong><p>{d.before?`${d.before.applying} of ${d.before.total} guarded`:"Not recorded"} → {d.after?`${d.after.applying} of ${d.after.total} guarded`:"Not recorded"}{d.cohort_changed?" · peer cohort changed or unavailable":" · same recorded peer cohort"}</p><details><summary>Read source provenance</summary>{([["Earlier",d.before,p.before],["Later",d.after,p.after]] as const).map(([label,count,run])=><div key={label}><h4>{label}</h4>{count?count.citations.map(c=><p key={c.id}><a href={runDestination("/",run.id)}><code>{c.span.path}:{c.span.start_line}–{c.span.end_line}</code></a></p>):<p>Missing or ambiguous observations.</p>}</div>)}</details><p className={styles.reason}>{d.reason}</p></li>)}</ul>:<p>No comparable saved peer observations. Legacy reports may not include peer records; static names cannot fill the gap.</p>}
      {onPolicyPage&&<div className={styles.controls}><button className={styles.control} aria-disabled={p.policy_offset===0} onClick={()=>{if(p.policy_offset)onPolicyPage(Math.max(0,p.policy_offset-20));}}>Previous policy observations</button><button className={styles.control} aria-disabled={p.policy_next_offset===null} onClick={()=>{if(p.policy_next_offset!==null)onPolicyPage(p.policy_next_offset);}}>Next policy observations</button></div>}
    </section><details className={styles.section}><summary>Comparison limits and saved report scope</summary><ul>{p.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul><div className={styles.pair}><section><h4>Earlier reproducibility</h4><Reproducibility run={p.before} /></section><section><h4>Later reproducibility</h4><Reproducibility run={p.after} /></section></div></details>
  </div>;
}
