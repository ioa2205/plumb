import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseProject, fetchProject, parseProjectExcerpt, parseConfirmedRule, confirmProjectRule, declareProjectRule, firstProjectPage } from "../lib/project-data.ts";
import ELK from "elkjs/lib/elk.bundled.js";
import { layoutGraph, layoutPositions } from "../lib/map-layout-core.ts";
import { mapPositions } from "../lib/map-layout.ts";
const saved=JSON.parse(readFileSync(new URL("./fixtures/project-views.json",import.meta.url),"utf8"));
const actual=saved.actual, replay=saved.archived_replay, confirmed=saved.confirmed_replay;
const signal=new AbortController().signal;
const parse=p=>parseProject(p,p.run_id,p.snapshot_id,firstProjectPage);
const json=value=>new Response(JSON.stringify(value),{headers:{"Content-Type":"application/json"}});

test("declared requirements preserve exact access, author and scope on acknowledgment",async()=>{
  const original=replay.rules[0].assertion, node=replay.flows[0].data[0];
  const input={snapshot_id:replay.snapshot_id,site_ids:[node.id],statement:"Owner required",author:"Reviewer",required_guard:"owner",forbidden_fields:["details"]};
  const policy={assertion:{...original,id:"policy:declared",statement:input.statement,author:input.author,status:"declared",kind:"owner",confirmed_by:null,confirmed_at:null,evidence:[]},snapshot_id:input.snapshot_id,source_run_id:replay.run_id,provenance:"Local declaration",forbidden_fields:input.forbidden_fields,sites:[{id:node.id,snapshot_id:input.snapshot_id,entry_point_id:replay.flows[0].entry.id,resource:original.resource,operation:"read",key_origin:"path",data_layer:"sqlalchemy",span:node.citation.span,guard_ids:[]}]};
  const p=await declareProjectRule(replay.run_id,input,signal,async(path,init)=>{assert.match(path,/\/project\/rules$/);assert.equal(init.method,"POST");assert.equal(init.redirect,"error");assert.equal(init.credentials,"same-origin");assert.deepEqual(JSON.parse(init.body),input);return json(policy);});
  assert.deepEqual(p,policy);
  for(const breakIt of [p=>p.snapshot_id="0".repeat(64),p=>p.sites[0].id="access:foreign",p=>p.assertion.author="Other",p=>p.forbidden_fields=[],p=>p.assertion.status="confirmed"]){const changed=structuredClone(policy);breakIt(changed);await assert.rejects(declareProjectRule(replay.run_id,input,signal,async()=>json(changed)),/rule|requirement/);}
  await assert.rejects(declareProjectRule(replay.run_id,input,signal,async()=>new Response("private",{status:409})),/revalidate/);
  assert.throws(()=>parse({...replay,bound_policies:[{...policy,snapshot_id:"0".repeat(64)}]}),/source or scope/);
});

test("actual frozen project and separately archived policy projection retain their provenance",()=>{
  assert.equal(parse(actual).flows_total,39);assert.equal(actual.rules_total,0);
  const page=parse(replay);assert.ok(page.rules.length>0);
  assert.equal(page.rules.find(r=>r.assertion.kind==="owner").sites_applying,10);
  assert.equal(page.rules.find(r=>r.assertion.kind==="owner").sites_total,11);
  for(const excerpt of saved.excerpts)assert.deepEqual(parseProjectExcerpt(excerpt,replay.run_id,excerpt.citation,0),excerpt);
  for(const rule of page.rules){const ink=confirmed.rules.find(r=>r.assertion.id===rule.assertion.id);if(ink.assertion.status==="confirmed")assert.equal(parseConfirmedRule(ink,rule).assertion.status,"confirmed");else assert.deepEqual(ink,rule);}
});

