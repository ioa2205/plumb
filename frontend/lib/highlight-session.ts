import { parseHighlightReply, parseHighlightRequest, type HighlightRequest, type SyntaxToken } from "./highlight-protocol.ts";

type WorkerPort=Pick<Worker,"postMessage"|"terminate"|"addEventListener"|"removeEventListener">;
const workerFactory=()=>new Worker(new URL("./highlight.worker.ts",import.meta.url),{type:"module",name:"plumb-code"});

/** A single bounded request; every completion, abort and timeout terminates its worker. */
export function highlightListing(value:HighlightRequest,signal:AbortSignal,create:()=>WorkerPort=workerFactory,timeoutMs=5000):Promise<SyntaxToken[][]|null> {
  const request=parseHighlightRequest(value);if(!request||signal.aborted)return Promise.resolve(null);
  return new Promise(resolve=>{
    let worker:WorkerPort;try{worker=create();}catch{resolve(null);return;}
    let finished=false;
    const finish=(tokens:SyntaxToken[][]|null)=>{
      if(finished)return;finished=true;clearTimeout(timer);signal.removeEventListener("abort",abort);
      worker.removeEventListener("message",message);worker.removeEventListener("error",error);worker.removeEventListener("messageerror",error);worker.terminate();resolve(tokens);
    };
    const abort=()=>finish(null);const error=()=>finish(null);
    const message=(event:Event)=>finish(parseHighlightReply((event as MessageEvent<unknown>).data,request.lines,request.id));
    const timer=setTimeout(abort,timeoutMs);
    signal.addEventListener("abort",abort,{once:true});worker.addEventListener("message",message);worker.addEventListener("error",error);worker.addEventListener("messageerror",error);
    try{worker.postMessage(request);}catch{finish(null);}
  });
}
