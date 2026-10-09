// @ts-check
// Copies facts from Plumb's saved records into the public data the site is built from.
//
//   node scripts/extract.mjs           write src/data/record.json, tokens, fonts and saved reports
//   node scripts/extract.mjs --check   fail if the committed output differs from the records
//
// The site never states a figure that is typed by hand: numbers, labels and code excerpts
// are read here, checked against the hashes the records carry, and refused if they contain
// anything that looks private. This script needs the whole repository; the build does not.

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PRIVATE_PATTERNS } from './private.mjs';

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO = resolve(LANDING, '..');
const RESULTS = 'docs/results';
const RAW = `${RESULTS}/2026-10-08-m7.8a-raw`;
const LAB = 'labs/tandir';

/** Every string inside a value, so text is checked as written rather than as JSON escapes. */
/** @param {unknown} value @returns {string[]} */
function strings(value) {
  if (typeof value === 'string') return [value];
  if (value && typeof value === 'object') return Object.values(value).flatMap(strings);
  return [];
}

const sha256 = (/** @type {string | Buffer} */ data) =>
  createHash('sha256').update(data).digest('hex');

/** @param {unknown} condition @param {string} message */
function must(condition, message) {
  if (!condition) throw new Error(`extract: ${message}`);
}

/** Repository files read during extraction, with their hashes. */
const sources = new Map();

/** @param {string} path repository-relative */
function bytes(path) {
  const data = readFileSync(join(REPO, path));
  sources.set(path, sha256(data));
  return data;
}
const text = (/** @type {string} */ path) => bytes(path).toString('utf8');
const json = (/** @type {string} */ path) => JSON.parse(text(path));

/**
 * One capture from a document that states a figure in prose. The pattern must match
 * exactly once, so a reworded record breaks the build instead of silently going stale.
 * @param {string} path @param {RegExp} pattern
 */
function stated(path, pattern) {
  const all = [...text(path).matchAll(new RegExp(pattern.source, `${pattern.flags.replace('g', '')}g`))];
  must(all.length === 1, `${path}: expected one match for ${pattern}, found ${all.length}`);
  return all[0].slice(1).map((group) => Number(group.replace(/,/g, '')));
}

// ---------------------------------------------------------------- the recorded run

