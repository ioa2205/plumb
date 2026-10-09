import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { consumeEvents, fetchReview, parseReview, parseEvent, requestControl, requestQueueEdit, ReviewError, MAX_EVENT_BYTES, MAX_VIEW_BYTES, readView } from "../lib/review-data.ts";
import { emptyFilters, parseFindingList, fetchFindingList } from "../lib/finding-list.ts";
const run=JSON.parse(readFileSync(new URL("./fixtures/recorded-run.json",import.meta.url),"utf8"));
const detail=JSON.parse(readFileSync(new URL("./fixtures/recorded-case.json",import.meta.url),"utf8"));
const signal=new AbortController().signal;
// Explicit software projections. These are transport regressions, not fresh model evidence.
const event=(seq=1)=>({run_id:run.id,seq,at:run.finished_at,kind:"run.completed",question_id:null,stage:null,status:null,message:null,coverage:run.coverage});
const view=JSON.parse(readFileSync(new URL("./fixtures/review-view.json",import.meta.url),"utf8")).review;
const frame=e=>`id: ${e.seq}\nevent: ${e.kind}\ndata: ${JSON.stringify(e)}\n\n`;
const f=detail.finding;
const row={id:f.id,display_id:f.display_id,title:f.title,family:f.family,conclusion:f.conclusion,severity:f.severity,runtime_verification:f.runtime_verification,disposition:f.disposition,location:f.exhibits[0].span};
const list={run,findings:[row],limitations:[],counts:{supported:1,rejected:0,inconclusive:0,candidate:0},total:1,offset:0,next_offset:null};

test("supplementary observations stay separate from counts and bind their frozen run",()=>{
  const observed={run_id:run.id,snapshot_id:run.snapshot_id,tool_version:"supplementary-signals-1",status:"ok",pack_sha256:"a".repeat(64),pack_date:"2026-10-07",pack_source:"GitHub Advisory Database",limitations:[],signals:[{id:"signal:fixture",category:"dependency",status:"observed",source:f.exhibits[0].span,rule_id:"GHSA-fv66-9v8q-g76r",rule_version:"supplementary-signals-1",summary:"Exact version exposure only.",fingerprint:null,ecosystem:"npm",package:"react-server-dom-webpack",version:"19.1.1",advisory_id:"GHSA-fv66-9v8q-g76r",limitations:[]}]};
  const parsed=parseFindingList({...list,supplementary:observed},run.id,0,emptyFilters);
  assert.equal(parsed.total,1);assert.deepEqual(parsed.counts,list.counts);assert.deepEqual(parsed.run.coverage,run.coverage);
  for(const patch of [{run_id:"other"},{snapshot_id:"b".repeat(64)},{signals:[...observed.signals,...observed.signals]},{pack_date:null},{status:"not_run"}])assert.throws(()=>parseFindingList({...list,supplementary:{...observed,...patch}},run.id,0,emptyFilters),ReviewError);
  const component=readFileSync(new URL("../components/FindingGroups.tsx",import.meta.url),"utf8");
  assert.match(component,/Supplementary security signals/);assert.match(component,/separate from challenged findings and coverage/);
});

test("actual saved review and finding projections preserve the original denominator and every event",()=>{
  const saved=JSON.parse(readFileSync(new URL("./fixtures/review-view.json",import.meta.url),"utf8"));
  const page=parseReview(saved.review,run.id,0);const findings=parseFindingList(saved.findings,run.id,0,emptyFilters);
  assert.deepEqual(page.run.coverage,run.coverage);
  assert.deepEqual(page.events.map(e=>e.seq),Array.from({length:page.cursor},(_,i)=>i+1));
  assert.equal(page.questions.length,run.coverage.completed);
  assert.equal(findings.counts.supported,1);assert.equal(findings.counts.rejected,1);
  assert.equal(findings.findings.find(f=>f.id===detail.finding.id).severity,"unknown");
});

