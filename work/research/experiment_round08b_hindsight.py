"""HINDSIGHT_CURRENT_VINTAGE_EXPLORATORY; never a verified real-time backtest."""
import hashlib
import json
import math
import statistics
from pathlib import Path

from analyze_round08 import LOCAL, OUT as PRODUCTION_DIR, ROOT, align, read_bsi, read_production, require, shift

LABEL = 'HINDSIGHT_CURRENT_VINTAGE_EXPLORATORY'
OUT = LOCAL / 'round08b_hindsight'
TARGETS = tuple(shift('2025-10', i) for i in range(12))
MIN_TRAIN = 12  # Fixed before scores; no minimum-window search.
MODELS = ('seasonal_naive', 'past_yoy_mean', 'bsi_ols')


def ols(xs, ys):
    require(len(xs) == len(ys) and len(xs) >= MIN_TRAIN, 'Insufficient OLS training rows')
    require(all(math.isfinite(v) for v in [*xs, *ys]), 'Nonfinite training value')
    x_mean, y_mean = statistics.mean(xs), statistics.mean(ys)
    denominator = math.fsum((x - x_mean) ** 2 for x in xs)
    require(denominator > 0, 'Constant BSI: slope unidentified; stop rather than tune/fallback')
    slope = math.fsum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    return y_mean - slope * x_mean, slope


def forecast_at(panel, target):
    """Return predictions without reading target/future Y into estimation."""
    cutoff = shift(target, -2)
    train = sorted((r for r in panel if r['forecast_target_month'] <= cutoff),
                   key=lambda r: r['forecast_target_month'])
    current = [r for r in panel if r['forecast_target_month'] == target]
    require(len(current) == 1, 'Missing/duplicate fixed target')
    require(len(train) >= MIN_TRAIN, 'Insufficient common training rows')
    x_target = current[0]['bsi_value']
    require(math.isfinite(x_target), 'Invalid target BSI')
    # Every training target and its feature come from the same common-month panel.
    xs, ys = [r['bsi_value'] for r in train], [r['production_yoy_pct'] for r in train]
    require(all(v is not None and math.isfinite(v) for v in ys), 'Missing/nonfinite training YoY')
    intercept, slope = ols(xs, ys)
    predictions = {'seasonal_naive': 0.0, 'past_yoy_mean': statistics.mean(ys),
                   'bsi_ols': intercept + slope * x_target}
    require(all(math.isfinite(v) for v in predictions.values()), 'Nonfinite prediction')
    return {'target': target, 'origin': target + '-01T00:00:00+09:00', 'cutoff': cutoff,
            'train_months': [r['forecast_target_month'] for r in train], 'train_n': len(train),
            'train_last': train[-1]['forecast_target_month'], 'target_survey_month': shift(target, -1),
            'intercept': intercept, 'slope': slope, 'predictions': predictions}


def metrics(errors):
    require(bool(errors) and all(math.isfinite(e) for e in errors), 'Empty/nonfinite error series')
    return {'n': len(errors), 'MAE_pp': statistics.mean(abs(e) for e in errors),
            'RMSE_pp': math.sqrt(statistics.mean(e * e for e in errors)),
            'bias_pp': statistics.mean(errors)}