function extractRun() {
  const report = json(`${RAW}/report.json`);
  const questions = json(`${RAW}/questions.json`);
  const journey = json(`${RESULTS}/2026-10-08-m7.8a-journey.json`);
  const preparation = json(`${RESULTS}/2026-10-08-m7.8a-preparation.json`);
  const refusedDoctor = JSON.parse(preparation.doctor.stdout);

  must(journey.passed === true && journey.run_id === report.run.id, 'journey and report disagree');
  must(journey.target_code_executed === false, 'journey says target code was executed');
  must(journey.actual_preflights.length === 1, 'expected one model admission');
  const admission = journey.actual_preflights[0];

  const lines = /** @type {string[]} */ (journey.lines);
  const line = (/** @type {RegExp} */ pattern) => {
    const found = lines.map((entry) => entry.match(pattern)).filter(Boolean);
    must(found.length === 1, `journey console: expected one line for ${pattern}`);
    return /** @type {RegExpMatchArray} */ (found[0]).slice(1).map(Number);
  };
  const [included, excludedFiles] = line(/^Included files: (\d+); excluded: (\d+)$/);
  const [python, tsx, typescript] = line(/^Source files: python (\d+), tsx (\d+), typescript (\d+)$/);
  const [fastapi, nextjs] = line(/^Discovered entries: fastapi (\d+), nextjs (\d+)$/);
  const [accessPaths] = line(/access paths: (\d+); unresolved links: \d+$/);
  const [patternLeads, overlapping] = line(/Opengrep supplied (\d+) cited pattern leads; (\d+) overlap/);

  // Requests the model answered for each finding, in the order the console printed them.
  /** @type {{ finding: string, kinds: Record<string, number> }[]} */
  const requestKinds = [];
  /** @type {Record<string, number>} */
  let pending = {};
  for (const entry of lines) {
    const answered = entry.match(/^\s+(\w+): answered$/);
    const finished = entry.match(/^(F-\d+): (supported|rejected|inconclusive) - /);
    if (answered) pending[answered[1]] = (pending[answered[1]] ?? 0) + 1;
    if (finished) {
      requestKinds.push({ finding: finished[1], kinds: pending });
      pending = {};
    }
  }
  const counted = requestKinds.flatMap((group) => Object.values(group.kinds)).reduce((a, b) => a + b, 0);
  must(counted === journey.requests_answered, 'console request lines do not add up to the saved count');

  // The public form of the command: the target folder as the handoff documents it, and the
  // one-off guard cache named for what it was rather than where it lived.
  const argv = /** @type {string[]} */ (preparation.argv).slice();
  must(/\\app\\labs\\tandir$/.test(argv[1]), 'unexpected review target');
  argv[1] = '.\\app\\labs\\tandir';
  const cacheFlag = argv.indexOf('--guard-cache');
  must(cacheFlag > 0, 'expected the declared fresh guard cache');
  argv[cacheFlag + 1] = '<new-empty-cache>';

  const profile = argv[argv.indexOf('--profile') + 1];

  return {
    id: report.run.id,
    type: report.run.run_type,
    lifecycle: report.run.lifecycle,
    created_at: report.run.created_at,
    started_at: report.run.started_at,
    finished_at: report.run.finished_at,
    model: report.run.model,
    toolchain: {
      llama_cpp_release: report.run.toolchain.llama_cpp_release,
      llama_cpp_build: report.run.toolchain.llama_cpp_build,
      backend: report.run.toolchain.backend,
      opengrep_version: report.run.toolchain.opengrep_version,
    },
    profile,
    command: argv,
    question_limit: preparation.budget.questions,
    declared_stop: {
      answers: preparation.budget.observed_answer_stop,
      seconds: preparation.budget.wall_stop_seconds,
    },
    coverage: report.run.coverage,
    snapshot: { id: report.snapshot.id, root_name: report.snapshot.root_name },
    overview: {
      included_files: included,
      excluded_files: excludedFiles,
      python,
      tsx,
      typescript,
      fastapi_entries: fastapi,
      nextjs_entries: nextjs,
      access_paths: accessPaths,
      pattern_leads: patternLeads,
      pattern_leads_in_scope: overlapping,
    },
    requests: {
      started: journey.requests_started,
      answered: journey.requests_answered,
      attempts: journey.model_attempts,
      by_finding: requestKinds,
    },
    prompt_tokens: journey.prompt_tokens,
    completion_tokens: journey.completion_tokens,
    elapsed_seconds: journey.elapsed_seconds,
    exit: journey.exit,
    budget_stop: journey.budget_stop,
    memory_abort: journey.memory_abort,
    forced_stops: journey.forced_owned_stops.length,
    owned_remaining: journey.owned_remaining.length,
    target_code_executed: journey.target_code_executed,
    browser_rendering_claimed: journey.browser_rendering_claimed,
    clean_user_profile: journey.clean_user_profile,
    admission: {
      available_bytes: admission.available_bytes,
      host_bytes: admission.requirement.host_bytes,
      device_bytes: admission.requirement.device_bytes,
      device_name: admission.requirement.device_name,
      ctx_size: admission.ctx_size,
    },
    initial_refusal: {
      available_bytes: refusedDoctor.inventory.memory.available_bytes,
      total_bytes: refusedDoctor.inventory.memory.total_bytes,
      exit: preparation.doctor.exit,
      message: refusedDoctor.messages[0],
      model_loaded: preparation.model_loaded,
    },
    machine: {
      cpu: refusedDoctor.inventory.cpu,
      physical_cores: refusedDoctor.inventory.physical_cores,
      os: refusedDoctor.inventory.os,
      architecture: refusedDoctor.inventory.architecture,
      total_memory_bytes: refusedDoctor.inventory.memory.total_bytes,
      gpu: admission.requirement.device_name,
    },
    report_read: {
      elapsed_seconds: journey.report_read.elapsed_seconds,
      exit: journey.report_read.exit,
      reports_unchanged: journey.saved_reports_unchanged_after_read,
    },
    limitations: report.limitations,
    console: extractConsole(lines, report.run.id),
    findings: extractFindings(report, questions, journey),
    peer: extractPeers(report),
    proposal: extractProposal(report),
    saved_reports: copySavedReports(journey),
  };
}

/** The words that stand in for the laptop's data folder in the published console lines. */
export const DATA_FOLDER = '<data folder>';

/**
 * What the review command printed, line by line. The only change is the laptop's own data
 * folder, which is replaced by a placeholder the page shows as such; two lines carry it.
 * @param {string[]} lines @param {string} runId
 */
function extractConsole(lines, runId) {
  const folder = /^[A-Za-z]:\\plumb-data(?=\\reviews\\)/;
  const published = lines.map((entry) => entry.replace(/(?<=^(?:Reports: |Saved ))[A-Za-z]:\\plumb-data(?=\\reviews\\)/, DATA_FOLDER));
  must(published.filter((entry) => entry.includes(DATA_FOLDER)).length === 2, 'expected the data folder on two console lines');
  must(!published.some((entry) => folder.test(entry)), 'a console line still names the data folder');
  must(published.some((entry) => entry === `Run: ${runId}`), 'console and report name different runs');
  return published;
}

