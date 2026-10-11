"use client";

import { useEffect, useRef, useState } from "react";
import type { AssessmentView } from "../generated/contracts";
import { createWebsiteAssessment, OWNED_WEBSITE_ORIGIN, websiteScope } from "../lib/website-workflow";
import styles from "./AssessmentPanel.module.css";

export function WebsiteScopeForm({disabled, onCreated}: {disabled: boolean; onCreated: (view: AssessmentView) => void}) {
  const [url, setUrl] = useState(OWNED_WEBSITE_ORIGIN); const [author, setAuthor] = useState(""); const [reference, setReference] = useState(""); const [basis, setBasis] = useState("");
  const [requests, setRequests] = useState(18); const [seconds, setSeconds] = useState(600); const [hours, setHours] = useState(1);
  const [authority, setAuthority] = useState(false); const [ownerOnly, setOwnerOnly] = useState(false); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  function resetApproval() {setAuthority(false); setOwnerOnly(false);}
  return <section className={styles.section} aria-labelledby="website-start"><h2 id="website-start">Start with an approved website URL</h2>
    <p>Development collection is available only for the owned hash-pinned Tandir lab. This step saves the URL and scope; the exact collection actions require a separate preview and approval.</p>
    <form className={styles.form} onSubmit={event => {event.preventDefault(); if (active.current) return; const controller = new AbortController(); active.current = controller; setBusy(true); const timeout = setTimeout(() => controller.abort(), 30_000); void (async () => {try {const scope = websiteScope(author, reference, requests, seconds, hours, crypto.randomUUID()); const view = await createWebsiteAssessment(url, scope, authority, ownerOnly, basis, controller.signal); if (!controller.signal.aborted) {resetApproval(); setMessage("Approved URL and prior owner access declarations saved. Preview the exact collection actions next."); onCreated(view);}} catch (error) {if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "The website scope could not be saved."); else setMessage("The browser wait ended. Check saved assessments before retrying.");} finally {clearTimeout(timeout); active.current = null; setBusy(false);}})();}}>
      <label>Approved website URL<input type="url" value={url} maxLength={4096} required spellCheck={false} onChange={event => {setUrl(event.target.value); resetApproval();}} /></label>
      <label>Authorizing person<input value={author} required maxLength={256} autoComplete="off" onChange={event => {setAuthor(event.target.value); resetApproval();}} /></label>
      <label>Authorization reference<input value={reference} required maxLength={4096} onChange={event => {setReference(event.target.value); resetApproval();}} /></label>
      <div className={styles.facts}><label>Maximum requests and judgments<input type="number" value={requests} min={18} max={30} required onChange={event => {setRequests(Number(event.target.value)); resetApproval();}} /></label><label>Maximum total seconds<input type="number" value={seconds} min={180} max={3600} required onChange={event => {setSeconds(Number(event.target.value)); resetApproval();}} /></label><label>Scope expires in hours<input type="number" value={hours} min={1} max={24} required onChange={event => {setHours(Number(event.target.value)); resetApproval();}} /></label></div>
      <details open><summary>Review scope, accounts, actions and privacy stops</summary><ul><li>Origin: <code>{OWNED_WEBSITE_ORIGIN}</code>. Paths: <code>/health</code>, <code>/auth/login</code>, <code>/orders</code> and the fixed receipt/invoice reads for the created synthetic order.</li><li>Separate designated synthetic customer sessions: Alice (owner) and Bob (other customer). One disposable synthetic order with a unique marker; no credentials are entered or retained as evidence.</li><li>Allowed actions: read, compare, plan, report, local analyze, collect, authenticate and create synthetic data. Collection reserves up to twelve HTTP attempts; each endpoint analysis reserves three independent judgments.</li><li>Stop on cancellation, expiry, exhausted budget, redirect, scope escape or unexpected private data. The runner clears sessions and stops its owned lab; failed and canceled work consumes the lifetime budget.</li></ul></details>
      <label>Basis for expected owner access<input value={basis} required maxLength={4096} onChange={event => {setBasis(event.target.value); setOwnerOnly(false);}} placeholder="Owned lab policy: an order belongs to its creating customer" /></label>
      <label className={styles.check}><input type="checkbox" checked={ownerOnly} required onChange={event => setOwnerOnly(event.target.checked)} /><span>I declare that only Alice may read her synthetic order's receipt and invoice. This expectation is separate from observed responses.</span></label>
      <label className={styles.check}><input type="checkbox" checked={authority} required onChange={event => setAuthority(event.target.checked)} /><span>I authorize this exact URL, paths, accounts, actions, budgets and expiry.</span></label>
      <button type="submit" className={styles.button} disabled={disabled || busy || !authority || !ownerOnly}>Create approved website scope</button>
    </form><p className={styles.message} role="status">{message}</p>
  </section>;
}
