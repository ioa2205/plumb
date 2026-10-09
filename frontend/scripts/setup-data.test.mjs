import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseReadiness, parseInspection, fetchReadiness, inspectFolder, validLocalFolder, reviewCommand, launchReview, resumeReview, parseSourceCheck, checkSource } from "../lib/setup-data.ts";
import { parseRun } from "../lib/run-metadata.ts";
const actual=JSON.parse(readFileSync(new URL("./fixtures/setup-views.json",import.meta.url),"utf8"));
const browser=JSON.parse(readFileSync(new URL("./fixtures/browser-review.json",import.meta.url),"utf8"));

test("actual protected API replay retains its paused/completed identity and current source observation",()=>{
  const inspection=parseInspection(browser.inspection);assert.ok(inspection.inspection_id);
  assert.equal(parseReadiness(browser.readiness).model_loaded,false);
  const before=parseRun(browser.first_checkpoint,browser.first_checkpoint.id),after=parseRun(browser.review.run,browser.first_checkpoint.id);
  assert.equal(before.lifecycle,"paused");assert.equal(after.lifecycle,"completed");
  assert.equal(before.snapshot_id,inspection.snapshot_id);assert.equal(after.snapshot_id,inspection.snapshot_id);
  assert.equal(before.coverage.total,after.coverage.total);assert.equal(after.coverage.pending,0);
  assert.equal(parseSourceCheck(browser.source_check,after.id,after.snapshot_id).state,"current");
});

test("actual readiness and inspected source preserve measured requirements, scope and citations",()=>{
  const r=parseReadiness(actual.readiness);const p=parseInspection(actual.inspection);
  assert.equal(r.required_ram_bytes,actual.setup_preview.doctor.profiles[0].host_required_bytes);
  assert.equal(r.model_loaded,false);assert.equal(r.downloads_started,false);
  assert.equal(p.snapshot_id,actual.inspection.snapshot_id);assert.equal(p.entries_total,Object.values(p.frameworks).reduce((a,b)=>a+b,0));
  assert.equal(p.target_executed,false);
  for(const e of p.entries)assert.equal(e.span.snapshot_id,p.snapshot_id);
});

test("a CPU profile needs no dedicated VRAM, and its memory rule still cannot be forged",()=>{
  const cpu={...actual.readiness,profile_id:"cpu-8k",ready:false,required_ram_bytes:2436385888,available_ram_bytes:4000000000,required_vram_bytes:0,available_vram_bytes:null,memory_fit:true};
  assert.equal(parseReadiness(cpu).required_vram_bytes,0);
  assert.equal(parseReadiness({...cpu,available_ram_bytes:2436385887,memory_fit:false}).memory_fit,false);
  for(const changes of [{memory_fit:false},{available_ram_bytes:1,memory_fit:true},{required_vram_bytes:-1},{required_vram_bytes:1}])assert.throws(()=>parseReadiness({...cpu,...changes}));
});

