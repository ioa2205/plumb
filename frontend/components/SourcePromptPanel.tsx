"use client";

import { useEffect, useRef, useState } from "react";
import type { InspectionView, SourcePromptResolution } from "../generated/contracts";
import { resolveSourcePrompt } from "../lib/setup-data";
import styles from "./AssessmentPanel.module.css";
import { ConversationPanel } from "./ConversationPanel";

export function SourcePromptPanel({inspection, limit, onResolved, onPending, profile = "auto"}: {inspection: InspectionView; limit: number; onResolved: (task: SourcePromptResolution | null) => void; onPending: (pending: boolean) => void; profile?: string}) {
  const [prompt, setPrompt] = useState(""); const [task, setTask] = useState<SourcePromptResolution | null>(null); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function resolve() {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller; const timer = setTimeout(() => controller.abort(), 15_000); setBusy(true); setMessage("Resolving the instruction against discovered source IDs…");
    try { const result = await resolveSourcePrompt(inspection, prompt, limit, controller.signal); if (!controller.signal.aborted) {setTask(result); onResolved(result); onPending(false); setMessage(result.status === "resolved" ? "Scope resolved. Review the filters before using Run review." : result.clarification || "Clarify the source instruction.");} }
    catch (error) {setMessage(controller.signal.aborted ? "Source task resolution timed out. Check the local backend, then retry." : error instanceof Error ? error.message : "The instruction could not resolve.");}
    finally {clearTimeout(timer); active.current = null; setBusy(false);}
  }
  return <><ConversationPanel key={inspection.inspection_id} profile={profile} target={{target_kind: "inspection", target_id: inspection.inspection_id!}} /><section className={styles.section} aria-labelledby="source-prompt-title"><h3 id="source-prompt-title">Direct the source review</h3><p>Validate a separate action scope such as “Review this project for order ownership problems,” or use the review filters below. Resolution starts no model and grants no authority.</p>
    <form className={styles.form} onSubmit={event => {event.preventDefault(); void resolve();}}><label>Source instruction<textarea rows={3} required disabled={busy} maxLength={4096} value={prompt} onChange={event => {setPrompt(event.target.value); setTask(null); onResolved(null); onPending(!!event.target.value.trim());}} /></label><div className={styles.actions}><button className={styles.button} disabled={busy} type="submit">Resolve source scope</button><button className={styles.quiet} disabled={busy} type="button" onClick={() => {setPrompt(""); setTask(null); setMessage("Use the manual filters below."); onResolved(null); onPending(false);}}>Use manual filters</button></div></form>
    <p role="status" className={styles.message}>{message}</p>{task && <div className={styles.row}><p><strong>{task.status.replaceAll("_", " ")}</strong></p><p>{task.clarification}</p><p>Families: {task.families.join(", ") || "None resolved"}. Resources: {task.resources.join(", ") || "All discovered resources"}. Routes: {task.routes.join(", ") || "All discovered routes"}. Questions before pausing: {task.limit}.</p><p className={styles.meta}>Target <code>{task.target_id}</code> · no network activity or model launch.</p></div>}
  </section></>;
}
