import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {parseCase,MAX_CASE_BYTES} from "../lib/case-data.ts";
import {copyCodeText,defaultCodeWindow,fetchCodePage,parseCodePage,readCitedText,selectedSpan} from "../lib/code-data.ts";
import {peerCitations} from "../lib/peer-data.ts";

// Actual frozen-source pages of a saved case/archived peer replay. No fresh accuracy claim.
const fixture=name=>JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`,import.meta.url),"utf8"));
const recorded=fixture("archived-peer-case");
const detail=parseCase(recorded,recorded.run.id,recorded.finding.id);
const pages=fixture("code-pages");const excerpts=fixture("recorded-excerpts");
const page=pages.find(p=>p.citation.start_line===detail.finding.exhibits[0].span.start_line&&p.mode==="context"&&p.before===3&&p.after===3);
const windowFor=p=>({mode:p.mode,before:p.before,after:p.after,offset:p.offset});

test("actual frozen pages preserve original citations apart from context and file pages",()=>{
  for(const p of pages){
    const exhibit=detail.finding.exhibits.find(e=>JSON.stringify(e.span)===JSON.stringify(p.citation));
    let selection;
    if(exhibit)selection={tag:exhibit.tag};
    else for(const row of detail.peer_comparison.rows){const i=peerCitations(row).findIndex(s=>JSON.stringify(s)===JSON.stringify(p.citation));if(i>=0){selection={site:row.site.id,citation:i};break;}}
    assert.ok(selection);assert.deepEqual(parseCodePage(p,detail,selection,windowFor(p)),p);
  }
  assert.equal(page.range_start,page.citation.start_line-3);assert.equal(page.range_end,page.citation.end_line+3);
  const files=pages.filter(p=>p.mode==="file");assert.equal(files.length,3);
  assert.deepEqual(files.map(p=>[p.start_line,p.end_line]),[[1,80],[81,160],[161,179]]);
  const excerpt=excerpts.find(e=>e.exhibit.tag==="E01");
  assert.deepEqual(page.lines.slice(excerpt.start_line-page.start_line,excerpt.end_line-page.start_line+1),excerpt.lines);
});

test("corrupt ranges, selectors, safety flags and changed file identity refuse",()=>{
  const mutations=[
    p=>p.run_id="other",p=>p.finding_id="other",p=>p.citation.snapshot_id="0".repeat(64),
    p=>p.citation.path="../escape",p=>p.citation.content_sha256="0".repeat(64),p=>p.citation.start_line++,
    p=>p.range_start++,p=>p.range_end++,p=>p.start_line++,p=>p.end_line--,p=>p.lines.pop(),p=>p.next_offset=99,
    p=>p.mode="file",p=>p.before++,p=>p.offset++,p=>p.text_is_redacted=false,p=>delete p.text_is_redacted,
    p=>delete p.comments_are_not_evidence,p=>delete p.context_is_not_evidence,p=>p.extra="private",
  ];
  for(const mutate of mutations){const changed=structuredClone(page);mutate(changed);assert.throws(()=>parseCodePage(changed,detail,{tag:"E01"},defaultCodeWindow));}
  for(const change of [{file_sha256:"0".repeat(64)},{file_line_count:180},{language:"typescript"}])assert.throws(()=>parseCodePage({...page,...change},detail,{tag:"E01"},defaultCodeWindow,page));
  assert.throws(()=>parseCodePage(page,detail,{tag:"E99"},defaultCodeWindow));
  assert.throws(()=>parseCodePage(page,detail,{tag:"E01"},{...defaultCodeWindow,offset:-1}));
  assert.throws(()=>parseCodePage(page,detail,{tag:"E01"},{...defaultCodeWindow,before:81}));
  assert.equal(selectedSpan(detail,{site:"absent",citation:0}),undefined);
});

test("code transport is bounded, same-origin, selector-only and refuses invalid requests before fetch",async()=>{
  const signal=new AbortController().signal;
  assert.deepEqual(await fetchCodePage(detail,{tag:"E01"},defaultCodeWindow,signal,undefined,async(path,options)=>{
    assert.equal(path,`/api/runs/${detail.run.id}/findings/${encodeURIComponent(detail.finding.id)}/exhibits/E01/code?mode=context&before=3&after=3&offset=0&lines=80`);
    assert.equal(options.credentials,"same-origin");assert.equal(options.redirect,"error");assert.equal(options.cache,"no-store");return Response.json(page);
  }),page);
  for(const status of [401,403,404,503])await assert.rejects(fetchCodePage(detail,{tag:"E01"},defaultCodeWindow,signal,undefined,async()=>new Response("private storage error",{status})),error=>!error.message.includes("private storage"));
  await assert.rejects(fetchCodePage(detail,{tag:"E01"},defaultCodeWindow,signal,undefined,async()=>new Response("x".repeat(MAX_CASE_BYTES+1),{headers:{"content-type":"application/json"}})),/too large/);
  const forbidden=async()=>assert.fail("invalid code selector reached fetch");
  for(const selection of [{tag:"../escape"},{site:"other",citation:0},{site:detail.peer_comparison.rows[0].site.id,citation:-1}])await assert.rejects(fetchCodePage(detail,selection,defaultCodeWindow,signal,undefined,forbidden));
  await assert.rejects(fetchCodePage(detail,{tag:"E01"},{mode:"file",before:3,after:3,offset:0},signal,undefined,forbidden));
});

test("copy reads only the complete citation, refuses later identity changes and limits memory",async()=>{
  const signal=new AbortController().signal;const excerpt=excerpts.find(e=>e.exhibit.tag==="E01");
  const exact={...page,before:0,after:0,range_start:page.citation.start_line,range_end:page.citation.end_line,start_line:page.citation.start_line,end_line:page.citation.end_line,lines:excerpt.lines};
  assert.equal(await readCitedText(detail,{tag:"E01"},signal,page,async()=>Response.json(exact)),excerpt.lines.join("\n"));
  // Synthetic long-citation transport fixture, not model evidence.
  const large=structuredClone(detail);large.finding.exhibits[0].span.end_line=page.citation.start_line+100;
  const start=large.finding.exhibits[0].span.start_line;
  const first={...page,citation:large.finding.exhibits[0].span,before:0,after:0,range_start:start,range_end:start+100,start_line:start,end_line:start+79,lines:Array(80).fill("source"),next_offset:80,file_line_count:start+150};
  const last={...first,offset:80,start_line:start+80,end_line:start+100,lines:Array(21).fill("tail"),next_offset:null};
  let requests=0;assert.equal((await readCitedText(large,{tag:"E01"},signal,undefined,async()=>Response.json(requests++ ? last : first))).split("\n").length,101);
  requests=0;await assert.rejects(readCitedText(large,{tag:"E01"},signal,undefined,async()=>Response.json(requests++ ? {...last,file_sha256:"0".repeat(64)} : first)),/frozen citation/);
  const oversized={...first,lines:Array(80).fill("x".repeat(3300))};requests=0;
  await assert.rejects(readCitedText(large,{tag:"E01"},signal,undefined,async()=>Response.json(requests++ ? {...last,lines:Array(21).fill("x".repeat(13000))} : oversized)),/too large to copy/);
});

test("clipboard reports success only after write, with a selectable fallback on refusal",async()=>{
  let copied="";await copyCodeText("literal <script> redacted",{writeText:async text=>{copied=text;}});assert.equal(copied,"literal <script> redacted");
  await assert.rejects(copyCodeText("source",undefined),/Select the text below/);
  await assert.rejects(copyCodeText("source",{writeText:async()=>{throw Error("private clipboard details");}}),error=>error.message.includes("Select the text below")&&!error.message.includes("private"));
});