def evaluate(panel):
    require(len({r['forecast_target_month'] for r in panel}) == len(panel), 'Duplicate panel month')
    actuals = {r['forecast_target_month']: r['production_yoy_pct'] for r in panel}
    require(all(t in actuals for t in TARGETS), 'Fixed evaluation month unavailable; do not shorten window')
    # Compute all predictions first. Actual targets enter only the subsequent scoring.
    forecasts = [forecast_at(panel, target) for target in TARGETS]
    details = []
    for forecast in forecasts:
        target, actual = forecast['target'], actuals[forecast['target']]
        require(actual is not None and math.isfinite(actual), 'Invalid evaluation YoY')
        for model in MODELS:
            prediction = forecast['predictions'][model]
            details.append({'experiment': LABEL, 'model': model, 'target': target,
                            'origin': forecast['origin'], 'cutoff': forecast['cutoff'],
                            'train_n': forecast['train_n'], 'train_last': forecast['train_last'],
                            'actual_yoy_pct': actual, 'predicted_yoy_pct': prediction,
                            'error_pp': prediction - actual, 'absolute_error_pp': abs(prediction - actual)})
    scores = {}
    for name, selected in [('fixed_12_months', TARGETS), ('exclude_provisional_2_months', TARGETS[:-2])]:
        scores[name] = {model: metrics([r['error_pp'] for r in details if r['model'] == model and r['target'] in selected])
                        for model in MODELS}
    comparisons = {}
    for name, scoreset in scores.items():
        comparisons[name] = {}
        for baseline in MODELS[:2]:
            base, bsi = scoreset[baseline]['MAE_pp'], scoreset['bsi_ols']['MAE_pp']
            comparisons[name][baseline] = {'BSI_minus_baseline_MAE_pp': bsi - base,
                                           'MAE_improvement_percent': 100 * (base - bsi) / base if base else None}
    return forecasts, details, scores, comparisons


def main():
    inputs = [PRODUCTION_DIR / 'production_generic.xml', PRODUCTION_DIR / 'production_dsd.xml',
              LOCAL / 'round07c_ecos/normalized_snapshot.json']
    recorded = json.loads((PRODUCTION_DIR / 'input_manifest.json').read_text(encoding='utf-8'))
    expected = {Path(r['file']).name: r['sha256'] for r in recorded}
    manifest = [{'file': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in inputs]
    require(all(r['sha256'] == expected[Path(r['file']).name] for r in manifest),
            'Input snapshot changed since ROUND 08-A; stop and review')
    production = read_production(inputs[0], inputs[1])
    bsi = read_bsi(inputs[2])
    require(len(production) == 57 and len(bsi) == 36, 'Unexpected source snapshot counts')
    panel = align(bsi, production)
    require(len(panel) == 34, 'Unexpected common target months')
    forecasts, details, scores, comparisons = evaluate(panel)
    provisional = {r['period'] for r in production if r['provisional_ui_flag']}
    require(provisional.intersection(TARGETS) == set(TARGETS[-2:]), 'Provisional-month assumption changed')
    failures = {model: max((r for r in details if r['model'] == model), key=lambda r: r['absolute_error_pp'])['target']
                for model in MODELS}
    worse = sum(next(r['absolute_error_pp'] for r in details if r['model'] == 'bsi_ols' and r['target'] == t) >
                next(r['absolute_error_pp'] for r in details if r['model'] == 'past_yoy_mean' and r['target'] == t)
                for t in TARGETS)
    summary = {'experiment': LABEL, 'historical_release_vintage_verified': False,
               'strict_gate_status': 'NO_VERIFIED_BACKTEST', 'snapshot_checked_on': '2026-11-03',
               'input_manifest': manifest, 'production_n': len(production), 'automobile_bsi_n': len(bsi),
               'common_panel_n': len(panel), 'eval_first': TARGETS[0], 'eval_last': TARGETS[-1],
               'train_cutoff_rule': 'target_month_minus_2_inclusive; common_panel_rows_only',
               'min_train_rows_fixed': MIN_TRAIN, 'first_train_n': forecasts[0]['train_n'],
               'last_train_n': forecasts[-1]['train_n'], 'error_definition': 'prediction_minus_actual',
               'metric_unit': 'percentage_points', 'scores': scores, 'bsi_comparisons': comparisons,
               'worst_absolute_error_month': failures, 'bsi_worse_than_mean_months': worse,
               'bsi_break_month': '2026-11', 'post_break_targets_in_evaluation': 0,
               'warning': 'Current revised/provisional snapshots and assumed release lag; no real-time or customer PC/ABS performance claim'}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, value in [('forecasts_with_training_audit.json', forecasts), ('monthly_errors.json', details),
                        ('summary.json', summary)]:
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Do not print official monthly actuals/predictions; derived aggregate scores only.
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
