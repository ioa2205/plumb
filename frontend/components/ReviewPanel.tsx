"use client";
import { Conditions } from "./Conditions";

import { useEffect, useState } from "react";
import type { QueueEdit, ReviewPage } from "../generated/contracts";
import { activeRun, activityText, consumeEvents, fetchReview, questionTitle, requestControl, requestQueueEdit, ReviewError } from "../lib/review-data";
import { lifecycleLabel, runDestination } from "../lib/run-metadata";
import { resumeReview } from "../lib/setup-data";
import { Command, ReviewGuide, Sheet, useSelectedRun } from "./Workbench";
import styles from "./ReviewPanel.module.css";

export function ReviewPanel() {
  const {id,selectionRevision}=useSelectedRun();
  return <ReviewSession key={`${id}:${selectionRevision}`} />;
}

function ReviewSession() {
  const {id,selectionRevision,updateRun}=useSelectedRun();
  const [page,setPage]=useState<ReviewPage|null>(null);const [offset,setOffset]=useState(0);
  const [connection,setConnection]=useState("Connecting to saved checkpoints…");const [revision,setRevision]=useState(0);
  const [control,setControl]=useState("");const [sending,setSending]=useState(false);
  useEffect(()=>{setOffset(0);setPage(null);setControl("");},[id,selectionRevision]);
  useEffect(()=>{
    if(!id)return;
    const controller=new AbortController();const signal=controller.signal;let stopped=false;let cursor:number|null=null;
    let refreshTimer:ReturnType<typeof setTimeout>|undefined;let retryTimer:ReturnType<typeof setTimeout>|undefined;
    let refreshing:Promise<ReviewPage>|null=null;
    async function refresh():Promise<ReviewPage>{
      if(refreshing)return refreshing;
      refreshing=fetchReview(id!,offset,AbortSignal.any([signal,AbortSignal.timeout(10000)])).then(value=>{if(!stopped){setPage(previous=>!previous||value.cursor>=previous.cursor||value.offset!==previous.offset||value.run.id!==previous.run.id?value:previous);updateRun(value.run);}return value;}).finally(()=>{refreshing=null;});
      return refreshing;
    }
    const schedule=()=>{if(!refreshTimer)refreshTimer=setTimeout(()=>{refreshTimer=undefined;void refresh().catch(error=>{if(!stopped)setConnection(error instanceof ReviewError?error.message:"Checkpoint could not be refreshed.");});},200);};
    const wait=(ms:number)=>new Promise<void>(resolve=>{const finish=()=>{signal.removeEventListener("abort",finish);resolve();};retryTimer=setTimeout(finish,ms);signal.addEventListener("abort",finish,{once:true});});
    async function watch(){
      let failures=0;
      while(!stopped){
        try{
          const value=await refresh();if(stopped)return;
          if(cursor===null)cursor=value.cursor;
          if(!activeRun(value.run)){setConnection(value.run.lifecycle==="paused"?"Paused checkpoint. Resume review below to continue.":"Final checkpoint loaded. Results are preserved.");return;}
          setConnection("Connected · activity updates automatically.");
          await consumeEvents(id!,cursor,signal,event=>{cursor=event.seq;failures=0;schedule();});
          if(stopped)return;
          // A final event can arrive while a prior snapshot is still being read.
          if(refreshing)await refreshing;
          const final=await refresh();if(!activeRun(final.run)){setConnection(final.run.lifecycle==="paused"?"Paused at checkpoint. Partial results are kept.":"Final checkpoint loaded. Results are preserved.");return;}
          setConnection("Activity connection closed. Reconnecting from the last event…");
        }catch(error){if(stopped)return;setConnection(error instanceof Error?error.message:"Connection interrupted.");if(!(error instanceof ReviewError)||!error.retry)return;}
        await wait(Math.min(10000,2000*2**Math.min(failures++,3)));
      }
    }
    void watch();
    return()=>{stopped=true;controller.abort();clearTimeout(refreshTimer);clearTimeout(retryTimer);};
  },[id,offset,revision,selectionRevision,updateRun]);
  async function act(action:"pause"|"cancel"){
    if(!id||sending)return;setSending(true);setControl("");
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
    try{await requestControl(id,action,controller.signal);setControl(`${action==="pause"?"Pause":"Cancel"} requested. Waiting for the worker's next checkpoint; saved results are kept.`);setRevision(n=>n+1);}
    catch(error){setControl(error instanceof ReviewError&&!error.retry?error.message:"The request was not acknowledged. Refresh before trying again; it may already be pending.");}
    finally{clearTimeout(timer);setSending(false);}
  }
  async function edit(question_id:string,action:QueueEdit["action"]){
    if(!id||sending||!page)return;setSending(true);setControl("");
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
    try{await requestQueueEdit(id,{question_id,action,expected_cursor:page.cursor,offset},controller.signal);setControl("Queue change saved. Refreshing the recorded order and coverage.");setRevision(n=>n+1);}
    catch(error){setControl(error instanceof ReviewError&&!error.retry?error.message:"The queue request was not acknowledged. Refresh before trying again; it may already be saved.");}
    finally{clearTimeout(timer);setSending(false);}
  }
  async function resume(){
    if(!id||sending)return;setSending(true);setControl("Checking the saved profile and memory before resuming…");const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),90000);
    try{const run=await resumeReview(id,controller.signal);if(!controller.signal.aborted){updateRun(run);setControl("Review resumed on the original frozen snapshot.");setRevision(n=>n+1);}}
    catch(error){setControl(controller.signal.aborted?"The browser wait ended. Refresh this review before retrying; resume may have started.":error instanceof Error?error.message:"Resume could not start. Check readiness and the terminal.");}
    finally{clearTimeout(timer);setSending(false);}
  }
  if(!id)return <Sheet title="Follow a review" description="Open a run above to see its queue, activity and saved progress."><ReviewGuide /></Sheet>;
  const current=page?.run.id===id?page:null;
  return <Sheet title="Review" description="Follow each question from its recorded priority to its saved result.">
    <p className={styles.connection} role="status">{connection}</p>
    <div className={styles.controls}><button onClick={()=>setRevision(n=>n+1)}>Refresh review</button><a href={runDestination("/findings/",id)}>Read findings</a></div>
    {current&&<ReviewView page={current} controlMessage={control} sending={sending} onControl={act} onPage={setOffset} onEdit={edit} onResume={()=>void resume()} />}
  </Sheet>;
}

