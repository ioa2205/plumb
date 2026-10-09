"use client";
import { useEffect, useState } from "react";
import type { ProjectCitation, ProjectFlow } from "../lib/project-data";
import { mapPositions } from "../lib/map-layout";
import type { MapPosition } from "../lib/map-layout-core";
import styles from "./ProjectPanel.module.css";

export function ProjectMap({flow,snapshot,onSource}:{flow:ProjectFlow;snapshot:string;onSource:(c:ProjectCitation)=>void}){
  const [positions,setPositions]=useState<MapPosition[]|null>(null);const [failed,setFailed]=useState(false);
  useEffect(()=>{const controller=new AbortController();setPositions(null);setFailed(false);
    const items=[{id:flow.entry.id,lane:0},...flow.guards.map(n=>({id:n.id,lane:1})),...flow.data.map(n=>({id:n.id,lane:2}))];
    mapPositions(`${snapshot}:${items.map(n=>`${n.id}:${n.lane}`).join("|")}`,items,controller.signal).then(value=>{if(!controller.signal.aborted){setPositions(value);setFailed(!value);}});
    return()=>controller.abort();
  },[flow,snapshot]);
  if(!positions)return <p role="status">{failed?"Map layout is unavailable. Use the list below for the same source records.":"Arranging the saved map…"}</p>;
  const nodes=[flow.entry,...flow.guards,...flow.data];const height=Math.max(...positions.map(n=>n.y+148));
  return <div className={styles.map} style={{height}} aria-label="Entry points, guard candidates and data site plan">
    <div className={styles.laneHeads}><strong>Entry point</strong><strong>Guard candidates</strong><strong>Data access</strong></div>
    <svg className={styles.connections} viewBox={`0 0 800 ${height}`} preserveAspectRatio="none" aria-hidden="true">{flow.links.map(edge=>{
      const a=positions.find(n=>n.id===edge.source);const b=positions.find(n=>n.id===edge.target);if(!a||!b)return null;
      const x=a.x+210,y=a.y+66,tx=b.x,ty=b.y+66;
      return <path key={edge.id} data-status={edge.status} data-optimistic={edge.optimistic} d={`M ${x} ${y} C ${x+30} ${y}, ${tx-30} ${ty}, ${tx} ${ty}`} />;
    })}</svg>
    {nodes.map(node=>{const p=positions.find(n=>n.id===node.id)!;return <button key={node.id} className={styles.mapNode} data-candidate={node!==flow.entry&&!flow.data.includes(node)} style={{left:`${p.x/8}%`,top:p.y,width:"26.25%"}} onClick={()=>onSource(node.citation)}>
      <strong>{node.label}</strong><span>{node.detail}</span><code>{node.citation.span.path}:{node.citation.span.start_line}</code>
    </button>;})}
  </div>;
}