/** @param {any} report @param {any[]} questions @param {any} journey */
function extractFindings(report, questions, journey) {
  return report.findings.map((/** @type {any} */ finding) => {
    const question = questions.find((entry) => finding.question_ids.includes(entry.id));
    must(question, `${finding.display_id}: saved question missing`);
    const result = question.answer.result;
    const accepted = journey.cases.find((/** @type {any} */ entry) => entry.id === finding.id);
    must(accepted?.fresh_saved_samples_match === true, `${finding.display_id}: samples not confirmed`);
    must(result.conclusion === finding.conclusion, `${finding.display_id}: conclusion mismatch`);
    must(result.samples.length === 3, `${finding.display_id}: expected three judgments`);

    return {
      display_id: finding.display_id,
      id: finding.id,
      route: accepted.route,
      family: finding.family,
      cwe: finding.cwe,
      title: finding.title,
      lede: finding.lede,
      conclusion: finding.conclusion,
      runtime_verification: finding.runtime_verification,
      severity: finding.severity,
      severity_rationale: finding.severity_rationale,
      strength: finding.strength,
      gaps: finding.gaps,
      unknowns: finding.unknowns,
      exhibit_count: finding.exhibits.length,
      evidence_violations: accepted.evidence_violations.length,
      priority_reasons: question.priority_reasons,
      looked: question.answer.looked,
      searches: result.searches.map((/** @type {any} */ search) => ({
        item: search.item,
        status: search.status,
        note: search.note,
        places: search.searched.map(spanLabel),
        guards: search.guard_ids.length,
      })),
      judgments: result.samples.map((/** @type {any} */ sample) => ({
        seed: sample.seed,
        question_type: sample.question_type,
        interpretation: sample.interpretation,
        answer: sample.answer,
        violations: sample.violations.length,
      })),
      guards: result.guards.map((/** @type {any} */ guard) => ({
        kind: guard.kind,
        canonical: guard.canonical,
        mechanism: guard.mechanism,
        subject: guard.subject,
        object: guard.object,
        where: spanLabel(guard.span),
      })),
    };
  });
}

/** @param {{ path: string, start_line: number, end_line: number }} span */
function spanLabel(span) {
  return span.start_line === span.end_line
    ? `${span.path}:${span.start_line}`
    : `${span.path}:${span.start_line}-${span.end_line}`;
}

/** @param {any} report */
function extractPeers(report) {
  const subject = report.findings.find((/** @type {any} */ finding) => finding.conclusion === 'supported');
  const comparison = report.peer_comparisons.find(
    (/** @type {any} */ entry) => entry.finding_id === subject.id,
  );
  must(comparison, 'peer comparison for the supported finding is missing');
  const { group } = comparison;
  must(group.deviations.length === 1, 'expected exactly one peer deviation');
  const deviation = group.deviations[0];
  must(deviation.site_id === comparison.subject_site_id, 'deviation is not the subject site');

  const rows = comparison.rows
    .map((/** @type {any} */ row) => ({
      site: row.site.id,
      method: row.entry.method,
      route: row.entry.route,
      handler: { path: row.entry.span.path, line: row.entry.span.start_line },
      applied: group.columns
        .filter((/** @type {any} */ column) => column.applied_site_ids.includes(row.site.id))
        .map((/** @type {any} */ column) => column.key),
      excluded: row.exclusion,
      subject: row.site.id === comparison.subject_site_id,
    }))
    // Source order, so the receipt route sits next to the invoice route it resembles.
    .sort(
      (/** @type {any} */ a, /** @type {any} */ b) =>
        a.handler.path.localeCompare(b.handler.path) || a.handler.line - b.handler.line,
    );

  const compared = rows.filter((/** @type {any} */ row) => !row.excluded);
  must(
    compared.length - 1 === deviation.peers_total,
    'compared rows do not match the recorded peer count',
  );

  return {
    resource: group.resource,
    min_peers: group.min_peers,
    min_share: group.min_share,
    columns: group.columns.map((/** @type {any} */ column) => column.key),
    deviation: {
      missing: deviation.missing,
      peers_applying: deviation.peers_applying,
      peers_total: deviation.peers_total,
    },
    compared: compared.length,
    excluded: rows.length - compared.length,
    rows,
    limitations: comparison.limitations,
  };
}

/** @param {any} report */
function extractProposal(report) {
  must(report.proposals.length === 1, 'expected one fix proposal record');
  const [proposal] = report.proposals;
  return {
    status: proposal.status,
    reason: proposal.reason,
    probe_status: proposal.probe_status,
    probe_reason: proposal.probe_reason,
  };
}

/** Byte-identical copies of the four reports, checked against the journey's hashes. */
/** @param {any} journey */
function copySavedReports(journey) {
  return ['report.html', 'report.md', 'report.json', 'report.sarif'].map((name) => {
    const data = bytes(`${RAW}/${name}`);
    must(sha256(data) === journey.saved_files_sha256[name], `${name}: hash differs from the journey`);
    assertPublic(name, data.toString('utf8'));
    emit(`public/saved-report/${name}`, data);
    return { name, bytes: data.length, sha256: sha256(data) };
  });
}

// ---------------------------------------------------------------- code the report cites

