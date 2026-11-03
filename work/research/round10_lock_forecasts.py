"""One-time prospective forecast lock from existing local snapshots; no network."""
import argparse
import hashlib
import json
import math
import statistics
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

from analyze_round08 import G, LOCAL, ROOT, consecutive, require, shift
from analyze_round09 import read_proxies
from experiment_round08b_hindsight import ols

OUT = LOCAL / 'round10_prospective'
TARGETS = ('2026-10', '2026-11')
MAPPING = {'C303': 'C3000', 'C222': 'C0000'}
SECTORS = {'C3000': 'automobile', 'C0000': 'manufacturing'}
KST = timezone(timedelta(hours=9))
LABEL = 'PROSPECTIVE_LOCK_OF_UNRELEASED_ACTIVITY'
SOURCE_FILES = ('work/research/round10_lock_forecasts.py', 'work/research/test_round10.py',
                'work/research/analyze_round08.py', 'work/research/analyze_round09.py',
                'work/research/experiment_round08b_hindsight.py', 'work/research/ROUND_10_PLAN.md')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def precheck_production(raw):
    """Check time labels before any production numeric values are consumed."""
    periods = [node.text for node in ET.fromstring(raw).findall(f'.//{G}Time')]
    require(bool(periods) and all(t and len(t) == 6 and t.isdigit() for t in periods), 'Invalid production time')
    require(all(t <= '202609' for t in periods), 'Target/future production present: STOP LOCK')
    require(max(periods) == '202609', 'Expected September production snapshot')


def load_inputs():
    paths = [LOCAL / 'round09_industry/industry_generic.xml', LOCAL / 'round09_industry/industry_dsd.xml',
             LOCAL / 'round07c_ecos/normalized_snapshot.json', LOCAL / 'round07_bsi/verified_sample.json',
             LOCAL / 'round07_bsi/bok_bsi_2026-09.pdf', LOCAL / 'round07_bsi/bok_bsi_2026-10_vF.pdf']
    paths += [LOCAL / f'round07c_ecos/search_512Y008_M_202312_202611_BD_{code}.json' for code in SECTORS]
    blobs = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in paths}
    precheck_production(blobs[paths[0].relative_to(ROOT).as_posix()])
    # Compare preserved snapshot manifests rather than accepting replacements.
    prior9 = json.loads((LOCAL / 'round09_industry/summary.json').read_text(encoding='utf-8'))
    hashes9 = {r['file'].replace('\\', '/'): r['sha256'] for r in prior9['input_manifest']}
    prior7 = json.loads((LOCAL / 'round07c_ecos/manifest.json').read_text(encoding='utf-8'))
    hashes7 = {r['file']: r['sha256'] for r in prior7}
    pdf_manifest_path = LOCAL / 'round07_bsi/manifest.json'
    prior_pdf = json.loads(pdf_manifest_path.read_text(encoding='utf-8'))
    pdf_hashes = {r['file']: r['sha256'] for r in prior_pdf['files']}
    for p in paths[:2]:
        require(digest(blobs[p.relative_to(ROOT).as_posix()]) == hashes9[p.relative_to(ROOT).as_posix()], 'Production hash mismatch')
    for p in [paths[2], *paths[6:]]:
        require(digest(blobs[p.relative_to(ROOT).as_posix()]) == hashes7[p.name], 'BSI snapshot hash mismatch')
    for p in paths[3:6]:
        require(digest(blobs[p.relative_to(ROOT).as_posix()]) == pdf_hashes[p.name], 'Prior PDF/evidence hash mismatch')
    for p in [LOCAL / 'round09_industry/summary.json', LOCAL / 'round09_industry/source_observations.json',
              LOCAL / 'round07c_ecos/manifest.json', pdf_manifest_path]:
        blobs[p.relative_to(ROOT).as_posix()] = p.read_bytes()
    # Parse the bytes that were checked, not a second mutable disk read.
    from io import BytesIO
    production = read_proxies(BytesIO(blobs[paths[0].relative_to(ROOT).as_posix()]),
                              BytesIO(blobs[paths[1].relative_to(ROOT).as_posix()]))
    require(len(production) == 114, 'Expected two 57-month production series')
    bsi_rows = json.loads(blobs[paths[2].relative_to(ROOT).as_posix()])
    samples = json.loads(blobs[paths[3].relative_to(ROOT).as_posix()])
    bsi = {}
    for code, sector in SECTORS.items():
        rows = [r for r in bsi_rows if r['sector'] == sector]
        require(len(rows) == 36, 'Expected 36 BSI observations')
        consecutive([r['forecast_target_month'] for r in rows])
        bsi[code] = {}
        for row in rows:
            month = row['forecast_target_month']
            require((row['table_code'], row['item_code1'], row['item_code2']) == ('512Y008', 'BD', code), 'Wrong BSI mapping')
            require(row['survey_month'] == shift(month, -1), 'Survey/forecast month mismatch')
            require(math.isfinite(row['value']) and 0 <= row['value'] <= 200, 'Invalid BSI value')
            bsi[code][month] = row
        raw = json.loads(blobs[paths[6 + list(SECTORS).index(code)].relative_to(ROOT).as_posix()])
        observations = [r for page in raw['pages'] for r in page['response']['StatisticSearch']['row']]
        require(len(observations) == 36 and len({r['TIME'] for r in observations}) == 36, 'Raw BSI count/duplicate error')
        for row in observations:
            month = row['TIME'][:4] + '-' + row['TIME'][4:]
            require((row['STAT_CODE'], row['ITEM_CODE1'], row['ITEM_CODE2']) == ('512Y008', 'BD', code), 'Wrong raw BSI codes')
            require(float(row['DATA_VALUE']) == bsi[code][month]['value'], 'Raw/normalized BSI mismatch')
    evidence = []
    for code, sector in SECTORS.items():
        for target in TARGETS:
            matches = [r for r in samples if r['sector'] == sector and r['forecast_target_month'] == target]
            require(len(matches) == 1, 'Missing/duplicate prior PDF evidence')
            sample, row = matches[0], bsi[code][target]
            require(sample['value'] == row['value'] and sample['publication_date'] == row['publication_date']
                    and sample['available_at'] == row['available_at'], 'PDF evidence/BSI mismatch')
            require(sample['classification'] == ('KSIC-11' if target == '2026-11' else 'KSIC-10'), 'Wrong BSI regime evidence')
            require(row['sample_break_at_target_month'] == (target == '2026-11'), 'Missing sample-break flag')
            evidence.append({'bsi_code': code, 'target': target, 'publication_date': sample['publication_date'],
                             'available_at_policy': sample['available_at'], 'pdf': sample['source_pdf'],
                             'pdf_page': sample['pdf_physical_page'], 'value_match': True,
                             'evidence_method': 'prior visually checked PDF transcription, rechecked against preserved API snapshot'})
    return production, bsi, blobs, evidence


