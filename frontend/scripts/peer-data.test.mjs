import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {parseCase,parsePeerExcerpt,fetchPeerExcerpt} from "../lib/case-data.ts";
import {peerCell,peerCitations,peerKinds,validPeer} from "../lib/peer-data.ts";

// Assembled replay: original saved challenge + archived peers, same frozen snapshot/group.
// The projection is software regression input, not a new review or accuracy measurement.
const recorded=JSON.parse(readFileSync(new URL("./fixtures/archived-peer-case.json",import.meta.url),"utf8"));
const clone=x=>structuredClone(x);

test("archived real peer replay keeps original IDs, exclusions and subject-excluding denominator",()=>{
  const detail=parseCase(recorded,recorded.run.id,recorded.finding.id);
  const peer=detail.peer_comparison;
  assert.equal(peer.rows.length,15);assert.equal(peer.group.excluded.length,4);
  const row=peer.rows.find(r=>r.site.id===peer.subject_site_id);
  assert.equal(detail.finding.display_id,"F-02");assert.equal(detail.finding.severity,"unknown");
  const owner=peerCell(peer,row,"owner");
  assert.equal(owner.deviation.peers_applying,10);assert.equal(owner.deviation.peers_total,10);
  assert.match(owner.label,/10 of 10 other compared sites/);
  assert.equal(peerCell(peer,row,"authenticated").state,"Applied");
  for(const kind of ["tenant","role"])assert.equal(peerCell(peer,row,kind).deviation,undefined);
});

test("peer parsing refuses forged membership, sources, guard authority and counts",()=>{
  const mutations=[
    p=>p.finding_id="other",p=>p.question_id="other",p=>p.subject_site_id="other",p=>p.group.id="other",
    p=>p.rows.pop(),p=>p.rows.push(p.rows[0]),p=>p.group.site_ids.reverse(),p=>p.rows[0].entry.id="other",
    p=>p.rows[0].site.resource="other",p=>p.rows[0].entry.span.snapshot_id="0".repeat(64),
    p=>p.rows.find(r=>r.guards.length).guards[0].confirmed=false,
    p=>p.rows.find(r=>r.guards.length).guards[0].mechanism="proxy_matcher",
    p=>p.group.columns[0].applied_site_ids.push(p.group.columns[0].applied_site_ids[0]),
    p=>p.group.deviations[0].peers_total++,p=>p.group.deviations=[],p=>p.group.excluded[0].reason="made up",
    p=>p.rows.find(r=>r.exclusion).evidence=[],
  ];
  for(const mutate of mutations){const changed=clone(recorded);mutate(changed.peer_comparison);assert.throws(()=>parseCase(changed,recorded.run.id,recorded.finding.id));}
});

test("universally absent and unresolved guards never manufacture a peer flag",()=>{
  const detail=clone(recorded);const peer=detail.peer_comparison;
  for(const row of peer.rows){row.guards=[];row.issues=["Recorded classification did not settle this guard"];}peer.group.columns=[];peer.group.deviations=[];
  assert.equal(validPeer(peer,detail.finding),true);
  for(const row of peer.rows)for(const kind of peerKinds){const cell=peerCell(peer,row,kind);assert.equal(cell.deviation,undefined);assert.equal(cell.state,"Unknown in this search");}
  peer.rows[0].issues=[];assert.equal(peerCell(peer,peer.rows[0],"owner").state,"Not recorded in this search");
});

test("peer excerpts bind to the exact saved row and citation, with bounded same-origin reads",async()=>{
  const detail=parseCase(recorded,recorded.run.id,recorded.finding.id);const row=detail.peer_comparison.rows[0];
  const span=peerCitations(row)[0];
  const page={run_id:detail.run.id,finding_id:detail.finding.id,site_id:row.site.id,citation:0,span,
    start_line:span.start_line,end_line:span.start_line,lines:["Fixture source text"],next_offset:span.end_line>span.start_line ? 1 : null,text_is_redacted:true,comments_are_not_evidence:true};
  assert.deepEqual(parsePeerExcerpt(page,detail,row.site.id,0,0),page);
  for(const change of [{site_id:"other"},{citation:1},{finding_id:"other"},{end_line:span.end_line+1},{text_is_redacted:false},{span:{...span,path:"../escape"}},{next_offset:999}])assert.throws(()=>parsePeerExcerpt({...page,...change},detail,row.site.id,0,0));
  const signal=new AbortController().signal;
  await fetchPeerExcerpt(detail,row.site.id,0,0,signal,async(path,options)=>{
    assert.match(path,/\/peers\/access%3A/);assert.equal(options.credentials,"same-origin");assert.equal(options.redirect,"error");return Response.json(page);
  });
  for(const [site,citation,offset] of [["other",0,0],[row.site.id,202,0],[row.site.id,-1,0],[row.site.id,0,-1]])await assert.rejects(fetchPeerExcerpt(detail,site,citation,offset,signal,async()=>assert.fail("uncited source reached network")));
});
