"""Contemporaneous industry-proxy exploration only; no prediction or tuning."""
import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET

from analyze_round08 import G, S, M, KO, LOCAL, OUT as C30_DIR, ROOT, consecutive, correlation, read_production, require, shift

OUT = LOCAL / 'round09_industry'
LABEL = 'CURRENT_VINTAGE_CONTEMPORANEOUS_EXPLORATORY'
PROXIES = {'C222': ('플라스틱 제품 제조업', 'C22'), 'C303': ('자동차 신품 부품 제조업', 'C30')}
SOURCE = 'https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1F02001&conn_path=I2'


def code_list(dsd, name):
    block = dsd.find(f'.//{S}CodeList[@id="{name}"]')
    require(block is not None, 'Missing DSD list: ' + name)
    rows = block.findall(S + 'Code')
    require(len({r.get('value') for r in rows}) == len(rows), 'Duplicate DSD code')
    return {r.get('value'): r for r in rows}


def ko_label(code):
    labels = [r.text for r in code.findall(S + 'Description') if r.get(KO) == 'ko']
    require(len(labels) == 1, 'Missing/ambiguous Korean DSD label')
    return labels[0]


def read_proxies(raw_path, dsd_path):
    data, dsd = ET.parse(raw_path).getroot(), ET.parse(dsd_path).getroot()
    require(data.findtext(f'{M}Header/{M}DataSetID') == '101_DT_1F02001', 'Wrong source table')
    require(dsd.find(f'.//{S}KeyFamily[@id="101_DT_1F02001"]') is not None, 'Wrong DSD table')
    for name, code, label in [('CL_A', '00', '전국'), ('CL_ITEM', 'T10', '생산지수(원지수)'),
                               ('CL_UNIT', '14101.ausgabe', '2020=100')]:
        items = code_list(dsd, name)
        require(set(items) == {code} and ko_label(items[code]) == label, 'Wrong selection: ' + name)
    industries = code_list(dsd, 'CL_B')
    require(set(industries) == set(PROXIES), 'Unexpected industry selection')
    for code, (label, parent) in PROXIES.items():
        require(ko_label(industries[code]) == label and industries[code].get('parentCode') == parent,
                'Industry name/parent mismatch')
    rows, seen = [], set()
    for series in data.findall(f'.//{G}Series'):
        keys = {r.get('concept'): r.get('value') for r in series.findall(f'{G}SeriesKey/{G}Value')}
        code = keys.get('B')
        require(code in PROXIES and code not in seen, 'Wrong/duplicate industry series')
        require(keys == {'FREQ': 'M', 'A': '00', 'B': code}, 'Wrong region/frequency/dimensions')
        seen.add(code)
        current = []
        for obs in series.findall(G + 'Obs'):
            time = obs.findtext(G + 'Time')
            require(time is not None and len(time) == 6 and time.isdigit(), 'Invalid monthly time')
            period = time[:4] + '-' + time[4:]
            # shift parses month validity and preserves the canonical monthly key.
            require(shift(period, 0) == period, 'Invalid month')
            value = float(obs.find(G + 'ObsValue').get('value'))
            require(math.isfinite(value) and value > 0, 'Missing/nonfinite/nonpositive index')
            current.append({'industry_code': code, 'industry_name': PROXIES[code][0],
                            'parent_code': PROXIES[code][1], 'period': period, 'value': value,
                            'org_id': '101', 'table_id': 'DT_1F02001', 'region_code': '00',
                            'item_id': 'T10', 'unit': '2020=100', 'source': SOURCE,
                            'publication_date': None, 'available_at': None,
                            'vintage_verified_for_origin': False,
                            'provisional_ui_flag': period in ('2026-08', '2026-09'),
                            'provisional_flag_basis': 'KOSIS selected table p) column labels',
                            'data_extracted_at_raw': data.findtext(f'{M}Header/{M}Extracted'),
                            'header_timezone_verified': False, 'table_updated_on_ui': '2026-10-30',
                            'analysis_kind': LABEL})
        consecutive([r['period'] for r in current])
        rows.extend(current)
    require(seen == set(PROXIES), 'Missing expected industry series')
    # GenericData lacks ITEM/UNIT; singleton DSD + unchanged UI selection is required.
    return sorted(rows, key=lambda r: (r['industry_code'], r['period']))


