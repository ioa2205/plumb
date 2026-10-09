import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash} from "node:crypto";
import {changeState,diffPage,diffTone,validChangeEvidence} from "../lib/change-data.ts";
import {probeOutcome,proofAnchor} from "../lib/proof-data.ts";
import {parseCase} from "../lib/case-data.ts";
const fixture=JSON.parse(readFileSync(new URL('./fixtures/recorded-change.json',import.meta.url),'utf8'));
const legacy=JSON.parse(readFileSync(new URL('./fixtures/recorded-case.json',import.meta.url),'utf8'));
const clone=x=>structuredClone(x);
const context=r=>({id:r.change.finding_id,snapshot_id:r.before.snapshot_id,probe_run_ids:[r.before.id],suggested_change_id:r.change.id});
const probes=r=>[r.before,r.after];

test("frozen proposals retain exact case links, scope and unavailable regression reasons",()=>{
  const detail=clone(legacy),f=detail.finding;
  detail.probe_runs=[];f.probe_run_ids=[];f.runtime_verification="not_attempted";f.suggested_change_id="change:software-proposal";
  const source=f.exhibits[0].span;
  const line={...source,end_line:source.start_line};
  const change={id:f.suggested_change_id,finding_id:f.id,intent:"Restore the required guard.",diff:"--- a/api/routes/orders.py\n+++ b/api/routes/orders.py\n@@ -1 +1 @@\n-old\n+new\n",files:[source.path],status:"proposed",replay_probe_run_ids:[],snapshot_id:f.snapshot_id,source_scope:source,source_edits:[{source:line,file_sha256:"a".repeat(64),action:"replace",code:"    return checked"}]};
  detail.suggested_change=change;
  detail.proposal={id:"proposal:software",finding_id:f.id,snapshot_id:f.snapshot_id,status:"proposed",reason:"Not applied or proven to fix.",change,probe_status:"unavailable",probe_reason:"Missing explicit fixture/principal mapping.",probe_spec:null,adapter_manifest_sha256:null};
  assert.equal(parseCase(detail,detail.run.id,f.id).proposal.probe_status,"unavailable");
  for(const mutate of [d=>d.proposal.snapshot_id="0".repeat(64),d=>d.proposal.change={...d.proposal.change,diff:d.proposal.change.diff+"changed"},d=>d.proposal.probe_status="available",d=>d.suggested_change.source_edits[0].source.start_line=9999]){const bad=clone(detail);mutate(bad);assert.throws(()=>parseCase(bad,detail.run.id,f.id));}
  const component=readFileSync(new URL("../components/ChangeSection.tsx",import.meta.url),"utf8");
  assert.match(component,/not executed/);assert.match(component,/proposal.probe_reason/);
});

test("both actual archived standalone replays retain their original IDs, source and fixed observations",()=>{
  const bytes=readFileSync(new URL('../../'+fixture.source_record,import.meta.url));
  assert.equal(createHash('sha256').update(bytes).digest('hex'),fixture.source_sha256);
  const originals=JSON.parse(bytes).calls.filter(c=>c.manifest.replay).map(c=>c.manifest.replay);
  fixture.replays.forEach((r,i)=>{
    assert.deepEqual(r,{change:originals[i].change,before:originals[i].before,after:originals[i].after});
    assert.equal(validChangeEvidence(context(r),r.change,probes(r)),true);
    assert.equal(probeOutcome(r.before),'reproduced');assert.equal(probeOutcome(r.after),'fixed');
    assert.equal(changeState(r.change).title,'Fixed in disposable replay');
    assert.equal(r.after.steps.find(s=>s.role==='attack').status,404);
    assert.equal(r.after.steps.find(s=>s.role==='control').marker_present,true);
  });
  assert.equal(parseCase(legacy,legacy.run.id,legacy.finding.id).suggested_change,null,'standalone replay is not attached to the older F-02 case');
});

test("explicit software states distinguish unrun suggestions, continued exposure and inconclusive replays",()=>{
  const r=clone(fixture.replays[0]);const f=context(r);
  const proposed={...r.change,status:'proposed',replay_probe_run_ids:[]};
  assert.equal(validChangeEvidence(f,proposed,[r.before]),true);
  assert.match(changeState(proposed).title,/not applied/);assert.match(changeState(proposed).explanation,/No patched-snapshot replay/);
  const notFixed=clone(r);notFixed.change.status='replayed_not_fixed';notFixed.after.steps.find(s=>s.role==='attack').status=200;notFixed.after.steps.find(s=>s.role==='attack').marker_present=true;notFixed.after.outcome='not_fixed';
  assert.equal(validChangeEvidence(context(notFixed),notFixed.change,probes(notFixed)),true);assert.equal(changeState(notFixed.change).tone,'risk');
  for(const failure of ['timeout','server','control','missing-attack']){
    const failed=clone(r);failed.change.status='replay_failed';const attack=failed.after.steps.find(s=>s.role==='attack'),control=failed.after.steps.find(s=>s.role==='control');
    if(failure==='timeout'){attack.status=null;attack.marker_present=null;attack.error='Software fixture timeout';}
    if(failure==='server'){attack.status=500;attack.marker_present=false;}
    if(failure==='control'){control.status=403;control.marker_present=false;}
    if(failure==='missing-attack')failed.after.steps=failed.after.steps.filter(s=>s.role!=='attack');
    failed.after.outcome='inconclusive';assert.equal(probeOutcome(failed.after),'inconclusive');
    assert.equal(validChangeEvidence(context(failed),failed.change,probes(failed)),true);assert.equal(changeState(failed.change).tone,'attention');
    failed.change.status='replayed_fixed';assert.equal(validChangeEvidence(context(failed),failed.change,probes(failed)),false);
  }
});

