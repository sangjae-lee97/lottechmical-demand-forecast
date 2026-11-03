"""Synthetic fixtures only; no official monthly observations/predictions embedded."""
import copy
import math
import statistics
import unittest

from experiment_round08b_hindsight import LABEL, MIN_TRAIN, MODELS, TARGETS, evaluate, forecast_at, metrics, ols, shift


def synthetic_panel():
    return [{'forecast_target_month': shift('2023-12', i), 'survey_month': shift('2023-12', i - 1),
             'bsi_value': float(80 + i % 7), 'production_yoy_pct': float(2 * (i % 7) - i % 3)}
            for i in range(34)]


class HindsightChecks(unittest.TestCase):
    def test_cutoff_is_inclusive_t_minus_two(self):
        forecasts, details, scores, _ = evaluate(synthetic_panel())
        self.assertEqual(len(forecasts), 12)
        self.assertEqual(len(details), 36)
        self.assertEqual((forecasts[0]['cutoff'], forecasts[0]['train_last'], forecasts[0]['train_n']),
                         ('2025-08', '2025-08', 21))
        self.assertEqual((forecasts[-1]['train_last'], forecasts[-1]['train_n']), ('2026-07', 32))
        for f in forecasts:
            self.assertTrue(all(month <= shift(f['target'], -2) for month in f['train_months']))
            self.assertNotIn(shift(f['target'], -1), f['train_months'])
            self.assertNotIn(f['target'], f['train_months'])
            self.assertEqual(f['target_survey_month'], shift(f['target'], -1))
        self.assertEqual(set(scores['fixed_12_months']), set(MODELS))

    def test_all_post_cutoff_targets_cannot_change_current_predictions(self):
        panel = synthetic_panel()
        for target in TARGETS:
            before = forecast_at(panel, target)
            changed = copy.deepcopy(panel)
            for row in changed:
                if row['forecast_target_month'] > shift(target, -2):
                    row['production_yoy_pct'] = 1_000_000.0
            self.assertEqual(before, forecast_at(changed, target))

    def test_future_features_not_read_and_target_feature_is_correct(self):
        panel, target = synthetic_panel(), TARGETS[0]
        before = forecast_at(panel, target)
        changed = copy.deepcopy(panel)
        for row in changed:
            if row['forecast_target_month'] > target:
                row['bsi_value'] += 1000
        self.assertEqual(before, forecast_at(changed, target))
        for row in changed:
            if row['forecast_target_month'] == target:
                row['bsi_value'] += 1
        after = forecast_at(changed, target)
        self.assertAlmostEqual(after['predictions']['bsi_ols'] - before['predictions']['bsi_ols'], before['slope'])
        self.assertEqual(after['predictions']['past_yoy_mean'], before['predictions']['past_yoy_mean'])

    def test_known_line_and_independent_stdlib_ols(self):
        xs = list(range(MIN_TRAIN))
        intercept, slope = ols(xs, [3 + 2 * x for x in xs])
        self.assertAlmostEqual(intercept, 3)
        self.assertAlmostEqual(slope, 2)
        panel = synthetic_panel()
        for target in TARGETS:
            forecast = forecast_at(panel, target)
            train = [r for r in panel if r['forecast_target_month'] <= shift(target, -2)]
            reference = statistics.linear_regression([r['bsi_value'] for r in train],
                                                    [r['production_yoy_pct'] for r in train])
            self.assertAlmostEqual(forecast['intercept'], reference.intercept)
            self.assertAlmostEqual(forecast['slope'], reference.slope)
            self.assertEqual(forecast['predictions']['seasonal_naive'], 0)
            self.assertEqual(forecast['predictions']['past_yoy_mean'],
                             statistics.mean(r['production_yoy_pct'] for r in train))

    def test_metrics_bias_sign_and_error_identity(self):
        result = metrics([-2, 0, 4])
        self.assertEqual(result['MAE_pp'], 2)
        self.assertAlmostEqual(result['RMSE_pp'], math.sqrt(20 / 3))
        self.assertAlmostEqual(result['bias_pp'], 2 / 3)
        _, details, _, _ = evaluate(synthetic_panel())
        for row in details:
            self.assertEqual(row['error_pp'], row['predicted_yoy_pct'] - row['actual_yoy_pct'])
            self.assertEqual(row['experiment'], LABEL)

    def test_sensitivity_uses_same_predictions_and_fixed_months(self):
        _, details, scores, comparisons = evaluate(synthetic_panel())
        self.assertEqual(TARGETS[0], '2025-10')
        self.assertEqual(TARGETS[-1], '2026-09')
        for model in MODELS:
            self.assertEqual(scores['fixed_12_months'][model]['n'], 12)
            self.assertEqual(scores['exclude_provisional_2_months'][model]['n'], 10)
            subset = [r for r in details if r['model'] == model and r['target'] not in ('2026-08', '2026-09')]
            self.assertEqual(scores['exclude_provisional_2_months'][model], metrics([r['error_pp'] for r in subset]))
        for baseline in MODELS[:2]:
            self.assertAlmostEqual(comparisons['fixed_12_months'][baseline]['BSI_minus_baseline_MAE_pp'],
                                   scores['fixed_12_months']['bsi_ols']['MAE_pp'] - scores['fixed_12_months'][baseline]['MAE_pp'])

    def test_bad_or_incomplete_inputs_stop_without_changing_window(self):
        panel = synthetic_panel()
        for invalid in [panel[:-1], panel + [panel[0]], panel[11:]]:
            with self.assertRaises(ValueError):
                evaluate(invalid)
        with self.assertRaises(ValueError):
            ols([1] * MIN_TRAIN, list(range(MIN_TRAIN)))
        with self.assertRaises(ValueError):
            metrics([float('nan')])


if __name__ == '__main__':
    unittest.main()
