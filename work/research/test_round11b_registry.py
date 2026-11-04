"""Synthetic R11-02 and approval-registry checks. No real approval or API."""
import copy
import io
import json
import unittest
import uuid
from contextlib import redirect_stdout
from unittest.mock import patch

import round11_ecos_snapshot_pipeline as p
import test_round11_pipeline as fixtures
import round11_baseline_registry as r


def dataset(months):
    return [{'table_code': '512Y008', 'item_code1': 'BD', 'item_code2': code,
             'forecast_target_month': t, 'survey_month': p.shift(t, -1), 'value': '10'}
            for code in p.SECTORS for t in months]


class FixtureCase(unittest.TestCase):
    def setUp(self):
        fixtures.PipelineChecks.setUp(self)

    def collect(self, server):
        return fixtures.PipelineChecks.collect(self, server)


class DataGateChecks(FixtureCase):
    def test_baseline_internal_gap_is_not_a_new_month(self):
        old = dataset(['2026-09', '2026-11'])
        new = dataset(['2026-09', '2026-10', '2026-11'])
        windows = {code: ['2026-09', '2026-11'] for code in p.SECTORS}
        self.assertEqual(sum(e['classification'] == 'NEW_TARGET_MONTH' for e in p.compare(old, new, windows)), 2)
        with self.assertRaisesRegex(p.PipelineError, 'BASELINE_INTERNAL_GAP'):
            p.compare_strict(old, new, windows)

    def test_strict_schema_duplicate_range_and_candidate_gaps(self):
        healthy = dataset(['2026-09', '2026-10', '2026-11'])
        cases = []
        cases.append((healthy + [healthy[0]], 'BASELINE_DUPLICATE_MONTH'))
        wrong = copy.deepcopy(healthy); wrong[0]['forecast_target_month'] = '2026-13'
        cases.append((wrong, 'BASELINE_INVALID_MONTH'))
        wrong = copy.deepcopy(healthy); wrong[0]['survey_month'] = '2026-09'
        cases.append((wrong, 'BASELINE_SURVEY_MONTH_MISMATCH'))
        cases.append(([r for r in healthy if not (r['item_code2'] == 'C3000' and r['forecast_target_month'] == '2026-11')], 'BASELINE_SECTOR_RANGE_MISMATCH'))
        for rows, error in cases:
            with self.assertRaisesRegex(p.PipelineError, error):
                p.validate_dataset(rows)
        with self.assertRaisesRegex(p.PipelineError, 'SNAPSHOT_INTERNAL_GAP'):
            p.validate_dataset(dataset(['2026-09', '2026-11']), 'SNAPSHOT')
        wrong = copy.deepcopy(healthy); wrong[0]['value'] = '1E+1'
        with self.assertRaisesRegex(p.PipelineError, 'SNAPSHOT_NONCANONICAL_V2_VALUE'):
            p.validate_dataset(wrong, 'SNAPSHOT', fixed_point=True)

    def test_new_month_year_boundary_and_historical_extension(self):
        old = dataset(['2026-12'])
        new = dataset(['2026-11', '2026-12', '2027-01'])
        windows = {code: ['2026-11', '2027-01'] for code in p.SECTORS}
        events = p.compare_strict(old, new, windows)
        self.assertEqual(sum(e['classification'] == 'HISTORICAL_EXTENSION' for e in events), 2)
        self.assertEqual(sum(e['classification'] == 'NEW_TARGET_MONTH' for e in events), 2)
        self.assertEqual({e['forecast_target_month'] for e in events if e['classification'] == 'NEW_TARGET_MONTH'}, {'2027-01'})

    def test_new_collection_stops_before_api_on_bad_baseline(self):
        p.BASELINE.write_bytes(p.encoded(dataset(['2026-09', '2026-11'])))
        p.BASE_MANIFEST.write_bytes(p.encoded([{'file': p.BASELINE.name, 'sha256': p.sha(p.BASELINE.read_bytes())}]))
        with patch.object(p, 'urlopen', side_effect=AssertionError('NO API')) as network:
            result, _ = p.collect_once()
            network.assert_not_called()
        self.assertNotEqual(result['exit_code'], 0)
        self.assertEqual(result['counts']['NEW_TARGET_MONTH'], 0)
        self.assertIn('BASELINE_INTERNAL_GAP', [r['code'] for r in result['validation_issues']])