/** Lines of the bundled lab, accepted only when they hash to the value the report cites. */
function extractExcerpts() {
  const report = json(`${RAW}/report.json`);
  const cited = new Map();
  for (const finding of report.findings) {
    for (const exhibit of finding.exhibits) {
      cited.set(`${finding.display_id}/${exhibit.tag}`, exhibit);
    }
  }

  /** @param {string} tag */
  const excerpt = (tag) => {
    const exhibit = cited.get(tag);
    must(exhibit, `${tag}: not an exhibit in the saved report`);
    const { path, start_line: start, end_line: end, content_sha256: expected } = exhibit.span;
    const source = text(`${LAB}/${path}`).replace(/\r\n/g, '\n').split('\n');
    const lines = source.slice(start - 1, end);
    must(sha256(lines.join('\n')) === expected, `${tag}: lab source no longer matches the report`);
    return { tag, role: exhibit.role, path, start, end, sha256: expected, lines };
  };
  /** @param {string} tag */
  const lineRange = (tag) => {
    const exhibit = cited.get(tag);
    must(exhibit, `${tag}: not an exhibit in the saved report`);
    return { tag, start: exhibit.span.start_line, end: exhibit.span.end_line };
  };

  return {
    receipt_handler: { ...excerpt('F-01/E01'), access: lineRange('F-01/E06') },
    invoice_handler: excerpt('F-02/E01'),
    invoice_helper: { ...excerpt('F-02/E02'), guard: lineRange('F-02/E07') },
    signed_in: { ...excerpt('F-01/E02'), guard: lineRange('F-01/E05') },
  };
}

// ---------------------------------------------------------------- separate runtime records

/** @param {any} run */
const probeSteps = (run) =>
  run.steps.map((/** @type {any} */ step) => ({
    role: step.role,
    principal: step.principal,
    expected_if_safe: step.expected_if_safe,
    status: step.status,
    marker_present: step.marker_present,
  }));

function extractRuntime() {
  /** @param {string} name */
  const probe = (name) => {
    const record = json(`${RESULTS}/2026-10-05-m4.2-${name}.json`);
    const request = record.spec.requests.find((/** @type {any} */ entry) => entry.role === 'attack');
    return {
      at: record.probe_run.started_at,
      route: request.path,
      outcome: record.probe_run.outcome,
      steps: probeSteps(record.probe_run),
    };
  };

  const replay = json(`${RESULTS}/2026-10-07-m4.5b-acceptance.json`);
  must(replay.passed === true && replay.attempts.length === 1, 'unexpected replay record');
  const [attempt] = replay.attempts;

  return {
    receipt: probe('receipt'),
    invoice: probe('invoice'),
    replay: {
      at: attempt.machine_start.time,
      review_id: replay.run_id,
      model_loaded: replay.model_loaded,
      before: { outcome: attempt.before.outcome, steps: probeSteps(attempt.before) },
      after: { outcome: attempt.after.outcome, steps: probeSteps(attempt.after) },
    },
  };
}

// ---------------------------------------------------------------- the second profile

/** "3 of 3" in a summary record, as two numbers. */
function countOf(/** @type {unknown} */ value) {
  const found = String(value).match(/^(\d+) of (\d+)$/);
  must(found, `expected "N of M", found ${JSON.stringify(value)}`);
  return /** @type {RegExpMatchArray} */ (found).slice(1).map(Number);
}

/**
 * The one real run of the processor-only profile: its first-use check, then a review of the
 * same two addresses as the recorded run. It is a separate, later review and is never merged
 * with the recorded one. The summary is checked against the two records it points to.
 *
 * Its timings are left out on purpose. The summary says they are not comparable: no benchmark
 * protocol was followed and the laptop was in its power-saving mode.
 * @param {any} recorded the recorded run, as extracted above
 */
