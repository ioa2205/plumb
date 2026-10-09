import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { durationLabel, earlierRun, fetchComparison, fetchHistory, groups, parseComparison, parseHistory } from "../lib/history-data.ts";
const saved=JSON.parse(readFileSync(new URL('./fixtures/run-views.json',import.meta.url),'utf8'));
const views=saved.software_comparisons;
const parse=p=>parseComparison(p,p.before.id,p.after.id,p.group,0,0);
const signal=new AbortController().signal;
const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});

test('actual saved history and separate software comparison preserve identity, scope and four conclusions',()=>{
  assert.deepEqual(parseHistory(saved.actual_history,0),saved.actual_history);
  for(const group of groups){const p=parse(views[group]);assert.equal(p.rows[0].group,group);assert.deepEqual(p.counts,{new:1,still_present:1,no_longer_observed:1,not_reviewed:1});assert.equal(p.after.coverage.excluded,1);}
  assert.equal(views.no_longer_observed.rows[0].after.conclusion,'rejected');
  assert.equal(views.not_reviewed.rows[0].after,null);
  assert.equal(durationLabel(views.new.after),'30.0 s');
  assert.equal(durationLabel({...views.new.after,finished_at:null}),'Ongoing or paused');
  assert.equal(earlierRun('?before='+views.new.before.id,views.new.after.id),views.new.before.id);
  assert.equal(earlierRun('?before='+views.new.before.id,views.new.before.id),null);
  assert.throws(()=>earlierRun('?before=../private',null));
  assert.throws(()=>earlierRun('?before=a&before=b',null));
});

test('forged absence, cross-run source, reversed order and false page counts refuse',()=>{
  for(const change of [p=>p.rows[0].after.conclusion='supported',p=>p.rows[0].before.id='foreign',p=>p.rows[0].after.location.snapshot_id='0'.repeat(64),p=>p.after.created_at='2020-01-01T00:00:00Z',p=>delete p.counts.not_reviewed,p=>p.next_offset=20]){
    const p=structuredClone(views.no_longer_observed);change(p);assert.throws(()=>parseComparison(p,views.new.before.id,views.new.after.id,'no_longer_observed',0,0));
  }
  const history=structuredClone(saved.actual_history);history.runs.push(history.runs[0]);assert.throws(()=>parseHistory(history,0));
});

test('history and comparison use bounded same-origin reads; invalid selectors never reach fetch',async()=>{
  let options;await fetchHistory(0,signal,async(path,init)=>{assert.equal(path,'/api/runs?offset=0');options=init;return json(saved.actual_history);});
  assert.equal(options.credentials,'same-origin');assert.equal(options.redirect,'error');assert.equal(options.cache,'no-store');
  const p=views.new;assert.deepEqual(await fetchComparison(p.before.id,p.after.id,'new',0,0,signal,async(path,init)=>{assert.ok(path.includes('before='+p.before.id));assert.equal(init.credentials,'same-origin');return json(p);}),p);
  const forbidden=()=>{assert.fail('Invalid selector reached transport');};
  await assert.rejects(fetchComparison('../private',p.after.id,'new',0,0,signal,forbidden));
  await assert.rejects(fetchComparison(p.after.id,p.after.id,'new',0,0,signal,forbidden));
  await assert.rejects(fetchHistory(-1,signal,forbidden));
  await assert.rejects(fetchHistory(0,signal,async()=>new Response('private storage detail',{status:503})),error=>!error.message.includes('private storage detail'));
});
