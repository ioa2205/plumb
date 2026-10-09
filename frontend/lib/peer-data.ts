import type { CaseDetailSchema, Finding } from "../generated/contracts";

export type PeerComparison=CaseDetailSchema.PeerComparison;
export type PeerRow=CaseDetailSchema.PeerRow;
export type PeerSpan=CaseDetailSchema.SourceSpan;
export const peerKinds=["authenticated","owner","tenant","role"] as const;
export type PeerKind=typeof peerKinds[number];
export const peerLabels:Record<PeerKind,string>={authenticated:"Signed in",owner:"Owner check",tenant:"Tenant scope",role:"Required role"};
const same=(a:readonly unknown[],b:readonly unknown[])=>a.length===b.length&&a.every((v,i)=>v===b[i]);
const unique=(a:readonly string[])=>new Set(a).size===a.length;
export function peerCitations(row:PeerRow):readonly PeerSpan[] {
  return [row.site.span,row.entry.span,...(row.guards||[]).map(g=>g.span),...(row.evidence||[])];
}
export function peerRoute(row:PeerRow):string {
  return `${row.entry.method||row.entry.kind.replaceAll("_"," ")} ${row.entry.route||row.entry.handler_symbol_id}`;
}
export function peerCell(peer:PeerComparison,row:PeerRow,kind:PeerKind) {
  const guards=(row.guards||[]).map((guard,index)=>({guard,citation:index+2})).filter(x=>x.guard.kind===kind);
  const deviation=peer.group.deviations?.find(d=>d.site_id===row.site.id&&d.missing===kind);
  const state=guards.length ? "Applied" : row.issues?.length ? "Unknown in this search" : "Not recorded in this search";
  return {guards,deviation,state,label:deviation ? `${state}; ${deviation.peers_applying} of ${deviation.peers_total} other compared sites apply it` : state};
}

/** Presentation consistency only. Source validation and recorded judgments stay on the backend. */
export function validPeer(peer:PeerComparison,finding:Finding):boolean {
  const group=peer.group;const rows=peer.rows;const ids=rows.map(r=>r.site.id);
  if(peer.finding_id!==finding.id||!finding.question_ids?.includes(peer.question_id)||group.id!==finding.peer_group_id
    ||group.snapshot_id!==finding.snapshot_id||!unique(ids)||!same(ids,group.site_ids)||!ids.includes(peer.subject_site_id))return false;
  const seen=new Map<string,string>();
  for(const row of rows) {
    const guards=row.guards||[];
    if(row.site.snapshot_id!==group.snapshot_id||row.site.resource!==group.resource||row.site.entry_point_id!==row.entry.id
      ||row.entry.snapshot_id!==group.snapshot_id||peerCitations(row).some(s=>s.snapshot_id!==group.snapshot_id||s.end_line<s.start_line)
      ||!unique(guards.map(g=>g.id))||guards.some(g=>!g.confirmed||g.mechanism==="proxy_matcher"||!peerKinds.some(k=>k===g.kind)||g.snapshot_id!==group.snapshot_id)
      ||(row.exclusion!=null&&(!row.exclusion.trim()||!row.evidence?.length)))return false;
    for(const guard of guards) {
      const value=JSON.stringify(guard);if(seen.has(guard.id)&&seen.get(guard.id)!==value)return false;seen.set(guard.id,value);
    }
  }
  const excluded=group.excluded||[];
  if(!unique(excluded.map(e=>e.site_id))||excluded.length!==rows.filter(r=>r.exclusion!=null).length
    ||excluded.some(e=>rows.find(r=>r.site.id===e.site_id)?.exclusion!==e.reason))return false;
  const voters=rows.filter(r=>r.exclusion==null);
  const columns=peerKinds.map(kind=>({kind,ids:voters.filter(r=>r.guards?.some(g=>g.kind===kind)).map(r=>r.site.id)})).filter(c=>c.ids.length);
  if(!unique(group.columns.map(c=>c.key))||group.columns.length!==columns.length
    ||columns.some(c=>!same(c.ids,group.columns.find(x=>x.key===c.kind)?.applied_site_ids||[])))return false;
  const expected=columns.flatMap(c=>voters.filter(r=>!c.ids.includes(r.site.id)&&voters.length>1
    &&c.ids.length>=(group.min_peers??3)&&c.ids.length/(voters.length-1)>=(group.min_share??.75))
    .map(r=>({site:r.site.id,key:c.kind,applying:c.ids.length,total:voters.length-1})));
  const deviations=group.deviations||[];
  return expected.length===deviations.length&&unique(deviations.map(d=>`${d.site_id}/${d.missing}`))
    &&expected.every(e=>deviations.some(d=>d.site_id===e.site&&d.missing===e.key&&d.peers_applying===e.applying&&d.peers_total===e.total));
}
