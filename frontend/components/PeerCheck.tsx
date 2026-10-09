"use client";

import { useState } from "react";
import { peerCell, peerKinds, peerLabels, peerRoute, type PeerComparison, type PeerKind, type PeerRow } from "../lib/peer-data";
import { Glyph } from "./Glyph";
import styles from "./PeerCheck.module.css";

export type PeerSelection={site:string;citation:number;label:string};
const pathParts=(path:string)=>path.split("/").map((part,i)=><span key={i}>{i>0&&<>/<wbr /></>}{part}</span>);

export function PeerCheck({peer,onSelect}:{peer:PeerComparison;onSelect:(selection:PeerSelection)=>void}) {
  const [count,setCount]=useState(20);const [cell,setCell]=useState<{site:string;kind:PeerKind}|null>(null);
  const voters=peer.rows.filter(r=>r.exclusion==null);const excluded=peer.rows.filter(r=>r.exclusion!=null);
  const subject=peer.rows.find(r=>r.site.id===peer.subject_site_id)!;
  const subjectGaps=peer.group.deviations?.filter(d=>d.site_id===subject.site.id)||[];
  const selected=cell ? peer.rows.find(r=>r.site.id===cell.site) : undefined;
  const observation=selected&&cell ? peerCell(peer,selected,cell.kind) : undefined;
  function select(row:PeerRow,citation:number,label:string) {onSelect({site:row.site.id,citation,label});}
  function inspect(row:PeerRow,kind:PeerKind) {
    setCell({site:row.site.id,kind});const observed=peerCell(peer,row,kind);
    const citation=observed.guards[0]?.citation ?? (row.evidence?.length ? 2+(row.guards?.length||0) : 1);
    select(row,citation,`${peerLabels[kind]} · ${observed.state}`);
  }
  const absent=peerKinds.filter(k=>!peer.group.columns.some(c=>c.key===k));
  return <div className={styles.peerCheck}>
    <p className={styles.claim}>{peer.group.resource} is accessed at {peer.rows.length} recorded sites. {voters.length} are compared; {excluded.length} are excluded.</p>
    {subject.exclusion!=null ? <p>This route is excluded: {subject.exclusion}.</p> : subjectGaps.length ? <p className={styles.lead}>{subjectGaps.map(d=><span key={d.missing}>{peerLabels[d.missing as PeerKind]} is not recorded here; {d.peers_applying} of {d.peers_total} other compared sites apply it. </span>)}<span>A comparison lead; the finding and proof above retain their own status.</span></p> : <p>This route has no recorded peer deviation. Its recorded guards and the review limitations are shown below.</p>}
    <table className={styles.matrix}>
      <caption>{peer.group.resource} · guard observations in the saved snapshot</caption>
      <thead><tr><th scope="col">Access site</th>{peerKinds.map(kind=><th scope="col" key={kind}>{kind==="role" ? "Role check" : peerLabels[kind]}</th>)}</tr></thead>
      <tbody>{voters.slice(0,count).map(row=>{
        const deviant=peer.group.deviations?.some(d=>d.site_id===row.site.id);
        return <tr key={row.site.id} className={deviant ? styles.deviant : ""}>
          <th scope="row"><button type="button" className={styles.site} onClick={()=>select(row,0,"Resource access")} aria-label={`Read resource access: ${peerRoute(row)}`}><span>{row.entry.method||row.entry.kind.replaceAll("_"," ")}</span> {pathParts(row.entry.route||row.entry.handler_symbol_id)}<span className={styles.where}>{row.site.span.path}:{row.site.span.start_line}</span></button>{row.site.id===subject.site.id&&<span className={styles.thisRoute}>This route</span>}</th>
          {peerKinds.map(kind=>{const item=peerCell(peer,row,kind);return <td key={kind}><button type="button" className={styles.cell} aria-label={`${peerRoute(row)} · ${peerLabels[kind]}: ${item.label}. Read recorded search and code.`} aria-pressed={cell?.site===row.site.id&&cell.kind===kind} onClick={()=>inspect(row,kind)}><Glyph name={item.guards.length ? "dot" : row.issues?.length ? "half" : "ring"} />{item.deviation&&<svg className={styles.mark} viewBox="0 0 46 30" aria-hidden="true"><path d="M27 4.2C17 2.6 5.4 6.4 4.3 14.6 3.3 22.3 14.2 27 25 25.9c10.4-1 17.2-6.3 16.7-12.6C41.2 6.6 31.7 2.4 20.6 4.1" /></svg>}</button></td>;})}
        </tr>;
      })}</tbody>
    </table>
    <p className={styles.note}>● Applied · ○ Not recorded in this search · ◐ Unknown. Select a route or guard to read its saved code.</p>
    {count<voters.length&&<button className={styles.action} type="button" onClick={()=>setCount(n=>n+20)}>Show next compared sites ({Math.min(20,voters.length-count)} of {voters.length-count} remaining)</button>}
    {selected&&cell&&observation&&<section className={styles.search} aria-label="Selected guard search"><p role="status"><strong>{peerRoute(selected)} · {peerLabels[cell.kind]}</strong><br />{observation.label}</p>
      {observation.guards.length ? observation.guards.map(({guard,citation})=><p key={guard.id}><button className={styles.action} type="button" onClick={()=>select(selected,citation,`${peerLabels[cell.kind]} · Applied`)}>Read guard: {guard.span.path}:{guard.span.start_line}</button><code>{guard.canonical}</code></p>) : <p>No confirmed guard of this kind was recorded for this site. This search does not prove that no protection exists.</p>}
      {!!selected.issues?.length&&<ul>{selected.issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul>}
      {selected.evidence?.map((span,i)=><button className={styles.action} type="button" key={i} onClick={()=>select(selected,2+(selected.guards?.length||0)+i,"Recorded search evidence")}>Read search evidence: {span.path}:{span.start_line}</button>)}
    </section>}
    <p className={styles.note}>A missing guard becomes a lead only when at least {peer.group.min_peers??3} other sites and {(peer.group.min_share??.75)*100}% of the other compared sites apply it. Each denominator excludes the site being checked and all excluded sites.</p>
    {!!absent.length&&<p className={styles.note}>{absent.map(k=>peerLabels[k]).join(", ")}: no compared site has a recorded guard of these kinds, so their absence is not a peer lead.</p>}
    {!!excluded.length&&<details className={styles.exclusions}><summary>Excluded sites ({excluded.length}) and cited reasons</summary><ul>{excluded.map(row=><li key={row.site.id}><strong>{peerRoute(row)}</strong><p>{row.exclusion}</p>{row.evidence?.map((span,i)=><button type="button" className={styles.action} key={i} onClick={()=>select(row,2+(row.guards?.length||0)+i,"Recorded exclusion evidence")}>Read exclusion: {span.path}:{span.start_line}</button>)}</li>)}</ul></details>}
    {!!peer.limitations?.length&&<details className={styles.exclusions}><summary>Peer check limitations ({peer.limitations.length})</summary><ul>{peer.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></details>}
  </div>;
}