function extractCpuProfile(recorded) {
  const name = '2026-10-10-a1-cpu-profile-attempt-2.json';
  const summary = json(`${RESULTS}/${name}`);
  const check = json(summary.first_use_check.record);
  const report = json(`${summary.review.records}report.json`);

  // The record is filed under the laptop's own calendar day, and so is the request that
  // started it. Its timestamps are in UTC, where the run began late on the day before.
  const [recordedOn] = /** @type {RegExpMatchArray} */ (name.match(/^\d{4}-\d{2}-\d{2}/));
  must(summary.conditions.requested_by.includes(recordedOn), 'the run and its record carry different days');
  const hoursFromThatDay = (Date.parse(report.run.started_at) - Date.parse(`${recordedOn}T00:00:00Z`)) / 3_600_000;
  must(hoursFromThatDay > -14 && hoursFromThatDay < 36, 'the review did not start on the day its record is filed under');

  must(summary.hypothesis_held === true, 'the declared hypothesis did not hold');
  must(summary.profile === check.profile.id && summary.required_ram_bytes === check.profile.host_required_bytes, 'summary and first-use check name different profiles');
  must(check.profile.device_required_bytes === 0 && check.profile.offload_layers === 0, 'the profile uses a graphics card');
  must(check.profile.model_sha256 === recorded.model.file_sha256 && report.run.model.file_sha256 === recorded.model.file_sha256, 'a different model was used');
  must(report.run.toolchain.backend === check.profile.backend, 'check and review used different model runners');

  // The first-use check: form and leak-freedom, counted again from its own record.
  must(summary.first_use_check.outcome === 'passed' && check.outcome === 'passed' && summary.first_use_check.exit_code === 0, 'the first-use check did not pass');
  const [answersValid, answers] = countOf(summary.first_use_check.structured_answers_parsed_with_valid_citations);
  const [kindsMatched] = countOf(summary.first_use_check.structured_answers_whose_guard_kinds_matched_the_expected_kinds);
  const [pairsClean, pairs] = countOf(summary.first_use_check.leak_check_pairs_secret_echoed_then_absent);
  must(
    check.answers.length === answers &&
      check.answers.filter((/** @type {any} */ entry) => entry.parsed && entry.invalid_citations.length === 0).length === answersValid &&
      check.answers.filter((/** @type {any} */ entry) => entry.kinds_match).length === kindsMatched,
    'first-use answers do not match their summary',
  );
  must(
    check.canary.length === pairs &&
      check.canary.filter((/** @type {any} */ pair) => pair.a_contains_token && !pair.leaked).length === pairsClean,
    'leak-check pairs do not match their summary',
  );

  // The review, against its own report.
  const { review } = summary;
  must(review.run_id === report.run.id && review.lifecycle === report.run.lifecycle, 'summary and report name different reviews');
  must(JSON.stringify(review.coverage) === JSON.stringify(report.run.coverage), 'summary and report disagree on coverage');
  const findings = review.findings.map((/** @type {any} */ finding) => {
    const saved = report.findings.find((/** @type {any} */ entry) => entry.display_id === finding.display_id);
    must(saved?.conclusion === finding.conclusion, `${finding.display_id}: summary and report disagree`);
    must(finding.conclusion === finding.expected, `${finding.display_id}: not the declared result`);
    const [, route] = /** @type {RegExpMatchArray} */ (finding.address.match(/^GET (\/\S+)$/) ?? []);
    must(route, `${finding.display_id}: unexpected address`);
    return { display_id: finding.display_id, route, conclusion: finding.conclusion, runtime_verification: saved.runtime_verification };
  });
  must(findings.length === report.findings.length, 'summary and report list different findings');

  return {
    id: summary.profile,
    backend: check.profile.backend,
    recorded_on: recordedOn,
    required_ram_bytes: summary.required_ram_bytes,
    // The same laptop as the recorded run: same processor, same installed memory.
    same_computer_as_recorded_run:
      check.host.cpu === recorded.machine.cpu && check.host.total_memory_bytes === recorded.machine.total_memory_bytes,
    first_use_check: {
      outcome: check.outcome,
      answers,
      answers_valid: answersValid,
      answers_matching_expected_kind: kindsMatched,
      leak_pairs: pairs,
      leak_pairs_clean: pairsClean,
    },
    review: {
      id: review.run_id,
      lifecycle: review.lifecycle,
      exit: review.exit_code,
      model_requests: review.model_requests,
      memory_abort: review.memory_abort,
      admitted_with_bytes: review.preflight.available_ram_bytes,
      coverage: review.coverage,
      findings,
    },
  };
}

// ---------------------------------------------------------------- model, package, checks

/** @param {string} id */
function extractModelPin(id) {
  const blocks = text('backend/setup/pins/models.toml').split('[[models]]').slice(1);
  const pins = blocks.map((block) =>
    Object.fromEntries(
      [...block.matchAll(/^(\w+) = (.+)$/gm)].map(([, key, value]) => [
        key,
        value.startsWith('"') ? JSON.parse(value) : Number(value),
      ]),
    ),
  );
  const pin = pins.find((entry) => entry.id === id);
  must(pin, `model pin ${id} missing`);
  return {
    id: pin.id,
    family: pin.family,
    base_model: pin.base_model,
    repo: pin.repo,
    file: pin.file,
    sha256: pin.sha256,
    size: pin.size,
    quantization: pin.quantization,
    license: pin.license,
  };
}

/**
 * The practice app's two sample customers and their orders, as its seed file creates them.
 * The overview draws the receipt flaw with these, so the picture shows the app's own data.
 * The marker each address carries for the runtime probe is left out.
 */
