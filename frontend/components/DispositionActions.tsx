"use client";

import {useEffect,useRef,useState} from "react";
import type {CaseDetail,DispositionUpdate} from "../generated/contracts";
import {dispositionIntent,saveDecision} from "../lib/disposition-data";
import {fetchCase} from "../lib/case-data";
import styles from "./DispositionActions.module.css";

const labels={open:"Reopen",dismissed:"Dismiss",accepted_risk:"Accept risk",resolved:"Mark resolved"};
export function DispositionActions({detail}:{detail:CaseDetail}){
  const [view,setView]=useState(detail);const [action,setAction]=useState<DispositionUpdate["disposition"]|null>(null);
  const [reason,setReason]=useState("");const [actor,setActor]=useState("Local reviewer");const [commit,setCommit]=useState("");
  const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");
  const controller=useRef<AbortController|null>(null);const summary=useRef<HTMLElement|null>(null);const reasonField=useRef<HTMLInputElement>(null);
  useEffect(()=>()=>controller.current?.abort(),[]);
  useEffect(()=>{if(action)reasonField.current?.focus();},[action]);
  function cancel(){controller.current?.abort();controller.current=null;setAction(null);setBusy(false);setMessage("Decision canceled. If a save started, refresh to check its recorded state.");summary.current?.focus();}
  async function perform(refresh=false){
    if(busy)return;const owned=new AbortController();controller.current=owned;setBusy(true);setMessage("");
    try{
      const result=refresh?await fetchCase(view.run.id,view.finding.id,owned.signal):await saveDecision(view,dispositionIntent(view,action!,reason,actor,commit),owned.signal);
      if(owned.signal.aborted)return;setView(result);setAction(null);setReason("");setCommit("");setMessage(refresh?"Saved reviewer state refreshed.":"Reviewer decision saved. Source conclusions and runtime proof are unchanged.");summary.current?.focus();
    }catch(error){if(!owned.signal.aborted)setMessage(error instanceof Error?error.message:"Decision unavailable. Refresh its saved state.");}
    finally{if(controller.current===owned){controller.current=null;setBusy(false);}}
  }
  const state=view.finding.disposition??"open";const history=view.disposition_history??[];
  return <details className={styles.disposition}>
    <summary ref={summary}>Disposition: {state.replaceAll("_"," ")}</summary>
    <p>Reviewer decisions preserve the original evidence and do not certify a runtime fix.</p>
    <div className={styles.actions} aria-label="Reviewer disposition actions">{(state==="open"?["dismissed","accepted_risk","resolved"]:["open"]).map(value=>{
      const choice=value as DispositionUpdate["disposition"];return <button key={value} type="button" disabled={busy} onClick={()=>{setAction(choice);setReason("");setCommit("");setMessage("");}}>{labels[choice]}{choice!=="resolved"?"…":""}</button>;
    })}<button type="button" disabled={busy} onClick={()=>void perform(true)}>Refresh saved state</button></div>
    {action&&<form onSubmit={event=>{event.preventDefault();void perform();}} aria-label={labels[action]}>
      <label>Reason<input ref={reasonField} required maxLength={1000} value={reason} disabled={busy} onChange={event=>setReason(event.target.value)}/></label>
      <label>Reviewer<input required maxLength={100} value={actor} disabled={busy} onChange={event=>setActor(event.target.value)}/></label>
      {action==="resolved"&&<label>Linked commit (full 40-character hash)<input required pattern="[0-9a-f]{40}" maxLength={40} value={commit} disabled={busy} onChange={event=>setCommit(event.target.value)}/></label>}
      <div className={styles.actions}><button type="submit" disabled={busy}>{busy?"Saving…":"Save decision"}</button><button type="button" onClick={cancel}>Cancel</button></div>
    </form>}
    <p role="status" aria-live="polite">{message}</p>
    {history.length>0&&<ol aria-label="Reviewer decision history">{history.map(d=><li key={d.version}>{d.disposition.replaceAll("_"," ")} · {d.actor} · <time dateTime={d.recorded_at}>{d.recorded_at}</time><p>{d.reason}</p>{d.resolution_commit&&<code>Linked commit: {d.resolution_commit}</code>}</li>)}</ol>}
    <div className={styles.actions} aria-label="Export current reviewer view">{["json","markdown","html","sarif"].map(format=><a key={format} href={`/api/runs/${encodeURIComponent(view.run.id)}/current-report?format=${format}`} download>Export current {format.toUpperCase()}</a>)}</div>
  </details>;
}
