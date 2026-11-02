"""Small checks for accounting, availability and non-identification boundaries."""
import copy
import unittest
from experiment import evaluate, forecast, generate, validate


class SafetyChecks(unittest.TestCase):
    def test_customer_accounting_and_lc_subset(self):
        events, truth = generate(0)
        validate(events)
        previous_w = 0
        for row in truth:
            self.assertAlmostEqual(row['I_open'] + row['R_total'] - row['C'], row['I_close'])
            self.assertAlmostEqual(previous_w + row['O_total'] - row['R_total'], row['W_close'])
            self.assertAlmostEqual(row['O_LC'], .45 * row['O_total'])
            self.assertGreaterEqual(row['I_close'], 0)
            previous_w = row['W_close']

    def test_unavailable_and_future_observations_cannot_change_forecast(self):
        events, _ = generate(0)
        expected = forecast(events, 35)
        changed = copy.deepcopy(events)
        for e in changed:
            if e['available_at'] > 35 or e['period'] > 35:
                e['value'] += 1_000_000
        self.assertEqual(expected, forecast(changed, 35))
        self.assertEqual(expected, forecast([e for e in events if e['available_at'] <= 35], 35))

    def test_inventory_without_receipts_is_not_consumption_measurement(self):
        events, _ = generate(0)
        changed = copy.deepcopy(events)
        for e in changed:
            if e['metric'] in ('inventory_report', 'shipment_lc'):
                e['value'] += 100_000
        self.assertEqual(forecast(events, 35), forecast(changed, 35))

    def test_order_only_abstains_and_share_changes_scenario(self):
        events, _ = generate(0)
        order_only = [e for e in events if e['metric'] == 'order_lc']
        result = forecast(order_only, 35)
        self.assertEqual(result['status'], 'NOT_IDENTIFIED')
        self.assertIsNone(result['with_state'])
        self.assertIsNone(result['state_mean'])
        self.assertIsNone(result['state_forecast_high'])
        self.assertGreater(forecast(events, 35, .30)['order_3ma'], forecast(events, 35, .60)['order_3ma'])

    def test_bad_unit_duplicate_and_early_availability_rejected(self):
        events, _ = generate(0)
        for field, value in [('unit', 'kg'), ('value', float('nan')), ('available_at', -1)]:
            changed = copy.deepcopy(events)
            changed[0][field] = value
            with self.assertRaises(ValueError):
                validate(changed)
        with self.assertRaises(ValueError):
            validate(events + [events[0]])

    def test_same_seed_and_same_truth_in_failure_scenario(self):
        base_events, base_truth = generate(7)
        bad_events, bad_truth = generate(7, True)
        self.assertEqual((base_events, base_truth), generate(7))
        self.assertEqual(base_truth, bad_truth)
        self.assertNotEqual(base_events, bad_events)

    def test_changing_evaluation_truth_does_not_change_predictions(self):
        events, truth = generate(0)
        changed_truth = copy.deepcopy(truth)
        for row in changed_truth:
            row['C'] += 1000
        original = evaluate(events, truth, 0, 'base', .45)
        changed = evaluate(events, changed_truth, 0, 'base', .45)
        self.assertEqual([r['prediction'] for r in original], [r['prediction'] for r in changed])
        self.assertNotEqual([r['error'] for r in original], [r['error'] for r in changed])


if __name__ == '__main__':
    unittest.main()