def pair_stats(series, left, right, excluded=()):
    months = sorted((set(series[left]) & set(series[right])) - set(excluded))
    levels = [(series[left][t], series[right][t]) for t in months]
    growth = [(100 * (series[left][t] / series[left][shift(t, -12)] - 1),
               100 * (series[right][t] / series[right][shift(t, -12)] - 1))
              for t in months if shift(t, -12) in series[left] and shift(t, -12) in series[right]]
    return {'left': left, 'right': right, 'first': months[0] if months else None,
            'last': months[-1] if months else None, 'original_index': correlation(levels),
            'yoy_percent': correlation(growth)}


def summarize(rows):
    series = {}
    for row in rows:
        values = series.setdefault(row['industry_code'], {})
        require(row['period'] not in values, 'Duplicate industry/month')
        values[row['period']] = row['value']
    require(set(series) == {'C30', *PROXIES}, 'Incomplete candidate set')
    quality = {}
    for code, values in series.items():
        consecutive(list(values))
        require(all(math.isfinite(v) and v > 0 for v in values.values()), 'Invalid index')
        months = sorted(values)
        growth = [100 * (values[t] / values[shift(t, -12)] - 1) for t in months if shift(t, -12) in values]
        quality[code] = {'rows': len(months), 'first': months[0], 'last': months[-1],
                         'missing_months': 0, 'duplicate_months': 0, 'invalid_values': 0,
                         'original_index_mean': statistics.mean(values.values()),
                         'original_index_sample_sd': statistics.stdev(values.values()) if len(values) > 1 else None,
                         'yoy_n': len(growth), 'yoy_mean_pct': statistics.mean(growth) if growth else None,
                         'yoy_sample_sd_pp': statistics.stdev(growth) if len(growth) > 1 else None,
                         'provisional_rows': sum(r['provisional_ui_flag'] for r in rows if r['industry_code'] == code),
                         'year_counts': {year: sum(t.startswith(year) for t in months) for year in sorted({t[:4] for t in months})}}
    pairs = [('C30', 'C222'), ('C30', 'C303'), ('C222', 'C303')]
    years = sorted({t[:4] for t in series['C30']})
    annual = []
    for year in years:
        excluded = {t for values in series.values() for t in values if not t.startswith(year)}
        annual.extend({'year': year, **pair_stats(series, left, right, excluded)} for left, right in pairs[:2])
    return {'experiment': LABEL, 'strict_gate_status': 'NO_VERIFIED_BACKTEST',
            'historical_release_vintage_verified': False, 'checked_on': '2026-11-03',
            'quality': quality, 'pairs_all_months': [pair_stats(series, a, b) for a, b in pairs],
            'pairs_exclude_provisional_targets': [pair_stats(series, a, b, ('2026-08', '2026-09')) for a, b in pairs],
            'per_year': annual,
            'warning': 'Same-month realized activity only, not forecast inputs or customer PC/ABS consumption; C303 is a C30 component'}


def main():
    raw, dsd = OUT / 'industry_generic.xml', OUT / 'industry_dsd.xml'
    old_raw, old_dsd = C30_DIR / 'production_generic.xml', C30_DIR / 'production_dsd.xml'
    old_manifest = json.loads((C30_DIR / 'input_manifest.json').read_text(encoding='utf-8'))
    old_hashes = {r['file'].replace('\\', '/').split('/')[-1]: r['sha256'] for r in old_manifest}
    require(all(hashlib.sha256(p.read_bytes()).hexdigest() == old_hashes[p.name] for p in (old_raw, old_dsd)),
            'Existing C30 snapshot changed')
    rows = read_proxies(raw, dsd)
    rows.extend(read_production(old_raw, old_dsd))
    summary = summarize(rows)
    require(all(q['rows'] == 57 and q['first'] == '2022-01' and q['last'] == '2026-09'
                for q in summary['quality'].values()), 'Requested 57-month window not complete')
    manifest = [{'file': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size,
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (raw, dsd, old_raw, old_dsd)]
    summary['input_manifest'] = manifest
    indexed = {code: {r['period']: r['value'] for r in rows if r['industry_code'] == code}
               for code in ('C30', 'C222', 'C303')}
    common = sorted(set.intersection(*(set(values) for values in indexed.values())))
    aligned = [{'period': t, 'original_index': {code: values[t] for code, values in indexed.items()},
                'yoy_percent': {code: 100 * (values[t] / values[shift(t, -12)] - 1)
                                if shift(t, -12) in values else None for code, values in indexed.items()},
                'use': 'same_month_exploration_only_not_forecast_inputs'} for t in common]
    for name, data in [('normalized_series.json', rows), ('aligned_panel.json', aligned), ('summary.json', summary)]:
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
