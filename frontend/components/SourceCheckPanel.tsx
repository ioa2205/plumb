"use client";

import { useEffect, useRef, useState } from "react";
import type { ReviewRun, SourceCheck } from "../generated/contracts";
import { checkSource } from "../lib/setup-data";
import { Conditions } from "./Conditions";
import styles from "./SetupPanel.module.css";

export function SourceCheckPanel({run}:{run:ReviewRun}){
  const [value,setValue]=useState<SourceCheck|null>(null);const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");const active=useRef<AbortController|null>(null);
  useEffect(()=>()=>active.current?.abort(),[]);
  async function check(){
    if(busy)return;setBusy(true);setMessage("Comparing current included source with the frozen review…");const controller=new AbortController();active.current=controller;const timer=setTimeout(()=>controller.abort(),90000);
    try{const p=await checkSource(run.id,run.snapshot_id,controller.signal);if(!controller.signal.aborted){setValue(p);setMessage("Source observation saved in this view. Original findings are unchanged.");}}
    catch(error){if(!controller.signal.aborted)setMessage(error instanceof Error?error.message:"Source could not be checked.");else setMessage("The browser wait ended. Check Runs and the terminal before retrying.");}
    finally{clearTimeout(timer);active.current=null;setBusy(false);}
  }
  return <details className={styles.section}><summary>Current source and frozen evidence</summary><p>Saved findings describe snapshot <code>{run.snapshot_id.slice(0,12)}</code>. Check the associated local folder without loading a model or running target code.</p><button className={styles.control} disabled={busy} onClick={()=>void check()}>Check current source</button><p role="status">{message}</p>{value&&<><p><strong>{value.state==="current"?"Included source and excluded scope unchanged":value.state==="changed"?"Current source differs from the reviewed snapshot":value.state==="unassociated"?"This older run has no recorded local folder association":"Current source state unknown"}</strong></p><p>Observed {new Date(value.checked_at).toISOString().slice(0,19).replace("T"," ")} UTC.</p>{value.changed_files!=null&&<p>{value.changed_files} changed; {value.added_files} added; {value.removed_files} removed included files. Excluded scope: {value.excluded_scope_changed?"changed":"unchanged"}.</p>}<Conditions conditions={value.conditions??[]} /><ul>{value.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul>{value.state!=="current"&&<a className={styles.control} href="/">Inspect current files</a>}</>}</details>;
}
