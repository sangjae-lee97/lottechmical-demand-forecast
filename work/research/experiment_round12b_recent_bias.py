"""Post-hoc recency/shrinkage exploration. Offline; no tuning or prospective claim."""
import json
import math
import statistics
from datetime import datetime, timezone, timedelta

import experiment_round12_industry_benchmark as a

OUT = a.LOCAL / 'round12b_benchmark'
REFERENCE = a.LOCAL / 'round12_benchmark/20261104T114907225557'
NEW_MODELS = ('rolling_yoy_mean_6', 'rolling_yoy_mean_12', 'bsi_blend_half')
MODELS = a.MODELS + NEW_MODELS
EXTENDED = tuple(a.shift('2025-01', i) for i in range(21))
SUBSETS = {'fixed_12_months': a.TARGETS, 'exclude_provisional_10_months': a.TARGETS[:-2],
           'extended_21_months': EXTENDED, 'earlier_9_months': EXTENDED[:9]}


def same(actual, expected):
    """Recursive replay gate: exact schema/labels, numerical tolerance 1e-10."""
    if type(actual) is float or type(expected) is float:
        a.require(isinstance(actual, (int, float)) and isinstance(expected, (int, float))
                  and math.isfinite(actual) and math.isfinite(expected)
                  and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10), 'ROUND12A_NUMERIC_MISMATCH')
    elif isinstance(actual, dict) and isinstance(expected, dict):
        a.require(set(actual) == set(expected), 'ROUND12A_SCHEMA_MISMATCH')
        for key in actual:
            same(actual[key], expected[key])
    elif isinstance(actual, list) and isinstance(expected, list):
        a.require(len(actual) == len(expected), 'ROUND12A_LENGTH_MISMATCH')
        for left, right in zip(actual, expected):
            same(left, right)
    else:
        a.require(actual == expected, 'ROUND12A_VALUE_MISMATCH')


def reproduce(panels, manifest, reference=REFERENCE):
    raw = (reference / 'aggregate.json').read_bytes()
    saved = json.loads(raw)
    same(manifest, saved['input_manifest'])
    for name, expected in saved['source_code_sha256'].items():
        a.require(a.digest((a.ROOT / 'work/research' / name).read_bytes()) == expected, 'ROUND12A_SOURCE_HASH_MISMATCH')
    hashes = {'aggregate.json': a.digest(raw)}
    for code in a.MAPPING:
        forecasts, details, summary = a.evaluate(panels[code])
        same(summary, saved['industries'][code])
        private_raw = (reference / f'{code}_private_details.json').read_bytes()
        prior = json.loads(private_raw)
        same({'panel': panels[code], 'forecasts': forecasts, 'errors': details}, prior)
        hashes[f'{code}_private_details.json'] = a.digest(private_raw)
    return {'status': 'PASS', 'reference_run': reference.name, 'reference_sha256': hashes,
            'industry_count': 2, 'existing_predictions_and_errors': 96,
            'tolerance': 'rel=1e-10,abs=1e-10; exact keys/months/source/input hashes'}


def forecast_at(panel, target):
    result = a.forecast_at(panel, target)
    train = sorted((r for r in panel if r['forecast_target_month'] <= result['cutoff']),
                   key=lambda r: r['forecast_target_month'])
    a.require(len(train) >= 12, 'Insufficient rolling training rows')
    for window in (6, 12):
        selected = train[-window:]
        a.require(len(selected) == window, 'Incomplete rolling window')
        result['predictions'][f'rolling_yoy_mean_{window}'] = statistics.mean(r['production_yoy_pct'] for r in selected)
        result[f'rolling_{window}_months'] = [r['forecast_target_month'] for r in selected]
    predictions = result['predictions']
    predictions['bsi_blend_half'] = 0.5 * predictions['bsi_ols'] + 0.5 * predictions['past_yoy_mean']
    a.require(all(math.isfinite(v) for v in predictions.values()), 'Nonfinite forecast')
    return result


def paired(details, model, baseline):
    # Reuse tested 12-A arithmetic with neutral labels; no model selection.
    selected = [{**r, 'model': 'bsi_ols' if r['model'] == model else 'reference'}
                for r in details if r['model'] in (model, baseline)]
    result = a.comparison(selected, 'reference')
    result['largest_candidate_disadvantage_month'] = result.pop('largest_BSI_disadvantage_month')
    return result


def summarize(details):
    scores = {m: a.metrics([r['error_pp'] for r in details if r['model'] == m]) for m in MODELS}
    comparisons = {m: {base: paired(details, m, base) for base in ('past_yoy_mean', 'seasonal_naive') if base != m}
                   for m in MODELS}
    direction, bias_diagnostics = {}, {}
    for model in MODELS:
        rows = [r for r in details if r['model'] == model]
        nonzero = [r for r in rows if r['actual_yoy_pct'] != 0]
        hits = sum(r['predicted_yoy_pct'] * r['actual_yoy_pct'] > 0 for r in nonzero)
        direction[model] = {'hits': hits, 'n_nonzero_actual': len(nonzero),
                            'hit_rate_percent': 100 * hits / len(nonzero) if nonzero else None}
        bias_diagnostics[model] = {'mean_prediction_yoy_pct': statistics.mean(r['predicted_yoy_pct'] for r in rows),
                                   'overprediction_months': sum(r['error_pp'] > 1e-10 for r in rows),
                                   'underprediction_months': sum(r['error_pp'] < -1e-10 for r in rows),
                                   'tied_months': sum(abs(r['error_pp']) <= 1e-10 for r in rows)}
    return {'scores': scores, 'comparisons': comparisons, 'direction': direction, 'bias_diagnostics': bias_diagnostics,
            'evaluation_actual_yoy_mean_pct': statistics.mean(r['actual_yoy_pct'] for r in details if r['model'] == 'past_yoy_mean')}


