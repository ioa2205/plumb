"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { AccessExpectation, AssessmentAnswer, AssessmentChecklist, AssessmentScope, AssessmentView, ComparisonRequest, EvidenceArtifact, EvidenceImportRequest, ObservedMap, ReportPreview } from "../generated/contracts";
import { compareObservations, createAssessment, fetchAssessment, fetchAssessmentChecklist, fetchAssessmentMap, fetchAssessmentReport, importEvidence, MAX_IMPORT_BYTES, parseScope, resolveAssessmentTask, saveExpectation, selectedAssessment, validAssessmentId } from "../lib/assessment-data";
import { Sheet } from "./Workbench";
import { AssessmentOperations } from "./AssessmentOperations";
import { WebsiteScopeForm } from "./WebsiteScopeForm";
import { ConversationPanel } from "./ConversationPanel";
import styles from "./AssessmentPanel.module.css";

type Review = EvidenceImportRequest["review"];
type ObservationContext = NonNullable<EvidenceArtifact["context"]>;
type Citation = NonNullable<AssessmentAnswer["citations"]>[number];
const id = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
function scopeExample(interactive = false): string {
  const now = new Date();
  const scope: AssessmentScope = {scope_id: id("scope"), assessment_id: id("assess"), application_id: "tandir-lab", application_name: "Tandir lab · synthetic development", origin: "http://127.0.0.1:8701", allowed_paths: ["/orders/1042/receipt", "/orders/1042/invoice"], allowed_actions: ["read", "compare", "plan", "report", "analyze"], accounts: [{account_id: "alice", role: "customer", label: "Synthetic owner"}, {account_id: "bob", role: "customer", label: "Synthetic second customer"}], synthetic_objects: [{object_id: "order-1042", owner_account_id: "alice", kind: "Order", synthetic: true, synthetic_marker: "TANDIR-FAKE-1042"}], authority: {granted_by: "Replace with the authorizing person", reference: "Replace with the explicit owned-lab authorization", granted_at: now.toISOString()}, expires_at: new Date(now.getTime() + 86_400_000).toISOString(), budget: {max_requests: 3, max_seconds: 180}, stop_conditions: ["Unexpected real personal information", "Scope escape", "Budget exhausted"], external_access_enabled: false};
  const value: AssessmentScope = interactive ? {...scope, application_id: "owned-tandir", application_name: "Owned Tandir lab · synthetic test mode", allowed_paths: ["/health", "/auth/login", "/orders"], allowed_actions: ["read", "compare", "plan", "report", "analyze", "collect", "authenticate", "create_synthetic"], budget: {max_requests: 30, max_seconds: 600}} : {...scope, application_name: "Tandir lab · offline synthetic example"};
  return JSON.stringify(value, null, 2);
}
function review(by: string): Review { return {reviewed_by: by.trim(), confirmed_sanitized: true, reviewed_at: new Date().toISOString()}; }
const CitationAction = createContext<(artifact: string) => void>(() => {});
function Citations({items}: {items: ReadonlyArray<Citation>}) {
  const select = useContext(CitationAction);
  return <span className={styles.actions}>{items.map((citation, index) => <a key={`${citation.artifact_id}-${citation.field}-${index}`} className={styles.tag} href={`#artifact-${encodeURIComponent(citation.artifact_id)}`} onClick={event => {event.preventDefault(); select(citation.artifact_id);}}>{citation.artifact_id} · {citation.field}</a>)}</span>;
}

