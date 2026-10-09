import ELK from "elkjs/lib/elk-api.js";
import { layoutGraph, layoutPositions, type MapItem, type MapPosition } from "./map-layout-core.ts";
type WorkerPort=Pick<Worker,"postMessage"|"terminate"|"addEventListener"|"removeEventListener"|"onmessage">;
const cache=new Map<string,MapPosition[]>();
const factory=()=>new Worker(new URL("elkjs/lib/elk-worker.min.js",import.meta.url),{type:"module",name:"plumb-map"});
export function validPositions(value:unknown,items:readonly MapItem[]):value is MapPosition[]{
  return Array.isArray(value)&&value.length===items.length&&new Set(value.map(n=>n?.id)).size===items.length
    &&value.every(n=>items.some(i=>i.id===n?.id&&n.x===20+i.lane*270)&&Number.isFinite(n.y)&&n.y>=48&&n.y<=20000);
}
/** Bounded local worker, terminated on every exit. Only validated snapshot layouts are cached. */
export function mapPositions(key:string,items:MapItem[],signal:AbortSignal,create:()=>WorkerPort=factory,timeout=5000):Promise<MapPosition[]|null>{
  if(signal.aborted)return Promise.resolve(null);
  const saved=cache.get(key);if(saved&&validPositions(saved,items))return Promise.resolve(saved);
  return new Promise(resolve=>{
    let worker:WorkerPort;try{worker=create();}catch{resolve(null);return;}
    let done=false;
    const finish=(positions:MapPosition[]|null)=>{if(done)return;done=true;clearTimeout(timer);signal.removeEventListener("abort",abort);worker.removeEventListener("error",abort);worker.removeEventListener("messageerror",abort);worker.onmessage=null;worker.terminate();if(positions){if(cache.size>=20)cache.delete(cache.keys().next().value!);cache.set(key,positions);}resolve(positions);};
    const abort=()=>finish(null);
    const timer=setTimeout(abort,timeout);signal.addEventListener("abort",abort,{once:true});worker.addEventListener("error",abort);worker.addEventListener("messageerror",abort);
    try{const elk=new ELK({workerFactory:()=>worker as Worker,algorithms:["layered"]});elk.layout(layoutGraph(items)).then(graph=>finish(layoutPositions(graph,items))).catch(()=>finish(null));}catch{finish(null);}
  });
}
