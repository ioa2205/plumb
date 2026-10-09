"use client";

import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { ProjectExcerpt, ProjectPage, ProjectRule, PolicyInput } from "../generated/contracts";
import type { ProjectCitation, ProjectFlow } from "../lib/project-data";
import { confirmProjectRule, declareProjectRule, fetchProject, fetchProjectExcerpt, firstProjectPage, parseProjectExcerpt, type ProjectOffsets } from "../lib/project-data";
import { Sheet, useSelectedRun } from "./Workbench";
import styles from "./ProjectPanel.module.css";
import { SetupPanel } from "./SetupPanel";
import { CapabilityTable } from "./CapabilityTable";
const MapView=lazy(()=>import("./ProjectMap").then(m=>({default:m.ProjectMap})));

export function ProjectPanel(){const {id,selectionRevision}=useSelectedRun();return <ProjectSession key={`${id}:${selectionRevision}`} />;}
function ProjectSession(){
  const {id,run}=useSelectedRun();const [page,setPage]=useState<ProjectPage|null>(null);const [offsets,setOffsets]=useState(firstProjectPage);const [revision,setRevision]=useState(0);
  const [message,setMessage]=useState("");const [busy,setBusy]=useState(false);const [sending,setSending]=useState<string|null>(null);const mutation=useRef<AbortController|null>(null);
  useEffect(()=>()=>mutation.current?.abort(),[]);
  useEffect(()=>{if(!id||!run)return;const controller=new AbortController();let active=true;const timer=setTimeout(()=>controller.abort(),15000);setBusy(true);setMessage("");
    fetchProject(id,run.snapshot_id,offsets,controller.signal).then(value=>{if(active)setPage(value);}).catch(error=>{if(active)setMessage(controller.signal.aborted?"The project lookup timed out. Try again.":error instanceof Error?error.message:"The project record is unavailable.");}).finally(()=>{clearTimeout(timer);if(active)setBusy(false);});
    return()=>{active=false;controller.abort();clearTimeout(timer);};
  },[id,run?.snapshot_id,offsets,revision]);
  async function confirm(rule:ProjectRule){
    if(sending)return;const controller=new AbortController();mutation.current=controller;const timer=setTimeout(()=>controller.abort(),15000);setSending(rule.assertion.id);setMessage("");
    try{const saved=await confirmProjectRule(rule,controller.signal);if(!controller.signal.aborted){setPage(p=>p?{...p,rules:p.rules.map(r=>r.assertion.id===saved.assertion.id?saved:r)}:p);setMessage("Rule confirmed and saved with this snapshot's source evidence.");}}
    catch(error){if(!controller.signal.aborted)setMessage(error instanceof Error?error.message:"Confirmation was not acknowledged. Refresh before trying again.");else setMessage("Confirmation timed out. Refresh to check its saved status before trying again.");}
    finally{clearTimeout(timer);setSending(null);}
  }
  async function declare(input:PolicyInput){
    if(sending||!id)return;const controller=new AbortController();mutation.current=controller;const timer=setTimeout(()=>controller.abort(),15000);setSending("declaration");setMessage("");
    try{await declareProjectRule(id,input,controller.signal);if(!controller.signal.aborted){setRevision(n=>n+1);setMessage("Declared requirement saved. New reviews use it; current reviews retain their frozen rules.");}}
    catch(error){setMessage(error instanceof Error?error.message:"Save was not acknowledged. Refresh before trying again.");}
    finally{clearTimeout(timer);setSending(null);}
  }
  if(!id)return <Sheet title="Understand your project" description="Open an authorized local folder for source inspection, or choose a recorded run above to explore its frozen evidence."><SetupPanel /></Sheet>;
  return <Sheet title={page?.name??"Project"} description="Follow entry points through possible checks to the data they use.">
    <p role="status">{message||(busy?"Reading the frozen project map…":"")}</p><div className={styles.controls}><button onClick={()=>setRevision(n=>n+1)}>Refresh project</button></div>
    {page&&<ProjectView page={page} onPage={setOffsets} onConfirm={confirm} onDeclare={declare} sendingPolicy={sending} />}
  </Sheet>;
}

