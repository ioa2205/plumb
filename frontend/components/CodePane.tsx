"use client";

import { useEffect, useRef, useState } from "react";
import type { CaseDetail, SnapshotCodePage } from "../generated/contracts";
import { CaseReadError } from "../lib/case-data";
import { copyCodeText, defaultCodeWindow, fetchCodePage, parseCodePage, readCitedText, selectedSpan, type CodeSelection, type CodeWindow } from "../lib/code-data";
import { highlightListing } from "../lib/highlight-session";
import type { SyntaxToken } from "../lib/highlight-protocol";
import styles from "./CaseFile.module.css";

const emptyPages:readonly SnapshotCodePage[]=[];
/** Only validated frozen source is displayed. One 80-line page stays mounted. */
export function CodePane({detail,selection,label,gloss,flag=false,focus=false,initialPages=emptyPages,clipboard}:{detail:CaseDetail;selection:CodeSelection;label:string;gloss:string;flag?:boolean;focus?:boolean;initialPages?:readonly SnapshotCodePage[];clipboard?:Pick<Clipboard,"writeText">|null}) {
  const span=selectedSpan(detail,selection);
  const [window,setWindow]=useState<CodeWindow>(defaultCodeWindow);
  const [page,setPage]=useState<SnapshotCodePage|null>(null);
  const [busy,setBusy]=useState(true);const [message,setMessage]=useState("");const [revision,setRevision]=useState(0);
  const [copyBusy,setCopyBusy]=useState(false);const [copyMessage,setCopyMessage]=useState("");const [copyFallback,setCopyFallback]=useState("");
  const pinned=useRef<SnapshotCodePage|undefined>(undefined);const caption=useRef<HTMLElement>(null);
  const copyController=useRef<AbortController|null>(null);const mounted=useRef(true);
  const [highlighted,setHighlighted]=useState<{page:SnapshotCodePage;tokens:SyntaxToken[][]|null}|null>(null);const highlightId=useRef(0);
  useEffect(()=>{
    if(!page)return;const controller=new AbortController();setHighlighted(null);
    if(!page.language){setHighlighted({page,tokens:null});return;}
    highlightListing({id:++highlightId.current,lines:page.lines,language:page.language},controller.signal).then(tokens=>{if(!controller.signal.aborted)setHighlighted({page,tokens});});
    return ()=>controller.abort();
  },[page]);
  useEffect(()=>{mounted.current=true;if(focus){caption.current?.focus();caption.current?.scrollIntoView({block:"nearest"});}
    return ()=>{mounted.current=false;copyController.current?.abort();};
  },[focus]);
  useEffect(()=>{
    const controller=new AbortController();let active=true;const timer=globalThis.window.setTimeout(()=>controller.abort(),10000);
    setBusy(true);setMessage("");
    const cached=initialPages.find(p=>p.run_id===detail.run.id&&p.finding_id===detail.finding.id&&p.citation.path===span?.path
      &&p.citation.start_line===span?.start_line&&p.citation.end_line===span?.end_line&&p.mode===window.mode
      &&p.before===window.before&&p.after===window.after&&p.offset===window.offset);
    const read=async()=>cached ? parseCodePage(cached,detail,selection,window,pinned.current) : fetchCodePage(detail,selection,window,controller.signal,pinned.current);
    read().then(value=>{if(active){pinned.current=value;setPage(value);}}).catch(error=>{
      if(active)setMessage(controller.signal.aborted ? "The snapshot lookup timed out. Try again." : error instanceof CaseReadError ? error.message : "The frozen source cannot be read. Try again.");
    }).finally(()=>{globalThis.window.clearTimeout(timer);if(active)setBusy(false);});
    return ()=>{active=false;controller.abort();globalThis.window.clearTimeout(timer);};
  },[detail,selection,window,revision,initialPages,span]);
  async function copy(kind:"location"|"excerpt") {
    if(!span||copyBusy)return;
    copyController.current?.abort();const controller=new AbortController();copyController.current=controller;
    const timer=globalThis.window.setTimeout(()=>controller.abort(),10000);setCopyBusy(true);setCopyMessage("");setCopyFallback("");
    let text="";
    try {
      text=kind==="location" ? `${span.path}:${span.start_line}` : page&&page.start_line<=span.start_line&&page.end_line>=span.end_line
        ? page.lines.slice(span.start_line-page.start_line,span.end_line-page.start_line+1).join("\n")
        : await readCitedText(detail,selection,controller.signal,pinned.current);
      if(controller.signal.aborted||!mounted.current)return;
      await copyCodeText(text,clipboard===null ? undefined : clipboard??navigator.clipboard);
      if(mounted.current&&copyController.current===controller)setCopyMessage(kind==="location" ? "Citation location copied." : "Complete cited excerpt copied, with secrets redacted.");
    } catch(error) {
      if(mounted.current&&copyController.current===controller){setCopyMessage(controller.signal.aborted ? "The copy lookup timed out. Try again." : error instanceof CaseReadError ? error.message : "Copy failed. Try again.");if(text)setCopyFallback(text);}
    } finally {globalThis.window.clearTimeout(timer);if(mounted.current&&copyController.current===controller)setCopyBusy(false);}
  }
  if(!span)return <p>This code citation was not recorded.</p>;
  return <figure className={styles.exhibit}><figcaption ref={caption} tabIndex={-1}><strong>{label}</strong><code>{span.path}</code><span>Cited lines {span.start_line}–{span.end_line}</span><p>{gloss}</p></figcaption>
    <div className={styles.codeActions} role="group" aria-label="Snapshot source controls">
      <button className={styles.action} type="button" disabled={busy} onClick={()=>setWindow(window.mode==="file" ? defaultCodeWindow : {mode:"file",before:0,after:0,offset:0})}>{window.mode==="file" ? "Return to citation" : "Open full file"}</button>
      <button className={styles.action} type="button" disabled={copyBusy} onClick={()=>void copy("location")}>Copy location</button>
      <button className={styles.action} type="button" disabled={busy||copyBusy||!page} onClick={()=>void copy("excerpt")}>Copy excerpt</button>
    </div>
    <p className={styles.note}>{page ? `Showing ${page.mode==="file" ? "frozen file" : "context"} lines ${page.start_line}–${page.end_line} of ${page.file_line_count}.` : "Reading the frozen file."} {message&&page ? "The last successfully read page is preserved. " : ""}Margin bars identify the original citation; surrounding lines are display context.</p>
    {window.mode==="context"&&<div className={styles.codeActions} role="group" aria-label="Expand snapshot context">
      <button type="button" className={styles.action} disabled={busy||window.before>=80||page?.range_start===1} onClick={()=>setWindow(w=>({...w,before:Math.min(80,w.before+10),offset:0}))}>Show 10 lines above</button>
      <button type="button" className={styles.action} disabled={busy||window.after>=80||page?.range_end===page?.file_line_count} onClick={()=>setWindow(w=>({...w,after:Math.min(80,w.after+10),offset:0}))}>Show 10 lines below</button>
    </div>}
    <pre className={styles.code} aria-label={"tag" in selection ? `Snapshot excerpt ${selection.tag}` : "Saved peer citation"}><code>{page?.lines.map((line,i)=>{
      const n=page.start_line+i;const cited=n>=span.start_line&&n<=span.end_line;
      const tokens=highlighted?.page===page ? highlighted.tokens?.[i] : null;
      return <span className={`${styles.line} ${cited ? flag ? styles.flaggedLine : styles.citedLine : ""}`} key={`${page.start_line}/${n}`}><span className={styles.number} aria-hidden="true">{n}</span><span className={styles.source}>{tokens ? tokens.map((token,j)=><span key={j} data-syntax={token.tone}>{token.text}</span>) : line}</span></span>;
    })}</code></pre>
    <p className={styles.note}>Frozen snapshot only, with secrets redacted. Comments are shown and never count as evidence. Copy excerpt includes only the original cited lines.</p>
    {highlighted?.page===page&&highlighted.tokens===null&&<p className={styles.note}>Syntax colors are unavailable for this page. Original code is shown.</p>}
    <p role="status">{message||(busy ? "Reading snapshot lines…" : page ? `Snapshot lines ${page.start_line}–${page.end_line} loaded.` : "")}</p>
    {message&&<button className={styles.action} type="button" onClick={()=>setRevision(n=>n+1)}>Retry source</button>}
    {page&&(page.offset>0||page.next_offset!=null)&&<div className={styles.codeActions} role="group" aria-label="Snapshot pages">
      <button className={styles.action} type="button" disabled={busy||page.offset===0} onClick={()=>setWindow(w=>({...w,offset:Math.max(0,w.offset-80)}))}>Previous 80 lines</button>
      <button className={styles.action} type="button" aria-disabled={busy||page.next_offset==null} onClick={()=>{if(!busy&&page.next_offset!=null)setWindow(w=>({...w,offset:page.next_offset!}));}}>Next 80 lines</button>
    </div>}
    <p role="status">{copyMessage||(copyBusy ? "Preparing cited text for copying…" : "")}</p>
    {copyFallback&&<label className={styles.copyFallback}>Select and copy this redacted text<textarea readOnly value={copyFallback} rows={Math.min(8,copyFallback.split("\n").length)} onFocus={event=>event.currentTarget.select()} /></label>}
  </figure>;
}