test("checkpoint and finding identities, coverage, pages and filters refuse inconsistent records",()=>{
  assert.equal(parseReview(view,run.id,0).cursor,view.cursor);
  for(const patch of [{cursor:2},{events:[{...event(),run_id:"foreign"}]},{offset:1},{next_offset:20},{run:{...run,coverage:{...run.coverage,total:999}}}])assert.throws(()=>parseReview({...view,...patch},run.id,0));
  assert.equal(parseFindingList(list,run.id,0,emptyFilters).findings[0].id,f.id);
  for(const patch of [{counts:{...list.counts,supported:2}},{counts:{supported:1}},{findings:[{...row,id:"foreign"}]},{findings:[{...row,location:{...row.location,snapshot_id:"a".repeat(64)}}]},{next_offset:20}])assert.throws(()=>parseFindingList({...list,...patch},run.id,0,emptyFilters));
  assert.throws(()=>parseFindingList(list,run.id,0,{...emptyFilters,severity:"critical"}));
});
test("event framing preserves literal text and rejects gaps, duplicates and forged completion",()=>{
  const e={...event(),kind:"question.activity",question_id:"q:1",message:"Read <script>literal</script>\n\nid: 900"};
  assert.deepEqual(parseEvent(frame(e).trim(),run.id,0),e);
  for(const patch of [{seq:2},{run_id:"foreign"},{kind:"question.finished"},{kind:"run.completed"}])assert.throws(()=>parseEvent(frame({...e,...patch}).trim(),run.id,0));
  assert.throws(()=>parseEvent(frame(event()).trim(),run.id,1));
});
test("stream reconnect uses last delivered ID, tolerates byte splits and excludes duplicate delivery",async()=>{
  const delivered=[];let cursor=0;
  // Drop the network after one complete frame; reconnect must start at 1.
  const broken=new ReadableStream({start(c){c.enqueue(new TextEncoder().encode(frame(event(1))));},pull(c){c.error(new Error("private"));}});
  await assert.rejects(consumeEvents(run.id,0,signal,e=>{delivered.push(e.seq);cursor=e.seq;},async()=>new Response(broken,{headers:{"content-type":"text/event-stream"}})),e=>e instanceof ReviewError&&e.retry&&!e.message.includes("private"));
  const text=frame(event(2))+frame({...event(3),message:"Recorded café."});const bytes=new TextEncoder().encode(text);
  const stream=new ReadableStream({start(c){for(const byte of bytes)c.enqueue(Uint8Array.of(byte));c.close();}});
  await consumeEvents(run.id,cursor,signal,e=>delivered.push(e.seq),async(url,options)=>{assert.equal(options.headers["Last-Event-ID"],"1");assert.equal(options.credentials,"same-origin");assert.equal(options.redirect,"error");return new Response(stream,{headers:{"content-type":"text/event-stream"}});});
  assert.deepEqual(delivered,[1,2,3]);
});
test("bounded streams and session failures stop safely; cancel remains an acknowledged request",async()=>{
  for(const status of [401,403,404,409])await assert.rejects(consumeEvents(run.id,0,signal,()=>{},async()=>new Response("private",{status})),e=>!e.retry&&!e.message.includes("private"));
  await assert.rejects(consumeEvents(run.id,0,signal,()=>{},async()=>new Response("x".repeat(MAX_EVENT_BYTES+1),{headers:{"content-type":"text/event-stream"}})),/too large/);
  await assert.rejects(readView("/api/runs/x",signal,async()=>new Response("x".repeat(MAX_VIEW_BYTES+1),{headers:{"content-type":"application/json"}})),/too large/);
  await requestControl(run.id,"cancel",signal,async(url,options)=>{assert.equal(url,`/api/runs/${run.id}/cancel`);assert.equal(options.method,"POST");return Response.json({requested:"cancel"},{status:202});});
  await assert.rejects(requestControl(run.id,"cancel",signal,async()=>new Response("",{status:200})),/acknowledge/);
  await assert.rejects(requestControl("../escape","pause",signal,async()=>assert.fail("must not request")));
});
test("finding requests filter at the server and use strict generated checkpoint reads",async()=>{
  await fetchFindingList(run.id,0,{...emptyFilters,severity:row.severity},signal,async(url)=>{assert.ok(url.includes(`severity=${row.severity}`));return Response.json(list);});
  assert.equal((await fetchReview(run.id,0,signal,async()=>Response.json(view))).run.id,run.id);
});
test("queue edits carry the checked checkpoint, remain same-origin and refuse stale state",async()=>{
  const edit={question_id:"q:1",action:"exclude",expected_cursor:48,offset:20};
  await requestQueueEdit(run.id,edit,signal,async(url,options)=>{assert.equal(url,`/api/runs/${run.id}/queue`);assert.equal(options.method,"POST");assert.equal(options.credentials,"same-origin");assert.deepEqual(JSON.parse(options.body),edit);return Response.json({});});
  await assert.rejects(requestQueueEdit(run.id,edit,signal,async()=>Response.json({detail:"private"},{status:409})),/Refresh/);
  await assert.rejects(requestQueueEdit(run.id,{...edit,question_id:"../outside"},signal,async()=>assert.fail("must not request")));
  const narrowed={...view,queue_excluded:1,run:{...view.run,coverage:{...view.run.coverage,completed:1,excluded:73}}};
  assert.equal(parseReview(narrowed,run.id,0).run.coverage.total,74);
  assert.throws(()=>parseReview({...narrowed,queue_excluded:2},run.id,0));
});
test("actual software queue-edit replay retains original recommendations and constant total",()=>{
  const saved=JSON.parse(readFileSync(new URL("./fixtures/queue-edit-views.json",import.meta.url),"utf8"));
  const pages=saved.states.map(raw=>parseReview(raw,raw.run.id,0));
  assert.deepEqual(pages.map(p=>p.run.coverage.total),[7,7,7,7]);
  assert.deepEqual(pages.map(p=>p.run.coverage.pending),[3,3,2,3]);
  assert.deepEqual(pages.map(p=>p.queue_excluded),[0,0,1,0]);
  assert.equal(pages[1].questions[0].id,"fixture:receipt");assert.equal(pages[1].questions[0].original_position,2);
  assert.equal(pages[2].questions[2].status,"excluded");assert.equal(pages[3].questions[2].status,"pending");
});
