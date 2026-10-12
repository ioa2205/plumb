"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatView, SavedResults } from "../generated/contracts";
import { chatRequest, partHeading, rungWords, savedResults, selectedChat, type ChatIntent } from "../lib/chat-data";
import { validJourneyId, websiteList } from "../lib/website-data";
import { Sheet } from "./Workbench";
import styles from "./AssessmentPanel.module.css";
import ask from "./Ask.module.css";

type Saved = NonNullable<SavedResults["results"]>[number];

/** A transcript on a sheet, not a chat window: no bubbles, no avatars, no typing animation. */
export function AskPanel() {
  const [view, setView] = useState<ChatView | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState<Saved[] | null>(null);
  const active = useRef<AbortController | null>(null);
  const current = useRef<string | null>(null);

  useEffect(() => {
    let id: string | null = null;
    try {id = selectedChat(window.location.search);} catch {setMessage("Use one valid chat ID."); return;}
    if (!id) return;
    const controller = new AbortController();
    chatRequest(`/api/chats/${id}`, undefined, controller.signal, id).then(value => {current.current = value.chat_id; setView(value);}).catch(() => setMessage("That chat could not be read. A new one starts with your next message."));
    return () => controller.abort();
  }, []);
  useEffect(() => () => {active.current?.abort();}, []);

  function remember(value: ChatView) {
    current.current = value.chat_id; setView(value);
    const url = new URL(window.location.href); url.searchParams.set("chat", value.chat_id); window.history.replaceState(null, "", url);
  }
  async function ensure(signal: AbortSignal): Promise<ChatView> {
    if (view) return view;
    const value = await chatRequest("/api/chats", {}, signal); remember(value); return value;
  }
  async function send(text: string, choice?: ChatIntent) {
    if (busy || !text.trim()) return;
    const controller = new AbortController(); active.current = controller; setBusy(true); setMessage("Reading your message.");
    const timer = setTimeout(() => controller.abort(), 630_000);
    try {
      let value = await ensure(controller.signal);
      const id = value.chat_id;
      value = await chatRequest(`/api/chats/${id}/ask`, {prompt: text.trim(), max_seconds: 300, ...(choice ? {choice} : {})}, controller.signal, id);
      setView(value);
      while (value.state === "running" && !controller.signal.aborted) {
        if (value.progress) setMessage(value.progress);
        await new Promise<void>(done => {const wait = setTimeout(done, 700); controller.signal.addEventListener("abort", () => {clearTimeout(wait); done();}, {once: true});});
        if (controller.signal.aborted) break;
        value = await chatRequest(`/api/chats/${id}`, undefined, controller.signal, id); setView(value);
      }
      setMessage(value.message ?? ""); if (value.state === "completed") setPrompt("");
    } catch (error) {
      setMessage(controller.signal.aborted ? "Stopped. Earlier turns are kept." : error instanceof Error ? error.message : "The message could not be sent.");
    } finally {clearTimeout(timer); active.current = null; setBusy(false);}
  }
  async function stop() {
    const id = current.current; active.current?.abort();
    if (!id) return;
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 10_000);
    try {setView(await chatRequest(`/api/chats/${id}/cancel`, null, controller.signal, id));}
    catch {setMessage("Stopping could not reach Plumb. Its own time limit still applies.");}
    finally {clearTimeout(timer);}
  }
  async function loadSaved() {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 15_000);
    try {
      const [results, websites] = await Promise.all([savedResults(controller.signal), websiteList(controller.signal)]);
      const journeys: Saved[] = (websites.journeys ?? []).filter(item => validJourneyId(item.journey_id)).map(item => ({target_kind: "website", target_id: item.journey_id, label: `Website test of ${item.scope.name}`}));
      setSaved([...(results.results ?? []), ...journeys]);
    } catch {setMessage("Saved results could not be listed.");}
    finally {clearTimeout(timer);}
  }
  async function select(item: Saved | null) {
    if (busy) return;
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 30_000);
    try {
      const value = await ensure(controller.signal);
      const next = await chatRequest(`/api/chats/${value.chat_id}/select`, item ? {target_kind: item.target_kind, target_id: item.target_id} : {}, controller.signal, value.chat_id);
      setView(next); setMessage(next.message ?? "");
    } catch (error) {setMessage(error instanceof Error ? error.message : "That result could not be selected.");}
    finally {clearTimeout(timer);}
  }
  const turns = view?.turns ?? [];
  const last = turns.at(-1);
  return <Sheet title="Ask" description="Ask in your own words: a question, a folder of code to review, or a website you are authorized to test. A message never starts or approves anything by itself.">
    <section className={styles.section} aria-label="What follow-ups are about">
      <p className={styles.meta}>{view?.target_label ? <>Follow-up questions are about: <strong>{view.target_label}</strong></> : "Nothing is selected. General questions need nothing selected."}</p>
      <details onToggle={event => {if ((event.target as HTMLDetailsElement).open && saved === null) void loadSaved();}}>
        <summary>Choose a saved result to ask about</summary>
        {saved === null ? <p className={styles.meta}>Reading saved results.</p> : saved.length === 0 ? <p className={styles.meta}>No saved review or website test yet.</p> : <ul className={styles.list}>{saved.map(item => <li key={item.target_id}><button className={styles.button} type="button" disabled={busy} onClick={() => void select(item)}>{item.label}</button></li>)}</ul>}
        {view?.target_kind && <button className={styles.quiet} type="button" disabled={busy} onClick={() => void select(null)}>Clear the selection</button>}
      </details>
    </section>
    {turns.length > 0 && <ol className={ask.transcript} aria-label="Conversation so far">{turns.map((turn, index) => <li key={index} className={ask.turn}>
      <h2 className={ask.asked}>{turn.prompt}</h2>
      <p className={styles.meta}>{turn.interpretation} ({rungWords(turn.intent_rung)})</p>
      {(turn.parts ?? []).map((part, key) => <div key={key} className={part.kind === "notice" ? ask.notice : ask.part}>
        <h3 className={ask.partHeading}>{partHeading(part)}</h3>
        <p className={ask.text}>{part.text}</p>
        <p className={styles.meta}>{part.basis}</p>
        {(part.evidence ?? []).length > 0 && <details><summary>Exact evidence ({(part.evidence ?? []).length})</summary>{(part.evidence ?? []).map(item => <div key={item.reference_id}><p className={styles.meta}><code>{item.reference_id}</code> · {item.label}</p><pre className={styles.evidence}>{item.quote}</pre></div>)}</details>}
      </div>)}
      {turn.task && <div className={ask.proposal}>
        <h3 className={ask.partHeading}>Proposal · nothing has started</h3>
        <p>{turn.task.summary}</p>
        {(turn.task.missing ?? []).length > 0 && <><p className={styles.meta}>Still needed</p><ul>{(turn.task.missing ?? []).map((item, key) => <li key={key}>{item}</li>)}</ul></>}
        {(turn.task.steps ?? []).length > 0 && <><p className={styles.meta}>What would happen, only after you confirm</p><ol>{(turn.task.steps ?? []).map((item, key) => <li key={key}>{item}</li>)}</ol></>}
        <div className={styles.actions}>{turn.task.kind === "website_setup" ? <a className={styles.button} href="/website/">Set up a website test</a> : turn.task.kind === "inspect_folder" ? <a className={styles.button} href="/">Open a project folder</a> : <span className={styles.meta}>Choose a saved result above, then ask again.</span>}</div>
      </div>}
      {index === turns.length - 1 && (turn.choices ?? []).length > 0 && <div className={styles.actions} role="group" aria-label="What did you mean?">{(turn.choices ?? []).map(choice => <button key={choice.intent} className={styles.button} type="button" disabled={busy} onClick={() => void send(turn.prompt, choice.intent)}>{choice.label}</button>)}</div>}
      {(turn.model_requests ?? 0) > 0 && <p className={styles.meta}>Local model: {turn.model_requests} request{turn.model_requests === 1 ? "" : "s"}, {Math.round(turn.model_seconds ?? 0)} s</p>}
    </li>)}</ol>}
    <form className={styles.form} onSubmit={event => {event.preventDefault(); void send(prompt);}}>
      <label>Message<textarea required rows={3} maxLength={4096} value={prompt} disabled={busy} onChange={event => setPrompt(event.target.value)} placeholder={last ? "" : "What is SQL injection?"} /></label>
      <div className={styles.actions}>
        <button className={styles.primary} type="submit" disabled={busy || turns.length >= 40}>Send</button>
        <button className={styles.quiet} type="button" disabled={!busy} onClick={() => void stop()}>Stop</button>
        <button className={styles.quiet} type="button" disabled={busy || !view} onClick={() => {setView(null); current.current = null; const url = new URL(window.location.href); url.searchParams.delete("chat"); window.history.replaceState(null, "", url); setMessage("A new chat starts with your next message.");}}>New chat</button>
      </div>
    </form>
    <p role="status" className={styles.message}>{message}</p>
    <p className={styles.meta}>{view?.limits || "Each answer stops at 320 tokens and 300 seconds. One model on this computer answers one message at a time."} Private on this computer.</p>
  </Sheet>;
}