def make_forecasts(production, bsi, origin):
    require(origin.tzinfo is not None, 'Origin requires timezone')
    require(origin.astimezone(KST).strftime('%Y-%m-%d') == '2026-11-03', 'Protocol requires actual November 3 origin; no backdating')
    p = {code: {} for code in MAPPING}
    for row in production:
        code, month = row['industry_code'], row['period']
        require(code in p and month not in p[code], 'Wrong/duplicate production row')
        require(month <= '2026-09', 'Target/future production present')
        require(math.isfinite(row['value']) and row['value'] > 0, 'Invalid production value')
        p[code][month] = row['value']
    forecasts, audits = [], []
    for code, bsi_code in MAPPING.items():
        require(bool(p[code]) and max(p[code]) == '2026-09', 'Wrong last production month')
        for target in TARGETS:
            require(target not in p[code], 'Target production already available')
            cutoff = shift(target, -2)
            require(target in bsi.get(bsi_code, {}), 'Missing mapped target BSI')
            current = bsi[bsi_code][target]
            require(current['survey_month'] == shift(target, -1), 'Wrong target BSI survey month')
            require(datetime.fromisoformat(current['available_at']) <= origin, 'Target BSI not available at execution')
            months = sorted(t for t in bsi[bsi_code] if t in p[code] and t <= cutoff)
            require(len(months) >= 12, 'Insufficient common training data')
            consecutive(months)
            require(all(shift(t, -12) in p[code] for t in months) and shift(target, -12) in p[code], 'Missing YoY denominator')
            xs = [bsi[bsi_code][t]['value'] for t in months]
            ys = [100 * (p[code][t] / p[code][shift(t, -12)] - 1) for t in months]
            intercept, slope = ols(xs, ys)
            values = {'seasonal_naive': 0.0, 'past_yoy_mean': statistics.mean(ys),
                      'bsi_ols': intercept + slope * current['value']}
            require(all(math.isfinite(v) for v in values.values()), 'Invalid forecast')
            audit = {'industry_code': code, 'target': target, 'bsi_code': bsi_code,
                     'cutoff': cutoff, 'train_months': months, 'train_n': len(months),
                     'intercept': intercept, 'slope': slope, 'target_bsi_value': current['value'],
                     'target_bsi_outside_training_range': not min(xs) <= current['value'] <= max(xs),
                     'target_bsi_post_sample_break': target == '2026-11',
                     'training_post_break_rows': sum(t >= '2026-11' for t in months)}
            audits.append(audit)
            for model, prediction in values.items():
                forecasts.append({'industry_code': code, 'target': target, 'model': model,
                                  'predicted_production_yoy_pct': prediction, 'bsi_code': bsi_code,
                                  'target_survey_month': current['survey_month'],
                                  'forecast_type': 'nowcast_of_unreleased_activity' if target == '2026-10' else 'within_month_prospective_forecast',
                                  'bsi_post_sample_break': target == '2026-11'})
    require(len(forecasts) == len({(r['industry_code'], r['target'], r['model']) for r in forecasts}) == 12, 'Expected 12 unique forecasts')
    return forecasts, audits


