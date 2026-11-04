"""R11-01 format/version replay regressions; all observations are synthetic."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from unittest.mock import patch

import round11_ecos_snapshot_pipeline as p
import test_round11_pipeline as fixtures


class VersionChecks(unittest.TestCase):
    def setUp(self):
        fixtures.PipelineChecks.setUp(self)
        self.stack.enter_context(patch.object(p, 'REPROCESSED', self.root / 'reprocessed'))

    def collect(self, server):
        return fixtures.PipelineChecks.collect(self, server)

    def legacy(self):
        server = fixtures.Server({code: [fixtures.row(code, time, value) for time, value in
                                        [('202609', 100), ('202610', 90), ('202611', 110)]] for code in p.SECTORS})
        base = []
        for code, rows in server.data.items():
            for row in rows:
                target = p.month(row['TIME'])
                base.append({'table_code': '512Y008', 'item_code1': 'BD', 'item_code2': code,
                             'forecast_target_month': target, 'survey_month': p.shift(target, -1),
                             'value': row['DATA_VALUE'], 'publication_date': None})
        p.BASELINE.write_bytes(p.encoded(base))
        p.BASE_MANIFEST.write_bytes(p.encoded([{'file': p.BASELINE.name, 'sha256': p.sha(p.BASELINE.read_bytes())}]))
        with patch.object(p, 'NORMALIZATION_VERSION', 1):
            result, digest = self.collect(server)
        self.assertEqual(result['exit_code'], 0)
        return result, digest

    def test_fixed_point_inputs_and_zero_policy(self):
        cases = {'100': '100', '100.0': '100', '1E+2': '100', '90': '90', '110': '110',
                 '0': '0', '-0': '0', '0.0': '0', '-0.000': '0', '200': '200',
                 '12.3400': '12.34', '1e-5': '0.00001',
                 '12.123456789012345678901234567890': '12.12345678901234567890123456789'}
        for source, expected in cases.items():
            self.assertEqual(p.number(source), expected)
            self.assertEqual(p.number(source, 2), expected)
            self.assertNotIn('e', expected.lower())
        self.assertEqual(p.number(100), '100')
        self.assertEqual(p.number(100.0), '100')

    def test_rejected_values_and_unknown_versions(self):
        for value in ['NaN', 'Infinity', '-Infinity', '-1', '201', '-0.01', None, True, 'not-numeric']:
            for version in (1, 2):
                with self.assertRaises(p.PipelineError):
                    p.number(value, version)
        for version in (None, 0, 3, True, '1'):
            with self.assertRaises(p.PipelineError):
                p.number('100', version)

    def test_legacy_spelling_and_full_v1_offline_replay(self):
        self.assertEqual([p.number(v, 1) for v in ('100', '90', '110', '-0')], ['1E+2', '9E+1', '1.1E+2', '-0'])
        result, digest = self.legacy()
        folder = p.STORE / result['run_id']
        before = fixtures.fingerprint(folder)
        rows = json.loads((folder / 'normalized.json').read_bytes())
        self.assertEqual(sum('e' in r['value'].lower() for r in rows), 6)
        output = io.StringIO()
        with patch.object(p, 'urlopen', side_effect=AssertionError('NO NETWORK')) as network, \
             patch.object(p, 'local_key', side_effect=AssertionError('NO KEY READ')) as key, redirect_stdout(output):
            self.assertEqual(p.main(['--validate-run', result['run_id'], '--expected-manifest-sha256', digest]), 0)
            network.assert_not_called()
            key.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['normalization_version'], 1)
        self.assertEqual(before, fixtures.fingerprint(folder))

    def test_new_collection_uses_v2_and_replays_v2(self):
        result, digest = self.collect(fixtures.Server())
        self.assertEqual(result['normalization_version'], 2)
        self.assertEqual(p.validate_run(result['run_id'], digest)['normalization_version'], 2)
        rows = json.loads((p.STORE / result['run_id'] / 'normalized.json').read_bytes())
        self.assertTrue(all('e' not in r['value'].lower() for r in rows))

    def test_format_only_differences_are_not_value_changes(self):
        rows = [fixtures.row('C3000', time, value) for time, value in [('202609', 100), ('202610', 90), ('202611', 110)]]
        old = p.normalize(rows, 'C3000', 'old_observed_at', 'old_run', 1)
        new = p.normalize(rows, 'C3000', 'old_observed_at', 'derived_run', 2)
        windows = {'C3000': ['2026-09', '2026-11']}
        self.assertEqual([e['classification'] for e in p.compare(old, new, windows)], ['UNCHANGED'] * 3)
        changed = copy.deepcopy(new)
        changed[0]['value'] = '101'
        self.assertEqual(sum(e['classification'] == 'HISTORICAL_VALUE_CHANGED' for e in p.compare(old, changed, windows)), 1)

    def test_reprocess_without_network_preserves_inputs_timestamps_and_both_archives(self):
        parent, parent_digest = self.legacy()
        original = p.STORE / parent['run_id']
        parent_before, lock_before = fixtures.fingerprint(original), fixtures.fingerprint(p.LOCK)
        with patch.object(p, 'urlopen', side_effect=AssertionError('NO NETWORK')) as network, \
             patch.object(p, 'local_key', side_effect=AssertionError('NO KEY READ')) as key:
            derived, digest = p.reprocess_run(parent['run_id'], parent_digest)
            validated = p.validate_run(derived['run_id'], digest, p.REPROCESSED)
            network.assert_not_called()
            key.assert_not_called()
        self.assertEqual(validated['normalization_version'], 2)
        self.assertEqual(derived['network_calls_this_run'], 0)
        self.assertEqual(derived['reprocessing_checks'], {'rows': 6, 'numeric_unchanged': 6, 'value_text_changed': 6,
                                                         'parent_scientific_strings': 6, 'v2_scientific_strings': 0})
        self.assertEqual(derived['requests'], parent['requests'])
        new_folder = p.REPROCESSED / derived['run_id']
        old_rows = json.loads((original / 'normalized.json').read_bytes())
        new_rows = json.loads((new_folder / 'normalized.json').read_bytes())
        self.assertEqual([r['observed_at'] for r in new_rows], [r['observed_at'] for r in old_rows])
        self.assertTrue(all(Decimal(a['value']) == Decimal(b['value']) for a, b in zip(old_rows, new_rows)))
        for r in parent['files']:
            if r['kind'] == 'api_raw':
                self.assertEqual((original / r['path']).read_bytes(), (new_folder / r['path']).read_bytes())
        self.assertEqual(derived['counts'], parent['counts'])
        self.assertEqual(parent_before, fixtures.fingerprint(original))
        self.assertEqual(lock_before, fixtures.fingerprint(p.LOCK))
        before = fixtures.fingerprint(new_folder)
        p.reprocess_run(parent['run_id'], parent_digest)
        self.assertEqual(before, fixtures.fingerprint(new_folder))

    def test_archive_version_is_required_and_not_guessed(self):
        result, _ = self.legacy()
        folder = p.STORE / result['run_id']
        manifest = json.loads((folder / 'manifest.json').read_bytes())
        manifest['normalization_version'] = 99
        raw = p.encoded(manifest)
        (folder / 'manifest.json').write_bytes(raw)  # Synthetic fixture only.
        (folder / 'manifest.sha256').write_text(p.sha(raw))
        with self.assertRaisesRegex(p.PipelineError, 'UNSUPPORTED_NORMALIZATION_VERSION'):
            p.validate_run(result['run_id'], p.sha(raw))


if __name__ == '__main__':
    unittest.main()