test("association, status, snapshot, runner and outcome corruption cannot establish a fix",()=>{
  for(const mutate of [
    r=>r.change.finding_id='finding:other',r=>r.change.id='change:other',r=>r.change.status='invented',r=>r.change.extra='outside',
    r=>r.change.diff='not a unified diff',r=>r.change.replay_probe_run_ids=[],r=>r.change.replay_probe_run_ids.push(r.after.id),r=>r.change.replay_probe_run_ids=[r.before.id],
    r=>r.after.finding_id='finding:other',r=>r.after.id=r.before.id,r=>r.after.snapshot_role='vulnerable',r=>r.after.snapshot_id=r.before.snapshot_id,
    r=>r.after.outcome='not_fixed',r=>r.after.runner='docker',r=>r.after.runner_manifest_sha256='b'.repeat(64),r=>r.after.started_at=r.before.started_at,
    r=>r.before.steps.find(s=>s.role==='control').marker_present=false,r=>r.after.steps.find(s=>s.role==='attack').expected_if_safe='allowed',
    r=>r.after.finished_at='invalid-date',r=>r.after.finished_at=r.before.started_at,
    r=>r.change.status='proposed',r=>r.change.status='replayed_not_fixed',r=>r.change.status='replay_failed',
  ]){const r=clone(fixture.replays[0]);mutate(r);assert.equal(validChangeEvidence(context(fixture.replays[0]),r.change,probes(r)),false);}
  const r=fixture.replays[0];assert.equal(validChangeEvidence(context(r),r.change,[r.before]),false);
  assert.equal(validChangeEvidence(context(r),null,probes(r)),false);
  assert.equal(validChangeEvidence({...context(r),suggested_change_id:null},null,[r.before]),true);
  const hostile=clone(legacy);hostile.probe_runs[0].steps.find(s=>s.role==='control').marker_present=false;
  assert.throws(()=>parseCase(hostile,legacy.run.id,legacy.finding.id),/evidence links/);
  assert.equal(proofAnchor(r.after.id),`proof-${r.after.id}`);
});

test("diff pagination preserves literal text and keeps additions and deletions distinct from headers",()=>{
  const original=fixture.replays[0].change.diff;
  assert.deepEqual(diffPage(original,0).lines,original.split('\n'));
  const large=Array.from({length:181},(_,i)=>i===90?'+literal <script>':` line ${i}`).join('\n');let offset=0,lines=[];
  while(true){const page=diffPage(large,offset);assert.ok(page.lines.length<=80);lines.push(...page.lines);if(page.next===null)break;offset=page.next;}
  assert.equal(lines.join('\n'),large);
  assert.equal(diffTone('--- a/x'),'context');assert.equal(diffTone('+++ b/x'),'context');
  assert.equal(diffTone('--decrement'),'deletion');assert.equal(diffTone('++increment'),'addition');assert.equal(diffTone('+literal <img>'),'addition');
  for(const bad of [-1,1.5,182])assert.throws(()=>diffPage(large,bad));
});

test("production case parsing accepts a labeled software proposal and rejects patched-proof corruption",()=>{
  // Software integration fixture only; it does not attach the standalone actual replay.
  const value=clone(legacy),proposal={...fixture.replays[0].change,id:'fixture:proposal',finding_id:value.finding.id,status:'proposed',replay_probe_run_ids:[]};
  value.finding.suggested_change_id=proposal.id;value.suggested_change=proposal;
  assert.equal(parseCase(value,value.run.id,value.finding.id).suggested_change.id,proposal.id);
  for(const changes of [{status:'replayed_fixed'},{replay_probe_run_ids:['fixture:missing']},{finding_id:'fixture:other'}]){
    const bad={...value,suggested_change:{...proposal,...changes}};assert.throws(()=>parseCase(bad,value.run.id,value.finding.id));
  }
});

test("a refused general proposal coexists with a separately validated bundled change",()=>{
  const value=clone(legacy),change={...fixture.replays[0].change,id:"fixture:bundled",finding_id:value.finding.id,status:"proposed",replay_probe_run_ids:[]};
  value.finding.suggested_change_id=change.id;value.suggested_change=change;
  value.proposal={id:"proposal:refused",finding_id:value.finding.id,snapshot_id:value.finding.snapshot_id,status:"refused",reason:"Invalid fixture answer",change:null,probe_status:"unavailable",probe_reason:"No general proposal",probe_spec:null,adapter_manifest_sha256:null};
  assert.equal(parseCase(value,value.run.id,value.finding.id).proposal.status,"refused");
  for(const update of [{finding_id:"other"},{snapshot_id:"a".repeat(64)},{change,status:"refused"}]){
    const bad=clone(value);Object.assign(bad.proposal,update);
    assert.throws(()=>parseCase(bad,value.run.id,value.finding.id));
  }
});