def write_lock(folder, payload, blobs):
    # Exclusive directory/file creation: no overwrite, resume, force or re-lock mode.
    folder.mkdir(parents=True, exist_ok=False)
    for relative, raw in blobs.items():
        path = Path(relative)
        require(not path.is_absolute() and '..' not in path.parts, 'Unsafe sealed input path')
        target = folder / 'sealed_inputs' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as file:
            file.write(raw)
    raw = canonical(payload)
    sha = digest(raw)
    files = {'forecasts.canonical.json': raw, 'forecasts.sha256': (sha + '\n').encode('ascii'),
             'input_manifest.json': canonical(payload['input_manifest']),
             'model_params.json': canonical(payload['training_audit'])}
    for name, content in files.items():
        with (folder / name).open('xb') as file:
            file.write(content)
    return sha


def verify_lock(folder, expected_sha):
    raw = (folder / 'forecasts.canonical.json').read_bytes()
    require(digest(raw) == expected_sha == (folder / 'forecasts.sha256').read_text().strip(), 'Forecast digest mismatch')
    payload = json.loads(raw)
    require(canonical(payload) == raw, 'Noncanonical forecast JSON')
    require(len(payload['forecasts']) == 12, 'Unexpected forecast count')
    require(json.loads((folder / 'model_params.json').read_bytes()) == payload['training_audit'], 'Model params changed')
    require(json.loads((folder / 'input_manifest.json').read_bytes()) == payload['input_manifest'], 'Input manifest changed')
    for row in payload['input_manifest']:
        path = Path(row['path'])
        require(not path.is_absolute() and '..' not in path.parts, 'Unsafe manifest path')
        require(digest((folder / 'sealed_inputs' / path).read_bytes()) == row['sha256'], 'Sealed input changed')
    return {'forecast_sha256': expected_sha, 'forecast_count': len(payload['forecasts']),
            'origin_kst': payload['origin_kst'], 'generated_at_kst': payload['generated_at_kst'],
            'source_commit_sha': payload['source_commit_sha'], 'input_files': len(payload['input_manifest']),
            'status': 'LOCK_HASH_AND_SEALED_INPUTS_VERIFIED', 'performance_evaluation': 'NOT_PERFORMED_NO_ACTUALS'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--lock', action='store_true')
    mode.add_argument('--verify', action='store_true')
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    if args.verify:
        require(bool(args.expected_sha256), 'Use the digest published in the GitHub report')
        print(json.dumps(verify_lock(OUT, args.expected_sha256), indent=2))
        return
    require(not OUT.exists(), 'Lock already exists: refusing to regenerate')
    origin = datetime.now(KST)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    subprocess.run(['git', 'ls-files', '--error-unmatch', '--', *SOURCE_FILES], cwd=ROOT, check=True, capture_output=True)
    require(subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *SOURCE_FILES], cwd=ROOT).returncode == 0,
            'Commit source/config/tests before locking')
    production, bsi, blobs, evidence = load_inputs()
    forecasts, audit = make_forecasts(production, bsi, origin)
    for relative in SOURCE_FILES:
        blobs[relative] = (ROOT / relative).read_bytes()
    manifest = [{'path': path, 'bytes': len(raw), 'sha256': digest(raw)} for path, raw in sorted(blobs.items())]
    payload = {'experiment': LABEL, 'origin_kst': origin.isoformat(timespec='microseconds'),
               'origin_utc': origin.astimezone(timezone.utc).isoformat(timespec='microseconds'),
               'generated_at_kst': datetime.now(KST).isoformat(timespec='microseconds'),
               'source_commit_sha': commit, 'input_manifest': manifest, 'target_bsi_publication_evidence': evidence,
               'last_production_month': '2026-09', 'target_production_absent': True,
               'config': {'mapping': MAPPING, 'targets': TARGETS, 'cutoff': 't_minus_2_inclusive',
                          'minimum_training_rows': 12, 'training': 'all_common_target_months_through_cutoff',
                          'models': ['seasonal_naive', 'past_yoy_mean', 'bsi_ols_with_intercept'],
                          'target': '100*(production_t/production_t_minus_12-1)',
                          'forecast_unit': 'percent_YoY', 'tuning': False, 'clipping': False},
               'historical_vintages_verified': False, 'strict_historical_gate': 'NO_VERIFIED_BACKTEST',
               'performance_evaluation': 'NOT_PERFORMED_NO_ACTUALS',
               'evaluation_protocol': 'First official target-month release; archive contemporaneous numerator/denominator and release metadata; score frozen forecasts only; revised vintages separately',
               'training_audit': audit, 'forecasts': forecasts}
    sha = write_lock(OUT, payload, blobs)
    print(json.dumps(verify_lock(OUT, sha), indent=2))


if __name__ == '__main__':
    main()
