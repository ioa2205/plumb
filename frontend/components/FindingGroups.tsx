"use client";

import type { FindingList } from "../generated/contracts";
import { useRef } from "react";
import { conclusionOrder, emptyFilters, filterOptions, type FindingFilters } from "../lib/finding-list";
import { caseDestination } from "../lib/case-data";
import { Glyph, type GlyphName } from "./Glyph";
import styles from "./SavedFindings.module.css";

const labels={supported:"Supported",inconclusive:"Inconclusive",candidate:"Candidates",rejected:"Rejected"};
const glyphs:Record<keyof typeof labels,GlyphName>={supported:"dot",inconclusive:"half",candidate:"ring",rejected:"slash"};
const filterLabels={family:"Family",severity:"Severity",runtime_verification:"Runtime verification",disposition:"Disposition"};
const level={unknown:0,low:1,medium:2,high:3,critical:4};
const words=(s:string)=>s.replaceAll("_"," ").replace(/^./,c=>c.toUpperCase());
/** The focus target survives while the previous page's controls unmount. */
export function FindingResults({page,onPage}:{page:FindingList|null;onPage:(offset:number)=>void}){
  const title=useRef<HTMLHeadingElement>(null);
  return <section aria-labelledby="finding-results-title"><h2 id="finding-results-title" ref={title} tabIndex={-1}>Finding results</h2>
    {page&&<FindingGroups page={page} onPage={offset=>{title.current?.focus();onPage(offset);}} />}
  </section>;
}
export function FindingFiltersBar({filters,onChange}:{filters:FindingFilters;onChange:(filters:FindingFilters)=>void}){
  return <div className={styles.filters}>{(Object.keys(filterLabels) as (keyof FindingFilters)[]).map(key=><label key={key}>{filterLabels[key]}<select value={filters[key]} onChange={event=>onChange({...filters,[key]:event.target.value})}><option value="">All</option>{filterOptions[key].map(value=><option key={value} value={value}>{words(value)}</option>)}</select></label>)}<button className={styles.action} onClick={()=>onChange(emptyFilters)}>Clear filters</button></div>;
}
export function FindingGroups({page,onPage}:{page:FindingList;onPage?:(offset:number)=>void}){
  function rows(conclusion:keyof typeof labels){const findings=page.findings.filter(f=>f.conclusion===conclusion);return findings.length?<ul className={styles.list}>{findings.map(f=><li key={f.id}><a href={caseDestination(page.run.id,f.id)}>
    <span className={styles.identity}><Glyph name={glyphs[f.conclusion]} /><code>{f.display_id}</code><span>{labels[f.conclusion]}</span></span><strong>{f.title}</strong>
    <span className={styles.status} data-risk={f.severity==="high"||f.severity==="critical"}><span className={styles.gauge} data-unknown={f.severity==="unknown"} aria-hidden="true">{[1,2,3,4].map(tick=><i key={tick} data-active={tick<=level[f.severity]}/>)}</span>{words(f.severity)} severity · {f.runtime_verification==="not_reproduced"?"Not reproduced under tested conditions":words(f.runtime_verification)} · {words(f.disposition)}</span>
    <code>{f.location?`${f.location.path}:${f.location.start_line}`:"No primary location recorded"}</code>
  </a></li>)}</ul>:<p className={styles.scope}>{page.counts[conclusion]?"No cases in this group on this page.":"No cases match this group."}</p>;}
  return <>
    <p role="status">{page.total} of {page.run.finding_ids?.length??0} recorded cases match. {page.findings.length?`Showing ${page.offset+1}–${page.offset+page.findings.length}.`:""}</p>
    {conclusionOrder.map(conclusion=>conclusion==="rejected"?<details className={styles.group} key={conclusion}><summary><Glyph name="slash" /> Rejected ({page.counts.rejected})</summary><p className={styles.scope}>Rejected lookalikes remain part of the investigation. Open a case to read its cited protection.</p>{rows(conclusion)}</details>:<section className={styles.group} key={conclusion} aria-labelledby={`group-${conclusion}`}><h3 id={`group-${conclusion}`}><Glyph name={glyphs[conclusion]} /> {labels[conclusion]} ({page.counts[conclusion]})</h3>{rows(conclusion)}</section>)}
    {onPage&&<div className={styles.paging}><button className={styles.action} aria-disabled={page.offset===0} onClick={()=>{if(page.offset>0)onPage(Math.max(0,page.offset-20));}}>Previous findings</button><button className={styles.action} aria-disabled={page.next_offset===null} onClick={()=>{if(page.next_offset!==null)onPage(page.next_offset);}}>Next findings</button></div>}
    {!page.total&&<p>No matching finding records. This does not establish that the project is safe.</p>}
    {!page.supplementary&&<p className={styles.scope}>Supplementary security signals were not recorded for this saved run.</p>}
    {page.supplementary&&<section className={styles.group} aria-labelledby="supplementary-signals"><h3 id="supplementary-signals">Supplementary security signals ({page.supplementary.signals?.length??0})</h3>
      <p className={styles.scope}>Status: {words(page.supplementary.status)}. Observations are separate from challenged findings and coverage. Version exposure does not establish exploitability.</p>
      <p className={styles.scope}>Advisory snapshot: {page.supplementary.pack_date??"Unavailable"} · {page.supplementary.pack_source??"No source recorded"}</p>
      <details><summary>Signal provenance</summary><p>Rules: {page.supplementary.tool_version}</p><code>{page.supplementary.pack_sha256??"No advisory pack used"}</code></details>
      <ul>{page.supplementary.signals?.map(s=><li key={s.id}><strong>{words(s.category)} · {words(s.status)}</strong><p>{s.summary}</p><code>{s.source.path}:{s.source.start_line}–{s.source.end_line}</code>
        {s.package&&<p>{s.ecosystem}: {s.package} · {s.version??"Unknown version"}{s.advisory_id&&` · ${s.advisory_id}`}</p>}
        <details><summary>Rule and limitations</summary><code>{s.rule_id} · {s.rule_version}</code>{s.fingerprint&&<p>Redacted fingerprint: <code>{s.fingerprint}</code></p>}<ul>{s.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></details>
      </li>)}</ul><details><summary>Signal scope and limitations</summary><ul>{page.supplementary.limitations?.map((text,i)=><li key={i}>{text}</li>)}</ul></details>
    </section>}
    <details className={styles.group}><summary>Review limitations ({page.limitations.length})</summary><ul>{page.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></details>
  </>;
}
