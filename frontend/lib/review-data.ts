import type { ReviewPage, RunEvent, ReviewRun, QueueEdit } from "../generated/contracts";
import pageSchema from "../generated/review-page.schema.json" with { type: "json" };
import eventSchema from "../generated/run-event.schema.json" with { type: "json" };
import { parseRun, structuralMatches, validRunId } from "./run-metadata.ts";

export class ReviewError extends Error {
  readonly retry: boolean;
  constructor(message: string, retry = false) { super(message); this.retry = retry; }
}
export const MAX_VIEW_BYTES = 512 * 1024;
export const MAX_EVENT_BYTES = 64 * 1024;
export function activeRun(run: ReviewRun): boolean { return run.lifecycle === "running" || run.lifecycle === "queued"; }
export function runPath(id: string): string {
  if(!validRunId(id)) throw new ReviewError("Select a valid recorded run.");
  return `/api/runs/${encodeURIComponent(id)}`;
}
export async function viewResponse(path: string, signal: AbortSignal, request: typeof fetch, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try { response = await request(path,{...init,signal,credentials:"same-origin",cache:"no-store",redirect:"error"}); }
  catch { throw new ReviewError("Connection interrupted. Reconnecting to the saved checkpoint…",true); }
  if(response.status === 401 || response.status === 403) throw new ReviewError("Open the one-time Plumb link printed in the terminal to connect this browser session.");
  if(response.status === 404) throw new ReviewError("This record is not available yet. Check the run ID or refresh after its report is saved.");
  if(response.status === 409) throw new ReviewError("The review changed or a worker is active. Refresh and wait for a paused checkpoint before editing.");
  if(!response.ok) throw new ReviewError("Plumb cannot read this checkpoint right now. The saved results are preserved.",response.status >= 500);
  return response;
}
export async function readView(path: string, signal: AbortSignal, request: typeof fetch = fetch): Promise<unknown> {
  const response=await viewResponse(path,signal,request);
  if(!response.body || !response.headers.get("content-type")?.startsWith("application/json")) throw new ReviewError("Plumb returned an unreadable checkpoint.");
  const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  try {
    while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>MAX_VIEW_BYTES)throw new ReviewError("This checkpoint is too large to display. Use its saved report.");chunks.push(value);}
  } catch(error) { throw error instanceof ReviewError ? error : new ReviewError("Checkpoint transfer interrupted. Reconnecting…",true); }
  finally { await reader.cancel().catch(()=>{});reader.releaseLock(); }
  const bytes=new Uint8Array(size);let offset=0;for(const part of chunks){bytes.set(part,offset);offset+=part.byteLength;}
  try{return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));}catch{throw new ReviewError("Plumb returned an unreadable checkpoint.");}
}
export function parseReview(value: unknown, id: string, offset: number): ReviewPage {
  if(!structuralMatches(value,pageSchema))throw new ReviewError("This review checkpoint cannot be read.");
  const page=value as ReviewPage;const run=parseRun(page.run,id);const end=offset+page.questions.length;
  if(page.offset!==offset||page.next_offset!==(end<page.total?end:null)
    ||page.total!==run.coverage!.completed!+run.coverage!.pending!+(page.queue_excluded??0)||(page.questions.length>0&&end>page.total)
    ||(page.queue_excluded??0)>run.coverage!.excluded!
    ||page.questions.some(q=>q.original_position!=null&&q.original_position>page.total)
    ||new Set(page.questions.map(q=>q.id)).size!==page.questions.length
    ||page.questions.some((q,i)=>q.position!==offset+i+1||(q.location&&q.location.snapshot_id!==run.snapshot_id))
    ||page.events.length!==Math.min(100,page.cursor)
    ||page.events.some((e,i)=>e.run_id!==id||e.seq!==page.cursor-page.events.length+i+1))throw new ReviewError("This review checkpoint has inconsistent records.");
  return page;
}
export async function fetchReview(id:string,offset:number,signal:AbortSignal,request:typeof fetch=fetch):Promise<ReviewPage>{
  if(!Number.isSafeInteger(offset)||offset<0||offset>1_000_000)throw new ReviewError("Invalid queue page.");
  return parseReview(await readView(`${runPath(id)}/review?offset=${offset}`,signal,request),id,offset);
}
export function parseEvent(block:string,id:string,after:number):RunEvent|null {
  if(!block||block.startsWith(":"))return null;
  const fields=new Map(block.split("\n").filter(line=>!line.startsWith(":")).map(line=>{const at=line.indexOf(":");return [line.slice(0,at),line.slice(at+1).replace(/^ /,"")];}));
  if(!fields.has("data")){if(fields.has("retry"))return null;throw new ReviewError("The activity stream contains an unreadable event.");}
  let value:unknown;try{value=JSON.parse(fields.get("data")!);}catch{throw new ReviewError("The activity stream contains an unreadable event.");}
  if(!structuralMatches(value,eventSchema))throw new ReviewError("The activity stream contains an unreadable event.");
  const e=value as RunEvent;
  if(e.run_id!==id||String(e.seq)!==fields.get("id")||e.kind!==fields.get("event")||e.seq!==after+1
    ||e.kind.startsWith("question.")!==!!e.question_id
    ||(e.kind==="question.finished")!==!!e.status
    ||(e.kind==="question.stage"&&!e.stage)||(e.kind==="question.activity"&&!e.message)
    ||(e.coverage&&e.coverage.completed!+e.coverage.pending!+e.coverage.excluded!+e.coverage.unsupported!!==e.coverage.total))throw new ReviewError("Activity sequence changed. Refresh the review to reconnect safely.");
  return e;
}
/** Cursor advances only after validation and delivery. A reconnect supplies that exact ID. */
export async function consumeEvents(id:string,after:number,signal:AbortSignal,onEvent:(event:RunEvent)=>void,request:typeof fetch=fetch):Promise<void>{
  const response=await viewResponse(`${runPath(id)}/events`,signal,request,{headers:{"Last-Event-ID":String(after),Accept:"text/event-stream"}});
  if(!response.body||!response.headers.get("content-type")?.startsWith("text/event-stream"))throw new ReviewError("Plumb returned an unreadable activity stream.");
  const reader=response.body.getReader();const decoder=new TextDecoder("utf-8",{fatal:true});let pending="";
  try{
    while(true){const {done,value}=await reader.read();if(done){pending+=decoder.decode();if(pending.trim())throw new ReviewError("Activity transfer interrupted. Reconnecting…",true);return;}
      pending+=decoder.decode(value,{stream:true});let split:number;
      while((split=pending.indexOf("\n\n"))>=0){const block=pending.slice(0,split);pending=pending.slice(split+2);if(new TextEncoder().encode(block).length>MAX_EVENT_BYTES)throw new ReviewError("An activity record is too large to display.");const event=parseEvent(block,id,after);if(event){onEvent(event);after=event.seq;}}
      if(new TextEncoder().encode(pending).length>MAX_EVENT_BYTES)throw new ReviewError("An activity record is too large to display.");
    }
  }catch(error){throw error instanceof ReviewError?error:new ReviewError("Activity transfer interrupted. Reconnecting…",true);}
  finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
export async function requestControl(id:string,action:"pause"|"cancel",signal:AbortSignal,request:typeof fetch=fetch):Promise<void>{
  const response=await viewResponse(`${runPath(id)}/${action}`,signal,request,{method:"POST"});
  if(response.status!==202)throw new ReviewError("Plumb did not acknowledge the request. Refresh before trying again.");
}
export async function requestQueueEdit(id:string,edit:QueueEdit,signal:AbortSignal,request:typeof fetch=fetch):Promise<void>{
  if(!validRunId(edit.question_id)||!Number.isSafeInteger(edit.expected_cursor)||edit.expected_cursor<0
    ||!['up','down','exclude','include'].includes(edit.action))throw new ReviewError("Choose a pending question from this run.");
  const response=await viewResponse(`${runPath(id)}/queue`,signal,request,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(edit)});
  await response.body?.cancel();
}
export function questionTitle(type:ReviewPage["questions"][number]["type"]):string {
  return {guard_summary:"Which guards protect this access?",guard_equivalent:"Does this guard enforce the same access rule?",input_origin:"Where does this input come from?",sink_safety:"Can this input reach a sensitive operation safely?",intentional_exception:"Does code establish an intentional exception?",client_exposure:"What data reaches the client?",fix_sketch:"What change would address this finding?"}[type];
}
export function activityText(event:RunEvent):string {
  return event.message || (event.kind==="question.stage"?`Entered ${event.stage}.`:event.kind==="question.finished"?`Saved ${event.status?.replaceAll("_"," ")} result.`:event.kind.replaceAll("."," ").replace(/^./,c=>c.toUpperCase())+".");
}