const inventory=(counts:Readonly<Record<string,number>>,unit:string)=>Object.entries(counts).map(([name,count])=>`${name}: ${count} ${unit}`).join("; ")||"None recorded";
function SourceButton({citation,onSource}:{citation:ProjectCitation;onSource:(c:ProjectCitation)=>void}){return <button className={styles.sourceButton} onClick={()=>onSource(citation)}><code>{citation.span.path}:{citation.span.start_line}–{citation.span.end_line}</code><span>Read frozen source</span></button>;}
function FlowList({flow,onSource}:{flow:ProjectFlow;onSource:(c:ProjectCitation)=>void}){
  return <div className={styles.flowList}>
    {[{title:"Entry point",nodes:[flow.entry],total:1},{title:"Guard candidates",nodes:flow.guards,total:flow.guards_total},{title:"Data access",nodes:flow.data,total:flow.data_total}].map(group=><section key={group.title}><h3>{group.title}</h3>
      {group.nodes.length?<ul>{group.nodes.map(node=><li key={node.id}><strong>{node.label}</strong><p className={styles.meta}>{node.detail}{node.optimistic?" · optimistic, not an authorization boundary":""}</p><SourceButton citation={node.citation} onSource={onSource} /></li>)}</ul>:<p>No {group.title.toLowerCase()} mapped on this path. Missing map data cannot establish safety.</p>}
      {group.nodes.length<group.total&&<p className={styles.meta}>Showing {group.nodes.length} of {group.total} nodes. The saved full application map retains the remainder.</p>}
    </section>)}
  </div>;
}
const noExcerpts:readonly ProjectExcerpt[]=[];
export function ProjectView({page,onPage,onConfirm,onDeclare,sendingPolicy=null,initialExcerpts=noExcerpts}:{page:ProjectPage;onPage?:(o:ProjectOffsets)=>void;onConfirm?:(r:ProjectRule)=>void;onDeclare?:(p:PolicyInput)=>Promise<void>;sendingPolicy?:string|null;initialExcerpts?:readonly ProjectExcerpt[]}){
  const [flowId,setFlowId]=useState(page.flows[0]?.entry.id);const [list,setList]=useState(false);const [wide,setWide]=useState(false);const [selected,setSelected]=useState<ProjectCitation|null>(null);
  useEffect(()=>{const media=window.matchMedia("(min-width: 1180px)");const change=()=>setWide(media.matches);change();media.addEventListener("change",change);return()=>media.removeEventListener("change",change);},[]);
  const flow=page.flows.find(f=>f.entry.id===flowId)??page.flows[0];
  const offsets={offset:page.offset,scope_offset:page.scope_offset,policy_offset:page.policy_offset};
  const source=(c:ProjectCitation)=>setSelected(c);
  return <div className={styles.project}>
    <section aria-labelledby="summary-title"><h2 id="summary-title">Recorded project</h2>
      <p>{page.flows_total} discovered entry points across {Object.keys(page.frameworks).join(" and ")||"unclassified frameworks"}; {Object.values(page.resources).reduce((a,b)=>a+b,0)} static data access sites. Source citations below show where these records came from.</p>
      <p className={styles.meta}>{inventory(page.languages,"source files")}. {inventory(page.frameworks,"entries")}.</p>
      <p className={styles.meta}>Resource labels: {inventory(page.resources,"access sites")}. Labels aid navigation; they do not describe business intent.</p>
      <dl className={styles.facts}><div><dt>Included files</dt><dd>{page.included_files}</dd></div><div><dt>Excluded paths</dt><dd>{page.excluded_files}</dd></div><div><dt>Unresolved links</dt><dd>{page.unresolved_links}</dd></div><div><dt>Optimistic links</dt><dd>{page.optimistic_links}</dd></div></dl>
      <p className={styles.meta}>Snapshot <code>{page.snapshot_id.slice(0,12)}</code> · captured {new Date(page.captured_at).toISOString().slice(0,10)} UTC. Reading this screen starts no model.</p>
    </section>
    <CapabilityTable value={page.capabilities} />
    <section className={styles.section} aria-labelledby="map-title"><h2 id="map-title">Application site plan</h2>
      <p>Entry points → guard candidates → data. Possible static paths, with unresolved relationships retained. Choose an entry to inspect its sources.</p>
      {page.flows.length?<><label className={styles.selector}>Entry point<select value={flow?.entry.id??""} onChange={e=>{setFlowId(e.target.value);setSelected(null);}}>{page.flows.map(f=><option key={f.entry.id} value={f.entry.id}>{f.entry.label} · {f.entry.citation.span.path}</option>)}</select></label>
        <p className={styles.meta}>Entries {page.offset+1}–{page.offset+page.flows.length} of {page.flows_total}. Most data access paths first, then source order; this is not a security ranking.</p>
        {wide&&<div className={styles.controls}><button aria-pressed={list} onClick={()=>setList(n=>!n)}>{list?"Show site plan":"Show list instead"}</button></div>}
        {flow&&<>
          <p className={styles.unknown}>{flow.unresolved_links} unresolved and {flow.optimistic_links} optimistic links on this entry's possible flow. Unclassified guard candidates have not been validated as protections.</p>
          {wide&&!list?<Suspense fallback={<p>Loading local map layout…</p>}><MapView flow={flow} snapshot={page.snapshot_id} onSource={source} /></Suspense>:<FlowList flow={flow} onSource={source} />}
          <p className={styles.meta}>Solid ink = resolved; blue dashed = inferred; gray dashed = unresolved. Connectors show saved relationships between the visible nodes; omitted helpers can interrupt a visible path.</p>
          {wide&&!list&&<details><summary>Read the same map as a list</summary><FlowList flow={flow} onSource={source} /></details>}
          <details><summary>Saved relationships between shown nodes ({flow.links.length})</summary><ul>{flow.links.map(e=><li key={e.id}><strong>{e.kind.replaceAll("_"," ")} · {e.status}{e.optimistic?" · optimistic":""}</strong><p>{e.reason}</p></li>)}</ul><p className={styles.meta}>Connectors represent saved relationships only. Solid ink = resolved; blue dashed = inferred; gray dashed = unresolved. Paths through omitted helpers may have no direct connector here.</p></details>
        </>}
      </>:<p>No supported entry points were recorded. This does not establish that the project is safe.</p>}
      {onPage&&<div className={styles.controls}><button aria-disabled={page.offset===0} onClick={()=>{if(page.offset)onPage({...offsets,offset:Math.max(0,page.offset-12)});}}>Previous entries</button><button aria-disabled={page.next_offset===null} onClick={()=>{if(page.next_offset!==null)onPage({...offsets,offset:page.next_offset});}}>Next entries</button></div>}
    </section>
    {selected&&<ProjectSource key={selected.id} runId={page.run_id} citation={selected} initialExcerpts={initialExcerpts} />}
    <section className={styles.section} aria-labelledby="rules-title"><h2 id="rules-title">Access rules</h2>
      <p>Rules describe required behavior. New reviews freeze applicable declarations and confirmations against these exact accesses. A rule never proves a guard exists or changes agent permissions. Source changes require revalidation.</p>
      {(page.policy_conflicts??[]).map((text,i)=><p className={styles.unknown} key={i}>Rule conflict: {text}</p>)}
      {(page.bound_policies??[]).length>0&&<ul className={styles.rules}>{page.bound_policies!.map(p=><li key={p.assertion.id}><strong>{p.assertion.status==="declared"?"Declared requirement":"Confirmed requirement"}</strong><p>{p.assertion.statement}</p><p className={styles.meta}>{p.assertion.author} · {new Date(p.assertion.created_at).toISOString().slice(0,10)} UTC · {p.provenance}</p><p>Required guard: {p.assertion.kind}. Fields excluded from client data: {(p.forbidden_fields??[]).join(", ")||"None declared"}.</p><ul>{p.sites.map(s=><li key={s.id}><code>{s.span.path}:{s.span.start_line} · {s.id}</code></li>)}</ul></li>)}</ul>}
      {onDeclare&&<DeclareRule key={page.snapshot_id} page={page} onDeclare={onDeclare} busy={!!sendingPolicy} />}
      {page.rules.length?<ul className={styles.rules}>{page.rules.map(rule=><li key={rule.assertion.id} data-policy-status={rule.assertion.status}>
        <strong>{rule.assertion.status==="confirmed"?"Confirmed rule":"Inferred rule · awaiting review"}</strong><p>{rule.assertion.statement}</p><code>{rule.assertion.canonical}</code>
        <p className={styles.meta}>{rule.assertion.author} · {new Date(rule.assertion.created_at).toISOString().slice(0,10)} UTC · {rule.sites_applying} of {rule.sites_total} eligible sites. {rule.assertion.status==="confirmed"&&`Confirmed by ${rule.assertion.confirmed_by} on ${new Date(rule.assertion.confirmed_at!).toISOString().slice(0,10)} UTC.`}</p>
        <details><summary>Source provenance ({rule.citations.length} citations)</summary><p className={styles.meta}>Observed forms are retained separately; a shared kind does not assert identical operands or business intent.</p><ul>{rule.guard_forms.map(form=><li key={form}><code>{form}</code></li>)}</ul>{rule.citations.map(c=><SourceButton key={c.id} citation={c} onSource={source} />)}</details>
        {onConfirm&&<button className={styles.confirm} aria-disabled={!!sendingPolicy||rule.assertion.status==="confirmed"} onClick={()=>{if(!sendingPolicy&&rule.assertion.status!=="confirmed")onConfirm(rule);}}>{rule.assertion.status==="confirmed"?"Confirmed and saved":sendingPolicy===rule.assertion.id?"Saving confirmation…":"Confirm rule"}</button>}
      </li>)}</ul>:<p>No access-rule proposals were saved for this run. Static candidate names cannot supply a policy, and older reports may not contain peer records.</p>}
      {onPage&&<div className={styles.controls}><button aria-disabled={page.policy_offset===0} onClick={()=>{if(page.policy_offset)onPage({...offsets,policy_offset:Math.max(0,page.policy_offset-20)});}}>Previous rules</button><button aria-disabled={page.policy_next_offset===null} onClick={()=>{if(page.policy_next_offset!==null)onPage({...offsets,policy_offset:page.policy_next_offset});}}>Next rules</button></div>}
    </section>
    <section className={styles.section} aria-labelledby="scope-title"><h2 id="scope-title">Scope and unknowns</h2><p>{page.included_files} included files; {page.excluded_files} excluded paths or directories. Included source may still contain unsupported flows.</p>
      <p>{inventory(page.exclusion_reasons,"excluded paths")}. Unsupported exclusions: {page.exclusion_reasons.unsupported??0}. Unresolved links: {page.unresolved_links}.</p>
      <details><summary>Excluded paths and reasons ({page.excluded_files})</summary><ul>{page.exclusions.map(f=><li key={`${f.path}:${f.reason}`}><code>{f.path}</code> · {f.reason.replaceAll("_"," ")}</li>)}</ul>
        {onPage&&<div className={styles.controls}><button aria-disabled={page.scope_offset===0} onClick={()=>{if(page.scope_offset)onPage({...offsets,scope_offset:Math.max(0,page.scope_offset-20)});}}>Previous exclusions</button><button aria-disabled={page.scope_next_offset===null} onClick={()=>{if(page.scope_next_offset!==null)onPage({...offsets,scope_offset:page.scope_next_offset});}}>Next exclusions</button></div>}
      </details><details><summary>Limits of this project map</summary><ul>{page.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></details>
    </section>
  </div>;
}

function DeclareRule({page,onDeclare,busy}:{page:ProjectPage;onDeclare:(p:PolicyInput)=>Promise<void>;busy:boolean}){
  const sites=page.flows.flatMap(f=>f.data);const [site,setSite]=useState(sites[0]?.id??"");const [guard,setGuard]=useState("owner");const [fields,setFields]=useState("");const [statement,setStatement]=useState("");const [author,setAuthor]=useState("Local reviewer");
  return <details><summary>Declare a requirement for a frozen access</summary><form className={styles.controls} onSubmit={e=>{e.preventDefault();if(busy||!sites.some(s=>s.id===site))return;void onDeclare({snapshot_id:page.snapshot_id,site_ids:[site],required_guard:guard==="fields"?null:guard as PolicyInput["required_guard"],forbidden_fields:fields.split(",").map(s=>s.trim()).filter(Boolean),statement,author});}}>
    <label>Data access<select required value={site} onChange={e=>setSite(e.target.value)}>{sites.map(s=><option key={s.id} value={s.id}>{s.label} · {s.citation.span.path}:{s.citation.span.start_line}</option>)}</select></label>
    <label>Required guard<select value={guard} onChange={e=>setGuard(e.target.value)}>{["owner","tenant","authenticated","role","none","fields"].map(k=><option key={k} value={k}>{k==="none"?"Public access (conflicts with required guards)":k==="fields"?"Data minimization only":k}</option>)}</select></label>
    <label>Fields excluded from client data (comma separated)<input value={fields} maxLength={1000} onChange={e=>setFields(e.target.value)} required={guard==="fields"} /></label>
    <label>Requirement<input required value={statement} maxLength={1000} onChange={e=>setStatement(e.target.value)} /></label>
    <label>Author<input required value={author} maxLength={100} onChange={e=>setAuthor(e.target.value)} /></label>
    <button disabled={busy||!site} type="submit">{busy?"Saving rule…":"Save declared rule"}</button>
    <p>Select an exact access on this entry page. Earlier reviews remain immutable. Minimized field flows need separate source validation.</p>
  </form></details>;
}

function ProjectSource({runId,citation,initialExcerpts}:{runId:string;citation:ProjectCitation;initialExcerpts:readonly ProjectExcerpt[]}){
  const [offset,setOffset]=useState(0);const [page,setPage]=useState<ProjectExcerpt|null>(null);const [message,setMessage]=useState("");const [revision,setRevision]=useState(0);const caption=useRef<HTMLElement>(null);
  useEffect(()=>{caption.current?.focus();caption.current?.scrollIntoView({block:"nearest"});},[]);
  useEffect(()=>{const controller=new AbortController();let active=true;const timer=setTimeout(()=>controller.abort(),10000);setMessage("Reading frozen source…");
    const cached=initialExcerpts.find(p=>p.citation.id===citation.id&&p.offset===offset);
    const read=async()=>cached?parseProjectExcerpt(cached,runId,citation,offset):fetchProjectExcerpt(runId,citation,offset,controller.signal);
    read().then(value=>{if(active){setPage(value);setMessage("Frozen source loaded. Secrets are redacted; comments are not evidence.");}}).catch(error=>{if(active)setMessage(controller.signal.aborted?"Source lookup timed out. Try again.":error instanceof Error?error.message:"Source cannot be read.");}).finally(()=>clearTimeout(timer));
    return()=>{active=false;controller.abort();clearTimeout(timer);};
  },[runId,citation,offset,revision,initialExcerpts]);
  return <figure className={styles.source}><figcaption ref={caption} tabIndex={-1}><strong>Frozen source</strong><code>{citation.span.path}:{citation.span.start_line}–{citation.span.end_line}</code></figcaption>
    <pre><code>{page?.lines.map((line,i)=><span className={styles.line} key={`${page.start_line}:${i}`}><span aria-hidden="true">{page.start_line+i}</span><span>{line}</span></span>)}</code></pre><p role="status">{message}</p>
    <div className={styles.controls}><button onClick={()=>setRevision(n=>n+1)}>Refresh source</button><button aria-disabled={offset===0} onClick={()=>{if(offset)setOffset(Math.max(0,offset-80));}}>Previous source lines</button><button aria-disabled={!page?.next_offset} onClick={()=>{if(page?.next_offset)setOffset(page.next_offset);}}>Next source lines</button></div>
  </figure>;
}