test("foreign snapshots, invented counts, links, proposals and citations fail closed",()=>{
  for(const breakIt of [p=>p.snapshot_id="0".repeat(64),p=>p.excluded_files++,p=>p.flows[0].links.push({...p.flows[0].links[0],source:"foreign"}),p=>p.rules[0].source_run_id="foreign",p=>p.rules[0].assertion.evidence=[]]){
    const p=structuredClone(replay);breakIt(p);assert.throws(()=>parseProject(p,replay.run_id,replay.snapshot_id,firstProjectPage));
  }
  const original=saved.excerpts[0];for(const breakIt of [p=>p.lines.push("invented extra line"),p=>p.citation.span.content_sha256="0".repeat(64),p=>p.run_id="foreign"]){const p=structuredClone(original);breakIt(p);assert.throws(()=>parseProjectExcerpt(p,replay.run_id,original.citation,0));}
  const rule=replay.rules[0], ink=structuredClone(confirmed.rules.find(r=>r.assertion.id===rule.assertion.id));ink.assertion.statement="A different expectation";assert.throws(()=>parseConfirmedRule(ink,rule));
});

test("project reads and acknowledgments stay bounded and same-origin, with stale confirmations refused",async()=>{
  let options;const read=await fetchProject(actual.run_id,actual.snapshot_id,firstProjectPage,signal,async(path,init)=>{assert.match(path,/\/project\?/);options=init;return json(actual);});assert.deepEqual(read,actual);assert.equal(options.redirect,"error");assert.equal(options.credentials,"same-origin");
  const rule=replay.rules.find(r=>r.assertion.kind==="owner"), ink=confirmed.rules.find(r=>r.assertion.id===rule.assertion.id);
  const result=await confirmProjectRule(rule,signal,async(path,init)=>{assert.match(path,/\/confirm$/);assert.equal(init.method,"POST");assert.equal(init.credentials,"same-origin");assert.deepEqual(JSON.parse(init.body),{proposal_sha256:rule.proposal_sha256});return json(ink);});assert.deepEqual(result,ink);
  await assert.rejects(confirmProjectRule(rule,signal,async()=>new Response("private server detail",{status:409})),/rule changed/);
  await assert.rejects(fetchProject(actual.run_id,actual.snapshot_id,{...firstProjectPage,offset:-1},signal),/Invalid project page/);
});

test("actual ELK layered layout is deterministic and bounded, without a browser or model",async()=>{
  const f=replay.flows[0],items=[{id:f.entry.id,lane:0},...f.guards.map(n=>({id:n.id,lane:1})),...f.data.map(n=>({id:n.id,lane:2}))];
  const elk=new ELK(),a=layoutPositions(await elk.layout(layoutGraph(items)),items),b=layoutPositions(await elk.layout(layoutGraph(items)),items);assert.deepEqual(a,b);assert.equal(a.length,items.length);assert.ok(a.every(n=>Number.isFinite(n.y)&&n.y>=48));
  assert.throws(()=>layoutGraph([...items,...items]),/bounded/);
});

test("layout worker replies are validated and workers terminate on success, invalid reply, timeout and abort",async()=>{
  const items=[{id:"entry:1",lane:0}];
  class Port extends EventTarget{stopped=0;onmessage=null;constructor(reply){super();this.reply=reply;}postMessage(message){if(message.cmd==="register"||this.reply!==undefined)queueMicrotask(()=>this.onmessage?.(new MessageEvent("message",{data:{id:message.id,data:message.cmd==="register"?{}:{children:this.reply}}})));}terminate(){this.stopped++;}}
  for(const [i,reply] of [[{id:"entry:1",x:20,y:0}],[{id:"foreign",x:20,y:0}],undefined].entries()){const port=new Port(reply);const result=await mapPositions(`fixture:reply:${i}`,items,signal,()=>port,30);assert.equal(!!result,reply?.[0]?.id==="entry:1");assert.equal(port.stopped,1);}
  const controller=new AbortController(),port=new Port(undefined);const pending=mapPositions("fixture:abort",items,controller.signal,()=>port);controller.abort();assert.equal(await pending,null);assert.equal(port.stopped,1);
});
