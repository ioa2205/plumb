"use client";

import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReviewRun } from "../generated/contracts";
import { fetchRun, lifecycleLabel, runDestination, runLabel, selectedRun, validRunId, RunReadError } from "../lib/run-metadata";
import { Glyph } from "./Glyph";
import { ThemeSelect } from "./ThemeSelect";
import { Conditions } from "./Conditions";
import { SourceCheckPanel } from "./SourceCheckPanel";
import styles from "./Workbench.module.css";

const destinations = [
  { name: "Project", path: "/" },
  { name: "Review", path: "/review/" },
  { name: "Findings", path: "/findings/" },
  { name: "Runs", path: "/runs/" },
] as const;

export type Destination = typeof destinations[number]["name"];
const SelectedRunContext=createContext<{id:string|null;run:ReviewRun|null;selectionRevision:number;updateRun:(run:ReviewRun)=>void}>({id:null,run:null,selectionRevision:0,updateRun:()=>{}});
export function useSelectedRun() {return useContext(SelectedRunContext);}

/** Unloaded shell: no fabricated project, run, capability or progress. */
export function Workbench({ current, children }: { current: Destination; children: ReactNode }) {
  const [id,setId] = useState<string|null>(null);
  const [input,setInput] = useState("");
  const [run,setRun] = useState<ReviewRun|null>(null);
  const [message,setMessage] = useState("");
  const [loading,setLoading] = useState(false);
  const [revision,setRevision] = useState(0);
  const updateRun=useCallback((value:ReviewRun)=>{if(value.id===id)setRun(value);},[id]);
  useEffect(() => {
    try { const value=selectedRun(window.location.search); setId(value); setInput(value || ""); }
    catch { setMessage("Use one valid run ID from a review."); }
  },[]);
  useEffect(() => {
    if(!id) return;
    const controller = new AbortController(); let currentRequest=true;
    const timer = window.setTimeout(()=>controller.abort(),8000);
    setLoading(true); setRun(null); setMessage("");
    fetchRun(id,controller.signal).then(value=>{ if(currentRequest) setRun(value); }).catch(error=>{
      if(currentRequest) setMessage(controller.signal.aborted ? "The run lookup timed out. Check that Plumb is running, then try again." : error instanceof RunReadError ? error.message : "This run could not be read. Try opening it again.");
    }).finally(()=>{ window.clearTimeout(timer); if(currentRequest) setLoading(false); });
    return ()=>{ currentRequest=false; controller.abort(); window.clearTimeout(timer); };
  },[id,revision]);
  function select(value:string|null) {
    const url=new URL(window.location.href);
    if(value) url.searchParams.set("run",value); else url.searchParams.delete("run");
    url.searchParams.delete("finding");
    window.history.replaceState(null,"",url); setRun(null); setMessage(""); setId(value); setLoading(false); setRevision(count=>count+1);
  }
  return <div className={styles.app}>
    <a className="skip-link" href="#main">Skip to content</a>
    <aside className={styles.rail} aria-label="Workbench">
      <a href="/" className={styles.wordmark} aria-label="Plumb project"><Glyph name="plumb" />plumb</a>
      <nav aria-label="Main navigation" className={styles.nav}>
        {destinations.map(item => <a key={item.name} href={runDestination(item.path,id)} aria-current={item.name === current ? "page" : undefined}>{item.name}</a>)}
      </nav>
      <dl className={styles.capabilities}>
        <div><dt>Recorded model</dt><dd>{run?.model?.id || "Not recorded"}</dd></div>
        <div><dt>Recorded backend</dt><dd>{run?.toolchain?.backend || "Not recorded"}</dd></div>
        <div><dt>Knowledge pack</dt><dd>{run?.toolchain?.knowledge_pack_date || "Not recorded"}</dd></div>
      </dl>
    </aside>
    <header className={styles.bar}>
      <div className={styles.context}>{run ? <><strong>Snapshot <code title={run.snapshot_id}>{run.snapshot_id.slice(0,12)}</code></strong><span>{runLabel(run)} · {lifecycleLabel(run)}</span><code className={styles.runId}>{run.id}</code></> : <><strong>No project selected</strong><span>{loading ? "Reading recorded run…" : "No run selected"}</span></>}</div>
      <ThemeSelect />
      <details className={styles.picker}><summary>Open a recorded run</summary>
        <form onSubmit={event=>{ event.preventDefault(); const value=input.trim(); if(!validRunId(value)) { setMessage("Use the run ID printed by a review."); return; } select(value); }}>
          <label htmlFor="run-id">Run ID</label><input id="run-id" value={input} onChange={event=>setInput(event.target.value)} autoComplete="off" spellCheck={false} maxLength={128} required aria-describedby="run-help" />
          <div className={styles.actions}><button type="submit">Open run</button><button type="button" onClick={()=>{setInput("");select(null);}}>Clear selection</button></div>
          <p id="run-help">Copy the ID printed by a review. Opening a record starts no model or investigation.</p>
        </form>
      </details>
      <p className={styles.lookup} role="status">{message || (loading ? "Reading the recorded run." : run ? `Recorded run loaded. ${lifecycleLabel(run)}.` : "")}</p>
    </header>
    <main id="main" tabIndex={-1} className={styles.main}><SelectedRunContext.Provider value={{id,run,selectionRevision:revision,updateRun}}>{current!=="Review"&&<Conditions conditions={run?.conditions??[]} />}{run&&<SourceCheckPanel key={run.id} run={run} />}{children}</SelectedRunContext.Provider></main>
  </div>;
}

export function Sheet({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <article className={styles.sheet}>
    <h1>{title}</h1><p className={styles.lede}>{description}</p>{children}
  </article>;
}

export function Command({ children }: { children: string }) {
  return <pre className={styles.command}><code>{children}</code></pre>;
}

export function ReviewGuide() {
  return <section id="start" className={styles.section} aria-labelledby="start-title">
    <h2 id="start-title">Start a review from your terminal</h2>
    <p>From the Plumb folder, inspect code you own or are authorized to test. Inspection reads source without loading a model.</p>
    <Command>{"uv run plumb inspect <project-folder>"}</Command>
    <p>For the bundled example, investigate the receipt and protected invoice together. Plumb checks memory before loading the local model.</p>
    <Command>{"uv run plumb review labs/tandir --resource Order"}</Command>
    <p>The completed command prints a run ID and saves an HTML report. Open that report to read the evidence.</p>
    <Command>{"uv run plumb report <run-id> --open"}</Command>
    <p className={styles.note}>A review covers its recorded scope. Unsupported or unreviewed code remains unknown.</p>
  </section>;
}