function extractSample() {
  const seed = text(`${LAB}/api/tandir/seed.py`);
  const people = Object.fromEntries(
    [...seed.matchAll(/person\((\d+), "(\w+)", "([^"]+)", "(\w+)"/g)].map(([, id, username, name, role]) => [
      Number(id),
      { username, name, role },
    ]),
  );
  const addresses = Object.fromEntries(
    [...seed.matchAll(/^(ALICE|BOB)_ADDRESS = "([^"]+?) \(\1-MARKER\)"$/gm)].map(([, who, address]) => [who.toLowerCase(), address]),
  );
  const orders = seed
    .split(/\bOrder\(\n/)
    .slice(1)
    .map((block) => {
      const field = (/** @type {string} */ name) => Number(block.match(new RegExp(`\\b${name}=(\\d+),`))?.[1]);
      const address = block.match(/delivery_address=(ALICE|BOB)_ADDRESS/)?.[1].toLowerCase();
      return {
        id: field('id'),
        customer: people[field('customer_id')],
        address: address ? addresses[address] : undefined,
        items: [...block.matchAll(/name="([^"]+)",\s*quantity=(\d+)/g)].map(([, name, quantity]) => ({ name, quantity: Number(quantity) })),
      };
    });
  must(orders.length === 2, `expected two sample orders, found ${orders.length}`);
  for (const order of orders) {
    must(order.id > 0 && order.customer?.role === 'customer' && order.address && order.items.length > 0, `sample order ${order.id} is incomplete`);
  }
  const [alice, bob] = ['alice', 'bob'].map((username) => orders.find((order) => order.customer.username === username));
  must(alice && bob, 'expected one order each for alice and bob');
  // What the receipt route sends back, field by field, so the picture shows no more than that.
  const schema = text(`${LAB}/api/tandir/schemas.py`).match(/^class ReceiptOut\(BaseModel\):\n((?: {4}\w+: .+\n)+)/m);
  must(schema, 'ReceiptOut schema not found');
  const receiptFields = [.../** @type {RegExpMatchArray} */ (schema)[1].matchAll(/^ {4}(\w+):/gm)].map((match) => match[1]);
  return { victim: alice, intruder: bob, receipt_fields: receiptFields };
}

/**
 * The program that runs the model for one profile: what setup downloads besides the model
 * file. The measured profile and the processor-only profile each have their own.
 * @param {string} backend
 */
function extractRuntimePin(backend) {
  const pins = text('backend/setup/pins/llama_cpp.toml');
  const section = pins.split(/^\[\[variants\.("?)([\w.-]+)\1\.assets\]\]$/m);
  /** @type {{ name: string, size: number }[]} */
  const assets = [];
  for (let index = 1; index < section.length; index += 3) {
    if (section[index + 1] !== backend) continue;
    const body = section[index + 2];
    const name = body.match(/^name = "([^"]+)"$/m)?.[1];
    const size = Number(body.match(/^size = (\d+)$/m)?.[1]);
    must(name && size > 0, `runtime pin for ${backend} is incomplete`);
    assets.push({ name: /** @type {string} */ (name), size });
  }
  must(assets.length === 1, `expected one ${backend} runtime download, found ${assets.length}`);
  const [release] = pins.match(/^release = "([^"]+)"$/m)?.slice(1) ?? [];
  must(release, 'runtime release missing');
  return { release, backend, name: assets[0].name, size: assets[0].size };
}

/**
 * The words Plumb prints beside every pinned model other than the default. The models have
 * not been compared on the same cases, so the site repeats this label and adds nothing to it.
 */
function extractModelLabel() {
  const found = text('backend/profiles.py').match(/^NOT_COMPARED = "([^"]+)"$/m);
  must(found, 'the label for models other than the default is missing');
  return /** @type {RegExpMatchArray} */ (found)[1];
}

/** The pattern scanner that setup also installs when Plumb is run from source. */
function extractScannerPin() {
  const pins = text('backend/setup/pins/opengrep.toml');
  const release = pins.match(/^release = "([^"]+)"$/m)?.[1];
  const size = Number(pins.match(/^size = (\d+)$/m)?.[1]);
  must(release && size > 0, 'scanner pin is incomplete');
  return { name: 'Opengrep', release, size };
}

/**
 * The Windows package offered for download. It is a rebuild of the recorded run's package
 * that leaves out launcher files naming the build folder and two private names; the
 * investigator code is checked to be identical. Only facts the checks recorded are kept.
 */
function extractDownload() {
  const smoke = json(`${RESULTS}/2026-10-09-m7.9b-package-smoke.json`);
  const followup = json(`${RESULTS}/2026-10-09-m7.9b-package-followup.json`);
  const recorded = json(`${RESULTS}/2026-10-08-m7.7f-package-smoke.json`).artifact;
  const { artifact } = smoke;
  must(artifact.passed && artifact.zip_inventory_and_hashes_pass && artifact.private_files_absent, 'download artifact checks did not pass');
  must(artifact.source_dirty === false, 'download was built from uncommitted source');
  must(JSON.stringify(artifact.implementation_sha256) === JSON.stringify(recorded.implementation_sha256), 'download investigator differs from the recorded package');
  const passed = Object.fromEntries(smoke.checks.map((/** @type {any} */ check) => [check.args[0], check.passed]));
  must(passed['--help'] && passed.setup && passed.inspect && smoke.web.passed, 'download command checks did not pass');
  must(followup.report_opened && followup.current_report_unchanged, 'download did not open the recorded report');
  const name = String(artifact.archive).split(/[\\/]/).pop();
  must(/^plumb-[\w.-]+\.zip$/.test(name), 'unexpected download name');
  return {
    name,
    archive_bytes: artifact.archive_bytes,
    archive_sha256: artifact.archive_sha256,
    inventoried_files: artifact.inventoried_files,
    files_left_out: recorded.inventoried_files - artifact.inventoried_files,
    investigator_files_identical: Object.keys(artifact.implementation_sha256).length,
    // The package was built before the processor-only profile: its investigator has no such file.
    has_cpu_profile: Object.keys(artifact.implementation_sha256).includes('backend/cpu_profile.py'),
    checked_at: smoke.created_at,
    doctor_refused_for_memory: followup.doctor_summary?.messages?.some((/** @type {string} */ m) => /RAM/.test(m)) ?? false,
  };
}

