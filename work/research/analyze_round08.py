"""Offline KOSIS/ECOS snapshot checks. No training or raw-data publication."""
import argparse
import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / 'work/data/local_only'
OUT = LOCAL / 'round08_production'
G = '{http://www.SDMX.org/resources/SDMXML/schemas/v2_0/generic}'
S = '{http://www.SDMX.org/resources/SDMXML/schemas/v2_0/structure}'
M = '{http://www.SDMX.org/resources/SDMXML/schemas/v2_0/message}'
KO = '{http://www.w3.org/XML/1998/namespace}lang'
SOURCE = 'https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1F02001&conn_path=I2'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def shift(period, offset):
    date = datetime.strptime(period, '%Y-%m')
    number = date.year * 12 + date.month - 1 + offset
    return f'{number // 12:04}-{number % 12 + 1:02}'


def consecutive(periods):
    require(bool(periods), 'Empty monthly series')
    require(len(periods) == len(set(periods)), 'Duplicate monthly key')
    require(sorted(periods) == [shift(min(periods), i) for i in range(len(periods))],
            'Missing monthly period')


def read_production(data_path, dsd_path):
    data, dsd = ET.parse(data_path).getroot(), ET.parse(dsd_path).getroot()
    require(data.findtext(f'{M}Header/{M}DataSetID') == '101_DT_1F02001', 'Wrong table')
    require(dsd.find(f'.//{S}KeyFamily[@id="101_DT_1F02001"]') is not None, 'Wrong DSD table')
    expected = {'CL_A': ('00', '전국'), 'CL_B': ('C30', '자동차 및 트레일러 제조업'),
                'CL_ITEM': ('T10', '생산지수(원지수)'), 'CL_UNIT': ('14101.ausgabe', '2020=100')}
    for list_id, (code, label) in expected.items():
        block = dsd.find(f'.//{S}CodeList[@id="{list_id}"]')
        require(block is not None, 'Missing DSD code list: ' + list_id)
        codes = block.findall(S + 'Code')
        require(len(codes) == 1 and codes[0].get('value') == code, 'Unexpected DSD selection: ' + list_id)
        labels = [e.text for e in codes[0].findall(S + 'Description') if e.get(KO) == 'ko']
        require(labels == [label], 'DSD label mismatch: ' + list_id)
    series = data.findall(f'.//{G}Series')
    require(len(series) == 1, 'Expected exactly one production series')
    keys = {e.get('concept'): e.get('value') for e in series[0].findall(f'{G}SeriesKey/{G}Value')}
    require(keys == {'FREQ': 'M', 'A': '00', 'B': 'C30'}, 'Wrong series dimensions')
    # This KOSIS export omits ITEM and UNIT from SeriesKey. Require a singleton
    # companion DSD and the documented same UI selection; never infer across tables.
    rows = []
    for obs in series[0].findall(G + 'Obs'):
        raw_period = obs.findtext(G + 'Time')
        require(raw_period is not None and len(raw_period) == 6, 'Invalid monthly encoding')
        period = datetime.strptime(raw_period, '%Y%m').strftime('%Y-%m')
        value = float(obs.find(G + 'ObsValue').get('value'))
        require(math.isfinite(value) and value > 0, 'Invalid original index value')
        rows.append({'period': period, 'value': value, 'org_id': '101', 'table_id': 'DT_1F02001',
                     'region_code': '00', 'industry_code': 'C30', 'item_id': 'T10', 'unit': '2020=100',
                     'publication_date': None, 'available_at': None, 'asof_evidence': None,
                     'vintage_verified_for_origin': False, 'source': SOURCE,
                     'snapshot_extracted_at_raw': data.findtext(f'{M}Header/{M}Extracted'),
                     'snapshot_timezone_verified': False,
                     'table_updated_on': '2026-10-30',
                     'provisional_ui_flag': period in ('2026-08', '2026-09'),
                     'provisional_flag_basis': 'KOSIS selected table column p) labels',
                     'vintage': 'current_download_not_original_release'})
    consecutive([r['period'] for r in rows])
    return sorted(rows, key=lambda r: r['period'])


def read_bsi(path):
    source = json.loads(path.read_text(encoding='utf-8'))
    rows = [r for r in source if r['sector'] == 'automobile']
    require(bool(rows), 'No automobile BSI')
    for r in rows:
        require((r['table_code'], r['item_code1'], r['item_code2']) == ('512Y008', 'BD', 'C3000'),
                'Wrong BSI series')
        require(r['survey_month'] == shift(r['forecast_target_month'], -1), 'BSI survey/target mismatch')
        require(math.isfinite(r['value']) and 0 <= r['value'] <= 200, 'Invalid BSI')
    consecutive([r['forecast_target_month'] for r in rows])
    return rows


def verified_input(row, origin):
    """Fail closed: current snapshots alone cannot prove historical availability."""
    if not (row.get('publication_date') and row.get('available_at') and row.get('asof_evidence')
            and row.get('vintage_verified_for_origin') is True):
        return False
    try:
        available = datetime.fromisoformat(row['available_at'])
        published = datetime.fromisoformat(row['publication_date']).date()
        point = datetime.fromisoformat(origin)
        return bool(available.tzinfo and point.tzinfo and available.date() >= published and available <= point)
    except (TypeError, ValueError):
        return False