class RegistryChecks(FixtureCase):
    def setUp(self):
        super().setUp()
        legacy = self.root / 'legacy'
        legacy.mkdir()
        baseline, manifest = legacy / 'baseline.json', legacy / 'manifest.json'
        baseline.write_bytes(p.encoded(dataset(['2026-09', '2026-10', '2026-11'])))
        manifest.write_bytes(p.encoded([{'file': baseline.name, 'sha256': p.sha(baseline.read_bytes())}]))
        self.stack.enter_context(patch.object(p, 'BASELINE', baseline))
        self.stack.enter_context(patch.object(p, 'BASE_MANIFEST', manifest))
        self.registry = self.root / 'registry'
        self.stack.enter_context(patch.object(r, 'REGISTRY', self.registry))

    def candidate(self, months=None, version=2):
        months = months or ['2026-09', '2026-10', '2026-11']
        server = fixtures.Server({code: [fixtures.row(code, t.replace('-', ''), 10) for t in months] for code in p.SECTORS})
        with patch.object(p, 'NORMALIZATION_VERSION', version):
            result, digest = self.collect(server)
        return p.STORE / result['run_id'], digest, result

    def approve(self, folder, digest):
        state = r.verify_registry(self.registry)
        doc = {'schema_version': 1, 'decision': 'APPROVE', 'reviewer_id': 'SYNTHETIC_REVIEWER_NOT_USER',
               'approved_at': p.now(), 'reason': 'Synthetic test approval only', 'scope': 'comparison_baseline_only',
               'snapshot_manifest_sha256': digest, 'snapshot_run_id': folder.name,
               'previous_approval_sha256': state['tip_sha256'], 'evidence': [{'sha256': digest}],
               'remaining_limitations': ['Synthetic data, no real human or production approval']}
        path = self.root / ('synthetic_decision_' + uuid.uuid4().hex + '.json')
        path.write_bytes(p.encoded(doc))
        return path

    def test_dry_run_no_registry_creation_and_requires_explicit_execution(self):
        folder, digest, _ = self.candidate()
        result = r.check_candidate(folder, digest)
        self.assertFalse(result['human_approved'])
        self.assertFalse(self.registry.exists())
        decision = self.approve(folder, digest)
        self.assertTrue(r.approve(folder, digest, decision)['dry_run'])
        self.assertFalse(self.registry.exists())
        output = io.StringIO()
        with redirect_stdout(output):
            code = r.main(['--approve', '--snapshot-kind', 'collected', '--run-id', folder.name,
                           '--expected-manifest-sha256', digest, '--decision-file', str(decision)])
        self.assertEqual(code, 1)
        self.assertFalse(self.registry.exists())

    def test_approval_new_month_transition_and_historical_comparison(self):
        base, base_sha, _ = self.candidate()
        first = r.approve(base, base_sha, self.approve(base, base_sha), execute=True)
        candidate, candidate_sha, _ = self.candidate(['2026-09', '2026-10', '2026-11', '2026-12'])
        before = r.compare_approved(candidate, candidate_sha, baseline_id=first['approval_id'])
        self.assertEqual(before['counts']['NEW_TARGET_MONTH'], 2)  # one new calendar month per sector
        self.assertEqual({e['forecast_target_month'] for e in before['events'] if e['classification'] == 'NEW_TARGET_MONTH'}, {'2026-12'})
        history_before = fixtures.fingerprint(self.registry / 'records' / first['approval_id'])
        second = r.approve(candidate, candidate_sha, self.approve(candidate, candidate_sha), execute=True)
        after = r.compare_approved(candidate, candidate_sha, use_current=True)
        self.assertEqual(after['counts']['UNCHANGED'], 8)
        self.assertEqual(after['counts']['NEW_TARGET_MONTH'], 0)
        historical = r.compare_approved(candidate, candidate_sha, baseline_id=first['approval_id'])
        self.assertEqual(historical['comparison_sha256'], before['comparison_sha256'])
        self.assertEqual(history_before, fixtures.fingerprint(self.registry / 'records' / first['approval_id']))
        state = r.verify_registry(self.registry, second['record_sha256'])
        self.assertEqual(len(state['records']), 2)
        self.assertTrue(all(not a['record']['model_input_promoted'] and not a['record']['vintage_verification_granted'] for a in state['records']))
        with self.assertRaises(p.PipelineError):
            r.compare_approved(candidate, candidate_sha)

    def test_v1_failed_gap_tampered_and_noncanonical_candidates_rejected(self):
        v1, v1_sha, _ = self.candidate(version=1)
        with self.assertRaisesRegex(p.PipelineError, 'V2_APPROVAL_CANDIDATE_REQUIRED'):
            r.check_candidate(v1, v1_sha)
        gap, gap_sha, result = self.candidate(['2026-09', '2026-11'])
        self.assertNotEqual(result['exit_code'], 0)
        with self.assertRaises(p.PipelineError):
            r.check_candidate(gap, gap_sha)
        good, digest, _ = self.candidate()
        (good / 'normalized.json').write_bytes(b'[]')
        with self.assertRaisesRegex(p.PipelineError, 'ARCHIVED_FILE_HASH_MISMATCH'):
            r.check_candidate(good, digest)
        self.assertFalse(self.registry.exists())

    def test_legacy_gap_archive_replays_but_cannot_be_approved(self):
        folder, _, _ = self.candidate()
        missing = p.encoded(dataset(['2026-09', '2026-11']))
        (folder / 'baseline/normalized_snapshot.json').write_bytes(missing)
        (folder / 'baseline/manifest.json').write_bytes(p.encoded([{'file': p.BASELINE.name, 'sha256': p.sha(missing)}]))
        manifest = json.loads((folder / 'manifest.json').read_bytes())
        manifest.pop('validation_policy_version')  # synthetic pre-R11-02 archive
        new, events, issues = p.replay(folder, manifest, folder.name, 2)
        self.assertFalse(issues)
        self.assertEqual(sum(e['classification'] == 'NEW_TARGET_MONTH' for e in events), 2)
        (folder / 'normalized.json').write_bytes(p.encoded(new))
        (folder / 'diff.json').write_bytes(p.encoded(events))
        manifest.update(p.summary(events, issues, 1))
        for entry in manifest['files']:
            raw = (folder / entry['path']).read_bytes()
            entry['sha256'], entry['bytes'] = p.sha(raw), len(raw)
        raw = p.encoded(manifest)
        (folder / 'manifest.json').write_bytes(raw)
        (folder / 'manifest.sha256').write_text(p.sha(raw))
        self.assertTrue(p.validate_run(folder.name, p.sha(raw))['collection_passed'])
        before = fixtures.fingerprint(folder)
        with self.assertRaisesRegex(p.PipelineError, 'BASELINE_INTERNAL_GAP'):
            r.check_candidate(folder, p.sha(raw))
        self.assertEqual(before, fixtures.fingerprint(folder))
        self.assertFalse(self.registry.exists())

    def test_decision_scope_binding_time_and_missing_evidence_rejected(self):
        folder, digest, _ = self.candidate()
        path = self.approve(folder, digest)
        original = json.loads(path.read_bytes())
        for changed in [{'scope': 'model_training'}, {'snapshot_manifest_sha256': '0' * 64},
                        {'previous_approval_sha256': '0' * 64}, {'reviewer_id': ''}, {'evidence': []},
                        {'remaining_limitations': []}, {'approved_at': '2099-01-01T00:00:00+09:00'}]:
            path.write_bytes(p.encoded({**original, **changed}))
            with self.assertRaises(p.PipelineError):
                r.approve(folder, digest, path, execute=True)
            self.assertFalse(self.registry.exists())

    def test_history_hash_pointer_and_trusted_tip_tamper_rejected(self):
        folder, digest, _ = self.candidate()
        approved = r.approve(folder, digest, self.approve(folder, digest), execute=True)
        with self.assertRaisesRegex(p.PipelineError, 'REGISTRY_TIP_MISMATCH'):
            r.verify_registry(self.registry, '0' * 64)
        current_path = self.registry / 'current.json'
        saved = current_path.read_bytes()
        current = json.loads(saved); current['record_sha256'] = '0' * 64
        current_path.write_bytes(p.encoded(current))
        with self.assertRaises(p.PipelineError):
            r.compare_approved(folder, digest, use_current=True)
        current_path.write_bytes(saved)
        decision_path = self.registry / 'records' / approved['approval_id'] / 'decision.json'
        saved_decision = decision_path.read_bytes()
        decision_path.write_bytes(saved_decision + b' ')
        with self.assertRaisesRegex(p.PipelineError, 'APPROVAL_DECISION_HASH_MISMATCH'):
            r.verify_registry(self.registry)
        decision_path.write_bytes(saved_decision)
        record = decision_path.parent / 'record.json'
        record.write_bytes(record.read_bytes() + b' ')
        with self.assertRaisesRegex(p.PipelineError, 'APPROVAL_RECORD_HASH_MISMATCH'):
            r.verify_registry(self.registry)

    def test_atomic_pointer_updated_only_after_complete_record_validation(self):
        folder, digest, _ = self.candidate()
        real_replace = r.os.replace
        real_write = r.write_new
        observed = []
        def write(path, raw):
            if path.parent == self.registry and path.name.startswith('.current.'):
                state = r.verify_registry(self.registry, writer_active=True, allow_pending=True)
                self.assertIsNone(state['current'])
                self.assertEqual(len(state['records']), 1)
                observed.append(True)
            return real_write(path, raw)
        def replace(source, destination):
            self.assertEqual(destination, self.registry / 'current.json')
            self.assertFalse(destination.exists())
            self.assertEqual(observed, [True])
            return real_replace(source, destination)
        with patch.object(r, 'write_new', side_effect=write), patch.object(r.os, 'replace', side_effect=replace):
            r.approve(folder, digest, self.approve(folder, digest), execute=True)
        self.assertEqual(observed, [True])
        self.assertIsNotNone(r.verify_registry(self.registry)['current'])

    def test_pointer_failure_keeps_old_pointer_and_fails_closed_on_incomplete_tail(self):
        folder, digest, _ = self.candidate()
        r.approve(folder, digest, self.approve(folder, digest), execute=True)
        pointer_before = (self.registry / 'current.json').read_bytes()
        new, new_sha, _ = self.candidate(['2026-09', '2026-10', '2026-11', '2026-12'])
        decision = self.approve(new, new_sha)
        with patch.object(r.os, 'replace', side_effect=OSError('synthetic pointer failure')):
            with self.assertRaises(OSError):
                r.approve(new, new_sha, decision, execute=True)
        self.assertEqual(pointer_before, (self.registry / 'current.json').read_bytes())
        self.assertEqual(len(list((self.registry / 'records').iterdir())), 2)
        with self.assertRaisesRegex(p.PipelineError, 'REGISTRY_INCOMPLETE_POINTER_WRITE'):
            r.verify_registry(self.registry)

    def test_approved_copies_survive_original_source_changes_and_lock_blocks_writers(self):
        folder, digest, _ = self.candidate()
        approved = r.approve(folder, digest, self.approve(folder, digest), execute=True)
        (folder / 'normalized.json').write_bytes(b'[]')  # synthetic source; approved copy stays intact
        self.assertEqual(r.verify_registry(self.registry)['current']['approval_id'], approved['approval_id'])
        (self.registry / '.writer.lock').write_bytes(b'synthetic abandoned transaction')
        with self.assertRaisesRegex(p.PipelineError, 'REGISTRY_INCOMPLETE_WRITER_LOCK'):
            r.verify_registry(self.registry)


if __name__ == '__main__':
    unittest.main()
