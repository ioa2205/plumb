"use client";

import { useState } from "react";
import type { JourneyCreate } from "../generated/contracts";
import { buildWebsiteSetup, emptySetup, type SetupAccount, type SetupDraft, type SetupObject } from "../lib/website-setup";
import styles from "./AssessmentPanel.module.css";

export function WebsiteSetupForm({busy, onCreate}: {busy: boolean; onCreate: (request: JourneyCreate) => Promise<void>}) {
  const [draft, setDraft] = useState(emptySetup);
  const [error, setError] = useState("");
  const set = <K extends keyof SetupDraft>(key: K, value: SetupDraft[K]) => setDraft(previous => ({...previous, [key]: value, confirmed: key === "confirmed" ? Boolean(value) : false}));
  const account = (index: number, patch: Partial<SetupAccount>) => set("accounts", draft.accounts.map((value, position) => position === index ? {...value, ...patch} : value));
  const object = (index: number, patch: Partial<SetupObject>) => set("objects", draft.objects.map((value, position) => position === index ? {...value, ...patch} : value));
  const existing = draft.accounts.some(value => value.existing);
  const creating = draft.accounts.some(value => !value.existing);
  return <form className={styles.form} onSubmit={event => {event.preventDefault(); setError(""); try {void onCreate(buildWebsiteSetup(draft));} catch (reason) {setError(reason instanceof Error ? reason.message : "Check the scope fields.");}}}>
    <p>Describe the approved test in these fields. Saving creates a plan; it visits nothing. You approve the exact plan before running it.</p>
    <fieldset disabled={busy} className={styles.setupGroup}>
      <legend>Website and authorization</legend>
      <label>Website address<input required maxLength={300} value={draft.address} onChange={event => set("address", event.target.value)} placeholder="https://your-website.example" /></label>
      <label>Name in reports<input maxLength={300} value={draft.name} onChange={event => set("name", event.target.value)} /></label>
      <label>Purpose of this test<textarea required maxLength={1024} rows={2} value={draft.purpose} onChange={event => set("purpose", event.target.value)} /></label>
      <label>Who authorized this test? Include their role<input required maxLength={300} value={draft.authorizedBy} onChange={event => set("authorizedBy", event.target.value)} /></label>
      <label>Authorization reference, such as a ticket and date<input required maxLength={1024} value={draft.authorization} onChange={event => set("authorization", event.target.value)} /></label>
      <label>Approved page paths, one per line<textarea required rows={2} value={draft.paths} onChange={event => set("paths", event.target.value)} /></label>
      <label>Starting page path<input required maxLength={512} value={draft.start} onChange={event => set("start", event.target.value)} /></label>
      <details><summary>Other explicitly approved addresses</summary><label>Additional HTTPS origins, one per line<textarea rows={2} value={draft.otherOrigins} onChange={event => set("otherOrigins", event.target.value)} /></label><p className={styles.meta}>The same approved path list applies to each address. Linked sites, sign-in providers and CDNs inherit no permission.</p></details>
      <details><summary>Known public contact details</summary><label>Public values, such as the site's support email, one per line<textarea rows={2} value={draft.publicValues} onChange={event => set("publicValues", event.target.value)} /></label><p className={styles.meta}>Declare public contact details you expect to see. Unexpected personal information still stops the test.</p></details>
    </fieldset>
    <fieldset disabled={busy} className={styles.setupGroup}>
      <legend>Optional test accounts</legend>
      <p className={styles.meta}>Use designated synthetic accounts only. Passwords are entered when you run the approved plan.</p>
      {draft.accounts.map((value, index) => <div key={index} className={styles.row}>
        <label>Account {index + 1} ID<input required maxLength={128} value={value.id} onChange={event => account(index, {id: event.target.value})} /></label>
        <label>Label for reports<input maxLength={300} value={value.label} onChange={event => account(index, {label: event.target.value})} /></label>
        <label>Role<input required maxLength={300} value={value.role} onChange={event => account(index, {role: event.target.value})} /></label>
        <label>Username or test email<input required maxLength={128} value={value.username} onChange={event => account(index, {username: event.target.value})} /></label>
        <label className={styles.check}><input type="checkbox" checked={value.existing} onChange={event => account(index, {existing: event.target.checked})} />This account already exists</label>
        {!value.existing && <label>Designated synthetic email for sign-up<input type="email" maxLength={254} value={value.email} onChange={event => account(index, {email: event.target.value})} /></label>}
        <button className={styles.quiet} type="button" onClick={() => set("accounts", draft.accounts.filter((_, position) => position !== index))}>Remove account {index + 1}</button>
      </div>)}
      <button className={styles.button} type="button" disabled={draft.accounts.length >= 6} onClick={() => set("accounts", [...draft.accounts, {id: "", label: "", role: "user", username: "", existing: true, email: ""}])}>Add a test account</button>
      {existing && <div className={styles.row}>
        <h3>Sign-in check</h3>
        <label>Sign-in page path<input required value={draft.loginPath} onChange={event => set("loginPath", event.target.value)} /></label>
        <label>Page path shown after successful sign-in<input value={draft.loginSuccessPath} onChange={event => set("loginSuccessPath", event.target.value)} /></label>
        <label>Or text shown only after successful sign-in<input maxLength={128} value={draft.loginSuccessText} onChange={event => set("loginSuccessText", event.target.value)} /></label>
      </div>}
      {creating && <div className={styles.row}>
        <h3>Approved synthetic sign-up</h3>
        <label>Sign-up page path<input required value={draft.signupPath} onChange={event => set("signupPath", event.target.value)} /></label>
        <label>Page path shown after the account is created<input value={draft.signupSuccessPath} onChange={event => set("signupSuccessPath", event.target.value)} /></label>
        <label>Or text that confirms creation<input maxLength={128} value={draft.signupSuccessText} onChange={event => set("signupSuccessText", event.target.value)} /></label>
        <label>Approved side effects, including messages or charges<textarea required maxLength={300} rows={2} value={draft.signupEffects} onChange={event => set("signupEffects", event.target.value)} /></label>
        <label className={styles.check}><input type="checkbox" checked={draft.sendsMessages} onChange={event => set("sendsMessages", event.target.checked)} />Sign-up sends an email or SMS to the designated test contact</label>
      </div>}
    </fieldset>
    <fieldset disabled={busy} className={styles.setupGroup}>
      <legend>Optional comparisons of known synthetic objects</legend>
      <p className={styles.meta}>A comparison reads only the exact object you name. Use a unique marker in its content so an ordinary login page cannot be mistaken for the object. The rule below reserves it to its owner.</p>
      {draft.objects.map((value, index) => <div key={index} className={styles.row}>
        <label>Object {index + 1}: exact page or API path<input required value={value.path} onChange={event => object(index, {path: event.target.value})} /></label>
        <label>What is this object?<input required maxLength={300} value={value.label} onChange={event => object(index, {label: event.target.value})} /></label>
        <label>Unique synthetic marker in its response<input required minLength={6} maxLength={128} value={value.marker} onChange={event => object(index, {marker: event.target.value})} /></label>
        <label>Owner test account<select required value={value.owner} onChange={event => object(index, {owner: event.target.value})}><option value="">Choose the owner</option>{draft.accounts.filter(item => item.id).map(item => <option key={item.id} value={item.id}>{item.label || item.id}</option>)}</select></label>
        <label>Owner-only access rule<textarea required maxLength={1024} rows={2} value={value.rule} onChange={event => object(index, {rule: event.target.value})} /></label>
        <button className={styles.quiet} type="button" onClick={() => set("objects", draft.objects.filter((_, position) => position !== index))}>Remove object {index + 1}</button>
      </div>)}
      <button className={styles.button} type="button" disabled={draft.accounts.length < 2 || draft.objects.length >= 20} onClick={() => set("objects", [...draft.objects, {path: "", label: "", marker: "", owner: "", rule: ""}])}>Add a synthetic object</button>
    </fieldset>
    <fieldset disabled={busy} className={styles.setupGroup}>
      <legend>Limits</legend>
      {([['hours', 'Authorization valid for hours', 1, 168], ['requests', 'Maximum requests', 1, 2000], ['seconds', 'Maximum test seconds', 1, 7200], ['megabytes', 'Maximum response megabytes', 1, 256], ['questions', 'Maximum model questions', 0, 60]] as const).map(([key, label, min, max]) => <label key={key}>{label}<input required type="number" min={min} max={max} step={1} value={draft[key]} onChange={event => set(key, event.target.value)} /></label>)}
      <label className={styles.check}><input type="checkbox" checked={draft.confirmed} onChange={event => set("confirmed", event.target.checked)} />I confirm these exact addresses, accounts, objects and actions are authorized within these limits.</label>
      <div className={styles.actions}><button className={styles.primary} type="submit" disabled={!draft.confirmed}>Create the plan</button></div>
    </fieldset>
    {error && <p role="alert" className={styles.condition}>{error}</p>}
  </form>;
}
