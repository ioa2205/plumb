// @ts-check
// Current artifact claims must come from this ZIP's own checks, never an older package.

/** @param {unknown} value @param {string} message */
function must(value, message) {
  if (!value) throw new Error(`download: ${message}`);
}

/** @param {any} portable @param {any} smoke */
export function matchDownloadEvidence(portable, smoke) {
  const { artifact } = smoke;
  must(portable.passed === true && portable.package_inventory_verified_before_and_after === true,
    'the current portable website check did not pass');
  must(smoke.passed === true && artifact?.passed === true &&
    artifact.zip_inventory_and_hashes_pass === true && artifact.private_files_absent === true,
    'the current inert artifact checks did not pass');
  must(artifact.archive === portable.archive && artifact.archive_bytes === portable.archive_size &&
    artifact.archive_sha256 === portable.archive_sha256 &&
    artifact.inventoried_files === portable.inventory_files &&
    artifact.source_commit === portable.source_commit,
    'inert checks and website acceptance name different package bytes or source');
  must(artifact.source_dirty === false && portable.source_dirty === false,
    'the package was built from uncommitted source');
  must(portable.model_loaded === false && portable.external_website_tested === false &&
    portable.chromium_download_exercised === false && smoke.model_loaded === false &&
    smoke.downloads_or_installation === false,
    'the package checks performed unclaimed inference, downloads or external testing');
  return artifact;
}

/** @param {string} archive */
export function downloadIdentity(archive) {
  const name = archive.split(/[\\/]/).pop() ?? '';
  const built = name.match(/^plumb-[\w.-]+-(\d{4})(\d{2})(\d{2})-[a-z][a-z0-9-]*\.zip$/);
  must(built, 'the ZIP name carries no valid build day or suffix');
  return { name, built_on: /** @type {RegExpMatchArray} */ (built).slice(1).join('-') };
}

/** @param {any} smoke @param {string} runId */
export function reportClaims(smoke, runId) {
  const report = smoke.checks.find((/** @type {any} */ item) => item.args[0] === 'report');
  return {
    older_report_refused: smoke.saved_report_is_historical === true && report?.passed === false &&
      /refused/i.test(report.stdout),
    recorded_report_opened: smoke.report_opened === true && smoke.current_report_unchanged === true &&
      smoke.checks.some((/** @type {any} */ item) => item.passed && item.args[0] === 'report' && item.args[1] === runId),
  };
}
