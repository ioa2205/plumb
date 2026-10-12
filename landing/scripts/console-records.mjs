// @ts-check
// Saves what two read-only Plumb commands print, so the site can show them as recorded
// instead of retyping them. Neither command loads the AI model, downloads anything or
// touches a project: `plumb models` lists the pinned model choices with the memory free at
// that moment, and `plumb ask` answers about a saved finding from its saved evidence.
//
//   node landing/scripts/console-records.mjs <new-output.json>
//
// Run from a source checkout whose data folder holds the recorded run. The output is a new
// file under docs/results/; an existing file is never overwritten.

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = process.argv[2];
if (!output) throw new Error('name the new record file to write');
if (existsSync(output)) throw new Error(`${output} already exists; records are never overwritten`);

const record = JSON.parse(readFileSync(join(REPO, 'landing/src/data/record.json'), 'utf8'));
const runId = record.run.id;
const question = `Explain ${record.run.findings[0].display_id} and its limitations`;

/** @param {string[]} args */
function plumb(args) {
  try {
    return { exit: 0, stdout: execFileSync('uv', ['run', '--locked', 'plumb', ...args], { cwd: REPO, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }) };
  } catch (error) {
    const failed = /** @type {any} */ (error);
    return { exit: failed.status ?? 1, stdout: String(failed.stdout ?? '') };
  }
}

/** Plumb's own model process, if one is running. The capture must leave none behind. */
function modelProcesses() {
  const list = execFileSync('tasklist', ['/FI', 'IMAGENAME eq llama-server.exe', '/NH'], { encoding: 'utf8' });
  return list.split(/\r?\n/).filter((line) => /^llama-server\.exe/i.test(line)).length;
}

const before = modelProcesses();
const printed = plumb(['models']);
const structured = plumb(['models', '--json']);
const answered = plumb(['ask', runId, question]);
const after = modelProcesses();

const catalog = JSON.parse(structured.stdout);
const answer = JSON.parse(answered.stdout);

const result = {
  kind: 'landing_read_only_command_capture',
  recorded_at: new Date().toISOString(),
  source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: REPO, encoding: 'utf8' }).trim(),
  model_processes_before: before,
  model_processes_after: after,
  models: {
    command: 'uv run --locked plumb models',
    exit: printed.exit,
    lines: printed.stdout.split(/\r?\n/).filter((line, index, all) => line !== '' || index < all.length - 1),
    catalog: {
      checked_at: catalog.checked_at,
      selected_profile: catalog.selected_profile,
      available_ram_bytes: catalog.available_ram_bytes,
      available_vram_bytes: catalog.available_vram_bytes,
      models: catalog.models.map((/** @type {any} */ model) => ({
        model_id: model.model_id,
        family: model.family,
        quantization: model.quantization,
        size_bytes: model.size_bytes,
        verified_installed: model.verified_installed,
        unavailable_reason: model.unavailable_reason,
        profiles: model.profiles.map((/** @type {any} */ profile) => ({
          profile_id: profile.profile_id,
          backend: profile.backend,
          hardware_compatible: profile.hardware_compatible,
          memory_fit: profile.memory_fit,
          required_ram_bytes: profile.required_ram_bytes,
          required_vram_bytes: profile.required_vram_bytes,
          first_use_check: profile.first_use_check,
          launch_available: profile.launch_available,
          automatic_eligible: profile.automatic_eligible,
          quality_state: profile.quality_state,
          quality_records: profile.quality_records.map((/** @type {any} */ entry) => entry.path),
        })),
      })),
    },
  },
  ask: {
    command: `uv run --locked plumb ask ${runId} "${question}"`,
    exit: answered.exit,
    run_id: answer.run_id,
    prompt: answer.prompt,
    finding: answer.finding.display_id,
    conclusion: answer.finding.conclusion,
    runtime_verification: answer.finding.runtime_verification,
    exhibits: answer.finding.exhibits.length,
    checks: answer.finding.checks.length,
    unknowns: answer.finding.unknowns,
    limitations: answer.limitations.length,
    generated_by: answer.generated_by,
    network_activity: answer.network_activity,
    authorization_granted: answer.authorization_granted,
  },
};

writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`);
console.log(`Saved ${output}: ${result.models.lines.length} lines from plumb models, ${result.ask.exhibits} exhibits from plumb ask.`);
