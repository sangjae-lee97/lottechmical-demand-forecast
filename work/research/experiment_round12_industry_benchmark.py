"""Offline fixed industry benchmark; current-vintage hindsight, never customer demand."""
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone, timedelta
from io import BytesIO

from analyze_round08 import LOCAL, ROOT, consecutive, require, shift
from analyze_round09 import read_proxies
from experiment_round08b_hindsight import LABEL, TARGETS, forecast_at as base_forecast, metrics

OUT = LOCAL / 'round12_benchmark'
MAPPING = {'C303': ('C3000', 'automobile'), 'C222': ('C0000', 'manufacturing')}
MODELS = ('seasonal_naive', 'past_yoy_mean', 'bsi_ols', 'yoy_last_available_tminus2')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def valid_month(month):
    require(isinstance(month, str) and len(month) == 7 and shift(month, 0) == month, 'Invalid month')


def build_panel(production, bsi, industry):
    require(industry in MAPPING, 'Wrong industry')
    code, sector = MAPPING[industry]
    values = {}
    for row in production:
        require(row['industry_code'] == industry and (row['org_id'], row['table_id'], row['region_code'],
                row['item_id'], row['unit']) == ('101', 'DT_1F02001', '00', 'T10', '2020=100'), 'Wrong production codes')
        month = row['period']
        valid_month(month)
        require(month not in values and math.isfinite(row['value']) and row['value'] > 0, 'Duplicate/invalid production')
        values[month] = row['value']
    require(sorted(values) == [shift('2022-01', i) for i in range(57)], 'Wrong production period')
    require({r['period'] for r in production if r['provisional_ui_flag']} == set(TARGETS[-2:]), 'Unexpected provisional flags')
    features = {}
    for row in bsi:
        require((row['table_code'], row['item_code1'], row['item_code2'], row['sector']) ==
                ('512Y008', 'BD', code, sector), 'Wrong BSI codes/mapping')
        month = row['forecast_target_month']
        valid_month(month)
        require(row['survey_month'] == shift(month, -1), 'Survey/target month mismatch')
        require(month not in features and math.isfinite(row['value']) and 0 <= row['value'] <= 200, 'Duplicate/invalid BSI')
        features[month] = row['value']
    require(sorted(features) == [shift('2023-12', i) for i in range(36)], 'Wrong BSI period')
    panel = [{'forecast_target_month': t, 'survey_month': shift(t, -1), 'bsi_value': features[t],
              'production_yoy_pct': 100 * (values[t] / values[shift(t, -12)] - 1)}
             for t in sorted(set(values) & set(features))]
    validate_panel(panel)
    return panel


def validate_panel(panel):
    months = [r['forecast_target_month'] for r in panel]
    for row in panel:
        valid_month(row['forecast_target_month'])
        require(row['survey_month'] == shift(row['forecast_target_month'], -1), 'Wrong panel survey month')
    consecutive(months)
    require(sorted(months) == [shift('2023-12', i) for i in range(34)], 'Incomplete common panel')


def forecast_at(panel, target):
    # Only historical Y <= t-2 and current X_t are consumed by base_forecast.
    result = base_forecast(panel, target)
    previous = [r for r in panel if r['forecast_target_month'] == result['cutoff']]
    require(len(previous) == 1, 'Missing/duplicate t-2 YoY')
    result['predictions']['yoy_last_available_tminus2'] = previous[0]['production_yoy_pct']
    require(all(math.isfinite(v) for v in result['predictions'].values()), 'Nonfinite forecast')
    return result


def comparison(details, baseline):
    by_model = {m: {r['target']: r for r in details if r['model'] == m} for m in ('bsi_ols', baseline)}
    months = sorted(by_model['bsi_ols'])
    require(months and set(months) == set(by_model[baseline]), 'Unpaired comparison')
    differences = {t: abs(by_model['bsi_ols'][t]['error_pp']) - abs(by_model[baseline][t]['error_pp']) for t in months}
    base = statistics.mean(abs(by_model[baseline][t]['error_pp']) for t in months)
    delta = statistics.mean(differences.values())
    loo = []
    for omitted in months:
        selected = [t for t in months if t != omitted]
        if not selected:
            continue
        b = statistics.mean(abs(by_model[baseline][t]['error_pp']) for t in selected)
        d = statistics.mean(differences[t] for t in selected)
        loo.append({'omitted': omitted, 'delta_MAE_pp': d, 'skill_percent': -100 * d / b if b else None})
    skills = [r['skill_percent'] for r in loo if r['skill_percent'] is not None]
    return {'delta_MAE_pp': delta, 'skill_percent': -100 * delta / base if base else None,
            'wins': sum(d < -1e-10 for d in differences.values()),
            'ties': sum(abs(d) <= 1e-10 for d in differences.values()),
            'losses': sum(d > 1e-10 for d in differences.values()),
            'largest_absolute_error_gap_pp': max(abs(d) for d in differences.values()),
            'largest_BSI_disadvantage_month': max(differences, key=differences.get),
            'loo_delta_min_pp': min((r['delta_MAE_pp'] for r in loo), default=None),
            'loo_delta_max_pp': max((r['delta_MAE_pp'] for r in loo), default=None),
            'loo_skill_min_percent': min(skills, default=None), 'loo_skill_max_percent': max(skills, default=None),
            'loo_direction_reversals': sum(r['delta_MAE_pp'] * delta < 0 for r in loo)}


