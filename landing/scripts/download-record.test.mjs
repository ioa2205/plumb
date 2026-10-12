import assert from 'node:assert/strict';
import { test } from 'node:test';

import { downloadIdentity, matchDownloadEvidence, reportClaims } from './download-record.mjs';
import { setLang } from '../src/lib/lang.mjs';
import { websiteLimits } from '../src/lib/website-limits.mjs';

function records() {
  const portable = {
    passed: true, package_inventory_verified_before_and_after: true,
    archive: 'D:\\data\\plumb-0.0.0-prototype-20261012-web.zip', archive_size: 42,
    archive_sha256: 'a'.repeat(64), inventory_files: 10, source_commit: 'b'.repeat(40),
    source_dirty: false, model_loaded: false, external_website_tested: false,
    chromium_download_exercised: false,
  };
  const smoke = {
    passed: true, model_loaded: false, downloads_or_installation: false,
    artifact: {
      passed: true, zip_inventory_and_hashes_pass: true, private_files_absent: true,
      archive: portable.archive, archive_bytes: portable.archive_size,
      archive_sha256: portable.archive_sha256, inventoried_files: portable.inventory_files,
      source_commit: portable.source_commit, source_dirty: false,
    },
  };
  return {portable, smoke};
}

test('current web suffix and older single-letter suffixes retain their actual date', () => {
  assert.deepEqual(downloadIdentity('D:\\data\\plumb-0.0.0-prototype-20261012-web.zip'), {
    name: 'plumb-0.0.0-prototype-20261012-web.zip', built_on: '2026-10-12',
  });
  assert.equal(downloadIdentity('plumb-0.0.0-prototype-20261011-j.zip').built_on, '2026-10-11');
  assert.throws(() => downloadIdentity('unnamed.zip'));
});

test('fresh evidence agrees on every artifact identity and cannot inherit prior passes', () => {
  const { portable, smoke } = records();
  assert.equal(matchDownloadEvidence(portable, smoke), smoke.artifact);
  for (const field of ['archive', 'archive_bytes', 'archive_sha256', 'inventoried_files', 'source_commit']) {
    const changed = structuredClone(smoke);
    changed.artifact[field] = 'different artifact';
    assert.throws(() => matchDownloadEvidence(portable, changed), /different package/);
  }
  for (const field of ['passed', 'zip_inventory_and_hashes_pass', 'private_files_absent']) {
    const changed = structuredClone(smoke);
    delete changed.artifact[field];
    assert.throws(() => matchDownloadEvidence(portable, changed), /did not pass/);
  }
  assert.throws(() => matchDownloadEvidence({...portable, model_loaded: true}, smoke), /unclaimed/);
  assert.throws(() => matchDownloadEvidence({...portable, external_website_tested: true}, smoke), /unclaimed/);
  assert.throws(() => matchDownloadEvidence(portable, {...smoke, downloads_or_installation: true}), /unclaimed/);
});

test('missing or refused historical report proof never becomes an opened-report claim', () => {
  assert.deepEqual(reportClaims({checks: []}, 'recorded-run'), {
    older_report_refused: false, recorded_report_opened: false,
  });
  assert.deepEqual(reportClaims({checks: [{args: ['report', 'recorded-run'], passed: false,
    stdout: 'Report refused'}], saved_report_is_historical: true}, 'recorded-run'), {
    older_report_refused: true, recorded_report_opened: false,
  });
  const smoke = {checks: [{args: ['report', 'different-run'], passed: true}],
    report_opened: true, current_report_unchanged: true};
  assert.equal(reportClaims(smoke, 'recorded-run').recorded_report_opened, false);
  smoke.checks[0].args[1] = 'recorded-run';
  assert.equal(reportClaims(smoke, 'recorded-run').recorded_report_opened, true);
});

test('both languages distinguish the recorded collector from scoped website permissions', () => {
  const download = {features: {external_testing_enabled: false,
    external_scope_and_qualification_required: true}, external_website_tested: false};
  try {
    setLang('en');
    assert.match(websiteLimits(download), /recorded Tandir requests.*approved scope and plan/);
    setLang('uz');
    assert.match(websiteLimits(download), /Tandir.*tasdiqlagan qamrov va reja/);
    for (const patch of [
      {...download, external_website_tested: true},
      {...download, features: {...download.features, external_scope_and_qualification_required: false}},
    ]) assert.throws(() => websiteLimits(patch), /saved records do not/);
  } finally {setLang('en');}
});
