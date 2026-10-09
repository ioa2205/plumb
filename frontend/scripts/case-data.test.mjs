import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {parseCase,parsePage,parseExcerpt,caseDestination,selectedFinding,fetchCase,fetchPage,fetchExcerpt,observed,proofSummary,MAX_CASE_BYTES} from "../lib/case-data.ts";
const recorded=JSON.parse(readFileSync(new URL("./fixtures/recorded-case.json",import.meta.url),"utf8"));
const excerpts=JSON.parse(readFileSync(new URL("./fixtures/recorded-excerpts.json",import.meta.url),"utf8"));
const clone=value=>structuredClone(value);

test("saved real receipt replay retains unknown severity, exact proof links and cited code",()=>{
  const detail=parseCase(recorded,recorded.run.id,recorded.finding.id);
  assert.equal(detail.finding.display_id,"F-02");assert.equal(detail.finding.severity,"unknown");
  assert.equal(detail.peer_comparison,"not_recorded");assert.equal(detail.suggested_change,null);
  assert.equal(detail.probe_runs[0].outcome,"reproduced");
  assert.match(proofSummary(detail),/bob's attack request returned the victim marker/);
  assert.match(proofSummary(detail),/alice's legitimate-user control also succeeded/);
  assert.equal(proofSummary({...detail,probe_runs:[]}),null);
  for(const excerpt of excerpts) {
    const parsed=parseExcerpt(excerpt,detail,excerpt.exhibit.tag,0);
    assert.equal(parsed.start_line,parsed.exhibit.span.start_line);
    assert.equal(parsed.lines.length,parsed.end_line-parsed.start_line+1);
  }
  const hostile=clone(recorded);hostile.finding.title='<img src=x onerror="private">';
  assert.equal(parseCase(hostile,recorded.run.id,recorded.finding.id).finding.title,hostile.finding.title,"claims stay literal strings, never HTML");
});

test("case parsing refuses cross-run/snapshot/probe/change corruption and unknown fields",()=>{
  const mutations=[
    x=>x.finding.id="other",x=>x.finding.run_id="other",x=>x.finding.snapshot_id="b".repeat(64),
    x=>x.finding.exhibits[0].span.snapshot_id="b".repeat(64),x=>x.probe_runs[0].finding_id="other",
    x=>x.probe_runs[0].snapshot_id="b".repeat(64),x=>x.probe_runs.push(x.probe_runs[0]),
    x=>x.finding.probe_run_ids=[],x=>x.finding.suggested_change_id="missing",
    x=>x.peer_comparison="invented",x=>x.extra="unknown",x=>x.finding.exhibits.push(x.finding.exhibits[0]),
  ];
  for(const mutate of mutations){const value=clone(recorded);mutate(value);assert.throws(()=>parseCase(value,recorded.run.id,recorded.finding.id));}
  assert.throws(()=>parseCase(null,recorded.run.id,recorded.finding.id));
  for(const mutate of [x=>x.lines=[],x=>x.lines.pop(),x=>x.start_line++,x=>x.end_line++,x=>x.next_offset=999,x=>x.exhibit.span.content_sha256="b".repeat(64),x=>x.finding_id="other",x=>x.text_is_redacted=false]) {
    const value=clone(excerpts[0]);mutate(value);assert.throws(()=>parseExcerpt(value,recorded,value.exhibit.tag,0));
  }
});

test("pages and selection preserve canonical order and refuse ambiguous or escaping identifiers",()=>{
  const page={run:recorded.run,findings:[recorded.finding],limitations:recorded.limitations,total:2,offset:1,next_offset:null};
  assert.equal(parsePage(page,recorded.run.id,1).findings[0].id,recorded.finding.id);
  for(const change of [{offset:0},{total:1},{next_offset:1},{findings:[]},{run:{...recorded.run,id:"other"}}])assert.throws(()=>parsePage({...page,...change},recorded.run.id,1));
  assert.equal(selectedFinding(`?finding=${recorded.finding.id}`),recorded.finding.id);
  assert.equal(selectedFinding(""),null);
  for(const query of ["?finding=x&finding=y","?finding=../secret","?finding=%3Cimg%3E","?finding=x%0A"])assert.throws(()=>selectedFinding(query));
  assert.equal(caseDestination(recorded.run.id,recorded.finding.id),`/findings/?run=${recorded.run.id}&finding=${encodeURIComponent(recorded.finding.id)}`);
  assert.throws(()=>caseDestination(recorded.run.id,"//outside"));
});

test("proof observations distinguish an exposed marker from denial, timeout and server failure",()=>{
  const attack=recorded.probe_runs[0].steps.find(s=>s.role==="attack");
  assert.equal(observed(attack),"allowed");
  assert.equal(observed({...attack,status:404,marker_present:false}),"denied");
  for(const changes of [{status:500,marker_present:false},{status:null},{marker_present:null},{status:403,marker_present:true}])assert.equal(observed({...attack,...changes}),"unknown");
  assert.equal(observed({...attack,status:200,marker_present:false}),"denied");
});

test("bounded same-origin reads return exact records and hide storage/transfer errors",async()=>{
  const signal=new AbortController().signal;
  const success=await fetchCase(recorded.run.id,recorded.finding.id,signal,async(path,options)=>{
    assert.equal(path,`/api/runs/${recorded.run.id}/findings/${encodeURIComponent(recorded.finding.id)}`);
    assert.equal(options.credentials,"same-origin");assert.equal(options.cache,"no-store");assert.equal(options.redirect,"error");return Response.json(recorded);
  });assert.deepEqual(success,recorded);
  const excerpt=await fetchExcerpt(recorded,"E01",0,signal,async()=>Response.json(excerpts[0]));assert.deepEqual(excerpt,excerpts[0]);
  for(const status of [401,404,503])await assert.rejects(fetchCase(recorded.run.id,recorded.finding.id,signal,async()=>new Response("private exception",{status})),e=>!e.message.includes("private exception"));
  await assert.rejects(fetchCase(recorded.run.id,recorded.finding.id,signal,async()=>new Response("x".repeat(MAX_CASE_BYTES+1),{headers:{"content-type":"application/json"}})),/too large/);
  await assert.rejects(fetchCase(recorded.run.id,recorded.finding.id,signal,async()=>new Response("<html>private</html>")),/readable case/);
  await assert.rejects(fetchCase(recorded.run.id,recorded.finding.id,signal,async()=>Response.json({...recorded,extra:"private"})),/cannot be read/);
  const forbidden=async()=>{assert.fail("invalid request reached the network");};
  await assert.rejects(fetchPage("../escape",0,signal,forbidden));
  await assert.rejects(fetchPage(recorded.run.id,-1,signal,forbidden));
  await assert.rejects(fetchExcerpt(recorded,"E99",0,signal,forbidden));
  await assert.rejects(fetchCase(recorded.run.id,"../escape",signal,forbidden));
  await assert.rejects(fetchCase(recorded.run.id,recorded.finding.id,signal,async()=>{throw new Error("private transport");}),e=>!e.message.includes("private transport"));
});
