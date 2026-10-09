import type { CaseDetail, SnapshotCodePage } from "../generated/contracts";
import codeSchema from "../generated/snapshot-code-page.schema.json" with { type: "json" };
import { CaseReadError, MAX_CASE_BYTES, readCaseRecord, validFindingId } from "./case-data.ts";
import { peerCitations } from "./peer-data.ts";
import { structuralMatches, validRunId } from "./run-metadata.ts";

export type CodeSelection={tag:string}|{site:string;citation:number};
export type CodeWindow={mode:"context"|"file";before:number;after:number;offset:number};
export const defaultCodeWindow:CodeWindow={mode:"context",before:3,after:3,offset:0};

export function selectedSpan(detail:CaseDetail,selection:CodeSelection) {
  if("tag" in selection)return detail.finding.exhibits.find(e=>e.tag===selection.tag&&e.role!=="developer_note")?.span;
  const peer=detail.peer_comparison;const row=typeof peer==="object" ? peer.rows.find(r=>r.site.id===selection.site) : undefined;
  return row&&Number.isSafeInteger(selection.citation)&&selection.citation>=0 ? peerCitations(row)[selection.citation] : undefined;
}
function validWindow(window:CodeWindow):boolean {
  return ["context","file"].includes(window.mode)&&[window.before,window.after].every(n=>Number.isSafeInteger(n)&&n>=0&&n<=80)
    &&Number.isSafeInteger(window.offset)&&window.offset>=0&&window.offset<=1_000_000
    &&(window.mode!=="file"||(window.before===0&&window.after===0));
}
export function parseCodePage(value:unknown,detail:CaseDetail,selection:CodeSelection,window:CodeWindow,previous?:SnapshotCodePage):SnapshotCodePage {
  const span=selectedSpan(detail,selection);
  if(!span||!validWindow(window)||!structuralMatches(value,codeSchema))throw new CaseReadError("These snapshot lines cannot be read.");
  const page=value as SnapshotCodePage;const citation=page.citation;
  const start=window.mode==="file" ? 1 : Math.max(1,span.start_line-window.before);
  const end=window.mode==="file" ? page.file_line_count : Math.min(page.file_line_count,span.end_line+window.after);
  if(!validRunId(detail.run.id)||!validFindingId(detail.finding.id)||page.run_id!==detail.run.id||page.finding_id!==detail.finding.id
    ||citation.snapshot_id!==detail.run.snapshot_id||citation.snapshot_id!==span.snapshot_id||citation.path!==span.path
    ||citation.start_line!==span.start_line||citation.end_line!==span.end_line||citation.content_sha256!==span.content_sha256
    ||span.end_line>page.file_line_count||page.mode!==window.mode||page.before!==window.before||page.after!==window.after
    ||page.range_start!==start||page.range_end!==end||page.offset!==window.offset||page.start_line!==start+window.offset
    ||page.end_line!==Math.min(end,page.start_line+79)||page.lines.length!==page.end_line-page.start_line+1
    ||page.next_offset!==(page.end_line<end ? page.end_line-start+1 : null)
    ||page.text_is_redacted!==true||page.comments_are_not_evidence!==true||page.context_is_not_evidence!==true
    ||(previous&&(page.file_sha256!==previous.file_sha256||page.file_line_count!==previous.file_line_count||page.language!==previous.language))) {
    throw new CaseReadError("These lines do not match the selected frozen citation.");
  }
  return page;
}
export async function fetchCodePage(detail:CaseDetail,selection:CodeSelection,window:CodeWindow,signal:AbortSignal,previous?:SnapshotCodePage,request:typeof fetch=fetch):Promise<SnapshotCodePage> {
  if(!selectedSpan(detail,selection)||!validWindow(window)||!validRunId(detail.run.id)||!validFindingId(detail.finding.id))throw new CaseReadError("Use a recorded code citation from this case.");
  const selector="tag" in selection ? `exhibits/${encodeURIComponent(selection.tag)}` : `peers/${encodeURIComponent(selection.site)}/citations/${selection.citation}`;
  const params=new URLSearchParams({mode:window.mode,before:String(window.before),after:String(window.after),offset:String(window.offset),lines:"80"});
  const path=`/api/runs/${encodeURIComponent(detail.run.id)}/findings/${encodeURIComponent(detail.finding.id)}/${selector}/code?${params}`;
  return parseCodePage(await readCaseRecord(path,signal,request),detail,selection,window,previous);
}
/** Clipboard text contains only the complete original citation, never surrounding context. */
export async function readCitedText(detail:CaseDetail,selection:CodeSelection,signal:AbortSignal,previous?:SnapshotCodePage,request:typeof fetch=fetch):Promise<string> {
  let offset=0;let bytes=0;const parts:string[]=[];let pinned=previous;
  while(true) {
    const page=await fetchCodePage(detail,selection,{mode:"context",before:0,after:0,offset},signal,pinned,request);
    pinned=page;const text=page.lines.join("\n");bytes+=new TextEncoder().encode(text).byteLength+(parts.length ? 1 : 0);
    if(bytes>MAX_CASE_BYTES)throw new CaseReadError("The cited excerpt is too large to copy. Copy its location instead.");
    parts.push(text);if(page.next_offset==null)return parts.join("\n");offset=page.next_offset;
  }
}
export async function copyCodeText(text:string,clipboard:Pick<Clipboard,"writeText">|undefined):Promise<void> {
  if(!clipboard)throw new CaseReadError("Clipboard access is unavailable. Select the text below and copy it.");
  try {await clipboard.writeText(text);}catch {throw new CaseReadError("The browser refused clipboard access. Select the text below and copy it.");}
}