def align(bsi, production):
    y = {r['period']: r for r in production}
    rows = []
    for x in sorted(bsi, key=lambda r: r['forecast_target_month']):
        target = x['forecast_target_month']
        if target not in y:
            continue
        origin = target + '-01T00:00:00+09:00'
        baseline = y.get(shift(target, -12))
        rows.append({'forecast_target_month': target, 'survey_month': x['survey_month'],
                     'production_period': target, 'origin': origin, 'bsi_value': x['value'],
                     'production_index': y[target]['value'],
                     'production_yoy_pct': 100 * (y[target]['value'] / baseline['value'] - 1) if baseline else None,
                     'bsi_available_at': x.get('available_at'),
                     'bsi_vintage_verified_for_origin': x.get('vintage_verified_for_origin', False),
                     'baseline_period': baseline['period'] if baseline else None,
                     'baseline_available_at': baseline.get('available_at') if baseline else None,
                     'bsi_input_verified': verified_input(x, origin),
                     'baseline_input_verified': bool(baseline and verified_input(baseline, origin)),
                     'sample_break': bool(x.get('sample_break_at_target_month')),
                     'analysis_kind': 'exploratory_current_snapshots_not_forecasts'})
    return rows


def correlation(pairs):
    valid = [(x, y) for x, y in pairs if x is not None and y is not None]
    xs, ys = zip(*valid) if valid else ([], [])
    r = statistics.correlation(xs, ys) if len(valid) >= 3 and len(set(xs)) > 1 and len(set(ys)) > 1 else None
    return {'n': len(valid), 'pearson_r': r}


def summarize(aligned, bsi, production):
    y = {r['period']: r['value'] for r in production}
    x = {r['forecast_target_month']: r['value'] for r in bsi}
    lags = []
    # Anchor BSI months to the actual same-month overlap. No lag search or tuning.
    for offset in [-1, 0, 1]:
        levels, changes = [], []
        for r in aligned:
            month = shift(r['forecast_target_month'], offset)
            value, last_year = y.get(month), y.get(shift(month, -12))
            if value is not None:
                levels.append((r['bsi_value'], value))
                changes.append((r['bsi_value'], 100 * (value / last_year - 1) if last_year else None))
        lags.append({'definition': 'corr(BSI_t, Y_(t+k)); anchors=same_month_overlap', 'k': offset,
                     'index_level': correlation(levels), 'yoy_percent': correlation(changes)})
    per_year = []
    for year in sorted({r['forecast_target_month'][:4] for r in aligned}):
        subset = [r for r in aligned if r['forecast_target_month'].startswith(year)]
        per_year.append({'year': year, 'index_level': correlation([(r['bsi_value'], r['production_index']) for r in subset]),
                         'yoy_percent': correlation([(r['bsi_value'], r['production_yoy_pct']) for r in subset])})
    verified = [r for r in aligned if r['bsi_input_verified'] and r['baseline_input_verified']]
    return {'status': 'EXPLORATORY_ONLY', 'backtest_status': 'NO_VERIFIED_BACKTEST',
            'reason': 'Historical BSI release/vintage and lagged production release/vintage not verified',
            'production_rows': len(production), 'production_first': min(y), 'production_last': max(y),
            'bsi_rows': len(bsi), 'aligned_rows': len(aligned),
            'aligned_first': aligned[0]['forecast_target_month'] if aligned else None,
            'aligned_last': aligned[-1]['forecast_target_month'] if aligned else None,
            'bsi_targets_without_y': sorted(set(x) - set(y)),
            'provisional_y_rows': sum(r['provisional_ui_flag'] for r in production),
            'break_rows_in_overlap': sum(r['sample_break'] for r in aligned),
            'verified_same_origin_input_pairs': len(verified),
            'lags': lags, 'per_year': per_year,
            'warning': 'No causal, leading-indicator or out-of-sample predictive claim; seasonality, revisions and small samples remain'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production', type=Path, default=OUT / 'production_generic.xml')
    parser.add_argument('--dsd', type=Path, default=OUT / 'production_dsd.xml')
    parser.add_argument('--bsi', type=Path, default=LOCAL / 'round07c_ecos/normalized_snapshot.json')
    args = parser.parse_args()
    production, bsi = read_production(args.production, args.dsd), read_bsi(args.bsi)
    aligned = align(bsi, production)
    summary = summarize(aligned, bsi, production)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in [('normalized_production.json', production), ('aligned_snapshots.json', aligned),
                       ('analysis_summary.json', summary)]:
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = [{'file': str(p.resolve().relative_to(ROOT)), 'bytes': p.stat().st_size,
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in [args.production, args.dsd, args.bsi]]
    (OUT / 'input_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Only derived statistics/counts are printed; official observation values stay local.
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # No forecast fitting path: the missing as-of evidence blocks model comparison.
    print('NO_VERIFIED_BACKTEST: no models trained or forecast scores produced')


if __name__ == '__main__':
    main()
