"""Synthetic-only checks; no official observations or predictions embedded."""
import copy
import json
import math
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import experiment_round12b_recent_bias as b
from test_round12_industry_benchmark import inputs


def panels():
    return {code: b.a.build_panel(*inputs(code), code) for code in b.a.MAPPING}


def panel():
    return panels()['C303']


def reference(folder, source):
    summaries = {}
    for code, rows in source.items():
        forecasts, details, summary = b.a.evaluate(rows)
        summaries[code] = summary
        (folder / f'{code}_private_details.json').write_text(json.dumps({'panel': rows, 'forecasts': forecasts, 'errors': details}))
    saved = {'input_manifest': [], 'source_code_sha256': {}, 'industries': summaries}
    (folder / 'aggregate.json').write_text(json.dumps(saved))
    return saved


class RecencyChecks(unittest.TestCase):
    def test_earliest_origin_tminus2_and_exact_windows(self):
        rows = panel()
        for target in b.EXTENDED:
            f = b.forecast_at(rows, target)
            training = [r for r in rows if r['forecast_target_month'] <= b.a.shift(target, -2)]
            self.assertEqual(f['train_months'], [r['forecast_target_month'] for r in training])
            for size in (6, 12):
                self.assertEqual(f[f'rolling_{size}_months'], f['train_months'][-size:])
                self.assertEqual(f['predictions'][f'rolling_yoy_mean_{size}'], statistics.mean(r['production_yoy_pct'] for r in training[-size:]))
        first = b.forecast_at(rows, '2025-01')
        self.assertEqual((first['train_n'], first['train_last']), (12, '2024-11'))
        self.assertEqual((len(b.EXTENDED), len(b.SUBSETS['earlier_9_months'])), (21, 9))

    def test_future_y_tminusone_and_future_x_not_consumed(self):
        for target in b.EXTENDED:
            rows = panel()
            before = b.forecast_at(rows, target)
            for r in rows:
                if r['forecast_target_month'] > b.a.shift(target, -2):
                    r['production_yoy_pct'] = float('nan')
                if r['forecast_target_month'] > target or r['forecast_target_month'] == b.a.shift(target, -1):
                    r['bsi_value'] = float('nan')
            self.assertEqual(before, b.forecast_at(rows, target))

    def test_current_feature_fixed_half_and_rolling_unchanged(self):
        for target in b.EXTENDED:
            rows = panel()
            first = b.forecast_at(rows, target)
            pred = first['predictions']
            self.assertEqual(pred['bsi_blend_half'], 0.5 * pred['bsi_ols'] + 0.5 * pred['past_yoy_mean'])
            next(r for r in rows if r['forecast_target_month'] == target)['bsi_value'] += 1
            second = b.forecast_at(rows, target)
            for model in ('rolling_yoy_mean_6', 'rolling_yoy_mean_12', 'past_yoy_mean'):
                self.assertEqual(pred[model], second['predictions'][model])
            self.assertAlmostEqual(second['predictions']['bsi_blend_half'] - pred['bsi_blend_half'], 0.5 * first['slope'])

    def test_extended_main_and_10month_are_identical_predictions(self):
        rows = panel()
        forecasts, details, summary = b.evaluate(rows)
        for f in forecasts:
            if f['target'] in b.a.TARGETS:
                old = b.a.forecast_at(rows, f['target'])
                self.assertEqual({m: f['predictions'][m] for m in b.a.MODELS}, old['predictions'])
        with patch.object(b, 'forecast_at', side_effect=AssertionError('No refit')):
            for name, selected in b.SUBSETS.items():
                self.assertEqual(summary['subsets'][name], b.summarize([r for r in details if r['target'] in selected]))
        self.assertEqual(len(details), 147)

    def test_independent_seven_models_and_tampering(self):
        rows = panel()
        forecasts, details, summary = b.evaluate(rows)
        audit = summary['independent_arithmetic']
        self.assertEqual((audit['origins_checked'], audit['predictions_and_errors_checked'], audit['metric_sets_checked']), (21, 147, 28))
        forecasts[0]['predictions']['rolling_yoy_mean_6'] += 1
        with self.assertRaises(ValueError):
            b.independent_check(rows, forecasts, details, summary['subsets'])

    def test_reproduction_matches_and_both_industries_gate_new_models(self):
        b.OUT.mkdir(parents=True, exist_ok=True)
        source = panels()
        with tempfile.TemporaryDirectory(dir=b.OUT) as temp:
            folder = Path(temp)
            saved = reference(folder, source)
            self.assertEqual(b.reproduce(source, [], folder)['status'], 'PASS')
            saved['industries']['C222']['fixed_12_months']['scores']['past_yoy_mean']['MAE_pp'] += 0.01
            (folder / 'aggregate.json').write_text(json.dumps(saved))
            with patch.object(b, 'evaluate') as new_experiment:
                with self.assertRaisesRegex(ValueError, 'ROUND12A_NUMERIC_MISMATCH'):
                    b.run_analysis(source, [], folder)
                new_experiment.assert_not_called()

    def test_replay_gate_source_manifest_and_private_errors_tamper(self):
        b.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=b.OUT) as temp:
            folder, source = Path(temp), panels()
            saved = reference(folder, source)
            with self.assertRaises(ValueError):
                b.reproduce(source, [{'file': 'wrong'}], folder)
            saved['source_code_sha256'] = {'experiment_round12_industry_benchmark.py': '0' * 64}
            (folder / 'aggregate.json').write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, 'SOURCE_HASH'):
                b.reproduce(source, [], folder)
            reference(folder, source)
            path = folder / 'C303_private_details.json'
            private = json.loads(path.read_text())
            private['errors'][0]['error_pp'] += 1
            path.write_text(json.dumps(private))
            with self.assertRaises(ValueError):
                b.reproduce(source, [], folder)

    def test_pairwise_loo_bias_and_overprediction(self):
        details = []
        for i, (candidate, baseline) in enumerate([(1, 2), (4, 2), (2, 2)]):
            for model, error in [('bsi_blend_half', candidate), ('past_yoy_mean', baseline)]:
                details.append({'target': str(i), 'model': model, 'error_pp': error})
        result = b.paired(details, 'bsi_blend_half', 'past_yoy_mean')
        self.assertEqual((result['wins'], result['ties'], result['losses']), (1, 1, 1))
        self.assertEqual((result['loo_skill_min_percent'], result['loo_skill_max_percent']), (-50, 25))
        self.assertEqual(result['loo_direction_reversals'], 1)
        _, details, summary = b.evaluate(panel())
        for model in b.MODELS:
            selected = [r for r in details if r['model'] == model and r['target'] in b.a.TARGETS]
            diagnostic = summary['subsets']['fixed_12_months']['bias_diagnostics'][model]
            self.assertEqual(diagnostic['overprediction_months'], sum(r['predicted_yoy_pct'] > r['actual_yoy_pct'] for r in selected))
            self.assertAlmostEqual(summary['subsets']['fixed_12_months']['scores'][model]['bias_pp'],
                                   sum(r['predicted_yoy_pct'] - r['actual_yoy_pct'] for r in selected) / 12)

    def test_direction_zero_policy(self):
        details = [{'target': str(i), 'model': m, 'actual_yoy_pct': actual, 'predicted_yoy_pct': 0.0,
                    'error_pp': -actual} for i, actual in enumerate([0, 2, -2]) for m in b.MODELS]
        summary = b.summarize(details)
        for model in b.MODELS:
            self.assertEqual(summary['direction'][model], {'hits': 0, 'n_nonzero_actual': 2, 'hit_rate_percent': 0})

    def test_nonfinite_constant_duplicate_gap_and_survey_rejected(self):
        for rows in (panel()[:-1], panel() + [panel()[0]]):
            with self.assertRaises(ValueError):
                b.evaluate(rows)
        for key, value in [('bsi_value', 85.0), ('production_yoy_pct', float('nan'))]:
            rows = panel()
            for r in rows:
                r[key] = value
            with self.assertRaises(ValueError):
                b.evaluate(rows)
        rows = panel()
        rows[0]['survey_month'] = rows[0]['forecast_target_month']
        with self.assertRaises(ValueError):
            b.evaluate(rows)


if __name__ == '__main__':
    unittest.main()