export function AssessmentPanel() {
  const [view, setView] = useState<AssessmentView | null>(null);
  const [selection, setSelection] = useState("");
  const [scopeText, setScopeText] = useState("");
  const [authority, setAuthority] = useState(false);
  const [busy, setBusy] = useState(false);
  const [workerActive, setWorkerActive] = useState(false);
  const [analysisProfile, setAnalysisProfile] = useState("auto");
  const [message, setMessage] = useState("");
  const [payload, setPayload] = useState("");
  const [har, setHar] = useState<Record<string, unknown> | null>(null); const [harCount, setHarCount] = useState(0); const [harIndex, setHarIndex] = useState(""); const [harAccount, setHarAccount] = useState(""); const [harObject, setHarObject] = useState(""); const [harSession, setHarSession] = useState(""); const [harRequest, setHarRequest] = useState(""); const [harProvenance, setHarProvenance] = useState("");
  const [reviewedBy, setReviewedBy] = useState("");
  const [sanitized, setSanitized] = useState(false);
  const [screenshotDescription, setScreenshotDescription] = useState(""); const [screenshotProvenance, setScreenshotProvenance] = useState(""); const [screenshotTime, setScreenshotTime] = useState("");
  const [prompt, setPrompt] = useState("");
  const [evidenceIds, setEvidenceIds] = useState<ReadonlyArray<string>>([]);
  const [answer, setAnswer] = useState<AssessmentAnswer | null>(null);
  const [map, setMap] = useState<ObservedMap | null>(null);
  const [checklist, setChecklist] = useState<AssessmentChecklist | null>(null);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [reportReviewed, setReportReviewed] = useState(false);
  const [artifactPage, setArtifactPage] = useState(0);
  const [left, setLeft] = useState(""); const [right, setRight] = useState(""); const [control, setControl] = useState(""); const [expectationId, setExpectationId] = useState("");
  const [path, setPath] = useState(""); const [object, setObject] = useState(""); const [allowedAccounts, setAllowedAccounts] = useState<ReadonlyArray<string>>([]);
  const [statement, setStatement] = useState(""); const [basis, setBasis] = useState(""); const [declaredBy, setDeclaredBy] = useState("");
  const active = useRef<AbortController | null>(null);
  const assessmentId = view?.scope.assessment_id;
  const refreshAfterWorker = useCallback(() => {
    if (!assessmentId) return;
    const controller = new AbortController();
    void fetchAssessment(assessmentId, controller.signal).then(value => {setView(value); setMap(null); setChecklist(null); setPreview(null); setReportReviewed(false);}).catch(error => setMessage(error instanceof Error ? error.message : "Reload this saved assessment to read the worker result."));
  }, [assessmentId]);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    try {
      const value = selectedAssessment(window.location.search);
      if (value) { setSelection(value); void perform("Reading the saved local assessment…", async signal => { adopt(await fetchAssessment(value, signal)); return "Saved assessment loaded. Imported evidence remains separate from executed tests."; }); }
    } catch (error) { setMessage(error instanceof Error ? error.message : "Enter a valid local assessment ID."); }
    // Selection is restored once; later loads use the explicit controls below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const stopped = !!view?.stopped;
  const expired = !!view && Date.parse(view.scope.expires_at) <= Date.now();
  const blocked = busy || workerActive || stopped || expired;
  const artifacts = view?.artifacts ?? [];
  function adopt(value: AssessmentView) {
    setView(value); setSelection(value.scope.assessment_id); setMap(null); setChecklist(null); setPreview(null); setReportReviewed(false); setEvidenceIds([]); setArtifactPage(0);
    setHar(null); setPayload(""); setSanitized(false); setLeft(""); setRight(""); setControl(""); setExpectationId("");
    setPath(value.scope.allowed_paths[0] ?? ""); setObject(value.scope.synthetic_objects?.[0]?.object_id ?? "");
    const url = new URL(window.location.href); url.searchParams.set("assessment", value.scope.assessment_id); window.history.replaceState(null, "", url);
  }
  async function perform(start: string, action: (signal: AbortSignal) => Promise<string>) {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller; const timer = setTimeout(() => controller.abort(), 90_000);
    setBusy(true); setMessage(start);
    try { const result = await action(controller.signal); if (!controller.signal.aborted) setMessage(result); }
    catch (error) { setMessage(controller.signal.aborted ? "The browser wait ended. Read the saved local status before retrying; work may still be finishing." : error instanceof Error ? error.message : "The assessment action could not complete."); }
    finally { clearTimeout(timer); active.current = null; setBusy(false); }
  }
  async function readFile(file: File | undefined) {
    if (!file) return;
    if (file.size > MAX_IMPORT_BYTES) { setMessage("This file exceeds the 2 MiB import limit. Select only the sanitized entries needed for the assessment."); return; }
    const text = await file.text(); setPayload(text); setSanitized(false); setHar(null);
    try {const value: unknown = JSON.parse(text); if (value && typeof value === "object" && "log" in value && value.log && typeof value.log === "object" && "entries" in value.log && Array.isArray(value.log.entries)) {if (!value.log.entries.length || value.log.entries.length > 100) throw new Error("Select a bounded HAR containing 1–100 entries."); setHar(value as Record<string, unknown>); setHarCount(value.log.entries.length); setHarIndex(""); setMessage("HAR loaded as inert data. Select one entry and declare its designated context before preparing the import."); return;}} catch (error) {if (error instanceof Error && error.message.startsWith("Select a bounded")) {setMessage(error.message); setPayload(""); return;}}
    setMessage("File copied into the local input. Review it for secrets and personal information before importing.");
  }
  function prepareHarEntry() {
    if (!har || !harIndex || !harAccount || !harObject || !harSession.trim() || !harRequest.trim() || !harProvenance.trim()) {setMessage("Select a HAR entry and fill all designated collection context fields."); return;}
    const index = Number(harIndex); if (!Number.isInteger(index) || index < 0 || index >= harCount) return;
    const context: ObservationContext = {account_id: harAccount, object_id: harObject, session_context_id: harSession.trim(), request_context_id: harRequest.trim()};
    setPayload(JSON.stringify({har, selected_entries: [index], contexts: {[index]: context}, provenance: harProvenance.trim()}, null, 2)); setSanitized(false); setMessage("One explicitly selected HAR entry is prepared. Review the sanitized attachment and confirm its designated context before importing.");
  }
  async function readScreenshot(file: File | undefined) {
    if (!file) return;
    if (file.type !== "image/png" || file.size > 1024 * 1024 || !screenshotTime.trim() || !screenshotProvenance.trim() || !screenshotDescription.trim()) {setMessage("Enter the screenshot's collection time, provenance and description, then select a reviewed PNG of at most 1 MiB."); return;}
    const bytes = new Uint8Array(await file.arrayBuffer()); let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    setPayload(JSON.stringify({records: [{kind: "screenshot", collected_at: screenshotTime.trim(), provenance: screenshotProvenance.trim(), description: screenshotDescription.trim(), content_base64: btoa(binary)}]}, null, 2));
    setSanitized(false); setMessage("Screenshot copied into the inert input. Confirm human review of its pixels before importing; no image understanding is performed.");
  }
  function download(text: string, name: string) {
    const url = URL.createObjectURL(new Blob([text], {type: "text/markdown;charset=utf-8"}));
    const link = document.createElement("a"); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function selectArtifact(identity: string) {
    const index = artifacts.findIndex(artifact => artifact.artifact_id === identity); if (index < 0) return;
    setArtifactPage(Math.floor(index / 20));
    setTimeout(() => {const element = document.getElementById(`artifact-${encodeURIComponent(identity)}`); if (element instanceof HTMLDetailsElement) {element.open = true; element.querySelector("summary")?.focus(); element.scrollIntoView({block: "start", behavior: "instant"});}}, 0);
  }
  return <CitationAction.Provider value={selectArtifact}><Sheet title="Private web assessment" description="Work with authorized, sanitized observations on this computer. Prompts resolve to bounded tasks; imported evidence keeps its collection context and limitations.">
    <p className={styles.condition}>External website access is disabled. Use designated test accounts and synthetic objects. Unexpected sensitive information requires stopping collection and preparing a private incident report.</p>
    {!view && <WebsiteScopeForm disabled={busy} onCreated={value => {adopt(value); setAnswer(null); setMessage("Approved website scope saved. Preview the bounded owned-lab actions, review collected evidence, analyze both comparisons and preview the private report.");}} />}
    <section className={styles.section} aria-labelledby="assessment-open"><h2 id="assessment-open">Open a saved assessment</h2>
      <form className={styles.form} onSubmit={event => {event.preventDefault(); void perform("Reading the saved local assessment…", async signal => {if (!validAssessmentId(selection.trim())) throw new Error("Enter the assessment ID printed by Plumb."); adopt(await fetchAssessment(selection.trim(), signal)); setAnswer(null); return "Saved assessment loaded. No model or website request started.";});}}>
        <label>Assessment ID<input value={selection} onChange={event => setSelection(event.target.value)} required maxLength={128} autoComplete="off" spellCheck={false} /></label>
        <button className={styles.button} disabled={busy} type="submit">Open assessment</button>
      </form>
      <details className={styles.section}><summary>Create an explicit assessment scope</summary><p>Record the real authority, expiry, allowed paths/actions, designated accounts, synthetic objects and stop conditions. A prompt cannot grant this authority.</p>
        <form className={styles.form} onSubmit={event => {event.preventDefault(); void perform("Validating the explicit scope…", async signal => {let value: unknown; try {value = JSON.parse(scopeText);} catch {throw new Error("Scope must be valid JSON matching the assessment contract.");} adopt(await createAssessment(parseScope(value), authority, signal)); setAuthority(false); setAnswer(null); return "Scope saved locally. External website access stays disabled.";});}}>
          <div className={styles.actions}><button className={styles.quiet} type="button" disabled={busy} onClick={() => {setScopeText(scopeExample()); setAuthority(false);}}>Fill an offline Tandir example</button><button className={styles.quiet} type="button" disabled={busy} onClick={() => {setScopeText(scopeExample(true)); setAuthority(false);}}>Fill an owned-lab test example</button></div>
          <label>Assessment scope JSON<textarea rows={12} value={scopeText} onChange={event => {setScopeText(event.target.value); setAuthority(false);}} maxLength={65536} required spellCheck={false} /></label>
          <label className={styles.check}><input type="checkbox" checked={authority} onChange={event => setAuthority(event.target.checked)} required /><span>I confirm this recorded authority and its limits.</span></label>
          <button className={styles.button} type="submit" disabled={busy || !authority}>Create local assessment</button>
        </form>
      </details>
    </section>
    <p className={styles.message} role="status">{message}</p>
    {view && <>
      <section className={styles.section} aria-labelledby="website-steps"><h2 id="website-steps">Website workflow</h2><ol><li>Approved URL and scope: saved. Exact collection action approval is separate.</li><li>Collect bounded evidence, then review it: {artifacts.length ? `${artifacts.length} reviewed exhibits saved.` : "Awaiting collection or reviewed import."}</li><li>Prepare comparisons with declared access and protected controls: {view.comparisons?.length ?? 0} saved.</li><li>Analyze with three local judgments per comparison: {view.analyses?.filter(item => item.generated_by === "local_model").length ?? 0} saved. Failed, canceled and inconclusive results retain their limitations.</li><li>Preview and save the private report below after human review.</li></ol><a className={styles.button} href="#operations-title">Continue collection or analysis</a></section>
      <section className={styles.section} aria-labelledby="scope-title"><h2 id="scope-title">{view.scope.application_name}</h2>
        <dl className={styles.facts}><div><dt>Saved assessment</dt><dd><code>{view.scope.assessment_id}</code></dd></div><div><dt>Authorized origin</dt><dd><code>{view.scope.origin}</code></dd></div><div><dt>Authority</dt><dd>{view.scope.authority.granted_by} · {view.scope.authority.reference}</dd></div><div><dt>Expiry</dt><dd>{view.scope.expires_at}</dd></div><div><dt>Budget</dt><dd>{view.scope.budget?.max_requests} requests · {view.scope.budget?.max_seconds} seconds</dd></div><div><dt>Allowed actions</dt><dd>{view.scope.allowed_actions.join(", ")}</dd></div></dl>
        <p>Consumed budget: {view.spent_requests ?? 0} requests · {Math.ceil(view.spent_seconds ?? 0)} seconds. Remaining: {Math.max(0, (view.scope.budget?.max_requests ?? 3) - (view.spent_requests ?? 0))} requests · {Math.max(0, Math.floor((view.scope.budget?.max_seconds ?? 180) - (view.spent_seconds ?? 0)))} seconds. Failed and canceled work also consumes the saved lifetime budget.</p>
        <p>Allowed paths: {view.scope.allowed_paths.map(value => <code key={value}>{value} </code>)}</p>
        <p>Designated roles: {view.scope.accounts.map(account => `${account.label} (${account.account_id}, ${account.role})`).join("; ")}.</p>
        <p>Synthetic objects: {view.scope.synthetic_objects?.map(item => `${item.object_id}, owner ${item.owner_account_id}`).join("; ") || "None declared"}.</p>
        <p>Stop conditions: {view.scope.stop_conditions.join("; ")}.</p>
        {(stopped || expired) && <p className={styles.condition}>{stopped ? `Assessment stopped: ${view.stop_reason}` : "The recorded scope expired. Further imports and analysis are refused; saved results can still be read."}</p>}
      </section>
      <section className={styles.section} aria-labelledby="import-title"><h2 id="import-title">Import reviewed observations</h2><p>Use selected HAR entries, request/response records, notes or a reviewed screenshot envelope. Files remain inert: embedded URLs are never fetched and imported HTML is displayed as text.</p>
        <form className={styles.form} onSubmit={event => {event.preventDefault(); void perform("Sanitizing and validating the reviewed input…", async signal => {if (!sanitized) throw new Error("Review the input before importing."); try {const value = await importEvidence(view, payload, review(reviewedBy), signal); adopt(value); setPayload(""); setSanitized(false); setAnswer(null); return value.stopped ? `Assessment stopped: ${value.stop_reason}. The original input was discarded; prepare the private incident report.` : "Reviewed artifacts saved locally with hashes and collection provenance.";} catch (error) {try {const saved = await fetchAssessment(view.scope.assessment_id, signal); if (saved.stopped) {adopt(saved); setPayload(""); setSanitized(false); setAnswer(null); return `Assessment stopped: ${saved.stop_reason}. The original input was discarded; prepare the private incident report.`;}} catch {/* Preserve the original local error when rereading is unavailable. */} throw error;}});}}>
          <label>Sanitized JSON or selected HAR file<input type="file" accept=".json,.har,application/json" onChange={event => {void readFile(event.target.files?.[0]); event.target.value = "";}} disabled={blocked} /></label>
          {har && <fieldset><legend>Select an inert HAR entry</legend><p>Only the selected entry becomes evidence. Import each account context separately.</p><label>Entry index (zero based)<select value={harIndex} onChange={event => setHarIndex(event.target.value)}><option value="">Select one of {harCount} entries</option>{Array.from({length: harCount}, (_, index) => <option key={index} value={String(index)}>Entry {index}</option>)}</select></label><label>Designated account<select value={harAccount} onChange={event => setHarAccount(event.target.value)}><option value="">Select an account</option>{view.scope.accounts.map(account => <option key={account.account_id} value={account.account_id}>{account.label} · {account.role}</option>)}</select></label><label>Designated synthetic object<select value={harObject} onChange={event => setHarObject(event.target.value)}><option value="">Select a synthetic object</option>{view.scope.synthetic_objects?.map(item => <option key={item.object_id} value={item.object_id}>{item.object_id}</option>)}</select></label><label>Session context ID<input value={harSession} maxLength={128} onChange={event => setHarSession(event.target.value)} /></label><label>Request comparison context ID<input value={harRequest} maxLength={128} onChange={event => setHarRequest(event.target.value)} /></label><label>Collection provenance<input value={harProvenance} maxLength={4096} onChange={event => setHarProvenance(event.target.value)} /></label><button type="button" className={styles.button} onClick={prepareHarEntry} disabled={blocked}>Prepare selected HAR entry</button></fieldset>}
          <label>Import payload<textarea rows={7} value={payload} onChange={event => {setPayload(event.target.value); setSanitized(false);}} maxLength={MAX_IMPORT_BYTES} required spellCheck={false} /></label>
          <details><summary>Record, selected HAR and note formats</summary><pre className={styles.evidence}>{JSON.stringify({records: [{collected_at: "2026-10-10T00:00:00Z", provenance: "Owned Tandir fixture; captured manually", context: {account_id: "bob", object_id: "order-1042", session_context_id: "bob-session", request_context_id: "receipt-test"}, request: {method: "GET", url: "http://127.0.0.1:8701/orders/1042/receipt", headers: {}}, response: {status: 200, headers: {}, body: "TANDIR-FAKE-1042"}}]}, null, 2)}</pre><p>HAR envelope: <code>{'{"har":{"log":{"entries":[...] }},"selected_entries":[0],"contexts":{"0":{"account_id":"bob","object_id":"order-1042","session_context_id":"bob-session","request_context_id":"receipt-test"}},"provenance":"Manual sanitized capture"}'}</code></p><p>Note record: <code>{'{"records":[{"kind":"note","collected_at":"2026-10-10T00:00:00Z","provenance":"Human statement","text":"Expected access is declared separately."}]}'}</code></p><p>Set collection times and contexts to the actual capture. Human review is required for headers, cookies, URLs, bodies and screenshot pixels.</p></details>
          <details><summary>Attach a reviewed screenshot</summary><p>PNG only, at most 1 MiB. The backend strips image metadata and stores the attachment privately. Review screenshot pixels yourself before import.</p><label>Collection time with timezone<input placeholder="2026-10-10T00:00:00Z" value={screenshotTime} maxLength={100} onChange={event => setScreenshotTime(event.target.value)} /></label><label>Collection provenance<input value={screenshotProvenance} maxLength={4096} onChange={event => setScreenshotProvenance(event.target.value)} /></label><label>Human screenshot description<input value={screenshotDescription} maxLength={4096} onChange={event => setScreenshotDescription(event.target.value)} /></label><label>Reviewed PNG<input type="file" accept="image/png,.png" disabled={blocked} onChange={event => {void readScreenshot(event.target.files?.[0]); event.target.value = "";}} /></label></details>
          <label>Human reviewer<input value={reviewedBy} onChange={event => setReviewedBy(event.target.value)} maxLength={256} required autoComplete="off" /></label>
          <label className={styles.check}><input type="checkbox" checked={sanitized} onChange={event => setSanitized(event.target.checked)} required /><span>I reviewed all selected evidence and removed credentials and real personal information.</span></label>
          <button className={styles.button} type="submit" disabled={blocked || !sanitized}>Import reviewed evidence</button>
        </form>
      </section>
      <section className={styles.section} aria-labelledby="prompt-title"><h2 id="prompt-title">Ask about this evidence</h2><p>Resolve a task, explain an observation, compare selected artifacts, ask what is missing or prepare a checklist/report. Resolution starts no website interaction or model analysis.</p>
        <form className={styles.form} onSubmit={event => {event.preventDefault(); void perform("Resolving the bounded task against saved evidence…", async signal => {const result = await resolveAssessmentTask(view, {prompt: prompt.trim(), evidence_ids: evidenceIds, budget: view.scope.budget}, signal); setAnswer(result); return result.task.status === "resolved" ? "Task resolved locally. Read its scope, citations and unknowns." : result.task.clarification || "Clarify the task before proceeding.";});}}>
          <label>Instruction<textarea rows={3} maxLength={4096} value={prompt} onChange={event => setPrompt(event.target.value)} required placeholder="What evidence is missing before this can be reported?" /></label>
          <details><summary>Select up to three saved artifacts</summary>{artifacts.length ? artifacts.map(artifact => <label className={styles.check} key={artifact.artifact_id}><input type="checkbox" checked={evidenceIds.includes(artifact.artifact_id)} disabled={!evidenceIds.includes(artifact.artifact_id) && evidenceIds.length >= 3} onChange={event => setEvidenceIds(previous => event.target.checked ? [...previous, artifact.artifact_id] : previous.filter(value => value !== artifact.artifact_id))} /><span>{artifact.artifact_id} · {artifact.kind}</span></label>) : <p>Import reviewed artifacts first.</p>}</details>
          <button className={styles.primary} type="submit" disabled={blocked}>Resolve task</button>
        </form>
        {answer && <div className={styles.row}><h3>Resolved task: {answer.task.action.replaceAll("_", " ")}</h3><p>{(answer.task.status ?? "resolved").replaceAll("_", " ")} · target <code>{answer.task.target_id}</code> · {answer.generated_by === "local_model" ? "Local model" : "Deterministic evidence answer"}</p><p>{answer.task.clarification}</p><p>{answer.text}</p><Citations items={answer.citations ?? []} /><ul>{answer.unknowns?.map((item, index) => <li key={index}>{item}</li>)}</ul><p className={styles.meta}>A resolved instruction grants no authority and starts no network activity.</p></div>}
        {!!view.answers?.length && <details className={styles.section}><summary>Saved answers ({view.answers.length})</summary><ul className={styles.list}>{view.answers.slice(-20).map(item => <li className={styles.row} key={item.answer_id}><p>{item.text}</p><Citations items={item.citations ?? []} /><p className={styles.meta}>{item.task.status} · {item.generated_by}</p></li>)}</ul><p>Showing the latest {Math.min(20, view.answers.length)} saved answers.</p></details>}
      </section>
      <section className={styles.section} aria-labelledby="map-title"><h2 id="map-title">Observed endpoints and manual checklist</h2><p>This map covers imported observations. A planned check is never counted as an executed test.</p>
        <button className={styles.button} disabled={busy} onClick={() => {void perform("Reading the observed map and checklist…", async signal => {const [nextMap, nextChecklist] = await Promise.all([fetchAssessmentMap(view, signal), fetchAssessmentChecklist(view.scope.assessment_id, signal)]); setMap(nextMap); setChecklist(nextChecklist); return "Map and checklist loaded from the saved imported evidence.";});}}>Load map and checklist</button>
        {map && <><table className={styles.table}><caption>{map.endpoints?.length ?? 0} endpoints observed in imported artifacts</caption><thead><tr><th scope="col">Endpoint</th><th scope="col">Accounts / objects</th><th scope="col">Evidence</th></tr></thead><tbody>{map.endpoints?.map(endpoint => <tr key={endpoint.endpoint_id}><td><code>{endpoint.method} {endpoint.path}</code><p>Imported observation</p></td><td>{endpoint.account_ids.join(", ")}<p>{endpoint.object_ids.join(", ")}</p></td><td><Citations items={endpoint.citations} /></td></tr>)}</tbody></table><ul>{map.unknowns.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
        {checklist && <><ul className={styles.list}>{checklist.items.map(item => <li className={styles.row} key={item.check_id}><h3><code>{item.path}</code></h3><p className={styles.proposed}>Manual plan · {(item.status ?? "planned").replaceAll("_", " ")}</p><p>{item.instructions}</p><p>{item.account_ids.join(", ")} · {item.object_ids.join(", ")}</p><ul>{item.limitations?.map((text, index) => <li key={index}>{text}</li>)}</ul></li>)}</ul><p>Untested paths: {checklist.untested_paths.join(", ") || "See the limitations; imported observations are not trusted execution."}</p></>}
      </section>
      <section className={styles.section} aria-labelledby="expected-title"><h2 id="expected-title">Declare expected access</h2><p>Record the expectation and its basis separately from actual observations.</p>
        <form className={styles.form} onSubmit={event => {event.preventDefault(); void perform("Saving the declared expectation…", async signal => {const expectation: AccessExpectation = {expectation_id: id("expectation"), path, object_id: object, allowed_account_ids: allowedAccounts, statement: statement.trim(), declared_by: declaredBy.trim(), basis: basis.trim()}; adopt(await saveExpectation(view, expectation, signal)); return "Expected access saved with its declared basis.";});}}>
          <label>Allowed endpoint<select required value={path} onChange={event => setPath(event.target.value)}>{view.scope.allowed_paths.map(value => <option value={value} key={value}>{value}</option>)}</select></label>
          <label>Synthetic object<select required value={object} onChange={event => setObject(event.target.value)}><option value="">Select a declared object</option>{view.scope.synthetic_objects?.map(item => <option value={item.object_id} key={item.object_id}>{item.object_id}</option>)}</select></label>
          <fieldset><legend>Accounts expected to have access</legend>{view.scope.accounts.map(account => <label className={styles.check} key={account.account_id}><input type="checkbox" checked={allowedAccounts.includes(account.account_id)} onChange={event => setAllowedAccounts(previous => event.target.checked ? [...previous, account.account_id] : previous.filter(value => value !== account.account_id))} /><span>{account.label} · {account.role}</span></label>)}</fieldset>
          <label>Expected behavior<input required maxLength={4096} value={statement} onChange={event => setStatement(event.target.value)} /></label><label>Declared basis<input required maxLength={4096} value={basis} onChange={event => setBasis(event.target.value)} /></label><label>Declared by<input required maxLength={256} value={declaredBy} onChange={event => setDeclaredBy(event.target.value)} /></label>
          <button className={styles.button} type="submit" disabled={blocked || !object || !allowedAccounts.length}>Save expectation</button>
        </form>
      </section>
      <section className={styles.section} aria-labelledby="comparison-title"><h2 id="comparison-title">Expected versus observed</h2><p>Compare designated account contexts and a legitimate control. A successful HTTP response alone cannot prove unauthorized access.</p>
        <form className={styles.form} onSubmit={event => {event.preventDefault(); void perform("Checking the comparison and its counterevidence…", async signal => {const input: ComparisonRequest = {left_artifact_id: left, right_artifact_id: right, control_artifact_id: control || null, expectation_id: expectationId || null}; const comparison = await compareObservations(view, input, signal); adopt(await fetchAssessment(view.scope.assessment_id, signal)); return `Comparison saved: ${comparison.conclusion}. Imported observations remain distinct from trusted reproduction.`;});}}>
          {([["First observation", left, setLeft], ["Second observation", right, setRight], ["Legitimate control", control, setControl]] as const).map(([label, value, change]) => <label key={label}>{label}<select value={value} onChange={event => change(event.target.value)} required={label !== "Legitimate control"}><option value="">{label === "Legitimate control" ? "No control supplied" : "Select an artifact"}</option>{artifacts.filter(artifact => artifact.kind === "request_response").map(artifact => <option key={artifact.artifact_id} value={artifact.artifact_id}>{artifact.artifact_id} · {artifact.context?.account_id}</option>)}</select></label>)}
          <label>Declared expectation<select value={expectationId} onChange={event => setExpectationId(event.target.value)}><option value="">No expectation supplied</option>{view.expectations?.map(item => <option value={item.expectation_id} key={item.expectation_id}>{item.statement}</option>)}</select></label>
          <button className={styles.button} type="submit" disabled={blocked || !left || !right}>Compare observations</button>
        </form>
        <ul className={styles.list}>{view.comparisons?.slice(-20).map(comparison => <li className={styles.row} key={comparison.comparison_id}><h3>{comparison.conclusion}</h3><p>{comparison.summary}</p><Citations items={comparison.citations ?? []} /><h3>Missing evidence</h3><ul>{comparison.missing_evidence?.map((text, index) => <li key={index}>{text}</li>)}</ul><h3>Alternative explanations</h3><ul>{comparison.alternative_explanations?.map((text, index) => <li key={index}>{text}</li>)}</ul><p className={styles.meta}>Imported evidence · trusted runtime verification not attempted.</p></li>)}</ul>
      </section>
      <AssessmentOperations key={view.scope.assessment_id} view={view} disabled={busy || stopped || expired} onActive={setWorkerActive} onRefresh={refreshAfterWorker} profile={analysisProfile} onProfileChange={setAnalysisProfile} /><ConversationPanel key={`conversation-${view.scope.assessment_id}`} target={{target_kind: "assessment", target_id: view.scope.assessment_id}} profile={analysisProfile} />
      <section className={styles.section} aria-labelledby="report-title"><h2 id="report-title">Private report</h2><p>Preview description, endpoints, safe reproduction, impact, mitigation, tools, methodology and limitations. Saving creates a local private report; there is no submission or upload.</p>
        <button className={styles.button} disabled={busy} onClick={() => {void perform("Preparing the sanitized private preview…", async signal => {setPreview(await fetchAssessmentReport(view, signal)); setReportReviewed(false); return "Private preview prepared. Review the full sanitized text before saving.";});}}>Preview private report</button>
        {preview && <><pre className={styles.report}>{preview.markdown}</pre><div className={styles.form}><label className={styles.check}><input type="checkbox" checked={reportReviewed} onChange={event => setReportReviewed(event.target.checked)} /><span>I reviewed this sanitized private report, its citations and limitations.</span></label><label>Report reviewer<input required value={reviewedBy} maxLength={256} onChange={event => setReviewedBy(event.target.value)} /></label><button className={styles.button} disabled={busy || !reportReviewed || !reviewedBy.trim()} onClick={() => {void perform("Saving the human-reviewed private report…", async signal => {const saved = await fetchAssessmentReport(view, signal, {review:review(reviewedBy),preview_sha256:preview.preview_sha256}); setPreview(saved); if(saved.markdown!==preview.markdown){setReportReviewed(false);return "The report changed while being reviewed. Read the new sanitized preview before downloading.";} download(saved.markdown, `${view.scope.assessment_id}-private-report.md`); return "Private report saved locally and downloaded. Nothing was submitted or uploaded.";});}}>Save and download private report</button></div></>}
      </section>
      <section className={styles.section} aria-labelledby="artifact-title"><h2 id="artifact-title">Imported exhibits ({artifacts.length})</h2><p>Each exhibit retains its field citations, hash, provenance and human attachment review. Screenshots are attachments; no image interpretation is claimed.</p>
        {artifacts.slice(artifactPage * 20, (artifactPage + 1) * 20).map(artifact => <details className={`${styles.row} ${styles.artifact}`} key={artifact.artifact_id} id={`artifact-${encodeURIComponent(artifact.artifact_id)}`}><summary>{artifact.artifact_id} · {artifact.kind.replaceAll("_", " ")} · imported</summary><p>{artifact.provenance}</p><p className={styles.meta}>Collected {artifact.collected_at} · reviewed by {artifact.review.reviewed_by}</p><p className={styles.meta}><code>SHA-256 {artifact.sha256}</code></p>{artifact.context && <p>Account {artifact.context.account_id} · object {artifact.context.object_id} · session {artifact.context.session_context_id} · request {artifact.context.request_context_id}</p>}<pre className={styles.evidence}>{Object.entries(artifact.fields).map(([key, value]) => `${key}: ${value}`).join("\n")}</pre></details>)}
        {artifacts.length > 20 && <div className={styles.actions}><button className={styles.button} disabled={artifactPage === 0} onClick={() => setArtifactPage(page => page - 1)}>Previous exhibits</button><span>Showing {artifactPage * 20 + 1}–{Math.min((artifactPage + 1) * 20, artifacts.length)} of {artifacts.length}</span><button className={styles.button} disabled={(artifactPage + 1) * 20 >= artifacts.length} onClick={() => setArtifactPage(page => page + 1)}>Next exhibits</button></div>}
      </section>
    </>}
  </Sheet></CitationAction.Provider>;
}