/** Shared with explicitly labeled saved-record previews; transport/control lives above. */
export function ReviewView({page,controlMessage="",sending=false,onControl,onPage,onEdit,onResume}:{page:ReviewPage;controlMessage?:string;sending?:boolean;onControl?:(action:"pause"|"cancel")=>void;onPage?:(offset:number)=>void;onEdit?:(question:string,action:QueueEdit["action"])=>void;onResume?:()=>void}){
  const run=page.run;const coverage=run.coverage;const active=activeRun(run);
  const [now,setNow]=useState<number|null>(null);
  useEffect(()=>{setNow(Date.now());if(!active)return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[active]);
  const elapsed=run.started_at&&(run.finished_at||active&&now)?Math.max(0,Math.floor(((run.finished_at?Date.parse(run.finished_at):now!)-Date.parse(run.started_at))/1000)):null;
  const elapsedText=elapsed===null?null:`${Math.floor(elapsed/60)}m ${elapsed%60}s elapsed${run.finished_at?"":" since start (includes pauses)"}`;
  return <div className={styles.review}>
    <section className={styles.progress} aria-labelledby="progress-title">
      <h2 id="progress-title">{lifecycleLabel(run)}{run.stage?` · ${run.stage}`:""}</h2>
      {elapsedText&&<p className={styles.meta}>{elapsedText}</p>}
      <p className={styles.count}><strong>{coverage?.completed??0}</strong> of <strong>{coverage?.total??0}</strong> discovered checks processed</p>
      <dl className={styles.counts}><div><dt>Pending</dt><dd>{coverage?.pending??0}</dd></div><div><dt>Excluded</dt><dd>{coverage?.excluded??0}</dd></div><div><dt>Unsupported</dt><dd>{coverage?.unsupported??0}</dd></div></dl>
      <p className={styles.meta}>Processed includes inconclusive and failed questions; canceled questions remain pending. Processing does not mean the code is safe. Excluded and unsupported checks remain in the denominator.</p>
      <Conditions conditions={run.conditions??[]} />
      {active&&onControl&&<div className={styles.controls}><button disabled={sending||!!page.requested} onClick={()=>onControl("pause")}>Pause at checkpoint</button><button disabled={sending||page.requested==="cancel"} onClick={()=>onControl("cancel")}>Cancel review</button></div>}
      <p role="status">{controlMessage||(page.requested?`${page.requested==="pause"?"Pause":"Cancel"} requested; waiting for the worker's next checkpoint.`:"")}</p>
      {run.lifecycle==="paused"&&<div><p>Resume the original frozen snapshot. Current edits are not included; profile and memory checks run again.</p>{run.run_type==="live"&&onResume&&<button className={styles.control} disabled={sending||!!page.requested} onClick={onResume}>Resume review</button>}<details><summary>Terminal alternative</summary><Command>{`uv run plumb resume ${run.id}`}</Command></details></div>}
    </section>
    <div className={styles.columns}>
      <section aria-labelledby="queue-title"><h2 id="queue-title">Question queue <span className={styles.meta}>({page.total})</span></h2>
        <p className={styles.meta}>Current review order; the original recommendation stays beside each question. Priority reasons explain selection; they do not establish a vulnerability.</p>
        {onEdit&&<p className={styles.meta}>{run.lifecycle==="paused"?"Edit questions that have not started. Moving a question keeps coverage unchanged. Excluding one moves it from pending to excluded; the total stays the same.":"Pause at a checkpoint to reorder or narrow pending questions."} {page.queue_excluded??0} questions excluded by your queue choices.</p>}
        {page.questions.length?<ol className={styles.queue} start={page.offset+1}>{page.questions.map(q=><li key={q.id} value={q.position} className={q.status==="running"?styles.current:undefined}>
          <h3>{questionTitle(q.type)}</h3><p className={styles.meta}>{q.family.replaceAll("_"," ")} · {q.status.replaceAll("_"," ")}{q.status==="running"?` · ${q.stage}`:""}</p>
          <p className={styles.meta}>Current #{q.position} · Original recommendation #{q.original_position??q.position}</p>
          <p className={styles.location}><code>{q.location?`${q.location.path}:${q.location.start_line}–${q.location.end_line}`:"No source location recorded"}</code></p>
          <ul className={styles.reasons}>{q.priority_reasons.length?q.priority_reasons.map((reason,i)=><li key={i}>{reason}</li>):<li>No priority reasons recorded.</li>}</ul>
          {q.exploration&&<p className={styles.exploration}>Exploration: lower-ranked by design</p>}
          {onEdit&&run.run_type==="live"&&run.lifecycle==="paused"&&!page.requested&&(q.status==="pending"||q.status==="excluded")&&<div className={styles.controls} role="group" aria-label={`Edit question ${q.position}`}>
            {q.status==="pending"&&<><button aria-disabled={sending} aria-label={`Move question ${q.position} earlier`} onClick={()=>{if(!sending)onEdit(q.id,"up");}}>Move earlier</button><button aria-disabled={sending} aria-label={`Move question ${q.position} later`} onClick={()=>{if(!sending)onEdit(q.id,"down");}}>Move later</button></>}
            <button key="scope" aria-disabled={sending} aria-label={`${q.status==="excluded"?"Include":"Exclude"} question ${q.position}`} onClick={()=>{if(!sending)onEdit(q.id,q.status==="excluded"?"include":"exclude");}}>{q.status==="excluded"?"Include in review":"Exclude from review"}</button>
          </div>}
          <details><summary>Question identifier</summary><code>{q.id}</code></details>
        </li>)}</ol>:<p>No questions on this page. See the recorded scope above.</p>}
        {onPage&&<div className={styles.controls}><button aria-disabled={page.offset===0} onClick={()=>{if(page.offset>0)onPage(Math.max(0,page.offset-20));}}>Previous questions</button><button aria-disabled={page.next_offset===null} onClick={()=>{if(page.next_offset!==null)onPage(page.next_offset);}}>Next questions</button></div>}
        <p className={styles.meta}>{page.questions.length?`Questions ${page.offset+1}–${page.offset+page.questions.length} of ${page.total}.`:""}</p>
      </section>
      <section aria-labelledby="activity-title"><h2 id="activity-title">Activity</h2><p className={styles.meta}>{page.cursor>100?`Latest 100 of ${page.cursor} saved events.`:`${page.cursor} saved events.`} Factual activity from the worker.</p>
        {page.events.length?<ol className={styles.activity} reversed start={page.cursor} tabIndex={0} aria-label="Recorded activity, newest first">{[...page.events].reverse().map(event=><li key={event.seq}><code>#{event.seq}</code> <time dateTime={event.at}>{new Date(event.at).toISOString().slice(11,19)} UTC</time><p>{activityText(event)}</p>{event.question_id&&<code>{event.question_id}</code>}</li>)}</ol>:<p>No activity recorded yet.</p>}
      </section>
    </div>
  </div>;
}