function extractPackage() {
  const handoff = json(`${RESULTS}/2026-10-08-m7.8-handoff-checks.json`);
  const smoke = json(`${RESULTS}/2026-10-08-m7.7f-package-smoke.json`);
  must(handoff.passed === true, 'handoff verification did not pass');
  must(smoke.artifact.archive_sha256 === handoff.archive_sha256, 'package records disagree');
  return {
    archive_bytes: handoff.archive_bytes,
    archive_sha256: handoff.archive_sha256,
    inventoried_files: smoke.artifact.inventoried_files,
    references_checked: handoff.local_references_checked,
    clean_user_profile: smoke.clean_user_profile,
  };
}

function extractSoftware() {
  const checkpoint = json(`${RESULTS}/2026-10-08-m7.7f-python-checkpoint.json`);
  const full = checkpoint.full;
  const retry = checkpoint.isolated_retry;
  must(Number(retry.failures) === 0 && Number(retry.errors) === 0, 'isolated retry did not pass');
  const failed = Number(full.failures) + Number(full.errors);
  const [frontendTests] = stated(
    `${RESULTS}/2026-10-08-m7.7f-current-candidate.md`,
    /all (\d+) frontend\s+tests pass/,
  );
  return {
    python: {
      collected: Number(full.tests),
      skipped: Number(full.skipped),
      failed_first_run: failed,
      passed_first_run: Number(full.tests) - Number(full.skipped) - failed,
      passed_on_isolated_retry: Number(retry.tests),
    },
    frontend_tests: frontendTests,
  };
}

/** Development results that are stated in the evaluation notes rather than in one JSON field. */
function extractDevelopment() {
  const evaluation = `${RESULTS}/2026-10-06-evaluation.md`;
  const [cases, vulnerable, controls] = stated(
    evaluation,
    /The (\d+)-case slice contains (\d+) vulnerable cases and (\d+) defended controls/,
  );
  const [scannerHit, scannerOf, oneShotHit, oneShotOf] = stated(
    evaluation,
    /\| Defended-control false-positive rate \| (\d+)\/(\d+) = [\d.]+;[^|]*\| (\d+)\/(\d+) = /,
  );
  const [scannerRecall, scannerRecallOf, oneShotRecall, oneShotRecallOf] = stated(
    evaluation,
    /\| Authorization recall \| (\d+)\/(\d+) = [\d.]+;[^|]*\| (\d+)\/(\d+) = /,
  );
  const [familyCases, familyRequests] = stated(
    evaluation,
    /completed\s+(\d+) cases and (\d+) requests: one expected protected-path rejection and eleven\s+Inconclusive results/,
  );
  must(scannerOf === controls && oneShotOf === controls, 'control counts disagree');

  /** @param {string} path */
  const caseTable = (path) =>
    [...text(path).matchAll(/^\| (D\d(?:-L)?) ([^|]+?) \| (Supported|Rejected|Inconclusive) \|/gm)].map(
      ([, id, label, conclusion]) => ({ id, label, conclusion }),
    );
  const actionPhone = caseTable(`${RESULTS}/2026-10-08-m6.9r-action-phone.md`);
  const phonePair = caseTable(`${RESULTS}/2026-10-08-m6.9v-phone-client-binding.md`);
  must(actionPhone.length === 4 && phonePair.length === 2, 'development case tables changed');

  // Original family run and the later focused run, case by case. "-L" marks a protected lookalike.
  const focused = [...text(evaluation).matchAll(/^\| ([BC]\d(?:-L)?): ([^|]+?) \| ([^|]+?) \| ([^|]+?) \|$/gm)].map(
    ([, id, label, original, later]) => ({
      id,
      label,
      protected: id.endsWith('-L'),
      original: original.split(/[;,]/)[0],
      focused: later.split(/[;,]/)[0],
    }),
  );
  must(focused.length === 4, 'focused run table changed');

  return {
    baseline: {
      cases,
      vulnerable,
      controls,
      scanner: { controls_flagged: scannerHit, authorization_found: scannerRecall, authorization_of: scannerRecallOf },
      one_shot: { controls_flagged: oneShotHit, authorization_found: oneShotRecall, authorization_of: oneShotRecallOf },
    },
    family_run: { cases: familyCases, requests: familyRequests, expected_rejections: 1, inconclusive: 11 },
    action_phone: actionPhone,
    phone_pair: phonePair,
    focused,
  };
}