test("browser review dispatch preserves inspected identity, consent and selected scope",async()=>{
  const p={...actual.inspection,inspection_id:"inspect-"+"a".repeat(32)};const signal=new AbortController().signal;
  const run={id:"review-"+"b".repeat(32),snapshot_id:p.snapshot_id,run_type:"live",lifecycle:"queued",created_at:"2026-10-06T00:00:00Z",coverage:{total:1,pending:1,completed:0,excluded:0,unsupported:0}};
  const body={inspection_id:p.inspection_id,authorized:true,limit:1,families:["authorization"],resources:[],routes:["/orders/{order_id}/invoice"]};let calls=0;
  const request=async(url,options)=>{calls++;assert.equal(url,"/api/projects/review");assert.equal(options.method,"POST");assert.equal(options.credentials,"same-origin");assert.equal(options.redirect,"error");assert.deepEqual(JSON.parse(options.body),body);return Response.json(run);};
  assert.equal((await launchReview(p,body,signal,request)).snapshot_id,p.snapshot_id);
  for(const change of [{authorized:false},{authorized:1},{inspection_id:"../../escape"},{inspection_id:"inspect-"+"c".repeat(32)},{limit:0},{families:[]},{families:["authorization","authorization"]},{families:["unknown"]},{families:["injection"],resources:["Order"]}])await assert.rejects(launchReview(p,{...body,...change},signal,request));
  assert.equal(calls,1);
  await assert.rejects(launchReview(p,body,signal,async()=>Response.json({...run,snapshot_id:"0".repeat(64)})),/snapshot/);
  assert.equal((await resumeReview(run.id,signal,async(url,options)=>{assert.equal(url,`/api/runs/${run.id}/resume`);assert.deepEqual(JSON.parse(options.body),{limit:5});return Response.json(run);})).id,run.id);
  await assert.rejects(resumeReview(run.id,signal,async()=>Response.json({...run,id:"review-"+"c".repeat(32)})),/different/);
});
test("source observations distinguish changed hashes from unavailable or unassociated source",async()=>{
  const id="review-"+"b".repeat(32),snapshot=actual.inspection.snapshot_id;
  const value={run_id:id,snapshot_id:snapshot,checked_at:"2026-10-06T00:00:00Z",state:"changed",current_snapshot_id:"c".repeat(64),changed_files:1,added_files:0,removed_files:0,excluded_scope_changed:false,conditions:[],limitations:["Software source observation"],model_loaded:false,target_executed:false};
  assert.equal(parseSourceCheck(value,id,snapshot).changed_files,1);
  for(const updates of [{state:"current"},{run_id:"review-"+"d".repeat(32)},{changed_files:null},{model_loaded:true},{target_executed:true}])assert.throws(()=>parseSourceCheck({...value,...updates},id,snapshot));
  const unknown={...value,state:"unavailable",current_snapshot_id:null,changed_files:null,added_files:null,removed_files:null,excluded_scope_changed:null};assert.equal(parseSourceCheck(unknown,id,snapshot).changed_files,null);
  for(const updates of [{changed_files:0},{current_snapshot_id:snapshot},{excluded_scope_changed:false}])assert.throws(()=>parseSourceCheck({...unknown,...updates},id,snapshot));
  assert.equal((await checkSource(id,snapshot,new AbortController().signal,async(url,options)=>{assert.equal(url,`/api/runs/${id}/source-check`);assert.equal(options.method,"POST");return Response.json(value);})).state,"changed");
});
test("forged readiness, memory, source identity or scope cannot establish inspection",()=>{
  for(const changes of [{model_loaded:true},{downloads_started:true},{memory_fit:!actual.readiness.memory_fit},{ready:true,model_verified:false},{requires_large_download_approval:!actual.readiness.requires_large_download_approval}])assert.throws(()=>parseReadiness({...actual.readiness,...changes}));
  for(const changes of [{target_executed:true},{entries_total:0},{excluded_files:999},{entries:[{...actual.inspection.entries[0],snapshot_id:"0".repeat(64)}]},{resources:{Invented:-1}}])assert.throws(()=>parseInspection({...actual.inspection,...changes}));
});
test("inspection requires authorization and a local path; PowerShell guidance quotes user paths safely",async()=>{
  for(const value of ["relative","\\\\server.invalid\\share","//server.invalid/share","D:\\","/","D:\\bad\npath"])assert.equal(validLocalFolder(value),false);
  assert.equal(reviewCommand("D:\\Projects\\owner's app"),"uv run plumb review 'D:\\Projects\\owner''s app'");
  assert.equal(reviewCommand("D:\\Projects\\$(malicious)`script"),"uv run plumb review 'D:\\Projects\\$(malicious)`script'");
  const signal=new AbortController().signal;let calls=0;
  const request=async(url,options)=>{calls++;assert.equal(url,"/api/projects/inspect");assert.equal(options.method,"POST");assert.equal(options.credentials,"same-origin");assert.equal(options.redirect,"error");assert.equal(options.cache,"no-store");assert.deepEqual(JSON.parse(options.body),{folder:"D:\\Projects\\owned",authorized:true});return Response.json(actual.inspection);};
  await inspectFolder("D:\\Projects\\owned",true,signal,request);assert.equal(calls,1);
  await assert.rejects(inspectFolder("relative",true,signal,request));await assert.rejects(inspectFolder("D:\\Projects\\owned",false,signal,request));assert.equal(calls,1);
  for(const status of [401,403,409,503])await assert.rejects(fetchReadiness(signal,async()=>new Response("private-machine-secret",{status})),e=>!e.message.includes("private-machine-secret"));
  await assert.rejects(fetchReadiness(signal,async()=>new Response("x".repeat(512*1024+1),{headers:{"content-type":"application/json"}})),/too large/);
  await assert.rejects(fetchReadiness(signal,async()=>{throw new Error("private-secret");}),e=>!e.message.includes("private-secret"));
});
