"""Synthetic fixtures only. Never creates or modifies the real forecast lock."""
import copy
import statistics
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from round10_lock_forecasts import G, KST, LOCAL, MAPPING, canonical, digest, make_forecasts, precheck_production, shift, verify_lock, write_lock

ORIGIN = datetime(2026, 11, 3, 12, tzinfo=KST)


def fixture():
    production = [{'industry_code': code, 'period': shift('2022-01', i), 'value': scale * (100 + i) + i % 3}
                  for code, scale in [('C222', 1), ('C303', 2)] for i in range(57)]
    bsi = {code: {shift('2023-12', i): {'value': 70 + i % modulus,
                                     'survey_month': shift('2023-12', i - 1),
                                     'available_at': '2026-09-30T00:00:00+09:00' if i == 34 else '2026-10-30T00:00:00+09:00'}
                  for i in range(36)} for code, modulus in [('C3000', 11), ('C0000', 5)]}
    return production, bsi


class LockChecks(unittest.TestCase):
    def test_count_mapping_cutoff_and_origin_type(self):
        forecasts, audits = make_forecasts(*fixture(), ORIGIN)
        self.assertEqual(len(forecasts), 12)
        self.assertEqual(len(audits), 4)
        for row in forecasts:
            self.assertEqual(row['bsi_code'], MAPPING[row['industry_code']])
            self.assertEqual(row['target_survey_month'], shift(row['target'], -1))
            self.assertEqual(row['bsi_post_sample_break'], row['target'] == '2026-11')
            self.assertEqual(row['forecast_type'], 'nowcast_of_unreleased_activity' if row['target'] == '2026-10' else 'within_month_prospective_forecast')
        for row in audits:
            self.assertEqual(row['train_n'], 33 if row['target'] == '2026-10' else 34)
            self.assertEqual(row['train_months'][-1], shift(row['target'], -2))
            self.assertTrue(all(t <= shift(row['target'], -2) for t in row['train_months']))
            self.assertEqual(row['training_post_break_rows'], 0)

    def test_independent_ols_and_mean(self):
        production, bsi = fixture()
        forecasts, audits = make_forecasts(production, bsi, ORIGIN)
        for row in audits:
            values = {r['period']: r['value'] for r in production if r['industry_code'] == row['industry_code']}
            xs = [bsi[row['bsi_code']][t]['value'] for t in row['train_months']]
            ys = [100 * (values[t] / values[shift(t, -12)] - 1) for t in row['train_months']]
            fit = statistics.linear_regression(xs, ys)
            self.assertAlmostEqual(row['intercept'], fit.intercept)
            self.assertAlmostEqual(row['slope'], fit.slope)
            selected = {r['model']: r['predicted_production_yoy_pct'] for r in forecasts
                        if (r['industry_code'], r['target']) == (row['industry_code'], row['target'])}
            self.assertEqual(selected['seasonal_naive'], 0)
            self.assertEqual(selected['past_yoy_mean'], statistics.mean(ys))

    def test_october_cannot_use_september_production(self):
        production, bsi = fixture()
        before = make_forecasts(production, bsi, ORIGIN)
        changed = copy.deepcopy(production)
        for row in changed:
            if row['period'] == '2026-09':
                row['value'] *= 3
        after = make_forecasts(changed, bsi, ORIGIN)
        self.assertEqual([r for r in before[0] if r['target'] == '2026-10'],
                         [r for r in after[0] if r['target'] == '2026-10'])
        self.assertNotEqual([r for r in before[0] if r['target'] == '2026-11'],
                            [r for r in after[0] if r['target'] == '2026-11'])

    def test_future_production_aborts_before_numeric_consumption(self):
        prefix = '<root xmlns:g="' + G[1:-1] + '">'
        precheck_production((prefix + '<g:Time>202609</g:Time></root>').encode())
        with self.assertRaises(ValueError):
            precheck_production((prefix + '<g:Time>202610</g:Time><g:ObsValue value="not-a-number"/></root>').encode())
        production, bsi = fixture()
        for target in ['2026-10', '2026-11']:
            with self.assertRaises(ValueError):
                make_forecasts(production + [{'industry_code': 'C222', 'period': target, 'value': 1}], bsi, ORIGIN)

    def test_invalid_denominator_duplicate_feature_and_origin_stop(self):
        production, bsi = fixture()
        for invalid in [production + [production[0]], [r for r in production if r['period'] != '2024-12']]:
            with self.assertRaises(ValueError):
                make_forecasts(invalid, bsi, ORIGIN)
        changed = copy.deepcopy(bsi)
        for row in changed['C3000'].values():
            row['value'] = 80
        with self.assertRaises(ValueError):
            make_forecasts(production, changed, ORIGIN)
        sparse = {code: {t: row for t, row in values.items() if t >= '2026-08'} for code, values in bsi.items()}
        with self.assertRaises(ValueError):
            make_forecasts(production, sparse, ORIGIN)
        changed = copy.deepcopy(bsi)
        changed['C3000']['2026-10']['survey_month'] = '2026-10'
        with self.assertRaises(ValueError):
            make_forecasts(production, changed, ORIGIN)
        with self.assertRaises(ValueError):
            make_forecasts(production, bsi, datetime(2026, 11, 4, tzinfo=KST))
        changed = copy.deepcopy(bsi)
        changed['C3000']['2026-11']['available_at'] = '2026-11-04T00:00:00+09:00'
        with self.assertRaises(ValueError):
            make_forecasts(production, changed, ORIGIN)

    def test_canonical_hash_and_nan_rejection(self):
        self.assertEqual(canonical({'b': 2, 'a': 1}), canonical({'a': 1, 'b': 2}))
        self.assertNotEqual(digest(canonical({'prediction': 1})), digest(canonical({'prediction': 2})))
        with self.assertRaises(ValueError):
            canonical({'prediction': float('nan')})

    def test_exclusive_lock_external_digest_and_sealed_inputs(self):
        # Workspace-scoped temporary directory; verify containment before cleanup.
        with tempfile.TemporaryDirectory(prefix='round10_synthetic_test_', dir=LOCAL) as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(LOCAL.resolve()))
            folder = Path(tmp) / 'synthetic_lock'
            blobs = {'synthetic.txt': b'synthetic only'}
            payload = {'forecasts': [{'synthetic_prediction': i} for i in range(12)], 'training_audit': [],
                       'input_manifest': [{'path': 'synthetic.txt', 'sha256': digest(blobs['synthetic.txt'])}],
                       'origin_kst': ORIGIN.isoformat(), 'generated_at_kst': ORIGIN.isoformat(),
                       'source_commit_sha': 'synthetic_test_only'}
            sha = write_lock(folder, payload, blobs)
            self.assertEqual(verify_lock(folder, sha)['forecast_count'], 12)
            original = (folder / 'forecasts.canonical.json').read_bytes()
            with self.assertRaises(FileExistsError):
                write_lock(folder, payload, blobs)
            self.assertEqual(original, (folder / 'forecasts.canonical.json').read_bytes())
            with self.assertRaises(ValueError):
                verify_lock(folder, '0' * 64)
            (folder / 'sealed_inputs/synthetic.txt').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                verify_lock(folder, sha)


if __name__ == '__main__':
    unittest.main()
