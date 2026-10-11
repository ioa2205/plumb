// Appearance/hydration checks against clearly labelled local fixtures. This is
// separate from authenticated backend acceptance and starts no model or lab.
// Run after pnpm build: node frontend/scripts/assessment-ui-images.mjs
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { conversationFixtures } from "./improvements-ui-fixtures.mjs";

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(FRONTEND, "out");
const SHOTS = resolve(FRONTEND, "../tmp/improvements-ui-shots");
const fixture = JSON.parse(readFileSync(join(FRONTEND, "scripts/fixtures/assessment-views.json"), "utf8"));
const setup = JSON.parse(readFileSync(join(FRONTEND, "scripts/fixtures/setup-views.json"), "utf8"));
const modelFixture = JSON.parse(readFileSync(join(FRONTEND, "scripts/fixtures/improvements-models.json"), "utf8"));
const readiness = {...setup.readiness, model_catalog: modelFixture.catalog};
const archived = JSON.parse(readFileSync(join(FRONTEND, "scripts/fixtures/archived-peer-case.json"), "utf8"));
const saved = {...archived, run: {...archived.run, run_type: "replay"}};
const codePages = JSON.parse(readFileSync(join(FRONTEND, "scripts/fixtures/code-pages.json"), "utf8"));
const manifest = JSON.parse(readFileSync(join(OUT, "plumb-export.json"), "utf8"));
const inspection = {...setup.inspection, inspection_id: "inspect-" + "a".repeat(32), name: "Tandir lab · saved inspection UI fixture"};
const sourceTask = {target_id: inspection.inspection_id, task_id: "source-task-" + "b".repeat(24), prompt: "Review this project for order ownership problems", families: ["authorization"], resources: ["Order"], routes: [], limit: 5, status: "resolved", clarification: null, authorization_granted: false, network_activity: false};
const savedAnswer = {run_id: saved.run.id, prompt: `Explain ${saved.finding.display_id} and its limitations`, finding: saved.finding, report_path: "Saved fixture report", limitations: [...saved.limitations, "Appearance fixture; this browser run starts no source or runtime test."], generated_by: "saved_evidence", network_activity: false, authorization_granted: false};
const conversations = conversationFixtures({inspection, saved, assessment: fixture.view, codePages});
const types = {".html": "text/html;charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml", ".json": "application/json", ".txt": "text/plain"};
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  const api = {
    [`/api/assessments/${fixture.view.scope.assessment_id}`]: fixture.view,
    [`/api/assessments/${fixture.view.scope.assessment_id}/map`]: fixture.map,
    [`/api/assessments/${fixture.view.scope.assessment_id}/checklist`]: fixture.checklist,
    [`/api/assessments/${fixture.view.scope.assessment_id}/prompt`]: fixture.answer,
    [`/api/assessments/${fixture.view.scope.assessment_id}/report`]: fixture.preview,
    [`/api/assessments/${fixture.view.scope.assessment_id}/actions/preview`]: fixture.lab_preview,
    "/api/projects/inspect": inspection,
    "/api/projects/prompt": sourceTask,
    "/api/setup": readiness,
    [`/api/runs/${saved.run.id}`]: saved.run,
    [`/api/runs/${saved.run.id}/findings/${saved.finding.id}`]: saved,
    [`/api/runs/${saved.run.id}/ask`]: savedAnswer,
  };
  if (url.pathname.startsWith("/api/")) {
    let path; try {path = decodeURIComponent(url.pathname);} catch {path = "";}
    let body;
    if (request.method === "POST") {
      let text = "";
      for await (const chunk of request) {text += chunk; if (text.length > 65536) {response.writeHead(413); response.end(); return;}}
      try {body = text ? JSON.parse(text) : null;} catch {response.writeHead(400); response.end(); return;}
    }
    const conversation = path.startsWith("/api/conversations") ? conversations(path, request.method, body) : null;
    const code = /\/exhibits\/(E\d+)\/code$/.exec(path);
    const span = code && saved.finding.exhibits.find(item => item.tag === code[1])?.span;
    const page = span && codePages.find(item => item.citation.snapshot_id === span.snapshot_id && item.citation.path === span.path && item.citation.start_line === span.start_line && item.citation.end_line === span.end_line && item.citation.content_sha256 === span.content_sha256 && item.mode === url.searchParams.get("mode") && item.before === Number(url.searchParams.get("before")) && item.after === Number(url.searchParams.get("after")) && item.offset === Number(url.searchParams.get("offset")));
    const value = conversation ?? api[path] ?? page;
    response.writeHead(value ? 200 : 404, {"content-type": "application/json", "cache-control": "no-store"});
    response.end(JSON.stringify(value ?? {detail: "No fixture for this local path"})); return;
  }
  const relative = url.pathname.replace(/^\//, "") + (url.pathname.endsWith("/") ? "index.html" : "");
  if (!Object.hasOwn(manifest.files, relative)) {response.writeHead(404); response.end("Fixture resource unavailable"); return;}
  const path = resolve(OUT, relative);
  if (!path.startsWith(OUT + sep)) {response.writeHead(404); response.end(); return;}
  const hashes = manifest.files[relative].script_hashes ?? [];
  const policy = `default-src 'none'; script-src 'self' ${hashes.map(hash => `'${hash}'`).join(" ")}; script-src-attr 'none'; style-src 'self'; style-src-attr 'none'; img-src 'self' data:; font-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`;
  response.writeHead(200, {"content-type": types[extname(path)] ?? "application/octet-stream", "content-security-policy": policy, "x-content-type-options": "nosniff", "cache-control": "no-store"}); response.end(readFileSync(path));
});
await new Promise(done => server.listen(0, "127.0.0.1", done));
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = mkdtempSync(join(tmpdir(), "plumb-task2-ui-"));
mkdirSync(SHOTS, {recursive: true});
const startup = {spawn_error: null, exit_code: null, signal: null, stderr: ""};
const chrome = spawn(process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe", ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-default-apps", "--disable-extensions", "--no-first-run", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], {stdio: ["ignore", "ignore", "pipe"], windowsHide: true});
chrome.on("error", error => {startup.spawn_error = error.code ?? error.message;});
chrome.on("exit", (code, signal) => {startup.exit_code = code; startup.signal = signal;});
chrome.stderr?.on("data", value => {startup.stderr = (startup.stderr + value.toString()).slice(-8192);});
const wait = ms => new Promise(done => setTimeout(done, ms));
const report = {label: `${fixture.label}; conversation answers and model catalog are labelled synthetic display fixtures`, model_fixture: modelFixture.label, authenticated_backend_acceptance: false, fresh_model_acceptance: false, model_loaded: false, runner_started: false, chrome_startup: startup, samples: [], requests: [], errors: []};
let socket;
try {
  let target;
  for (let attempt = 0; attempt < 240 && !target; attempt++) {await wait(250); if (startup.spawn_error || startup.exit_code !== null || startup.signal !== null) break; try {const portFile = join(profile, "DevToolsActivePort"); if (!existsSync(portFile)) continue; const port = readFileSync(portFile, "utf8").split("\n")[0]; if (!/^\d+$/.test(port)) continue; target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(item => item.type === "page");} catch {}}
  if (!target) throw new Error("Chrome did not start for the local appearance fixture");
  socket = new WebSocket(target.webSocketDebuggerUrl); await new Promise(done => socket.addEventListener("open", done));
  let sequence = 0; const pending = new Map();
  socket.addEventListener("message", event => {
    const data = JSON.parse(String(event.data));
    if (data.id && pending.has(data.id)) {const resolve = pending.get(data.id); pending.delete(data.id); resolve(data);}
    if (data.method === "Runtime.exceptionThrown") report.errors.push(data.params.exceptionDetails.text);
    if (data.method === "Network.requestWillBeSent") report.requests.push(data.params.request.url);
    if (data.method === "Log.entryAdded" && data.params.entry.level === "error") report.errors.push(data.params.entry.text);
  });
  const call = (method, params = {}) => new Promise((done, reject) => {const id = ++sequence; const timer = setTimeout(() => {pending.delete(id); reject(new Error(`Chrome command timed out: ${method}`));}, 15_000); pending.set(id, data => {clearTimeout(timer); if (data.error) reject(new Error(data.error.message)); else done(data);}); socket.send(JSON.stringify({id, method, params}));});
  const evaluate = async expression => {const value = await call("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true}); if (value.result.exceptionDetails) throw new Error(value.result.exceptionDetails.text); return value.result.result.value;};
  const until = async expression => {for (let attempt = 0; attempt < 40; attempt++) {if (await evaluate(expression)) return; await wait(250);} throw new Error(`Fixture UI did not settle: ${expression}`);};
  const click = async text => evaluate(`(() => {const item = [...document.querySelectorAll('button')].find(item => item.textContent.trim() === ${JSON.stringify(text)}); if(!item) throw Error('Missing button'); item.click();})()`);
  const fillLabel = async (label, value) => evaluate(`(() => {const item = [...document.querySelectorAll('label')].find(item => item.textContent.startsWith(${JSON.stringify(label)}))?.querySelector('input,textarea'); if(!item)throw Error('Missing field'); const setter = Object.getOwnPropertyDescriptor(item instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,'value').set; setter.call(item,${JSON.stringify(value)}); item.dispatchEvent(new Event('input',{bubbles:true})); item.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const openDetails = async text => evaluate(`(() => {const item = [...document.querySelectorAll('summary')].find(item => item.textContent.includes(${JSON.stringify(text)})); if (!item) throw Error('Missing disclosure'); item.closest('details').open = true;})()`);
  const selectLabel = async (label, value) => evaluate(`(() => {const caption = [...document.querySelectorAll('label')].find(item=>item.textContent.startsWith(${JSON.stringify(label)})); const item = caption?.querySelector('select') ?? document.getElementById(caption?.htmlFor); if (!item || !(item instanceof HTMLSelectElement)) throw Error('Missing selector'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(item,${JSON.stringify(value)}); item.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const checkLabel = async text => evaluate(`(() => {const item = [...document.querySelectorAll('label')].find(item=>item.textContent.includes(${JSON.stringify(text)}))?.querySelector('input[type=checkbox]'); if (!item) throw Error('Missing approval checkbox'); if (!item.checked) item.click();})()`);
  const askConversation = async () => {
    await until("document.querySelector('[aria-label=\"Local evidence conversation\"]') !== null");
    await fillLabel("Question or follow-up", "What does this loaded evidence establish about order access?"); await click("Ask local model");
    await until("document.querySelector('[aria-label=\"Local evidence conversation\"] ol')?.children.length === 1");
    await until("![...document.querySelectorAll('button')].find(item=>item.textContent.trim()==='Ask local model')?.disabled");
    await fillLabel("Question or follow-up", "Which parts of that answer are still unknown, and why?"); await click("Ask local model");
    await until("document.querySelector('[aria-label=\"Local evidence conversation\"] ol')?.children.length === 2");
    await evaluate("document.querySelectorAll('[aria-label=\"Local evidence conversation\"] details').forEach(item=>item.open=true)");
  };
  await call("Page.enable"); await call("Runtime.enable"); await call("Network.enable"); await call("Log.enable");
  await call("Page.addScriptToEvaluateOnNewDocument", {source: "window.fixturePolicyViolations=[]; document.addEventListener('securitypolicyviolation',e=>window.fixturePolicyViolations.push(e.violatedDirective));"});
  mkdirSync(SHOTS, {recursive: true});
  for (const [theme, scheme] of [["day", "light"], ["night", "dark"]]) for (const width of [1440, 390]) {
    await call("Emulation.setDeviceMetricsOverride", {width, height: 1000, deviceScaleFactor: 1, mobile: false});
    await call("Emulation.setEmulatedMedia", {features: [{name: "prefers-color-scheme", value: scheme}, {name: "prefers-reduced-motion", value: "reduce"}]});
    for (const screen of ["website-url", "assessment", "source-prompt", "saved-followup", "model-recorded", "model-untested"]) {
      const route = screen === "website-url" ? "/assess/" : screen === "assessment" ? `/assess/?assessment=${fixture.view.scope.assessment_id}` : screen === "source-prompt" || screen.startsWith("model-") ? "/" : `/findings/?run=${saved.run.id}&finding=${saved.finding.id}`;
      await call("Page.navigate", {url: origin + route}); await until("document.readyState === 'complete'"); await wait(500);
      if (screen === "website-url") {
        await until("document.body.textContent.includes('Start with an approved website URL')");
        await fillLabel("Approved website URL", "http://127.0.0.1:8701/orders");
        await fillLabel("Authorizing person", "Synthetic appearance reviewer");
        await fillLabel("Authorization reference", "Owned Tandir UI fixture; no actual collection permission");
        await fillLabel("Basis for expected owner access", "Synthetic display: an order belongs to its creating customer");
        await checkLabel("I declare that only Alice"); await checkLabel("I authorize this exact URL");
        await until("![...document.querySelectorAll('button')].find(item=>item.textContent.trim()==='Create approved website scope')?.disabled");
      } else if (screen === "assessment") {
        await until("document.body.textContent.includes('Tandir lab · synthetic UI fixture')");
        await click("Load map and checklist"); await until("document.querySelector('table') !== null");
        await fillLabel("Instruction", "Explain E-owner and E-other"); await click("Resolve task"); await until("document.body.textContent.includes('Resolved task:')");
        await click("Preview private report"); await until("document.querySelector('pre')?.textContent.includes('Private assessment draft') || [...document.querySelectorAll('pre')].some(item=>item.textContent.includes('Private assessment draft'))");
        await evaluate("[...document.querySelectorAll('summary')].find(item=>item.textContent.includes('Preview a bounded owned Tandir'))?.closest('details').setAttribute('open','')");
        await click("Preview lab actions"); await until("document.body.textContent.includes('Review the exact actions')");
        await askConversation();
      } else if (screen === "source-prompt") {
        await fillLabel("Absolute project folder", "D:\\synthetic-ui-fixture");
        await evaluate("document.querySelector('input[type=checkbox]').click()"); await click("Inspect source"); await until("document.body.textContent.includes('Direct the source review')");
        await fillLabel("Source instruction", sourceTask.prompt); await click("Resolve source scope"); await until("document.body.textContent.includes('Scope resolved.')");
        await askConversation();
      } else if (screen === "saved-followup") {
        await until("document.body.textContent.includes('Ask about this saved finding')"); await click("Read saved evidence answer"); await until("document.body.textContent.includes('Answered from saved evidence.')");
        await askConversation();
      } else {
        await click("Check readiness"); await until("document.body.textContent.includes('Readiness checked.')");
        await openDetails("Local model choice"); await until("document.body.textContent.includes('Historical owned Tandir source review')");
        await openDetails("Automatic selection basis"); await openDetails("Unavailable candidates");
        if (screen === "model-untested") {await selectLabel("Model and runtime profile", "cpu-8k-qwen3.5-4b-q4_k_m"); await until("document.body.textContent.includes('Model missing or unverified') && document.body.textContent.includes('First-use check: pending')");}
      }
      await evaluate("document.fonts.ready"); await wait(150);
      const metrics = await evaluate("({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,violations:window.fixturePolicyViolations,heading:document.querySelector('h1')?.textContent,emptyButtons:[...document.querySelectorAll('button')].filter(item=>!item.textContent.trim()&&!item.getAttribute('aria-label')).length})");
      if (metrics.scrollWidth > width || metrics.violations.length || metrics.emptyButtons) throw new Error(`Fixture layout/accessibility gate failed ${screen} ${width} ${theme}: ${JSON.stringify(metrics)}`);
      const screenshot = await call("Page.captureScreenshot", {format: "png", captureBeyondViewport: true, clip: {x: 0, y: 0, width, height: metrics.height, scale: 1}});
      const name = `${screen}-${width}-${theme}.png`; writeFileSync(join(SHOTS, name), Buffer.from(screenshot.result.data, "base64")); report.samples.push({screen,theme,...metrics,file:name});
      console.log(`Fixture ${screen} ${width} ${theme}: no overflow, CSP violations or unnamed buttons`);
    }
  }
  const external = report.requests.filter(url => !url.startsWith(origin) && !url.startsWith("data:") && url !== "about:blank");
  if (external.length) throw new Error("The appearance fixture emitted an unexpected external request");
  report.errors = [...new Set(report.errors)];
  if (report.errors.length) throw new Error(`Unexpected browser errors: ${report.errors.join("; ")}`);
  report.passed = true;
} catch (error) {report.passed = false; report.failure = error.message; throw error;}
finally {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({id: 2147483647, method: "Browser.close"}));
  for (let attempt = 0; attempt < 20 && chrome.exitCode === null && chrome.signalCode === null; attempt++) await wait(250);
  socket?.close(); if (chrome.exitCode === null && chrome.signalCode === null) chrome.kill();
  await new Promise(done => server.close(done)); await wait(500);
  report.cleanup = {chrome_exit_code: chrome.exitCode, chrome_signal: chrome.signalCode, server_closed: true};
  writeFileSync(join(SHOTS, "checks.json"), JSON.stringify(report, null, 2) + "\n");
  const root = resolve(tmpdir()); const own = resolve(profile);
  if (own.startsWith(root + sep) && dirname(own) === root && own.includes("plumb-task2-ui-")) {try {rmSync(own, {recursive: true, force: true});} catch {}}
}
