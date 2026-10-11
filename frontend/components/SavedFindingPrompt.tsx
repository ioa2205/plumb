"use client";

import { useEffect, useRef, useState } from "react";
import type { CaseDetail, SavedFindingAnswer } from "../generated/contracts";
import { askSavedFinding } from "../lib/saved-answer-data";
import { ConversationPanel } from "./ConversationPanel";
import styles from "./AssessmentPanel.module.css";

export function SavedFindingPrompt({detail, onExhibit}: {detail: CaseDetail; onExhibit: (tag: string) => void}) {
  const [prompt, setPrompt] = useState(`Explain ${detail.finding.display_id} and its limitations`); const [answer, setAnswer] = useState<SavedFindingAnswer | null>(null); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null); useEffect(() => () => active.current?.abort(), []);
  async function ask() {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller; const timer = setTimeout(() => controller.abort(), 15_000); setBusy(true); setMessage("Reading the saved finding and exact source exhibits…");
    try {const value = await askSavedFinding(detail, prompt, controller.signal); if (!controller.signal.aborted) {setAnswer(value); setMessage("Answered from saved evidence. No model, recheck or network test started.");}}
    catch (error) {setMessage(controller.signal.aborted ? "The saved answer lookup timed out. Check the backend, then retry." : error instanceof Error ? error.message : "The saved answer could not be read.");}
    finally {clearTimeout(timer); active.current = null; setBusy(false);}
  }
  return <><ConversationPanel key={detail.run.id} target={{target_kind: "review", target_id: detail.run.id}} /><section className={styles.section} aria-labelledby="saved-prompt-title"><h2 id="saved-prompt-title">Ask about this saved finding</h2><p>Use its finding ID to explain the evidence, limitations or report. Saved answers preserve the recorded verdict and unknowns.</p><form className={styles.form} onSubmit={event => {event.preventDefault(); void ask();}}><label>Saved evidence question<textarea rows={2} required value={prompt} maxLength={4096} onChange={event => setPrompt(event.target.value)} /></label><button className={styles.button} type="submit" disabled={busy}>Read saved evidence answer</button></form><p className={styles.message} role="status">{message}</p>{answer && <div className={styles.row}><p><strong>{answer.finding.title}</strong></p><p>{answer.finding.conclusion} · {answer.finding.runtime_verification?.replaceAll("_", " ")}</p><p>{answer.finding.lede}</p><div className={styles.actions}>{answer.finding.exhibits.filter(exhibit => exhibit.role !== "developer_note").map(exhibit => <button type="button" className={styles.tag} key={exhibit.tag} onClick={() => onExhibit(exhibit.tag)}>{exhibit.tag} · {exhibit.gloss}</button>)}</div><h3>Recorded unknowns</h3><ul>{[...(answer.finding.gaps ?? []), ...(answer.finding.unknowns ?? []), ...answer.limitations].map((text, index) => <li key={index}>{text}</li>)}</ul></div>}</section></>;
}
