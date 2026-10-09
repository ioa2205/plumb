import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseRun, selectedRun, runDestination, runLabel, lifecycleLabel, fetchRun, MAX_RUN_BYTES } from "../lib/run-metadata.ts";
const recorded=JSON.parse(readFileSync(new URL("./fixtures/recorded-run.json",import.meta.url),"utf8"));

test("real recorded metadata retains identity, lifecycle, model and denominator",()=>{
  const parsed=parseRun(recorded,recorded.id);
  assert.equal(parsed.snapshot_id,recorded.snapshot_id);
  assert.equal(parsed.model.file_sha256,recorded.model.file_sha256);
  assert.equal(parsed.coverage.completed+parsed.coverage.pending+parsed.coverage.excluded+parsed.coverage.unsupported,parsed.coverage.total);
  assert.equal(runLabel(parsed),"Live"); assert.equal(lifecycleLabel(parsed),"Completed");
  for(const kind of ["saved","replay"]) {
    const value=parseRun({...recorded,run_type:kind},recorded.id);
    assert.match(runLabel(value),kind==="saved" ? /^Saved run ·/ : /^Replay of saved run ·/);
    assert.match(runLabel(value),/UTC$/);
  }
});
test("malformed metadata cannot establish a displayed run",()=>{
  for(const changes of [{id:"other"},{snapshot_id:"../wrong"},{run_type:"unknown"},{model:{...recorded.model,file_sha256:"changed"}},{created_at:"not a date"},{stage:"investigating"},{coverage:{...recorded.coverage,total:999}},{extra:"not a contract field"}]) assert.throws(()=>parseRun({...recorded,...changes},recorded.id));
  assert.throws(()=>parseRun(null,recorded.id));
  assert.throws(()=>parseRun({...recorded,model:{...recorded.model,file_sha256:null}},recorded.id));
});
test("selection refuses ambiguous or escaping IDs and survives document navigation",()=>{
  assert.equal(selectedRun(""),null);
  assert.equal(selectedRun(`?run=${recorded.id}`),recorded.id);
  for(const search of ["?run=../secret","?run=x&run=y","?run=", "?run=%3Cscript%3E","?run=x%0A"]) assert.throws(()=>selectedRun(search));
  assert.equal(runDestination("/findings/",recorded.id),`/findings/?run=${recorded.id}`);
  assert.equal(runDestination("/",null),"/");
  assert.throws(()=>runDestination("https://external.invalid/",recorded.id));
});
test("same-origin reads accept actual data and never reflect server errors",async()=>{
  const signal=new AbortController().signal;
  const result=await fetchRun(recorded.id,signal,async(url,options)=>{
    assert.equal(url,`/api/runs/${recorded.id}`); assert.equal(options.credentials,"same-origin"); assert.equal(options.redirect,"error");
    return Response.json(recorded);
  });assert.equal(result.id,recorded.id);
  for(const status of [401,404,500]) await assert.rejects(fetchRun(recorded.id,signal,async()=>new Response("private server detail",{status})),error=>!error.message.includes("private server detail"));
  await assert.rejects(fetchRun(recorded.id,signal,async()=>new Response("<html>wrong</html>")),/readable run/);
  await assert.rejects(fetchRun(recorded.id,signal,async()=>Response.json({...recorded,id:"other"})),/cannot be read/);
  await assert.rejects(fetchRun(recorded.id,signal,async()=>new Response("x".repeat(MAX_RUN_BYTES+1),{headers:{"content-type":"application/json"}})),/too large/);
  await assert.rejects(fetchRun("../escape",signal,async()=>{throw new Error("must not request");}),/run ID/);
  await assert.rejects(fetchRun(recorded.id,signal,async()=>{throw new Error("private transport detail");}),error=>error.message.includes("cannot be reached") && !error.message.includes("private transport detail"));
  const broken=new ReadableStream({start(controller){controller.error(new Error("private stream detail"));}});
  await assert.rejects(fetchRun(recorded.id,signal,async()=>new Response(broken,{headers:{"content-type":"application/json"}})),error=>error.message.includes("transfer stopped") && !error.message.includes("private stream detail"));
});