def summarize(details):
    scores = {m: metrics([r['error_pp'] for r in details if r['model'] == m]) for m in MODELS}
    direction = {}
    for model in ('past_yoy_mean', 'bsi_ols'):
        selected = [r for r in details if r['model'] == model and r['actual_yoy_pct'] != 0]
        hits = sum(r['predicted_yoy_pct'] * r['actual_yoy_pct'] > 0 for r in selected)
        direction[model] = {'hits': hits, 'n_nonzero_actual': len(selected),
                            'hit_rate_percent': 100 * hits / len(selected) if selected else None}
    return {'scores': scores, 'comparisons': {m: comparison(details, m) for m in MODELS if m != 'bsi_ols'},
            'direction': direction,
            'evaluation_actual_yoy_sd_pp': statistics.stdev(r['actual_yoy_pct'] for r in details if r['model'] == 'bsi_ols')}


def independent_check(panel, forecasts, details):
    """Independent stdlib OLS and direct arithmetic, not the imported implementation."""
    rows = {r['forecast_target_month']: r for r in panel}
    for f in forecasts:
        train = [r for t, r in sorted(rows.items()) if t <= shift(f['target'], -2)]
        line = statistics.linear_regression([r['bsi_value'] for r in train], [r['production_yoy_pct'] for r in train])
        expected = dict(zip(MODELS, [0.0, sum(r['production_yoy_pct'] for r in train) / len(train),
                        line.intercept + line.slope * rows[f['target']]['bsi_value'], rows[shift(f['target'], -2)]['production_yoy_pct']]))
        require(math.isclose(line.slope, f['slope'], rel_tol=1e-10, abs_tol=1e-10)
                and math.isclose(line.intercept, f['intercept'], rel_tol=1e-10, abs_tol=1e-10), 'Independent OLS mismatch')
        for model in MODELS:
            require(math.isclose(f['predictions'][model], expected[model], rel_tol=1e-10, abs_tol=1e-10), 'Independent prediction mismatch')
            row = next(r for r in details if r['model'] == model and r['target'] == f['target'])
            require(math.isclose(row['error_pp'], expected[model] - rows[f['target']]['production_yoy_pct'],
                                 rel_tol=1e-10, abs_tol=1e-10), 'Independent error mismatch')
    for selected in (TARGETS, TARGETS[:-2]):
        for model in MODELS:
            errors = [r['error_pp'] for r in details if r['model'] == model and r['target'] in selected]
            result = metrics(errors)
            expected = {'MAE_pp': sum(abs(v) for v in errors) / len(errors),
                        'RMSE_pp': math.sqrt(sum(v * v for v in errors) / len(errors)),
                        'bias_pp': sum(errors) / len(errors)}
            require(all(math.isclose(result[k], v, rel_tol=1e-10, abs_tol=1e-10) for k, v in expected.items()),
                    'Independent score mismatch')
    return {'origins_checked': len(forecasts), 'predictions_and_errors_checked': len(details),
            'metric_sets_checked': 8, 'status': 'PASS'}


def evaluate(panel):
    validate_panel(panel)
    forecasts = [forecast_at(panel, t) for t in TARGETS]  # All predictions before scoring.
    actuals = {r['forecast_target_month']: r['production_yoy_pct'] for r in panel}
    details = []
    for f in forecasts:
        actual = actuals[f['target']]
        require(math.isfinite(actual), 'Nonfinite actual')
        for model, predicted in f['predictions'].items():
            details.append({'target': f['target'], 'model': model, 'actual_yoy_pct': actual,
                            'predicted_yoy_pct': predicted, 'error_pp': predicted - actual})
    full = summarize(details)
    sensitivity = summarize([r for r in details if r['target'] in TARGETS[:-2]])
    return forecasts, details, {'fixed_12_months': full, 'exclude_provisional_10_months': sensitivity,
                               'independent_arithmetic': independent_check(panel, forecasts, details),
                               'train_first_n': forecasts[0]['train_n'], 'train_last_n': forecasts[-1]['train_n']}


