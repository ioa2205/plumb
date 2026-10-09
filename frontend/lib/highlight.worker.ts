import { tokenizeListing } from "./highlight-core";
import { parseHighlightRequest } from "./highlight-protocol";

const worker=self as unknown as {onmessage:((event:MessageEvent<unknown>)=>void)|null;postMessage:(value:unknown)=>void};
worker.onmessage=event=>{
  const request=parseHighlightRequest(event.data);if(!request)return;
  tokenizeListing(request).then(tokens=>worker.postMessage({id:request.id,tokens})).catch(()=>worker.postMessage({id:request.id,tokens:null}));
};
