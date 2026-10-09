"use client";

import { useEffect, useState } from "react";
import type { CaseDetail, FindingList } from "../generated/contracts";
import { CaseReadError, fetchCase, selectedFinding } from "../lib/case-data";
import { emptyFilters, fetchFindingList, type FindingFilters } from "../lib/finding-list";
import { FindingFiltersBar, FindingResults } from "./FindingGroups";
import { useSelectedRun, ReviewGuide, Sheet } from "./Workbench";
import { CaseFile } from "./CaseFile";
import styles from "./SavedFindings.module.css";

export function SavedFindings() {
  const {id,selectionRevision}=useSelectedRun();const [finding,setFinding]=useState<string|null>(null);const [invalidSelection,setInvalidSelection]=useState(false);
  const [page,setPage]=useState<FindingList|null>(null);const [detail,setDetail]=useState<CaseDetail|null>(null);
  const [filters,setFilters]=useState<FindingFilters>(emptyFilters);
  const [offset,setOffset]=useState(0);const [message,setMessage]=useState("");const [busy,setBusy]=useState(false);const [revision,setRevision]=useState(0);
  useEffect(()=>{setOffset(0);try{setFinding(selectedFinding(window.location.search));setInvalidSelection(false);}catch(error){setInvalidSelection(true);setMessage(error instanceof CaseReadError ? error.message : "Invalid case selection.");}},[id,selectionRevision]);
  useEffect(()=>{
    setPage(null);setDetail(null);if(!id||invalidSelection){setBusy(false);return;}
    const controller=new AbortController();let active=true;const timer=window.setTimeout(()=>controller.abort(),10000);
    setBusy(true);setMessage("");
    const read=finding ? fetchCase(id,finding,controller.signal).then(value=>{if(active)setDetail(value);}) : fetchFindingList(id,offset,filters,controller.signal).then(value=>{if(active)setPage(value);});
    read.catch(error=>{if(active)setMessage(controller.signal.aborted ? "The saved finding lookup timed out. Try again." : error instanceof Error ? error.message : "This saved investigation cannot be read.");}).finally(()=>{window.clearTimeout(timer);if(active)setBusy(false);});
    return ()=>{active=false;controller.abort();window.clearTimeout(timer);};
  },[id,finding,offset,revision,invalidSelection,filters]);
  if(!id)return <Sheet title="No finding list loaded." description="Select a recorded run above to read its cases and cited code. An unloaded list says nothing about a project's security."><ReviewGuide /></Sheet>;
  if(detail)return <><a className={styles.back} href={`/findings/?${new URLSearchParams({run:id})}`}>All recorded findings</a><CaseFile key={detail.finding.id} detail={detail} /></>;
  return <Sheet title={finding ? "Open a saved case" : "Recorded findings"} description="Source conclusions, runtime verification and severity are separate. Opening these records starts no analysis or model.">
    <p role="status">{message || (busy ? "Reading saved findings…" : page ? `${page.total} recorded cases.` : "")}</p>
    {message&&<button className={styles.action} onClick={()=>setRevision(count=>count+1)}>Retry saved findings</button>}
    {!finding&&<FindingFiltersBar filters={filters} onChange={value=>{setFilters(value);setOffset(0);}} />}
    {page&&<p className={styles.scope}>{page.run.coverage?.completed} of {page.run.coverage?.total} discovered checks processed · {page.run.coverage?.pending} pending · {page.run.coverage?.excluded} excluded · {page.run.coverage?.unsupported} unsupported.</p>}
    {!finding&&<FindingResults page={page} onPage={setOffset} />}
  </Sheet>;
}
