"""Synthetic-only fixtures; no official monthly observations embedded."""
import copy
import math
import json
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import experiment_round12_industry_benchmark as e


def inputs(industry='C303'):
    code, sector = e.MAPPING[industry]
    production = [{'industry_code': industry, 'org_id': '101', 'table_id': 'DT_1F02001',
                   'region_code': '00', 'item_id': 'T10', 'unit': '2020=100',
                   'period': e.shift('2022-01', i), 'value': 80.0 + i * 0.4 + i % 5,
                   'provisional_ui_flag': i in (55, 56)} for i in range(57)]
    bsi = [{'table_code': '512Y008', 'item_code1': 'BD', 'item_code2': code, 'sector': sector,
            'forecast_target_month': e.shift('2023-12', i), 'survey_month': e.shift('2023-11', i),
            'value': 80.0 + i % 7} for i in range(36)]
    return production, bsi


def panel():
    return e.build_panel(*inputs(), 'C303')


class BenchmarkChecks(unittest.TestCase):
    def test_mapping_join_yoy_and_denominator(self):
        for industry in e.MAPPING:
            p, x = inputs(industry)
            result = e.build_panel(p, x, industry)
            self.assertEqual(len(result), 34)
            self.assertEqual(result[0]['forecast_target_month'], '2023-12')
            self.assertEqual(result[0]['survey_month'], '2023-11')
            self.assertEqual(result[0]['bsi_value'], x[0]['value'])
            self.assertAlmostEqual(result[0]['production_yoy_pct'], 100 * (p[23]['value'] / p[11]['value'] - 1))

    def test_fixed_origins_cutoff_and_four_models(self):
        forecasts, details, summary = e.evaluate(panel())
        self.assertEqual((len(forecasts), len(details)), (12, 48))
        self.assertEqual((summary['train_first_n'], summary['train_last_n']), (21, 32))
        self.assertEqual((e.TARGETS[0], e.TARGETS[-1]), ('2025-10', '2026-09'))
        for f in forecasts:
            self.assertEqual(set(f['predictions']), set(e.MODELS))
            self.assertEqual(f['train_last'], e.shift(f['target'], -2))
            self.assertTrue(all(t <= f['cutoff'] for t in f['train_months']))
            self.assertEqual(f['predictions']['seasonal_naive'], 0)

    def test_post_cutoff_y_is_never_read_into_predictions(self):
        for target in e.TARGETS:
            before = e.forecast_at(panel(), target)
            changed = copy.deepcopy(panel())
            for r in changed:
                if r['forecast_target_month'] > e.shift(target, -2):
                    r['production_yoy_pct'] = float('nan')
            self.assertEqual(before, e.forecast_at(changed, target))

    def test_tminusone_and_future_x_unused_current_x_is_used(self):
        for target in e.TARGETS:
            original = panel()
            before = e.forecast_at(original, target)
            changed = copy.deepcopy(original)
            for r in changed:
                if r['forecast_target_month'] > target or r['forecast_target_month'] == e.shift(target, -1):
                    r['bsi_value'] = float('nan')
            self.assertEqual(before, e.forecast_at(changed, target))
            next(r for r in changed if r['forecast_target_month'] == target)['bsi_value'] += 1
            after = e.forecast_at(changed, target)
            self.assertAlmostEqual(after['predictions']['bsi_ols'] - before['predictions']['bsi_ols'], before['slope'])

    def test_persistence_and_mean_match_train_only(self):
        rows = panel()
        for target in e.TARGETS:
            f = e.forecast_at(rows, target)
            training = [r for r in rows if r['forecast_target_month'] <= f['cutoff']]
            self.assertEqual(f['predictions']['yoy_last_available_tminus2'], training[-1]['production_yoy_pct'])
            self.assertEqual(f['predictions']['past_yoy_mean'], statistics.mean(r['production_yoy_pct'] for r in training))

    def test_independent_ols_and_exact_known_line(self):
        rows = panel()
        for r in rows:
            r['production_yoy_pct'] = 3 + 2 * r['bsi_value']
        f, details, summary = e.evaluate(rows)
        for r in f:
            self.assertAlmostEqual(r['intercept'], 3)
            self.assertAlmostEqual(r['slope'], 2)
        self.assertAlmostEqual(summary['fixed_12_months']['scores']['bsi_ols']['MAE_pp'], 0)
        self.assertEqual(e.independent_check(rows, f, details)['predictions_and_errors_checked'], 48)
        f[0]['predictions']['bsi_ols'] += 1
        with self.assertRaises(ValueError):
            e.independent_check(rows, f, details)

    def test_metrics_error_sign_and_independent_scores(self):
        scores = e.metrics([-2, 0, 4])
        self.assertEqual(scores['MAE_pp'], 2)
        self.assertAlmostEqual(scores['RMSE_pp'], math.sqrt(20 / 3))
        self.assertAlmostEqual(scores['bias_pp'], 2 / 3)
        _, details, result = e.evaluate(panel())
        for model in e.MODELS:
            rows = [r for r in details if r['model'] == model]
            errors = [r['predicted_yoy_pct'] - r['actual_yoy_pct'] for r in rows]
            s = result['fixed_12_months']['scores'][model]
            self.assertAlmostEqual(s['MAE_pp'], sum(abs(v) for v in errors) / 12)
            self.assertAlmostEqual(s['RMSE_pp'], math.sqrt(sum(v * v for v in errors) / 12))
            self.assertAlmostEqual(s['bias_pp'], sum(errors) / 12)

    def test_paired_wins_loo_and_zero_baseline(self):
        details = []
        for i, (bsi, baseline) in enumerate([(1, 2), (4, 2), (2, 2)]):
            for m, error in [('bsi_ols', bsi), ('past_yoy_mean', baseline)]:
                details.append({'model': m, 'target': str(i), 'error_pp': error})
        r = e.comparison(details, 'past_yoy_mean')
        self.assertEqual((r['wins'], r['ties'], r['losses']), (1, 1, 1))
        self.assertAlmostEqual(r['delta_MAE_pp'], 1 / 3)
        self.assertAlmostEqual(r['skill_percent'], -100 / 6)
        self.assertEqual((r['loo_delta_min_pp'], r['loo_delta_max_pp'], r['loo_direction_reversals']), (-0.5, 1, 1))
        self.assertEqual((r['loo_skill_min_percent'], r['loo_skill_max_percent']), (-50, 25))
        for row in details:
            if row['model'] == 'past_yoy_mean':
                row['error_pp'] = 0
        self.assertIsNone(e.comparison(details, 'past_yoy_mean')['skill_percent'])

    def test_ten_month_sensitivity_reuses_same_predictions(self):
        _, details, result = e.evaluate(panel())
        with patch.object(e, 'forecast_at', side_effect=AssertionError('must not refit')):
            same = e.summarize([r for r in details if r['target'] in e.TARGETS[:-2]])
        self.assertEqual(same, result['exclude_provisional_10_months'])
        self.assertTrue(all(s['n'] == 10 for s in same['scores'].values()))

    def test_direction_policy_zero_actual_excluded_zero_prediction_misses(self):
        rows = panel()
        for r in rows:
            r['production_yoy_pct'] = 0.0
        _, _, result = e.evaluate(rows)
        self.assertIsNone(result['fixed_12_months']['direction']['bsi_ols']['hit_rate_percent'])
        details = [{'target': str(i), 'model': m, 'actual_yoy_pct': actual, 'predicted_yoy_pct': 0,
                    'error_pp': -actual} for i, actual in enumerate([0, 2, -2]) for m in e.MODELS]
        self.assertEqual(e.summarize(details)['direction']['bsi_ols'], {'hits': 0, 'n_nonzero_actual': 2, 'hit_rate_percent': 0})

    def test_wrong_codes_months_duplicates_missing_and_nonfinite_fail(self):
        cases = [('p', 'table_id', 'OTHER'), ('p', 'period', '2022-13'), ('p', 'value', 0),
                 ('p', 'value', float('inf')), ('x', 'survey_month', '2023-12'),
                 ('x', 'item_code2', 'C0000'), ('x', 'value', float('nan'))]
        for kind, key, value in cases:
            with self.subTest(kind=kind, key=key):
                p, x = inputs()
                (p if kind == 'p' else x)[0][key] = value
                with self.assertRaises(ValueError):
                    e.build_panel(p, x, 'C303')
        for kind in ('p', 'x'):
            for duplicate in (False, True):
                p, x = inputs()
                rows = p if kind == 'p' else x
                rows.append(rows[0]) if duplicate else rows.pop(4)
                with self.assertRaises(ValueError):
                    e.build_panel(p, x, 'C303')

    def test_panel_gaps_duplicates_constants_and_nonfinite_stop(self):
        for rows in (panel()[:-1], panel() + [panel()[0]], panel()[1:]):
            with self.assertRaises(ValueError):
                e.evaluate(rows)
        for key, value in [('bsi_value', 80.0), ('production_yoy_pct', float('nan'))]:
            rows = panel()
            for r in rows:
                r[key] = value
            with self.assertRaises(ValueError):
                e.evaluate(rows)
        rows = panel()
        rows[0]['survey_month'] = rows[0]['forecast_target_month']
        with self.assertRaises(ValueError):
            e.evaluate(rows)

    def test_source_hash_mismatch_stops_before_parse(self):
        e.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=e.OUT) as folder:
            root = Path(folder)
            d9, d7 = root / 'round09_industry', root / 'round07c_ecos'
            d9.mkdir()
            d7.mkdir()
            names9 = ['industry_generic.xml', 'industry_dsd.xml']
            names7 = ['normalized_snapshot.json', 'search_512Y008_M_202312_202611_BD_C3000.json',
                      'search_512Y008_M_202312_202611_BD_C0000.json']
            for directory, names in [(d9, names9), (d7, names7)]:
                for name in names:
                    (directory / name).write_bytes(b'synthetic invalid parser input')
            (d9 / 'summary.json').write_text(json.dumps({'input_manifest':
                [{'file': 'round09_industry/' + n, 'sha256': '0' * 64} for n in names9]}))
            (d7 / 'manifest.json').write_text(json.dumps([{'file': n, 'sha256': '0' * 64} for n in names7]))
            with patch.object(e, 'ROOT', root), patch.object(e, 'LOCAL', root), patch.object(e, 'read_proxies') as parser:
                with self.assertRaisesRegex(ValueError, 'Input hash mismatch'):
                    e.load_inputs()
                parser.assert_not_called()


if __name__ == '__main__':
    unittest.main()