def load_inputs():
    directory = LOCAL / 'round09_industry'
    prior9 = json.loads((directory / 'summary.json').read_bytes())
    prior7 = json.loads((LOCAL / 'round07c_ecos/manifest.json').read_bytes())
    expected9 = {r['file'].replace('\\', '/'): r['sha256'] for r in prior9['input_manifest']}
    expected7 = {r['file']: r['sha256'] for r in prior7}
    names = ['industry_generic.xml', 'industry_dsd.xml']
    paths = [directory / n for n in names] + [LOCAL / 'round07c_ecos/normalized_snapshot.json']
    paths += [LOCAL / f'round07c_ecos/search_512Y008_M_202312_202611_BD_{c}.json' for c, _ in MAPPING.values()]
    blobs = {path: path.read_bytes() for path in paths}
    for path in paths:
        expected = expected9[path.relative_to(ROOT).as_posix()] if path.parent == directory else expected7[path.name]
        require(digest(blobs[path]) == expected, 'Input hash mismatch; stop')
    production = read_proxies(BytesIO(blobs[paths[0]]), BytesIO(blobs[paths[1]]))
    bsi = json.loads(blobs[paths[2]])
    require(len(production) == 114 and len(bsi) == 72, 'Unexpected input row counts')
    for path, (code, _) in zip(paths[3:], MAPPING.values()):
        raw = json.loads(blobs[path])
        rows = [r for page in raw['pages'] for r in page['response']['StatisticSearch']['row']]
        normalized = {r['forecast_target_month'].replace('-', ''): r for r in bsi if r['item_code2'] == code}
        require(len(rows) == len(normalized) == len({r['TIME'] for r in rows}) == 36, 'Raw BSI count/duplicate')
        for r in rows:
            require((r['STAT_CODE'], r['ITEM_CODE1'], r['ITEM_CODE2']) == ('512Y008', 'BD', code), 'Raw BSI codes')
            require(r['TIME'] in normalized and float(r['DATA_VALUE']) == normalized[r['TIME']]['value'], 'Raw BSI mismatch')
    panels = {industry: build_panel([r for r in production if r['industry_code'] == industry],
                                   [r for r in bsi if r['item_code2'] == code], industry)
              for industry, (code, _) in MAPPING.items()}
    manifest = [{'file': p.relative_to(ROOT).as_posix(), 'sha256': digest(raw)} for p, raw in blobs.items()]
    return panels, manifest


def main():
    panels, manifest = load_inputs()
    when = datetime.now(timezone(timedelta(hours=9)))
    run = OUT / when.strftime('%Y%m%dT%H%M%S%f')
    run.mkdir(parents=True, exist_ok=False)
    summaries = {}
    for industry, panel in panels.items():
        forecasts, details, summary = evaluate(panel)
        summaries[industry] = summary
        (run / f'{industry}_private_details.json').write_text(json.dumps({'panel': panel, 'forecasts': forecasts, 'errors': details},
                                                                      ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    aggregate = {'experiment': LABEL, 'strict_gate_status': 'NO_VERIFIED_BACKTEST', 'executed_at': when.isoformat(),
                 'historical_release_vintage_verified': False, 'mapping': MAPPING, 'input_manifest': manifest,
                 'input_production_rows_per_industry': 57, 'input_BSI_rows_per_sector': 36, 'common_panel_rows': 34,
                 'evaluation': [TARGETS[0], TARGETS[-1]], 'metric_unit': 'percentage_points',
                 'error_definition': 'prediction_minus_actual', 'training_cutoff': 't-2_inclusive',
                 'source_code_sha256': {name: digest((ROOT / 'work/research' / name).read_bytes()) for name in
                     ('experiment_round12_industry_benchmark.py', 'test_round12_industry_benchmark.py',
                      'analyze_round08.py', 'analyze_round09.py', 'experiment_round08b_hindsight.py')},
                 'industries': summaries}
    (run / 'aggregate.json').write_text(json.dumps(aggregate, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(aggregate, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
