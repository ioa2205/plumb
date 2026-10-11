"use client";

import { useEffect, useRef, useState } from "react";
import type { ConversationCreate, ConversationView } from "../generated/contracts";
import { conversationRequest } from "../lib/conversation-data";
import styles from "./AssessmentPanel.module.css";

export function ConversationPanel({target, profile = "auto"}: {target: ConversationCreate; profile?: string}) {
  const [view, setView] = useState<ConversationView | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const active = useRef<AbortController | null>(null);
  const currentId = useRef<string | null>(null);
  useEffect(() => () => {active.current?.abort(); if (currentId.current) void fetch(`/api/conversations/${currentId.current}/cancel`, {method: "POST", credentials: "same-origin", redirect: "error", keepalive: true}).catch(() => {});}, []);
  async function cancelSaved(identifier: string) {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 10_000);
    try {return await conversationRequest(target, `/api/conversations/${identifier}/cancel`, null, controller.signal, identifier);}
    finally {clearTimeout(timer);}
  }
  async function ask() {
    if (busy || !prompt.trim()) return;
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 315_000); active.current = controller; setBusy(true);
    setMessage("Reading bounded evidence with the local model. Admission and first-use checks apply.");
    try {
      let value = view ?? await conversationRequest(target, "/api/conversations", target, controller.signal);
      currentId.current = value.conversation_id; setView(value);
      value = await conversationRequest(target, `/api/conversations/${value.conversation_id}/ask`, {prompt: prompt.trim(), profile, max_seconds: 300}, controller.signal, value.conversation_id);
      setView(value);
      const deadline = Date.now() + 315_000;
      while (value.state === "running" && !controller.signal.aborted && Date.now() < deadline) {
        await new Promise<void>(done => {const finish = () => {clearTimeout(timer); controller.signal.removeEventListener("abort", finish); done();}; const timer = setTimeout(finish, 700); controller.signal.addEventListener("abort", finish, {once: true});});
        if (controller.signal.aborted) break;
        value = await conversationRequest(target, `/api/conversations/${value.conversation_id}`, undefined, controller.signal, value.conversation_id); setView(value);
      }
      if (value.state === "running") {
        await cancelSaved(value.conversation_id);
        setMessage("Question canceled or timed out. Saved turns are preserved.");
      } else {setMessage(value.message ?? "Local question finished."); if (value.state === "completed") setPrompt("");}
    } catch (error) {
      if (currentId.current) await cancelSaved(currentId.current).catch(() => {});
      setMessage(controller.signal.aborted ? "Question canceled or timed out; saved answers remain available." : error instanceof Error ? error.message : "The local question stopped.");
    }
    finally {clearTimeout(timer); active.current = null; setBusy(false);}
  }
  async function cancel() {
    active.current?.abort();
    if (currentId.current) {
      try {const value = await cancelSaved(currentId.current); setView(value);}
      catch {setMessage("Cancellation could not reach Plumb. The server time and memory gates still apply.");}
    }
  }
  return <section className={styles.section} aria-label="Local evidence conversation">
    <h3>Ask about the loaded evidence</h3>
    <p>Ask in your own words and follow up. Answers use the local model, exact source or reviewed observation citations, and recorded unknowns. Questions execute no actions and leave findings unchanged.</p>
    <form className={styles.form} onSubmit={event => {event.preventDefault(); void ask();}}>
      <label>Question or follow-up<textarea required rows={3} maxLength={4096} value={prompt} disabled={busy} onChange={event => setPrompt(event.target.value)} /></label>
      <div className={styles.actions}><button className={styles.button} type="submit" disabled={busy || view?.turns?.length === 20}>Ask local model</button><button className={styles.quiet} type="button" disabled={!busy} onClick={() => void cancel()}>Cancel question</button><button className={styles.quiet} type="button" disabled={busy || !view} onClick={() => {setView(null); currentId.current = null; setMessage("A new conversation will use this same target.");}}>New conversation</button></div>
    </form>
    <p role="status" className={styles.message}>{message}</p>
    {view && <><p className={styles.meta}><code>{view.conversation_id}</code> · {view.state} · private on this computer</p><ol className={styles.list}>{(view.turns ?? []).map((turn, index) => <li className={styles.row} key={index}><h4>{turn.prompt}</h4><p>{turn.answer}</p><details><summary>Exact evidence ({turn.evidence.length})</summary>{turn.evidence.map(item => <div key={item.reference_id}><p><code>{item.reference_id}</code> · {item.source ? `${item.source.path}:${item.source.start_line}` : item.observation ? `${item.observation.artifact_id} · ${item.observation.field}` : item.label}</p><pre className={styles.evidence}>{item.quote}</pre></div>)}</details><h4>Still unknown</h4><ul>{turn.unknowns.map((item, key) => <li key={key}>{item}</li>)}</ul></li>)}</ol></>}
    <p className={styles.meta}>Use the separate review filters, scope/account declarations and action previews to request work. A conversation cannot approve those actions.</p>
  </section>;
}
