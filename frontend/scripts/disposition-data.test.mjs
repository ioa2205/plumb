import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {dispositionIntent,applyDecision,validDispositionHistory,saveDecision} from "../lib/disposition-data.ts";
import {parseCase,MAX_CASE_BYTES} from "../lib/case-data.ts";

const saved=JSON.parse(readFileSync(new URL("./fixtures/recorded-case.json",import.meta.url),"utf8"));
function record(intent,updates={}){return {...intent,run_id:saved.run.id,finding_id:saved.finding.id,original_finding_sha256:"d".repeat(64),version:intent.expected_version+1,recorded_at:"2026-10-07T10:00:00Z",...updates};}

test("dismiss, accept risk, resolve and reopen preserve exact case evidence and proof",()=>{
  let view=saved;
  for(const action of ["dismissed","open","accepted_risk","open","resolved","open"]){
    const intent=dispositionIntent(view,action,"Reviewed owned source","Reviewer",action==="resolved"?"a".repeat(40):"");
    const next=applyDecision(view,record(intent),intent);
    const {disposition,disposition_reason,...evidence}=next.finding;
    const {disposition:old,disposition_reason:oldReason,...original}=saved.finding;
    assert.deepEqual(evidence,original);
    assert.equal(next.probe_runs,saved.probe_runs);assert.equal(next.run,saved.run);
    assert.equal(next.suggested_change,saved.suggested_change);
    assert.equal(next.disposition_history.length,intent.expected_version+1);
    assert.ok(validDispositionHistory(next));assert.deepEqual(parseCase(next,saved.run.id,saved.finding.id),next);
    view=next;
  }
  assert.equal(saved.disposition_history,undefined,"legacy input remains untouched");
});

test("reasons, commit links and legal state transitions are required",()=>{
  for(const [action,reason,actor,commit] of [["open","Reason","Reviewer",""],["dismissed"," ","Reviewer",""],["accepted_risk","Reason"," ",""],["dismissed","two\nlines","Reviewer",""],["dismissed","x".repeat(1001),"Reviewer",""],["resolved","Reason","Reviewer",""],["resolved","Reason","Reviewer","../file"]])assert.throws(()=>dispositionIntent(saved,action,reason,actor,commit));
  const intent=dispositionIntent(saved,"dismissed","Reason","Reviewer","");
  const closed=applyDecision(saved,record(intent),intent);
  assert.throws(()=>dispositionIntent(closed,"resolved","Reason","Reviewer","a".repeat(40)));
});

test("cross-finding, stale, nonsequential, altered state and foreign decision records refuse",()=>{
  const intent=dispositionIntent(saved,"dismissed","Reason","Reviewer","");
  for(const updates of [{run_id:"other"},{finding_id:"other"},{snapshot_id:"b".repeat(64)},{version:2},{expected_version:1},{previous_disposition:"resolved"},{disposition:"accepted_risk"},{reason:" "},{actor:" "},{resolution_commit:"a".repeat(40)},{recorded_at:"invalid"},{severity:"low"}])assert.throws(()=>applyDecision(saved,record(intent,updates),intent));
  const view=applyDecision(saved,record(intent),intent);
  const reopen=dispositionIntent(view,"open","Revisit","Reviewer","");
  for(const updates of [{original_finding_sha256:"b".repeat(64)},{recorded_at:"2026-10-06T10:00:00Z"}])assert.throws(()=>applyDecision(view,record(reopen,updates),reopen));
  for(const mutate of [x=>x.finding.disposition="open",x=>x.finding.disposition_reason="Changed",x=>x.disposition_history[0].finding_id="other",x=>x.disposition_history.push(x.disposition_history[0])]){
    const value=structuredClone(view);mutate(value);assert.throws(()=>parseCase(value,saved.run.id,saved.finding.id));
  }
});

test("protected saves acknowledge a bounded record once and leave inputs immutable on failure",async()=>{
  const intent=dispositionIntent(saved,"dismissed","Reason","Reviewer","");const signal=new AbortController().signal;
  let calls=0;
  const response=await saveDecision(saved,intent,signal,async(path,options)=>{
    calls++;assert.equal(path,`/api/runs/${saved.run.id}/findings/${encodeURIComponent(saved.finding.id)}/disposition`);
    assert.equal(options.method,"POST");assert.equal(options.credentials,"same-origin");assert.equal(options.redirect,"error");assert.equal(options.cache,"no-store");assert.equal(options.signal,signal);assert.deepEqual(JSON.parse(options.body),intent);
    return Response.json(record(intent));
  });
  assert.equal(calls,1);assert.equal(response.finding.disposition,"dismissed");
  for(const status of [401,403,404,409,422,503])await assert.rejects(saveDecision(saved,intent,signal,async()=>Response.json({detail:"private/path"},{status})),error=>!error.message.includes("private/path"));
  await assert.rejects(saveDecision(saved,intent,signal,async()=>{throw new Error("private/path");}),/not acknowledged/);
  await assert.rejects(saveDecision(saved,intent,signal,async()=>new Response("x".repeat(MAX_CASE_BYTES+1),{headers:{"content-type":"application/json"}})),/too large/);
  const abort=new AbortController();
  await assert.rejects(saveDecision(saved,intent,abort.signal,async()=>{abort.abort();return Response.json(record(intent));}),/canceled/);
  assert.equal(saved.finding.disposition,"open");assert.equal(saved.disposition_history,undefined);
});

test("reviewer reason redaction is accepted while evidence fields cannot be rewritten",()=>{
  const intent=dispositionIntent(saved,"dismissed","secret example","Reviewer","");
  const next=applyDecision(saved,record(intent,{reason:"[REDACTED] example"}),intent);
  assert.equal(next.finding.disposition_reason,"[REDACTED] example");
  assert.equal(next.finding.runtime_verification,saved.finding.runtime_verification);
});