def independent_check(panel, forecasts, details, summaries):
    rows = {r['forecast_target_month']: r for r in panel}
    for f in forecasts:
        train = [r for t, r in sorted(rows.items()) if t <= a.shift(f['target'], -2)]
        ys, xs = [r['production_yoy_pct'] for r in train], [r['bsi_value'] for r in train]
        line = statistics.linear_regression(xs, ys)
        a.require(math.isclose(f['intercept'], line.intercept, rel_tol=1e-10, abs_tol=1e-10)
                  and math.isclose(f['slope'], line.slope, rel_tol=1e-10, abs_tol=1e-10), 'Independent OLS mismatch')
        mean = sum(ys) / len(ys)
        ols = line.intercept + line.slope * rows[f['target']]['bsi_value']
        expected = dict(zip(MODELS, [0.0, mean, ols, ys[-1], sum(ys[-6:]) / 6, sum(ys[-12:]) / 12, (ols + mean) / 2]))
        for model, prediction in expected.items():
            a.require(math.isclose(f['predictions'][model], prediction, rel_tol=1e-10, abs_tol=1e-10), 'Independent prediction mismatch')
            row = next(r for r in details if r['model'] == model and r['target'] == f['target'])
            a.require(math.isclose(row['error_pp'], prediction - rows[f['target']]['production_yoy_pct'],
                                   rel_tol=1e-10, abs_tol=1e-10), 'Independent error mismatch')
    for subset, months in SUBSETS.items():
        for model in MODELS:
            errors = [r['error_pp'] for r in details if r['model'] == model and r['target'] in months]
            expected = {'MAE_pp': sum(abs(v) for v in errors) / len(errors),
                        'RMSE_pp': math.sqrt(sum(v * v for v in errors) / len(errors)),
                        'bias_pp': sum(errors) / len(errors)}
            for key, value in expected.items():
                a.require(math.isclose(summaries[subset]['scores'][model][key], value, rel_tol=1e-10, abs_tol=1e-10),
                          'Independent metric mismatch')
    return {'status': 'PASS', 'origins_checked': len(forecasts), 'predictions_and_errors_checked': len(details),
            'metric_sets_checked': len(SUBSETS) * len(MODELS)}


def evaluate(panel):
    a.validate_panel(panel)
    forecasts = [forecast_at(panel, target) for target in EXTENDED]
    actuals = {r['forecast_target_month']: r['production_yoy_pct'] for r in panel}
    details = []
    for f in forecasts:
        actual = actuals[f['target']]
        a.require(math.isfinite(actual), 'Nonfinite actual')
        for model, prediction in f['predictions'].items():
            details.append({'target': f['target'], 'model': model, 'actual_yoy_pct': actual,
                            'predicted_yoy_pct': prediction, 'error_pp': prediction - actual})
    summaries = {name: summarize([r for r in details if r['target'] in months]) for name, months in SUBSETS.items()}
    audit = independent_check(panel, forecasts, details, summaries)
    return forecasts, details, {'subsets': summaries, 'independent_arithmetic': audit,
                               'extended_first_train_n': forecasts[0]['train_n'], 'last_train_n': forecasts[-1]['train_n']}


def run_analysis(panels, manifest, reference=REFERENCE):
    gate = reproduce(panels, manifest, reference)  # Both industries must pass before ANY new model.
    results = {code: evaluate(panel) for code, panel in panels.items()}
    return gate, results


def main():
    panels, manifest = a.load_inputs()
    gate, results = run_analysis(panels, manifest)
    when = datetime.now(timezone(timedelta(hours=9)))
    run = OUT / when.strftime('%Y%m%dT%H%M%S%f')
    run.mkdir(parents=True, exist_ok=False)
    for code, (forecasts, details, _) in results.items():
        (run / f'{code}_private_details.json').write_text(json.dumps({'panel': panels[code], 'forecasts': forecasts, 'errors': details},
                                                       ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    aggregate = {'experiment': a.LABEL, 'strict_gate_status': 'NO_VERIFIED_BACKTEST',
                 'design': 'POST_HOC_HYPOTHESES_AFTER_ROUND12A; NO_TUNING; NOT_INDEPENDENT_CONFIRMATION',
                 'executed_at': when.isoformat(), 'historical_release_vintage_verified': False,
                 'mapping': a.MAPPING, 'input_manifest': manifest, 'round12a_reproduction': gate,
                 'subsets': SUBSETS, 'metric_unit': 'percentage_points', 'error_definition': 'prediction_minus_actual',
                 'training_cutoff': 'target_minus_2_inclusive', 'fixed_parameters': {'windows': [6, 12], 'blend_weight': 0.5},
                 'source_code_sha256': {name: a.digest((a.ROOT / 'work/research' / name).read_bytes()) for name in
                    ('experiment_round12b_recent_bias.py', 'test_round12b_recent_bias.py', 'experiment_round12_industry_benchmark.py',
                     'experiment_round08b_hindsight.py', 'analyze_round08.py', 'analyze_round09.py')},
                 'industries': {code: r[2] for code, r in results.items()}}
    (run / 'aggregate.json').write_text(json.dumps(aggregate, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(aggregate, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
