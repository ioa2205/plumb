"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CaseDetail, FindingSchema, SnapshotCodePage } from "../generated/contracts";
import { proofSummary } from "../lib/case-data";
import { Glyph, type GlyphName } from "./Glyph";
import styles from "./CaseFile.module.css";
import { PeerCheck, type PeerSelection } from "./PeerCheck";
import { PeerSource } from "./PeerSource";
import { CodePane } from "./CodePane";
import { ChangeSection } from "./ChangeSection";
import { ProofRecord } from "./ProofRecord";
import { DispositionActions } from "./DispositionActions";

const family={authorization:"Object-level authorization",injection:"Injection",path_traversal:"Path traversal",nextjs_exposure:"Client exposure"};
const conclusionGlyph:Record<FindingSchema.Conclusion,GlyphName>={supported:"dot",rejected:"slash",inconclusive:"half",candidate:"ring"};
const words=(value:string)=>value.replaceAll("_"," ");
const runtime={not_attempted:"Runtime not attempted",unavailable:"Runtime unavailable",inconclusive:"Runtime inconclusive",reproduced:"Reproduced",not_reproduced:"Not reproduced under tested conditions"};
const emptyCodePages:readonly SnapshotCodePage[]=[];
const severityLevel={unknown:0,low:1,medium:2,high:3,critical:4};

