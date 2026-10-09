import type { ElkNode } from "elkjs/lib/elk-api";
export type MapItem={id:string;lane:number};
export type MapPosition={id:string;x:number;y:number};
export function validMapItems(value:unknown):value is MapItem[]{
  return Array.isArray(value)&&value.length>0&&value.length<=12&&new Set(value.map(n=>n?.id)).size===value.length
    &&value.every(n=>n&&typeof n.id==="string"&&/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(n.id)&&Number.isInteger(n.lane)&&n.lane>=0&&n.lane<=2);
}
/** Layout constraints arrange columns; rendered connectors come only from saved map links. */
export function layoutGraph(items:MapItem[]):ElkNode{
  if(!validMapItems(items))throw new Error("Invalid bounded map input");
  return {id:"project",layoutOptions:{"elk.algorithm":"layered","elk.direction":"RIGHT","elk.randomSeed":"1","elk.spacing.nodeNode":"30","elk.layered.spacing.nodeNodeBetweenLayers":"60"},
      children:items.map(n=>({id:n.id,width:210,height:132})),
      edges:items.flatMap(a=>items.filter(b=>b.lane===a.lane+1).map(b=>({id:`${a.id}/${b.id}`,sources:[a.id],targets:[b.id]})))};
}
export function layoutPositions(value:unknown,items:MapItem[]):MapPosition[]|null{
  if(!value||typeof value!=="object"||!("children" in value)||!Array.isArray(value.children))return null;
  const nodes=value.children;if(nodes.length!==items.length||new Set(nodes.map(n=>n?.id)).size!==items.length
    ||nodes.some(n=>!items.some(i=>i.id===n?.id)||!Number.isFinite(n.y)||n.y<0||n.y>19952))return null;
  return nodes.map(n=>({id:n.id,x:20+items.find(i=>i.id===n.id)!.lane*270,y:Math.round(n.y)+48}));
}
