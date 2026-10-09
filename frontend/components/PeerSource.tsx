"use client";

import { useMemo } from "react";
import type { CaseDetail, SnapshotCodePage } from "../generated/contracts";
import { peerRoute } from "../lib/peer-data";
import type { PeerSelection } from "./PeerCheck";
import { CodePane } from "./CodePane";

export function PeerSource({detail,selection,initialPages}:{detail:CaseDetail;selection:PeerSelection;initialPages?:readonly SnapshotCodePage[]}) {
  const source=useMemo(()=>({site:selection.site,citation:selection.citation}),[selection.site,selection.citation]);
  const peer=detail.peer_comparison;const row=typeof peer==="object" ? peer.rows.find(r=>r.site.id===selection.site) : undefined;
  if(!row)return <p>This peer citation was not recorded.</p>;
  return <CodePane detail={detail} selection={source} label="Peer source" gloss={`${peerRoute(row)} · ${selection.label}`} focus initialPages={initialPages} />;
}
