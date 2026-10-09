import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {tokenizeListing} from "../lib/highlight-core.ts";
import {MAX_HIGHLIGHT_BYTES,MAX_HIGHLIGHT_TOKENS,parseHighlightReply,parseHighlightRequest} from "../lib/highlight-protocol.ts";
import {highlightListing} from "../lib/highlight-session.ts";

test("pinned Shiki preserves exact saved code pages and styles only reading aids",async()=>{
  const pages=JSON.parse(readFileSync(new URL('./fixtures/code-pages.json',import.meta.url),'utf8'));
  for(const page of pages){const tokens=await tokenizeListing({id:1,language:page.language,lines:page.lines});assert.ok(tokens);assert.deepEqual(tokens.map(row=>row.map(t=>t.text).join('')),page.lines);}
  const python=['@router.get("/receipt")','def receipt():','    # comment is never a guard','    return "literal <script>"'];
  const tokens=await tokenizeListing({id:1,language:'python',lines:python});
  assert.ok(tokens[0].some(t=>t.tone==='decorator'&&t.text.includes('@router.get')));
  assert.ok(tokens[1].some(t=>t.tone==='keyword'&&t.text.includes('def')));
  assert.ok(tokens[2].some(t=>t.tone==='comment'));
  assert.ok(tokens[3].some(t=>t.tone==='string'&&t.text.includes('<script>')));
  for(const language of ['javascript','typescript','tsx']){
    const lines=language==='tsx' ? ['export function A(){ return <span title="x">text</span>; }'] : ['// No ownership check','export const x = "safe";'];
    const listing=await tokenizeListing({id:2,language,lines});assert.ok(listing);assert.deepEqual(listing.map(row=>row.map(t=>t.text).join('')),lines);
  }
});

test("unsupported, oversized and malformed requests never enter tokenization",async()=>{
  const base={id:1,language:'python',lines:['return 1']};
  for(const value of [null,{}, {...base,id:0},{...base,id:1.5},{...base,language:'outside'},{...base,lines:[]},{...base,lines:Array(81).fill('x')},{...base,lines:['x'.repeat(4097)]},{...base,lines:['split\nline']},{...base,lines:[42]},{...base,path:'../secret'},{...base,lines:Array(80).fill('x'.repeat(1000))}]){
    assert.equal(parseHighlightRequest(value),null);assert.equal(await tokenizeListing(value),null);
  }
  assert.ok(MAX_HIGHLIGHT_BYTES<512*1024);
  // A grammar may normalize embedded CR; exact reply validation must then refuse it.
  const original=['return "x"\r','next'];const result=await tokenizeListing({id:1,language:'python',lines:original});
  if(result)assert.deepEqual(result.map(row=>row.map(t=>t.text).join('')),original);
});

test("worker output cannot inject classes, HTML, reordered or altered text",()=>{
  const reply={id:7,tokens:[[{text:'literal <img>',tone:'string'}]]};
  assert.deepEqual(parseHighlightReply(reply,['literal <img>'],7),reply.tokens);
  for(const value of [{...reply,id:8},{...reply,style:'red'}, {...reply,tokens:[]}, {...reply,tokens:[[{text:'literal <img>',tone:'bad-class'}]]},{...reply,tokens:[[{text:'different',tone:'plain'}]]},{...reply,tokens:[[{text:'literal <img>',tone:'plain',html:'injected'}]]},{...reply,tokens:[Array(MAX_HIGHLIGHT_TOKENS+1).fill({text:'',tone:'plain'})]}])assert.equal(parseHighlightReply(value,['literal <img>'],7),null);
});

class FakeWorker extends EventTarget {
  stopped=false;request=null;postMessage(value){this.request=value;}terminate(){this.stopped=true;}
  reply(value){this.dispatchEvent(new MessageEvent('message',{data:value}));}
}
test("every reply, mismatch, crash, abort, timeout and send failure stops its worker",async()=>{
  const request={id:1,language:'python',lines:['return 1']};
  for(const mode of ['success','mismatch','crash','messageerror','abort','timeout','send']){
    const worker=new FakeWorker();const controller=new AbortController();
    if(mode==='send')worker.postMessage=()=>{throw Error('send failed');};
    const pending=highlightListing(request,controller.signal,()=>worker,mode==='timeout' ? 1 : 1000);
    if(mode==='success'||mode==='mismatch')worker.reply({id:mode==='success'?1:99,tokens:[[{text:'return 1',tone:'plain'}]]});
    if(mode==='crash')worker.dispatchEvent(new Event('error'));
    if(mode==='messageerror')worker.dispatchEvent(new Event('messageerror'));
    if(mode==='abort')controller.abort();
    assert.equal(!!await pending,mode==='success');assert.equal(worker.stopped,true);
  }
  const stopped=new AbortController();stopped.abort();assert.equal(await highlightListing(request,stopped.signal,()=>assert.fail('aborted worker created')),null);
  assert.equal(await highlightListing({...request,language:'outside'},new AbortController().signal,()=>assert.fail('invalid worker created')),null);
  assert.equal(await highlightListing(request,new AbortController().signal,()=>{throw Error('workers unavailable');}),null);
});