/** Props are validated saved records. Code/diffs/claims always remain text nodes. */
export function CaseFile({detail,initialCodePages=emptyCodePages}:{detail:CaseDetail;initialCodePages?:readonly SnapshotCodePage[]}) {
  const f=detail.finding;
  const codeExhibits=f.exhibits.filter(e=>e.role!=="developer_note");
  const [selected,setSelected]=useState(codeExhibits[0]?.tag||"");
  const [peerSelection,setPeerSelection]=useState<PeerSelection|null>(null);
  const [pane,setPane]=useState<"case"|"exhibits">("case");
  const [selectionRevision,setSelectionRevision]=useState(0);
  const origin=useRef<HTMLButtonElement|null>(null);const title=useRef<HTMLHeadingElement>(null);
  const [returning,setReturning]=useState(false);
  useEffect(()=>{if(returning){const target=origin.current?.isConnected?origin.current:title.current;target?.focus();target?.scrollIntoView({block:"nearest"});setReturning(false);}},[returning]);
  const source=useMemo(()=>({tag:selected}),[selected]);
  useEffect(()=>{setSelected(codeExhibits[0]?.tag||"");setPane("case");setPeerSelection(null);setSelectionRevision(0);
  },[f.id]); // eslint-disable-line react-hooks/exhaustive-deps
  function select(tag:string) {setPeerSelection(null);setSelected(tag);setPane("exhibits");setSelectionRevision(n=>n+1);}
  function selectPeer(selection:PeerSelection) {setPeerSelection(selection);setPane("exhibits");setSelectionRevision(n=>n+1);}
  function tag(value:string,fromCase=true) {return <button key={value} className={styles.tag} type="button" onClick={event=>{if(fromCase)origin.current=event.currentTarget;select(value);}} aria-pressed={!peerSelection&&selected===value} aria-label={`Read exhibit ${value}`}>{value}</button>;}
  function cited(text:string) {return text.split(/(\[E\d{2,3}\])/).map((part,index)=>{const value=part.slice(1,-1);return /^\[E\d{2,3}\]$/.test(part)&&codeExhibits.some(e=>e.tag===value) ? <span key={index}>{tag(value)}</span> : part;});}
  const exhibit=codeExhibits.find(e=>e.tag===selected);
  const coverage=detail.run.coverage;
  return <div className={styles.caseFile}>
    <div className={styles.tabs} role="group" aria-label="Case file sections"><button type="button" aria-pressed={pane==="case"} onClick={()=>setPane("case")}>Case</button><button type="button" aria-pressed={pane==="exhibits"} onClick={()=>setPane("exhibits")}>Exhibits ({codeExhibits.length})</button></div>
    <div className={styles.columns} data-pane={pane}>
      <article className={styles.case} aria-labelledby="case-title">
        <p className={styles.eyebrow}>{f.display_id} · {family[f.family]} · {f.cwe.map(c=>`CWE-${c}`).join(" / ")}</p>
        <h1 id="case-title" ref={title} tabIndex={-1}>{f.title}</h1>
        <div className={styles.status}><span><Glyph name={conclusionGlyph[f.conclusion]} />{words(f.conclusion)}</span><span className={f.severity==="high"||f.severity==="critical" ? styles.risk : ""}><span className={styles.gauge} aria-hidden="true">{[1,2,3,4].map(level=><span key={level} data-filled={level<=severityLevel[f.severity]}/>)}</span>Severity: {f.severity}</span><span>{runtime[f.runtime_verification||"not_attempted"]}</span><DispositionActions key={`${detail.run.id}/${f.id}/${detail.disposition_history?.length??0}`} detail={detail}/></div>
        <p className={styles.lede}>{cited(f.lede)}</p>
        <p className={styles.scope}>{coverage ? `${coverage.completed} of ${coverage.total} discovered checks processed · ${coverage.pending} pending · ${coverage.excluded} excluded · ${coverage.unsupported} unsupported.` : "Coverage was not recorded."} This case does not establish whole-project safety.</p>
        <section className={styles.part} aria-labelledby="peer-title" onClickCapture={event=>{if(event.target instanceof Element){const button=event.target.closest("button");if(button)origin.current=button;}}}><h2 id="peer-title">{f.family==="authorization" ? "Peer check" : "Recorded flow"}</h2>
          {f.family==="authorization" ? typeof detail.peer_comparison==="object" ? <PeerCheck key={f.id} peer={detail.peer_comparison} onSelect={selectPeer} /> : <div className={styles.condition}><Glyph name="half" /><div><strong>Peer comparison not recorded</strong><p>The saved report contains the conclusion and searched code. It has no peer rows or comparison denominator.</p>{f.peer_group_id&&<code>{f.peer_group_id}</code>}</div></div> : f.flow?.length ? <ol className={styles.flow}>{f.flow.map((step,i)=><li key={i}>{step.label} {tag(step.exhibit_tag)}</li>)}</ol> : <p>No source-to-sink flow was recorded.</p>}
        </section>
        <section className={styles.part} aria-labelledby="impact-title"><h2 id="impact-title">Impact and evidence</h2><p>{f.severity_rationale}</p><p>Evidence strength: <strong>{f.strength}</strong>.</p><div className={styles.tags}>{codeExhibits.map(e=>tag(e.tag))}</div></section>
        <section className={styles.part} aria-labelledby="looked-title"><h2 id="looked-title">What Plumb looked for</h2>
          {f.checks?.length ? <ul className={styles.checks}>{f.checks.map((check,i)=><li key={i}><Glyph name={check.found ? "dot" : "ring"} /><div><strong>{check.item}</strong><p>{check.found ? "Found in code" : "Not established in this search"}{check.exhibit_tag&&<> · {tag(check.exhibit_tag)}</>}</p><details><summary>Search record</summary><p>{check.searched}</p></details></div></li>)}</ul> : <p>No challenge checklist was recorded.</p>}
        </section>
        <section className={styles.part} aria-labelledby="proof-title"><h2 id="proof-title">Proof</h2>
          {proofSummary(detail)&&<p>{proofSummary(detail)}</p>}
          {detail.probe_runs.length ? detail.probe_runs.map(probe=><ProofRecord key={probe.id} probe={probe} />) : <div className={styles.condition}><Glyph name="half" /><p>No runtime proof is recorded. {runtime[f.runtime_verification||"not_attempted"]}.</p></div>}
        </section>
        <section className={styles.part} aria-labelledby="change-title"><h2 id="change-title">Suggested change</h2><ChangeSection key={detail.suggested_change?.id??f.id} finding={f} change={detail.suggested_change} proposal={detail.proposal} probes={detail.probe_runs} /></section>
        <section className={styles.part} aria-labelledby="unknown-title"><h2 id="unknown-title">Still unknown</h2>{[...(f.gaps||[]),...(f.unknowns||[])].length ? <ul>{[...(f.gaps||[]),...(f.unknowns||[])].map((text,i)=><li key={i}>{text}</li>)}</ul> : <p>No additional unknowns were recorded. The review limitations still apply.</p>}<details><summary>Review limitations ({detail.limitations.length})</summary><ul>{detail.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></details></section>
      </article>
      <section className={styles.exhibits} aria-labelledby="exhibits-title"><header className={styles.exhibitHead}><h2 id="exhibits-title">Exhibits</h2><p>Snapshot <code title={detail.run.snapshot_id}>{detail.run.snapshot_id.slice(0,12)}</code></p></header>
        <button className={styles.action} type="button" onClick={()=>{setPane("case");setReturning(true);}}>Back to citation in case</button>
        <nav className={styles.tags} aria-label="Code exhibits">{codeExhibits.map(e=>tag(e.tag,false))}</nav>
        {peerSelection ? <PeerSource key={`${detail.run.id}/${f.id}/${peerSelection.site}/${peerSelection.citation}/${selectionRevision}`} detail={detail} selection={peerSelection} initialPages={initialCodePages} /> : exhibit ? <CodePane key={`${detail.run.id}/${f.id}/${selected}/${selectionRevision}`} detail={detail} selection={source} label={exhibit.tag} gloss={`${words(exhibit.role)} · ${exhibit.gloss}`} flag={exhibit.role==="deviant"||exhibit.role==="sink"} focus={selectionRevision>0} initialPages={initialCodePages} /> : <p>No code exhibits were recorded.</p>}
      </section>
    </div>
  </div>;
}
