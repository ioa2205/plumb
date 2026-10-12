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
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PRIVATE_PATTERNS } from './private.mjs';
import { downloadIdentity, matchDownloadEvidence, reportClaims } from './download-record.mjs';

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

/** The summary record of the one real run of the processor-only profile. */
const CPU_RUN = '2026-10-10-a1-cpu-profile-attempt-2.json';

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
  const name = CPU_RUN;
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
    // The review was typed in a source checkout, at a named commit, against the lab's source folder.
    from_source: typeof summary.commit === 'string' && /^plumb review labs\/tandir /.test(review.command),
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

/**
 * The investigator files, by hash, that completed the processor-only review. The review's own
 * invocation record lists them. Only the hashes are read; nothing else in it is published.
 * @param {any} cpuProfile the processor-only run, as extracted above
 * @returns {Record<string, string>}
 */
function extractCpuInvestigator(cpuProfile) {
  const folder = String(json(`${RESULTS}/${CPU_RUN}`).review.records).replace(/\/$/, '');
  const found = readdirSync(join(REPO, folder)).filter((entry) => /^invocation-[\d-]+\.json$/.test(entry));
  must(found.length === 1, `expected one invocation record of the processor-only review, found ${found.length}`);
  const invocation = json(`${folder}/${found[0]}`);
  must(
    invocation.run_id === cpuProfile.review.id &&
      invocation.profile.id === cpuProfile.id &&
      invocation.lifecycle === cpuProfile.review.lifecycle &&
      invocation.requests.length === cpuProfile.review.model_requests,
    'the invocation record is not the processor-only review',
  );
  return invocation.implementation;
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
 * The Windows package offered for download, built from the current source. Only facts its two
 * saved checks recorded are kept. Neither check loaded a model, so nothing here says that the
 * package has run a review: the pages have to say that it has not.
 *
 * Inert command/protection checks must pass. Historical report refusals are expected outcomes,
 * separate from an opened current report and from the newer no-model owned website journey.
 * @param {any} run the recorded run, as extracted above
 * @param {any} cpuProfile the processor-only run, as extracted above
 * @param {Record<string, string>} cpuInvestigator the files that completed that run, by hash
 * @param {any} scanner the pinned pattern scanner
 */
function extractDownload(run, cpuProfile, cpuInvestigator, scanner) {
  const portable = json(`${RESULTS}/2026-10-12-website-repair-portable.json`);
  const smoke = json(`${RESULTS}/2026-10-12-website-publication-portable-inert.json`);
  const followup = smoke;
  const planning = json(`${RESULTS}/2026-10-12-website-repair-planning.json`);
  const recorded = json(`${RESULTS}/2026-10-08-m7.7f-package-smoke.json`).artifact;
  const artifact = matchDownloadEvidence(portable, smoke);
  must(planning.conditions.type_qualified_for_exact_pins === false && planning.conditions.actual_model_menu_choice === false,
    'the current planning record no longer supports its unqualified limit');
  const check = (/** @type {string} */ command) => smoke.checks.find((/** @type {any} */ entry) => entry.args[0] === command);
  must(check('--help')?.passed && check('setup')?.passed && check('inspect')?.passed && smoke.web.passed, 'download command checks did not pass');
  const features = followup.feature_checks;
  must(
    features?.included_modules_import === true && features.security_card_pack_loaded === true &&
      features.security_card_count === 3 && features.security_card_license_present === true &&
      features.baseline_default_preserved === true && features.website_missing_runner_refused === true &&
      features.model_loaded === false && features.external_testing_enabled === false &&
      features.external_scope_and_qualification_required === true,
    'the current package features or unchanged safety defaults were not checked',
  );
  const identity = downloadIdentity(String(artifact.archive));

  // The investigator: the files Plumb records as its identity in every review.
  const files = /** @type {Record<string, string>} */ (artifact.implementation_sha256);
  const before = /** @type {Record<string, string>} */ (recorded.implementation_sha256);
  const names = Object.keys(files);
  must(Object.keys(before).every((file) => file in files), 'the download dropped an investigator file of the recorded package');
  must(names.every((file) => artifact.implementation_matches[file] === true), 'a packaged investigator file differs from its declared identity');
  const sameAs = (/** @type {Record<string, string>} */ other) =>
    Object.keys(other).length === names.length && names.every((file) => other[file] === files[file]);
  // The same files in the source code as it stands now, hashed here rather than taken on trust.
  const sourceNow = Object.fromEntries(
    names.map((file) => [file, existsSync(join(REPO, file)) ? sha256(readFileSync(join(REPO, file))) : '']),
  );

  // What the package's own commands printed, with no model loaded.
  const doctor = JSON.parse(check('doctor').stdout);
  const preview = JSON.parse(check('setup').stdout);

  return {
    ...identity,
    archive_bytes: artifact.archive_bytes,
    archive_sha256: artifact.archive_sha256,
    inventoried_files: artifact.inventoried_files,
    checked_at: smoke.created_at,
    // Every source file inside the package was compared with the checkout it was built from;
    // the artifact check does not pass unless all of them match.
    source_files_checked: artifact.current_source_files_checked,
    investigator_files: names.length,
    investigator_same_as_source: sameAs(sourceNow),
    same_investigator_as_cpu_profile_run: sameAs(cpuInvestigator),
    since_recorded_test: {
      same: names.filter((file) => before[file] === files[file]).length,
      changed: names.filter((file) => file in before && before[file] !== files[file]),
      added: names.filter((file) => !(file in before)),
    },
    has_cpu_profile: names.includes('backend/cpu_profile.py') && followup.profile_ids.includes(cpuProfile.id),
    has_calibrate_command: followup.has_calibrate_command === true,
    first_use_check_importable: followup.first_use_modules_import === true,
    // doctor names the default model and says, model by model, whether it fits in free memory.
    doctor_advises_on_models:
      doctor.model_recommendation?.default_model === run.model.id &&
      doctor.model_candidates.length > 1 &&
      doctor.model_candidates.every((/** @type {any} */ entry) => 'fits_available_ram' in entry),
    // The setup preview carries the model chosen with --model; earlier packages had no such field.
    setup_takes_model: 'model' in preview,
    knows_pattern_scanner: doctor.pattern_scanner?.name === scanner.name && doctor.pattern_scanner?.release === scanner.release,
    model_loaded: [smoke.model_loaded, portable.model_loaded, doctor.model_loaded, preview.model_loaded].some((value) => value !== false),
    // The checks used the model and its runner as already installed on the laptop: the
    // package's own install step fetched nothing.
    downloaded_or_installed: [smoke.downloads_or_installation, doctor.downloads_started, portable.chromium_download_exercised].some((value) => value !== false),
    model_already_installed: followup.doctor_summary?.model_verified === true && followup.doctor_summary?.runtime_verified === true,
    developer_tools_on_path: smoke.developer_tools_on_path || followup.developer_tools_on_path,
    clean_user_profile: smoke.clean_user_profile,
    folder_name_had_spaces: smoke.package_path_contains_spaces,
    launch_rechecks_memory: doctor.profiles.length > 0 && doctor.profiles.every((/** @type {any} */ profile) => profile.launch_rechecks_memory === true),
    doctor_refused_for_memory: followup.doctor_summary?.messages?.some((/** @type {string} */ m) => /RAM/.test(m)) ?? false,
    ...reportClaims(smoke, run.id),
    pinned_browser_checked: portable.conditions.pinned_browser_used === true && portable.calls.some((/** @type {any} */ entry) => entry.arguments[0] === 'browser' && entry.arguments[1] === 'check' && entry.returncode === 0),
    owned_website_completed: portable.conditions.journey_done === true && portable.conditions.designated_accounts_confirmed === true && portable.conditions.defended_has_no_findings === true,
    external_website_tested: portable.external_website_tested,
    model_planning_qualified: planning.conditions.type_qualified_for_exact_pins,
    features: {
      included_modules_import: features.included_modules_import,
      security_card_count: features.security_card_count,
      security_card_license_present: features.security_card_license_present,
      baseline_default_preserved: features.baseline_default_preserved,
      website_missing_runner_refused: features.website_missing_runner_refused,
      external_testing_enabled: features.external_testing_enabled,
      external_scope_and_qualification_required: features.external_scope_and_qualification_required,
    },
  };
}

/** Separate saved accounting of the later experimental observation comparison, never a ZIP review. */
function extractObservationComparison() {
  const accounting = json(`${RESULTS}/2026-10-11-tool-assisted/accounting.json`);
  must(accounting.saved_outputs_validated === true && accounting.replay_only === true, 'observation accounting was not validated as saved output');
  must(accounting.execution_state === 'resource_or_scope_stopped' && accounting.unrun_conditions > 0, 'observation comparison did not stop with unfinished conditions');
  must(
    accounting.summary.length === 4 && accounting.summary.every((/** @type {any} */ result) =>
      result.correct === 0 && result.incorrect_decisive === 0 && result.supported === 0 && result.inconclusive === result.analyzed_cases),
    'the observation comparison no longer supports the stated quality limit',
  );
  // The run itself, condition by condition: what was asked, what came back and why it stopped.
  const execution = json(`${TOOL}/execution.json`);
  const plan = json(`${TOOL}/preparation.json`);
  must(execution.state === accounting.execution_state && execution.unrun_conditions === accounting.unrun_conditions, 'the comparison run and its accounting disagree');
  must(execution.target_executed === false && execution.final_evaluation === false && execution.runtime_verification === 'not_attempted', 'the comparison ran something it should not have');
  must(plan.max_retries === 0 && plan.seeds.length === plan.per_condition_requests, 'the comparison plan changed');
  const approaches = /** @type {string[]} */ (accounting.summary.map((/** @type {any} */ entry) => entry.approach));
  const sum = (/** @type {number[]} */ values) => values.reduce((a, b) => a + b, 0);
  const conditions = execution.conditions.map((/** @type {any} */ entry) => ({
    case: entry.case_id,
    approach: entry.approach,
    expected: entry.expected_interpretation,
    conclusion: entry.analysis.conclusion,
    stop_reason: entry.analysis.stop_reason,
    attempts: entry.attempted_requests,
    answers: entry.completed_requests,
    prompt_tokens: entry.prompt_tokens,
    completion_tokens: entry.completion_tokens,
    usage_unknown_requests: entry.token_usage_unavailable_requests,
    wall_seconds: sum(entry.wall_seconds),
    correct: entry.correct,
  }));
  must(conditions.every((/** @type {any} */ entry) => approaches.includes(entry.approach) && entry.conclusion === 'inconclusive' && entry.correct === false), 'a comparison condition is no longer Inconclusive');
  must(sum(conditions.map((/** @type {any} */ entry) => entry.attempts)) === execution.judgment_attempts, 'comparison attempts do not add up');
  const planned = plan.cases.length * approaches.length;
  must(planned === conditions.length + execution.unrun_conditions, 'planned, run and unrun comparison conditions do not add up');
  return {
    acceptance_met: false,
    completed_analyses_inconclusive: true,
    conditions_unrun: true,
    baseline_retained: true,
    recorded_at: execution.started_at,
    seconds: execution.seconds,
    attempts: execution.judgment_attempts,
    answers: sum(conditions.map((/** @type {any} */ entry) => entry.answers)),
    planned,
    unrun: execution.unrun_conditions,
    cases: plan.cases.map((/** @type {any} */ entry) => ({ id: entry.case_id, expected: entry.expected_interpretation })),
    approaches,
    limits: {
      attempts: plan.max_judgment_attempts,
      seconds: plan.max_seconds,
      condition_attempts: plan.per_condition_requests,
      condition_seconds: plan.per_condition_seconds,
      retries: plan.max_retries,
    },
    profile: plan.profile.id,
    model: plan.profile.model_id,
    guidance_card: plan.guidance_card.id,
    conditions,
  };
}

// ---------------------------------------------------------------- web assessment

const TOOL = `${RESULTS}/2026-10-11-tool-assisted`;

/**
 * The one recorded collection of requests from the bundled practice app: the plan that was
 * shown, what was approved, and what each request got back. Sign-in replies are not kept as
 * evidence, so those steps carry no answer here. The run's own port number is left out.
 */
function extractCollection() {
  const saved = json(`${TOOL}/collection.json`);
  const preview = saved.preview.preview;
  const { trace } = saved;
  const permission = saved.developer_test_permission;
  must(saved.state === 'completed_pending_human_review' && saved.human_attachment_review === 'pending' && saved.automatic_import === false, 'the collection is no longer waiting for human review');
  must(saved.external_access_enabled === false && preview.external_access_enabled === false, 'the collection reached beyond the practice app');
  must(saved.model_loaded === false && saved.runtime_verification === 'not_attempted', 'the collection claims more than requests and answers');
  must(saved.preview.preview_sha256 === trace.preview_sha256 && permission.preview_sha256 === trace.preview_sha256 && permission.reviewed_preview === true, 'the approval is not for the plan that ran');
  must(/^http:\/\/127\.0\.0\.1:\d+$/.test(trace.runner_origin), 'the collection did not stay on this computer');
  must(trace.stopped === false && trace.stop_reason === null && trace.requests_used === preview.actions.length, 'the collection did not complete its plan');
  must(permission.approved_action_ids.length === preview.actions.length, 'not every planned request was approved');
  must(trace.requests_used <= preview.max_requests && trace.bytes_received <= preview.max_total_bytes && trace.seconds <= preview.max_seconds, 'the collection went over its limits');

  const records = new Map(trace.records.map((/** @type {any} */ entry) => [entry.artifact_id, entry]));
  const actions = preview.actions.map((/** @type {any} */ action, /** @type {number} */ index) => {
    const progress = trace.action_progress[index];
    must(progress.action_id === action.action_id && progress.completed === true && progress.attempts === 1 && progress.missing_evidence.length === 0, `${action.action_id}: not completed in one attempt`);
    must(permission.approved_action_ids.includes(action.action_id), `${action.action_id}: ran without approval`);
    const kept = progress.artifact_ids.map((/** @type {string} */ id) => records.get(id));
    must(kept.length <= 1 && kept.every(Boolean), `${action.action_id}: unexpected evidence`);
    const [answer] = kept;
    if (answer) must(answer.context.account_id === action.account_id && answer.request.method === action.method, `${action.action_id}: answer does not match the plan`);
    /** @type {any} */
    let body = null;
    try {
      body = answer ? JSON.parse(answer.response.body) : null;
    } catch {
      body = null;
    }
    return {
      id: action.action_id,
      account: action.account_id,
      method: action.method,
      template: action.path,
      path: answer ? new URL(answer.request.url).pathname : action.path,
      purpose: action.purpose,
      state_change: action.state_change,
      kept: Boolean(answer),
      status: answer ? answer.response.status : null,
      marker_present: answer ? String(answer.response.body).includes(preview.spec.marker) : null,
      detail: body && typeof body.detail === 'string' ? body.detail : null,
    };
  });
  must(records.size === actions.filter((/** @type {any} */ action) => action.kept).length, 'kept answers and plan disagree');

  // What "safe" would look like, as the plan itself declares it.
  const expectations = [...preview.spec.requests, ...preview.control_spec.requests]
    .filter((/** @type {any} */ request) => request.role !== 'setup')
    .map((/** @type {any} */ request) => ({ account: request.principal, method: request.method, template: request.path, role: request.role, expected_if_safe: request.expected_if_safe }));

  return {
    recorded_at: saved.started_at,
    seconds: trace.seconds,
    requests: trace.requests_used,
    bytes_received: trace.bytes_received,
    runner: preview.runner,
    loopback_only: true,
    marker: preview.spec.marker,
    limits: {
      requests: preview.max_requests,
      seconds: preview.max_seconds,
      response_bytes: preview.max_response_bytes,
      total_bytes: preview.max_total_bytes,
      permission_hours: (Date.parse(permission.expires_at) - Date.parse(preview.created_at)) / 3_600_000,
    },
    approved_by: permission.approved_by,
    human_review: saved.human_attachment_review,
    imported: saved.automatic_import,
    external_access: saved.external_access_enabled,
    model_loaded: saved.model_loaded,
    runtime_verification: saved.runtime_verification,
    actions,
    expectations,
  };
}

/** The three reviewed method cards Plumb can hand the model, by title and source. */
function extractCards() {
  const path = 'knowledge/data/security-cards-v1.json';
  const pack = json(path);
  const checked = json(`${TOOL}/playbooks.json`);
  must(sources.get(path) === checked.pack.sha256, 'the card pack differs from the one that was checked');
  must(pack.cards.length === 3 && pack.cards.every((/** @type {any} */ card) => card.kind === 'methodology_only'), 'the card pack changed');
  must(checked.target_authority === false && checked.cloud_inference === false && checked.verification.result === 'passed', 'the card checks did not pass');
  return {
    version: pack.version,
    license: pack.license_id,
    bytes: bytes(path).length,
    tests: checked.verification.tests,
    cards: pack.cards.map((/** @type {any} */ card) => ({
      id: card.id,
      title: card.title,
      family: card.family,
      sources: card.sources.map((/** @type {any} */ source) => ({ id: source.source_id, title: source.title, version: source.version })),
    })),
  };
}

/**
 * What `plumb models` and `plumb ask` printed when they were run for this site, from the
 * record landing/scripts/console-records.mjs saved. Neither loads the model.
 * @param {any} run the recorded run @param {any} cpuProfile the processor-only run
 */
function extractConsoleRecords(run, cpuProfile) {
  const saved = json(`${RESULTS}/2026-10-12-m7.9j-read-only-commands.json`);
  must(saved.model_processes_before === 0 && saved.model_processes_after === 0, 'a model process was running during the capture');
  must(saved.models.exit === 0 && saved.ask.exit === 0, 'a captured command failed');
  const { catalog } = saved.models;
  const models = catalog.models.map((/** @type {any} */ model) => {
    const states = [...new Set(model.profiles.map((/** @type {any} */ profile) => profile.quality_state))];
    must(states.length <= 1, `${model.model_id}: profiles disagree on quality`);
    return {
      id: model.model_id,
      family: model.family,
      quantization: model.quantization,
      size_bytes: model.size_bytes,
      installed: model.verified_installed,
      quality: states[0] ?? 'untested',
      profiles: model.profiles.map((/** @type {any} */ profile) => ({
        id: profile.profile_id,
        backend: profile.backend,
        required_ram_bytes: profile.required_ram_bytes,
        required_vram_bytes: profile.required_vram_bytes,
        memory_fit: profile.memory_fit,
        first_use_check: profile.first_use_check,
        launch_available: profile.launch_available,
        automatic_eligible: profile.automatic_eligible,
      })),
    };
  });
  const [first] = models;
  must(first.id === run.model.id && first.quality === 'recorded_scoped' && first.installed === true, 'the default model is no longer the one with a recorded result');
  must(first.profiles.some((/** @type {any} */ profile) => profile.id === run.profile) && first.profiles.some((/** @type {any} */ profile) => profile.id === cpuProfile.id), 'the default model lost a recorded profile');
  must(models.slice(1).every((/** @type {any} */ model) => model.quality === 'untested' && model.installed === false && model.profiles.every((/** @type {any} */ profile) => !profile.automatic_eligible)), 'another model is no longer untested');
  must(saved.ask.run_id === run.id && saved.ask.finding === run.findings[0].display_id && saved.ask.conclusion === run.findings[0].conclusion, 'the captured question is not about the recorded finding');
  must(saved.ask.generated_by === 'saved_evidence' && saved.ask.network_activity === false && saved.ask.authorization_granted === false, 'the captured answer did more than read saved evidence');
  return {
    recorded_at: saved.recorded_at,
    models: {
      command: saved.models.command,
      lines: saved.models.lines,
      available_ram_bytes: catalog.available_ram_bytes,
      selected_profile: catalog.selected_profile,
      list: models,
    },
    ask: {
      prompt: saved.ask.prompt,
      finding: saved.ask.finding,
      conclusion: saved.ask.conclusion,
      exhibits: saved.ask.exhibits,
      checks: saved.ask.checks,
      limitations: saved.ask.limitations,
      generated_by: saved.ask.generated_by,
    },
  };
}

/** The saved check of the workbench's new screens, which the site's pictures are cut from. */
function extractWorkbenchViews() {
  const saved = json(`${RESULTS}/2026-10-11-improvements-ui-checks.json`);
  must(saved.passed === true && saved.errors.length === 0 && saved.model_loaded === false && saved.runner_started === false, 'the workbench view check did not pass');
  must(saved.samples.every((/** @type {any} */ sample) => sample.violations.length === 0 && sample.emptyButtons === 0 && sample.scrollWidth <= sample.width), 'a workbench view overflowed or broke its page policy');
  return {
    captures: saved.samples.length,
    screens: [...new Set(saved.samples.map((/** @type {any} */ sample) => sample.screen))],
    widths: [...new Set(saved.samples.map((/** @type {any} */ sample) => sample.width))],
    fresh_model_acceptance: saved.fresh_model_acceptance,
    signed_in_acceptance: saved.authenticated_backend_acceptance,
    label: saved.label,
  };
}

/** The private report drafts written from the comparison's synthetic cases. None was exported. */
function extractReportDrafts() {
  const saved = json(`${TOOL}/private-reports.json`);
  const parts = ['description', 'safe_steps', 'impact', 'mitigation', 'tools', 'limitations'];
  must(saved.published === false && saved.synthetic_fixtures_only === true, 'a private report draft was published');
  must(
    saved.reports.every((/** @type {any} */ report) => parts.every((part) => report[part] === true) && report.endpoints.length > 0 && report.claimed_runtime_verification === 'not_attempted'),
    'a report draft lost a required part',
  );
  return { count: saved.reports.length, published: saved.published, synthetic_only: saved.synthetic_fixtures_only, parts: ['description', 'endpoints', ...parts.slice(1)] };
}

/** The read-only connection for other tools (MCP), as its saved acceptance check recorded it. */
function extractToolConnection() {
  const saved = json(`${RESULTS}/2026-10-06-m7.4-acceptance.json`);
  must(saved.passed === true && saved.model_loaded === false && saved.target_executed === false && saved.saved_report_files_unchanged === true, 'the tool connection check did not pass');
  must(saved.remaining_owned_child_pids.length === 0, 'the tool connection check left a process behind');
  const listings = saved.calls.filter((/** @type {any} */ call) => Array.isArray(call.tools));
  const names = listings.map((/** @type {any} */ call) => call.tools.map((/** @type {any} */ tool) => tool.name).sort().join(' '));
  must(listings.length === 2 && names[0] === names[1], 'the two connection modes list different lookups');
  return { recorded_at: saved.started, lookups: names[0].split(' '), modes: listings.length };
}

/** The latest whole run of the Python tests, with its one failure and how it was repaired. */
function extractLatestSuite() {
  const saved = json(`${TOOL}/software-checks.json`);
  const full = saved.python_full_run;
  must(saved.fresh_inference === false && full.collected === full.passed + full.failed + full.skipped, 'the latest suite figures do not add up');
  const repaired = saved.repairs.at(-1);
  must(repaired.failed === 0 && repaired.passed > 0, 'the repair of the latest suite failure did not pass');
  return { date: saved.date, collected: full.collected, passed: full.passed, failed: full.failed, skipped: full.skipped, repaired_checks: repaired.passed, schemas: saved.schemas.schemas };
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

// ---------------------------------------------------------------- the website test

const JOURNEY = `${RESULTS}/2026-10-12-website-repair-open`;

/**
 * The one recorded website test: Plumb's own practice website (Chorsu Parcel Lockers), its
 * synthetic accounts, the owner's rule, and what each account received for the same pickup
 * label. Refused unless it stayed on the owned fixture, ran only the approved plan, kept to
 * its limits, and left every finding a lead rather than a confirmed one.
 */
function extractJourney() {
  const journey = json(`${JOURNEY}/journey.json`);
  const scope = json(`${JOURNEY}/scope.json`);
  const acceptance = json(`${JOURNEY}/acceptance.json`);
  const conditions = Object.entries(acceptance.conditions);
  must(conditions.length > 0 && conditions.every(([, held]) => held === true), 'the website test acceptance did not hold');
  must(JSON.stringify(journey.scope) === JSON.stringify(scope), 'the website test and its saved scope differ');
  must(scope.mode === 'owned_fixture' && scope.targets.every((/** @type {any} */ target) => /^http:\/\/127\.0\.0\.1:\d+$/.test(target.origin)), 'the website test left Plumb’s own practice website');
  must(journey.status === 'done' && journey.approval.reviewed_plan === true && journey.approval.plan_sha256 === journey.plan_sha256, 'the website test did not run one approved plan to the end');
  must(journey.approval.approved_step_ids.length === journey.steps.length && journey.steps.every((/** @type {any} */ step) => step.state === 'completed'), 'the website test ran steps outside its approval');
  const { spent } = journey;
  must(spent.requests <= scope.budget.max_requests && spent.seconds <= scope.budget.max_seconds && spent.bytes <= scope.budget.max_bytes, 'the website test went over its limits');
  must(journey.findings.length > 0 && journey.findings.every((/** @type {any} */ finding) => finding.conclusion === 'candidate' && finding.runtime === 'observed_once_by_plumb_runner'), 'a website finding says more than a lead observed once');
  must(journey.incidents.length === 0, 'the website test recorded a privacy incident');

  const check = journey.checks.find((/** @type {any} */ entry) => entry.check_id === 'check-rule-1-rustam');
  must(check && check.state === 'completed' && check.comparison === 'candidate' && check.gaps.length === 0, 'the label comparison is missing or incomplete');
  const rule = scope.rules.find((/** @type {any} */ entry) => entry.rule_id === check.rule_id);
  const object = scope.objects.find((/** @type {any} */ entry) => entry.object_id === check.object_id);
  must(rule.allowed_account_ids.length === 1 && rule.allowed_account_ids[0] === check.owner_account_id && object.owner_account_id === check.owner_account_id, 'the rule and the object name different owners');
  must(object.synthetic === true && object.marker, 'the compared object is not a marked synthetic one');
  const fact = (/** @type {string} */ name) => check.facts[name];
  must(fact('owner received the object') === 'yes' && fact('other account received the object') === 'yes' && fact('response captures complete') === 'yes', 'the comparison does not show both accounts receiving the label');
  const finding = journey.findings.find((/** @type {any} */ entry) => entry.check_id === check.check_id);
  must(finding, 'no finding comes from the label comparison');
  const name = (/** @type {string} */ id) => scope.accounts.find((/** @type {any} */ account) => account.account_id === id).label.replace(/ \(.*\)$/, '');

  return {
    recorded_at: journey.created_at,
    site: scope.name.replace(/ \(.*\)$/, ''),
    mode: scope.mode,
    purpose: scope.purpose,
    accounts: scope.accounts.length,
    signup_approved: scope.allowed_actions.includes('sign_up'),
    rule: rule.statement,
    object: object.kind,
    path: object.path,
    owner: name(check.owner_account_id),
    other: name(check.other_account_id),
    owner_status: Number(fact('owner status')),
    other_status: Number(fact('other account status')),
    signed_out_status: Number(fact('signed-out status')),
    identical: fact('responses are identical') === 'yes',
    comparison: check.comparison,
    finding: { id: finding.finding_id, conclusion: finding.conclusion, runtime: finding.runtime },
    findings: journey.findings.length,
    supported: journey.findings.filter((/** @type {any} */ entry) => entry.conclusion === 'supported').length,
    pages: journey.pages.length,
    requests: spent.requests,
    max_requests: scope.budget.max_requests,
    seconds: Math.round(spent.seconds),
    max_seconds: scope.budget.max_seconds,
    model_questions: spent.model_questions,
    steps: journey.steps.length,
    stop_conditions: scope.stop_conditions.length,
    // How the test got in: a real browser, accounts signed in, and one created by an
    // approved sign-up. A hand-off is a pause for a person (a CAPTCHA or a one-time code).
    browser_used: journey.browser === 'used',
    signed_in: journey.accounts.filter((/** @type {any} */ account) => account.state === 'signed_in').length,
    created: journey.accounts.filter((/** @type {any} */ account) => account.state === 'created').length,
    handoffs: journey.handoffs.length,
    ...websiteControls(),
  };
}

/** What a person can do with a website test, read from the code: its commands, and the sign-in steps handed to them. */
function websiteControls() {
  const cli = text('backend/web_cli.py');
  const commands = cli.match(/choices=\[((?:"[a-z]+", )*"[a-z]+")\]/g)?.map((list) => [...list.matchAll(/"([a-z]+)"/g)].map((match) => match[1])).find((list) => list.includes('qualify'));
  must(commands && ['setup', 'run', 'show', 'report', 'stop'].every((command) => commands.includes(command)), 'the website commands changed');
  const contract = text('backend/contracts/web_journey.py');
  const kinds = contract.match(/challenge: Literal\[((?:"\w+", )*"\w+")\]/)?.[1].match(/\w+/g);
  must(kinds && kinds.includes('captcha') && kinds.includes('one_time_code'), 'the sign-in steps handed to a person changed');
  return { commands, handed_over: kinds };
}

/**
 * What a review notes beside its findings: shapes of secrets, two configuration rules and
 * the bundled list of known-vulnerable package versions. Read from the shipped code and the
 * pinned list, so the site cannot claim more rules or advisories than Plumb carries.
 */
function extractSignals() {
  const pin = json('analysis/advisory_pack/pin.json');
  const data = bytes('analysis/advisory_pack/pack.json');
  must(sha256(data) === pin.sha256 && data.length === pin.size, 'the advisory list differs from its pin');
  const pack = JSON.parse(data.toString('utf8'));
  must(Array.isArray(pack.records) && pack.records.length > 0 && /^\d{4}-\d{2}-\d{2}$/.test(pack.snapshot_date), 'the advisory list is unreadable');
  const observer = text('analysis/security_signals.py');
  const version = observer.match(/^VERSION = "([^"]+)"$/m)?.[1];
  const rules = [...new Set(observer.match(/"config-[a-z-]+"/g) ?? [])].map((rule) => rule.slice(1, -1));
  must(version === 'supplementary-signals-1' && rules.length === 2, 'the signal rules changed: reread what the site says about them');
  must(/package-lock\.json/.test(observer) && /uv\.lock/.test(observer), 'the lock files the advisories are matched against changed');
  const recorded = text(`${RESULTS}/2026-10-07-m3.14-signals.md`);
  must(/Signals never enter finding IDs/.test(recorded) && /\[REDACTED\]/.test(recorded), 'the signals record no longer says they stay apart from findings and hide secret values');
  return {
    version,
    config_rules: rules,
    advisories: pack.records.length,
    advisories_dated: pack.snapshot_date,
    advisories_from: pack.publisher,
  };
}

/**
 * The decisions a reviewer can record on a finding. They are appended beside it and never
 * rewrite its conclusion or evidence.
 */
function extractDecisions() {
  const contract = text('backend/contracts/investigation.py');
  const block = contract.match(/class Disposition\(StrEnum\):\n((?: {4}\w+ = "\w+"\n)+)/);
  must(block, 'the reviewer decisions are no longer listed where the site reads them');
  const values = [...block[1].matchAll(/= "(\w+)"/g)].map((match) => match[1]);
  must(JSON.stringify(values) === JSON.stringify(['open', 'dismissed', 'accepted_risk', 'resolved']), 'the reviewer decisions changed: reread what the site says about them');
  must(/no evidence or runtime fields are writable/.test(contract), 'a reviewer decision may now change evidence');
  return values;
}

/**
 * The one recorded conversation with the local model: a general question, answered and
 * labelled as general knowledge, with nothing run or approved. Only the first paragraph of
 * the answer is published, word for word.
 */
function extractChat() {
  const saved = json(`${RESULTS}/2026-10-12-website-repair-chat.json`);
  const accounting = json(`${RESULTS}/2026-10-12-website-repair-chat.accounting.json`);
  must(accounting.source === '2026-10-12-website-repair-chat.json' && accounting.fresh_inference === false && accounting.passed === true, 'the chat accounting does not cover the saved session');
  must(saved.cleanup_completed === true && saved.conditions.chat_granted_no_authority === true, 'the chat session granted something or left the model running');
  const turn = saved.turns.find((/** @type {any} */ entry) => entry.name === 'ordinary');
  must(turn && turn.state === 'completed' && turn.turn.intent === 'general_question', 'the general question is missing');
  const { turn: answer } = turn;
  must(answer.authorization_granted === false && answer.actions_executed === false && answer.finding_created === false, 'a chat answer changed something');
  must(answer.parts.length === 1 && answer.parts[0].kind === 'general' && answer.parts[0].evidence.length === 0, 'the general answer carries evidence it should not');
  // Which turns did not do what they were asked: published as a count, never hidden.
  const mixed = saved.turns.find((/** @type {any} */ entry) => entry.name === 'mixed');
  const general = mixed.turn.parts.find((/** @type {any} */ part) => part.kind === 'general');
  const declined = /^I cannot provide/.test(general.text);
  return {
    recorded_at: saved.at,
    profile: saved.profile_requested,
    prompt: answer.prompt,
    answer: answer.parts[0].text.split('\n\n')[0],
    basis: answer.parts[0].basis,
    message: turn.message,
    model_seconds: answer.model_seconds,
    turns: saved.turns.length,
    mixed_general_declined: declined,
    mixed_cited_by_code: mixed.turn.parts.some((/** @type {any} */ part) => part.kind === 'cited' && /by code/.test(part.basis)),
    first_run_unmet: saved.unmet,
  };
}

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
  const scanner = extractScannerPin();
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
    scanner_download: scanner,
    download: extractDownload(run, cpuProfile, extractCpuInvestigator(cpuProfile), scanner),
    observation_comparison: extractObservationComparison(),
    collection: extractCollection(),
    cards: extractCards(),
    console_records: extractConsoleRecords(run, cpuProfile),
    workbench_views: extractWorkbenchViews(),
    report_drafts: extractReportDrafts(),
    tool_connection: extractToolConnection(),
    journey: extractJourney(),
    chat: extractChat(),
    signals: extractSignals(),
    decisions: extractDecisions(),
    software: { ...extractSoftware(), latest: extractLatestSuite() },
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
      ? `Extraction matches ${sources.size} files: ${[...sources.keys()].filter((path) => path.startsWith(RESULTS)).length} saved records and the code they are checked against.`
      : `Wrote public data from ${sources.size} files: ${[...sources.keys()].filter((path) => path.startsWith(RESULTS)).length} saved records and the code they are checked against.`,
  );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