// ---------------------------------------------------------------- design tokens and fonts

function tokensCss() {
  const tokens = json('frontend/tokens.json');
  /** @param {Record<string, string>} theme */
  const block = (theme) =>
    Object.entries(theme)
      .map(([name, value]) => `  --${name}: ${value};`)
      .join('\n');
  // Hover washes are the ink colour of each theme at low opacity, as in design/study-finding.html.
  // Only raised layers (menus) cast a shadow: design.md §6 gives the day value; night is deeper.
  const day = `${block(tokens.themes.day)}\n  --hover: rgb(27 29 32 / 0.055);\n  --shadow-raised: 0 1px 2px rgb(20 22 25 / 0.06), 0 12px 32px rgb(20 22 25 / 0.10);\n  color-scheme: light;`;
  const night = `${block(tokens.themes.night)}\n  --hover: rgb(232 232 228 / 0.06);\n  --shadow-raised: 0 1px 2px rgb(0 0 0 / 0.5), 0 14px 36px rgb(0 0 0 / 0.55);\n  color-scheme: dark;`;
  return [
    '/* Generated by scripts/extract.mjs from frontend/tokens.json. Do not edit. */',
    `:root {\n  --sans: ${tokens.common.sans};\n  --mono: ${tokens.common.mono};\n${day}\n}`,
    `@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="day"]) {\n${night.replace(/^/gm, '  ')}\n  }\n}`,
    `:root[data-theme="night"] {\n${night}\n}`,
    '',
  ].join('\n');
}

const FONTS = [
  ...[400, 500, 600, 700].map((weight) => ['atkinson-hyperlegible-next', weight]),
  ...[400, 500, 600].map((weight) => ['atkinson-hyperlegible-mono', weight]),
];

function copyFonts() {
  for (const [family, weight] of FONTS) {
    const name = `${family}-latin-${weight}-normal.woff2`;
    const source = `frontend/node_modules/@fontsource/${family}/files/${name}`;
    if (existsSync(join(REPO, source))) {
      emit(`public/fonts/${name}`, readFileSync(join(REPO, source)));
    } else {
      // Installed workbench dependencies are optional; the committed copies stay in use.
      must(existsSync(join(LANDING, 'public/fonts', name)), `${name}: no source and no committed copy`);
    }
  }
  for (const license of ['Atkinson-Next-OFL.txt', 'Atkinson-Mono-OFL.txt']) {
    emit(`public/fonts/${license}`, readFileSync(join(REPO, 'frontend/public/fonts', license)));
  }
}

// ---------------------------------------------------------------- output

const checking = process.argv.includes('--check');
/** @type {string[]} */
const stale = [];

/** @param {string} path landing-relative @param {string | Buffer} data */
function emit(path, data) {
  const target = join(LANDING, path);
  const next = Buffer.isBuffer(data) ? data : Buffer.from(data, 'utf8');
  if (checking) {
    if (!existsSync(target) || !readFileSync(target).equals(next)) stale.push(path);
    return;
  }
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, next);
}

/** @param {string} label @param {string} content */
function assertPublic(label, content) {
  for (const pattern of PRIVATE_PATTERNS) {
    const found = content.match(pattern);
    must(!found, `${label}: private-looking text "${found?.[0]}" would be published`);
  }
}

function main() {
  const tokens = tokensCss();
  const run = extractRun();
  const cpuProfile = extractCpuProfile(run);
  const record = {
    run,
    excerpts: extractExcerpts(),
    runtime: extractRuntime(),
    sample: extractSample(),
    model: extractModelPin(run.model.id),
    other_models_label: extractModelLabel(),
    runtime_download: extractRuntimePin(run.toolchain.backend),
    cpu_profile: cpuProfile,
    cpu_runtime_download: extractRuntimePin(cpuProfile.backend),
    scanner_download: extractScannerPin(),
    package: extractPackage(),
    download: extractDownload(),
    software: extractSoftware(),
    development: extractDevelopment(),
    sources: Object.fromEntries([...sources.entries()].sort(([a], [b]) => a.localeCompare(b))),
  };
  must(record.model.sha256 === run.model.file_sha256, 'model pin and run disagree');
  must(record.runtime_download.release === run.toolchain.llama_cpp_release, 'runtime pin and run disagree');

  assertPublic('record.json', strings(record).join('\n'));
  emit('src/data/record.json', `${JSON.stringify(record, null, 2)}\n`);
  emit('src/styles/tokens.css', tokens);
  copyFonts();

  if (checking && stale.length > 0) {
    console.error(`Out of date with the saved records:\n  ${stale.join('\n  ')}`);
    process.exit(1);
  }
  console.log(
    checking
      ? `Extraction matches ${sources.size} saved records.`
      : `Wrote public data from ${sources.size} saved records.`,
  );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
