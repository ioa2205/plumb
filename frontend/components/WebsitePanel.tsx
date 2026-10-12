"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { HumanAuthInput, JourneyList, JourneyView, WebsiteReadiness } from "../generated/contracts";
import type { LiveHumanAuthView } from "../lib/website-data";
import { activityCounts, rungWords, selectedJourney, statusWords, stepWords, waitWords, websiteHuman, websiteHumanInput, websiteList, websiteReadiness, websiteReport, websiteRequest } from "../lib/website-data";
import { Glyph } from "./Glyph";
import { Sheet } from "./Workbench";
import { WebsiteSetupForm } from "./WebsiteSetupForm";
import styles from "./AssessmentPanel.module.css";
import ask from "./Ask.module.css";

type Journey = NonNullable<JourneyList["journeys"]>[number];

/** The person controls this private view. It is never a model tool or saved evidence. */
function HumanAuthPanel({journeyId, onUpdate}: {journeyId: string; onUpdate: (value: JourneyView) => void}) {
  const [human, setHuman] = useState<LiveHumanAuthView | null>(null);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  const [message, setMessage] = useState("Opening the private sign-in view.");
  const image = useRef<HTMLImageElement | null>(null);
  const acting = useRef(false);
  const refreshing = useRef(false);
  const revision = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    async function refresh() {
      if (acting.current || refreshing.current) return;
      refreshing.current = true;
      const current = revision.current;
      try {
        const value = await websiteHuman(journeyId, controller.signal);
        if (!mounted.current || current !== revision.current) return;
        setHuman(value);
        if (value) setMessage("");
        else {
          setText("");
          setMessage("The private browser is closed. Read the test status and choose whether to continue.");
          const view = await websiteRequest(`/api/websites/${journeyId}`, undefined, controller.signal);
          if (mounted.current) onUpdate(view);
        }
      } catch {
        if (!controller.signal.aborted && mounted.current && current === revision.current) {
          setHuman(null); setText("");
          setMessage("The private sign-in view cannot be reached. Check the test status.");
        }
      } finally {refreshing.current = false;}
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    return () => {mounted.current = false; clearInterval(timer); controller.abort();};
  }, [journeyId, onUpdate]);

  async function send(input: Omit<HumanAuthInput, "view_id">) {
    if (acting.current || !human?.ready) return;
    acting.current = true; revision.current++; setBusy(true); setText(""); setMessage("");
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 30_000);
    try {
      const value = await websiteHumanInput(journeyId, {...input, view_id: human.view_id}, controller.signal);
      if (mounted.current) {
        setHuman(value);
        setMessage(value ? "The private view is updated." : "Reading the sign-in result.");
        const view = await websiteRequest(`/api/websites/${journeyId}`, undefined, controller.signal);
        if (mounted.current) onUpdate(view);
      }
    } catch {
      if (mounted.current) {
        setText("");
        setMessage("The challenge action did not complete. Refresh the private view before trying again.");
      }
    } finally {
      clearTimeout(timer); acting.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const available = !!human?.ready && !busy;
  const pointValid = human && /^\d+$/.test(x) && /^\d+$/.test(y) && Number(x) < human.width && Number(y) < human.height;
  return <section className={styles.section} aria-labelledby="human-auth-title">
    <h2 id="human-auth-title">{human ? `Complete sign-in for ${human.label}` : "Complete the sign-in challenge"}</h2>
    {human && <>
      <p className={styles.condition}>{human.question}</p>
      <p>Click a field or challenge in the private view below. Enter text with the field underneath, then submit the challenge when it is ready.</p>
      <button className={`${styles.button} ${styles.humanSurface}`} type="button" disabled={!available} aria-label="Click in the private sign-in view; keyboard users can use the coordinate controls below" onClick={event => {
        const bounds = image.current?.getBoundingClientRect();
        if (!bounds || event.detail === 0) {setMessage("Use the keyboard coordinate controls below to choose a point."); return;}
        const px = Math.floor((event.clientX - bounds.left) * human.width / bounds.width);
        const py = Math.floor((event.clientY - bounds.top) * human.height / bounds.height);
        if (px < 0 || py < 0 || px >= human.width || py >= human.height) return;
        setX(String(px)); setY(String(py)); void send({kind: "pointer", x: px, y: py});
      }}>
        {/* The API accepts only a bounded PNG; no target markup is embedded in Plumb. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img ref={image} src={`data:image/png;base64,${human.screenshot_png}`} width={human.width} height={human.height} alt={`Private ${human.challenge.replaceAll("_", " ")} page for ${human.label}; input values are hidden`} />
      </button>
      <p className={styles.meta}>This view and entered text stay in memory. They are never sent to the model or saved in the test, logs or report. Input values are hidden in the picture.</p>
      <form className={styles.form} onSubmit={event => {event.preventDefault(); if (text) void send({kind: "text", text});}}>
        <label>Text for the selected field<input type="password" autoComplete="off" spellCheck={false} maxLength={1024} disabled={!available} value={text} onChange={event => setText(event.target.value)} /></label>
        <div className={styles.actions}><button className={styles.button} type="submit" disabled={!available || !text}>Send text to the selected field</button></div>
      </form>
      <details className={styles.form}><summary>Use keyboard coordinates</summary>
        <p className={styles.meta}>The private view is {human.width} by {human.height} pixels. Coordinates start at the top left.</p>
        <label>Horizontal position<input type="number" min={0} max={human.width - 1} value={x} disabled={!available} onChange={event => setX(event.target.value)} /></label>
        <label>Vertical position<input type="number" min={0} max={human.height - 1} value={y} disabled={!available} onChange={event => setY(event.target.value)} /></label>
        <div className={styles.actions}><button className={styles.button} type="button" disabled={!available || !pointValid} onClick={() => void send({kind: "pointer", x: Number(x), y: Number(y)})}>Click this position</button></div>
      </details>
      <div className={`${styles.actions} ${styles.humanActions}`}>
        <button className={styles.button} type="button" disabled={!available} onClick={() => void send({kind: "submit"})}>Submit challenge</button>
        <button className={styles.primary} type="button" disabled={!available} onClick={() => void send({kind: "completed"})}>Check sign-in and continue</button>
        <button className={styles.quiet} type="button" disabled={!available} onClick={() => void send({kind: "refresh"})}>Refresh private view</button>
        <button className={styles.quiet} type="button" disabled={!available} onClick={() => void send({kind: "pause"})}>Pause and close the browser</button>
      </div>
      <p className={styles.meta}>Checking sign-in uses the success condition you approved. It does not submit the original sign-in or sign-up again.</p>
    </>}
    <p role="status" className={styles.message}>{message}</p>
  </section>;
}

/** Scope, plan, approval and run are separate steps. Nothing is visited before the last one. */
export function WebsitePanel() {
  const [view, setView] = useState<JourneyView | null>(null);
  const [journeys, setJourneys] = useState<Journey[] | null>(null);
  const [ready, setReady] = useState<WebsiteReadiness | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [useModel, setUseModel] = useState(true);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [report, setReport] = useState("");
  const polling = useRef<AbortController | null>(null);

  const call = useCallback(async <T,>(work: (signal: AbortSignal) => Promise<T>, seconds = 60): Promise<T | null> => {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), seconds * 1000);
    try {return await work(controller.signal);}
    catch (error) {setMessage(error instanceof Error ? error.message : "The request did not complete."); return null;}
    finally {clearTimeout(timer);}
  }, []);

  const open = useCallback((value: JourneyView | null) => {
    setView(value); setReport(""); setReviewed(false); setAnswers({});
    const url = new URL(window.location.href);
    if (value) url.searchParams.set("journey", value.journey_id); else url.searchParams.delete("journey");
    window.history.replaceState(null, "", url);
  }, []);

  useEffect(() => {
    void call(websiteReadiness).then(value => {if (value) setReady(value);});
    void call(websiteList).then(value => {if (value) setJourneys([...(value.journeys ?? [])]);});
    let id: string | null = null;
    try {id = selectedJourney(window.location.search);} catch {setMessage("Use one valid website test ID."); return;}
    if (id) void call(signal => websiteRequest(`/api/websites/${id}`, undefined, signal)).then(value => {if (value) setView(value);});
    return () => polling.current?.abort();
  }, [call]);

  useEffect(() => {
    if (!view || !["running", "handoff"].includes(view.status ?? "")) return;
    const controller = new AbortController(); polling.current = controller;
    const timer = setInterval(() => {
      websiteRequest(`/api/websites/${view.journey_id}`, undefined, controller.signal).then(value => {setView(value); setMessage(value.activity ?? "");}).catch(() => {});
    }, 900);
    return () => {clearInterval(timer); controller.abort();};
  }, [view]);

  async function act(path: string, body: Parameters<typeof websiteRequest>[1], seconds = 60) {
    if (busy) return;
    setBusy(true); setMessage("");
    const value = await call(signal => websiteRequest(path, body, signal), seconds);
    if (value) {open(value); setMessage(value.activity ?? "");}
    setBusy(false);
  }
  const counts = view ? activityCounts(view) : null;
  const summary = new Map((view?.plan.steps ?? []).map(step => [step.step_id, step]));
  const provisioned = (view?.scope.accounts ?? []).filter(account => account.provisioned !== false);
  const needsSecrets = view?.scope.mode === "external" && provisioned.length > 0;
  const canRun = view && ["approved", "paused"].includes(view.status ?? "");

  return <Sheet title="Website test" description="Test a website you are authorized to test, inside limits you approve first. Plumb visits only what the scope names, uses only the test accounts you give it, and writes a private report of what it did and saw.">
    <section className={styles.section} aria-label="Readiness">
      <dl className={styles.facts}>
        <div><dt>Browser</dt><dd>{ready ? ready.browser_note : "Checking."}</dd></div>
        <div><dt>External websites</dt><dd>{ready ? ready.external_note : "Checking."}</dd></div>
      </dl>
    </section>

    {!view && <>
      <section className={styles.section} aria-labelledby="practice-title">
        <h2 id="practice-title">Try it on the practice website</h2>
        <p>Chorsu Parcel Lockers is Plumb’s own invented website. It runs on this computer only, with invented accounts. The open one has a flaw to find; the defended one has none.</p>
        <div className={styles.actions}>
          <button className={styles.primary} type="button" disabled={busy || ready?.browser_ready === false} onClick={() => void act("/api/websites/fixture", {variant: "open"}, 90)}>Plan a practice test</button>
          <button className={styles.button} type="button" disabled={busy || ready?.browser_ready === false} onClick={() => void act("/api/websites/fixture", {variant: "defended"}, 90)}>Plan a test of the defended one</button>
        </div>
      </section>
      <section className={styles.section} aria-labelledby="own-title">
        <h2 id="own-title">Your own website</h2>
        <WebsiteSetupForm busy={busy} onCreate={request => act("/api/websites", request)} />
      </section>
      <section className={styles.section} aria-labelledby="saved-title">
        <h2 id="saved-title">Saved website tests</h2>
        {journeys === null ? <p className={styles.meta}>Reading saved tests.</p> : journeys.length === 0 ? <p>No website test has been saved yet.</p> : <ul className={styles.list}>{journeys.map(item => <li key={item.journey_id} className={styles.row}><a href={`/website/?journey=${item.journey_id}`}>{item.scope.name}</a><p className={styles.meta}>{statusWords(item)} · {new Date(item.updated_at).toISOString().slice(0, 16).replace("T", " ")} UTC</p></li>)}</ul>}
      </section>
    </>}

    {view && counts && <>
      <section className={styles.section} aria-labelledby="scope-title">
        <h2 id="scope-title">{view.scope.name}</h2>
        <p className={styles.meta}><button className={styles.quiet} type="button" onClick={() => open(null)}>All website tests</button></p>
        <dl className={styles.facts}>
          <div><dt>Status</dt><dd><strong>{statusWords(view)}</strong>{view.stop_reason ? ` · ${view.stop_reason}` : ""}</dd></div>
          <div><dt>Approved addresses</dt><dd>{(view.scope.targets ?? []).map(target => <code key={target.origin}>{target.origin} {(target.paths ?? []).join(" ")} </code>)}</dd></div>
          <div><dt>Purpose</dt><dd>{view.scope.purpose}</dd></div>
          <div><dt>Authorized by</dt><dd>{view.scope.authority.granted_by} · {view.scope.authority.reference}</dd></div>
          <div><dt>Valid until</dt><dd>{new Date(view.scope.expires_at).toISOString().slice(0, 16).replace("T", " ")} UTC</dd></div>
          <div><dt>Used</dt><dd><code>{view.spent?.requests ?? 0} of {view.scope.budget?.max_requests} requests · {Math.round(view.spent?.seconds ?? 0)} of {view.scope.budget?.max_seconds} s · {view.spent?.model_questions ?? 0} of {view.scope.budget?.max_model_questions} model questions</code></dd></div>
        </dl>
      </section>

      <section className={styles.section} aria-labelledby="plan-title">
        <h2 id="plan-title">Plan · steps {counts.done} of {counts.steps} done</h2>
        <ol className={ask.steps}>{(view.steps ?? []).map(step => {
          const planned = summary.get(step.step_id);
          return <li key={step.step_id} className={ask.step}>
            <span>{planned?.summary ?? step.step_id}{planned?.state_changing && <span className={ask.changes}> · changes something on the website</span>}{step.note ? <><br /><span className={styles.meta}>{step.note}</span></> : null}</span>
            <span>{stepWords(step)}</span>
          </li>;
        })}</ol>
        <p>{waitWords(view)}</p>
        {(view.plan.not_covered ?? []).map((line, index) => <p key={index} className={styles.meta}>Not in this plan: {line}</p>)}
        {view.status === "planned" && <form className={styles.form} onSubmit={event => {event.preventDefault(); void act(`/api/websites/${view.journey_id}/approve`, {plan_sha256: view.plan_sha256, approved_by: reviewer.trim(), reviewed_plan: true});}}>
          <label>Your name, for the record<input required maxLength={120} value={reviewer} onChange={event => setReviewer(event.target.value)} autoComplete="off" /></label>
          <label className={styles.check}><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />I read this exact plan and I am authorized to approve it.</label>
          <div className={styles.actions}><button className={styles.primary} type="submit" disabled={busy || !reviewed || !reviewer.trim()}>Approve plan</button></div>
          <p className={styles.meta}>Approving visits nothing. The approval is for this plan and this test only.</p>
        </form>}
        {canRun && <form className={styles.form} onSubmit={event => {event.preventDefault(); void act(`/api/websites/${view.journey_id}/run`, {use_model: useModel, secrets, answers}); setSecrets({});}}>
          {needsSecrets && provisioned.map(account => <label key={account.account_id}>Password for {account.label}<input type="password" autoComplete="off" maxLength={256} value={secrets[account.secret_ref] ?? ""} onChange={event => setSecrets({...secrets, [account.secret_ref]: event.target.value})} /></label>)}
          {needsSecrets && <p className={styles.meta}>Passwords are held in memory for this run only. They are never saved, shown or sent to the model.</p>}
          {(view.waiting ?? []).map(question => <fieldset key={question.subject}><legend>{question.text}</legend>{(question.choices ?? []).map(choice => <label key={choice.label} className={styles.check}><input type="radio" name={question.subject} checked={answers[question.subject] === choice.label} onChange={() => setAnswers({...answers, [question.subject]: choice.label})} />{choice.meaning}</label>)}</fieldset>)}
          <label className={styles.check}><input type="checkbox" checked={useModel} onChange={event => setUseModel(event.target.checked)} />Ask the local model where code cannot decide</label>
          <div className={styles.actions}><button className={styles.primary} type="submit" disabled={busy}>{view.status === "approved" ? "Run test" : "Continue test"}</button></div>
        </form>}
        <div className={styles.actions}>
          {view.status === "running" && <button className={styles.button} type="button" onClick={() => void act(`/api/websites/${view.journey_id}/stop`, null)}>Stop at the next step</button>}
          {view.approval && !view.approval_revoked_at && view.status !== "done" && <button className={styles.quiet} type="button" disabled={busy} onClick={() => void act(`/api/websites/${view.journey_id}/revoke`, null)}>Withdraw approval</button>}
        </div>
      </section>

      {view.status === "handoff" && <HumanAuthPanel journeyId={view.journey_id} onUpdate={setView} />}

      <section className={styles.section} aria-labelledby="result-title">
        <h2 id="result-title">Result so far</h2>
        <p><code>{counts.supported}</code> supported finding{counts.supported === 1 ? "" : "s"}, <code>{counts.leads}</code> lead{counts.leads === 1 ? "" : "s"} not confirmed, <code>{counts.checks}</code> comparison{counts.checks === 1 ? "" : "s"}, <code>{counts.pages}</code> page observation{counts.pages === 1 ? "" : "s"}, <code>{counts.blocked}</code> blocked request{counts.blocked === 1 ? "" : "s"}.</p>
        <p className={styles.meta}>No supported finding does not mean this website is secure. Only the approved checks ran.</p>
        {(view.findings ?? []).map(finding => <article key={finding.finding_id} className={styles.row}>
          <h3><span className={`${ask.word} ${finding.conclusion === "supported" ? ask.supported : ask.lead}`}><Glyph name={finding.conclusion === "supported" ? "dot" : "ring"} />{finding.conclusion === "supported" ? "Supported" : "Lead, not confirmed"}</span> · {finding.title}</h3>
          <p>{finding.explanation}</p>
          <p className={styles.meta}>Wording by {finding.explanation_source === "model" ? "the local model, checked against its facts" : "code, from the same facts"}. Observed once by Plumb’s own runner.</p>
          <dl className={styles.facts}>
            <div><dt>Affected endpoint</dt><dd><code>{finding.affected_endpoint}</code></dd></div>
            <div><dt>Safe reproduction</dt><dd><ol>{(finding.safe_reproduction ?? []).map((line, index) => <li key={index}>{line}</li>)}</ol></dd></div>
            <div><dt>Potential impact</dt><dd>{finding.potential_impact}</dd></div>
            <div><dt>Evidence</dt><dd>{(finding.evidence ?? []).map(item => <code key={`${item.evidence_id}:${item.field}`}>{item.evidence_id} {item.field} </code>)}</dd></div>
            <div><dt>Mitigation</dt><dd>{finding.mitigation}</dd></div>
            <div><dt>Limits</dt><dd>{(finding.limits ?? []).join(" ")}</dd></div>
          </dl>
        </article>)}
      </section>

      <section className={styles.section} aria-labelledby="activity-title">
        <h2 id="activity-title">Activity</h2>
        <h3>Accounts</h3>
        {(view.accounts ?? []).length ? <ul className={styles.list}>{(view.accounts ?? []).map(account => <li key={account.account_id} className={styles.row}><strong>{account.account_id}</strong> · {(account.state ?? "not_tried").replaceAll("_", " ")}{account.note ? <p className={styles.meta}>{account.note}</p> : null}</li>)}</ul> : <p className={styles.meta}>No account is used.</p>}
        {(view.handoffs ?? []).map((line, index) => <p key={index} className={styles.condition}>Needs a person: {line}</p>)}
        <details><summary>Pages seen ({counts.pages})</summary><ul className={styles.list}>{(view.pages ?? []).map((page, index) => <li key={index} className={styles.row}><code>{page.path}</code> as {page.account_id ?? "a signed-out visitor"} · status {page.status ?? "not reported"}{page.kind ? ` · ${page.kind.replaceAll("_", " ")}` : ""}{(page.forms ?? []).length ? ` · forms: ${(page.forms ?? []).join(", ").replaceAll("_", " ")}` : ""}{page.note ? <p className={styles.meta}>{page.note}</p> : null}</li>)}</ul></details>
        <details><summary>Comparisons ({counts.checks})</summary><ul className={styles.list}>{(view.checks ?? []).map(check => <li key={check.check_id} className={styles.row}><code>{check.path}</code> · owner {check.owner_account_id}, other account {check.other_account_id} · <strong>{(check.comparison ?? "not_run").replaceAll("_", " ")}</strong><dl className={styles.facts}>{Object.entries(check.facts ?? {}).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>{check.note ? <p className={styles.meta}>{check.note}</p> : null}</li>)}</ul></details>
        <details><summary>Blocked requests ({counts.blocked})</summary><ul className={styles.list}>{(view.blocked ?? []).map((row, index) => <li key={index} className={styles.row}>{(row.kind ?? "other").replaceAll("_", " ")} · <code>{row.host || "no host"}</code> · {row.count ?? 1} time{(row.count ?? 1) === 1 ? "" : "s"}<p className={styles.meta}>{row.reason}</p></li>)}</ul></details>
        <details><summary>Decisions and who made them ({(view.decisions ?? []).length})</summary><ul className={styles.list}>{(view.decisions ?? []).map((record, index) => <li key={index} className={styles.row}><code>{record.question_type}</code> · {record.subject} → <strong>{record.value ?? "undecided"}</strong> · by {rungWords(record.rung)}{record.reason ? <p className={styles.meta}>{record.reason}</p> : null}</li>)}</ul></details>
        {(view.incidents ?? []).map((incident, index) => <p key={index} className={styles.condition}>Stopped at <code>{incident.path}</code>: unexpected {(incident.kinds ?? []).join(", ")}. The page content was discarded.</p>)}
      </section>

      <section className={styles.section} aria-labelledby="report-title">
        <h2 id="report-title">Private report</h2>
        {view.report_path ? <>
          <div className={styles.actions}><button className={styles.button} type="button" disabled={busy} onClick={() => void call(signal => websiteReport(view.journey_id, signal)).then(value => {if (value) setReport(value);})}>Read the report</button></div>
          <p className={styles.meta}>Saved on this computer at <code>{view.report_path}</code>. Review it before sharing any part of it.</p>
          {report && <pre className={styles.report}>{report}</pre>}
        </> : <p>The report is written when the test has run. It is written even when nothing is found.</p>}
      </section>
    </>}
    <p role="status" className={styles.message}>{message}</p>
  </Sheet>;
}
