"""One-shot local shadow lock of two fixed rolling means. No scoring or network."""
import argparse
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

from analyze_round08 import G, LOCAL, ROOT, require, shift
from analyze_round09 import read_proxies

KST = timezone(timedelta(hours=9))
OUT = LOCAL / 'round13_shadow_lock'
TARGETS = ('2026-10', '2026-11')
INDUSTRIES = ('C222', 'C303')
MODELS = ('rolling_yoy_mean_6', 'rolling_yoy_mean_12')
BASE = 'work/data/local_only/round09_industry/'
RAW, DSD, PRIOR = (BASE + name for name in ('industry_generic.xml', 'industry_dsd.xml', 'summary.json'))
PLAN = 'work/research/ROUND_13_SHADOW_PROSPECTIVE_PLAN.md'
SOURCES = ('work/research/round13_shadow_forecast_lock.py', 'work/research/test_round13_shadow_forecast_lock.py',
           'work/research/analyze_round08.py', 'work/research/analyze_round09.py',
           'work/research/test_round09.py', 'work/research/experiment_round12b_recent_bias.py', PLAN)
ROUND10_SHA = 'a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7'
ROUND10_TREE = 'f667fd1a5226e546b5867225ff68c9b3dac2c6b041a0e6b4d7e9e92d3ad14e3a'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(folder):
    require(folder.is_dir(), 'Missing protected directory')
    return {p.relative_to(folder).as_posix(): digest(p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file()}


def round10_guard():
    files = tree(LOCAL / 'round10_prospective')
    # Preserve the earlier tree encoding exactly; never load/score its forecasts.
    encoded = json.dumps(files, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8') + b'\n'
    require(len(files) == 22 and digest(encoded) == ROUND10_TREE and ROUND10_SHA in files.values(), 'Round10 integrity failure')
    return {'files': 22, 'tree_sha256': ROUND10_TREE, 'forecast_sha256': ROUND10_SHA, 'unchanged': True}


def protected_snapshot():
    result = {}
    for base in (LOCAL, ROOT / 'outputs', ROOT / 'work/prototype', ROOT / 'work/reviews'):
        for path in sorted(base.rglob('*')):
            if path.is_file() and OUT not in path.parents and '__pycache__' not in path.parts:
                require(not path.is_symlink(), 'Protected symlink rejected')
                result[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    return result


def origin_check(origin):
    require(isinstance(origin, datetime) and origin.tzinfo is not None
            and origin.utcoffset() == timedelta(hours=9) and origin.strftime('%Y-%m-%d') == '2026-11-04',
            'Protocol requires actual November 4 KST origin; no backdating')


def precheck_production(raw):
    times = [n.text for n in ET.fromstring(raw).findall(f'.//{G}Obs/{G}Time')]
    require(bool(times), 'Missing production observations')
    for time in times:
        require(isinstance(time, str) and re.fullmatch(r'\d{6}', time) is not None, 'Invalid production month')
        month = time[:4] + '-' + time[4:]
        require(shift(month, 0) == month and month <= '2026-09', 'Target/future production present: stop before values')
    require(max(times) == '202609', 'Expected production through September only')


def load_from_blobs(blobs):
    expected = {r['file'].replace('\\', '/'): r['sha256'] for r in json.loads(blobs[PRIOR])['input_manifest']}
    require(all(digest(blobs[name]) == expected[name] for name in (RAW, DSD)), 'Production source hash mismatch')
    precheck_production(blobs[RAW])
    return read_proxies(BytesIO(blobs[RAW]), BytesIO(blobs[DSD]))


def make_forecasts(production, origin):
    origin_check(origin)
    values = {code: {} for code in INDUSTRIES}
    # Inspect all month labels before consuming any numeric production value.
    for row in production:
        require(row['industry_code'] in INDUSTRIES, 'Wrong industry')
        month = row['period']
        require(isinstance(month, str) and len(month) == 7 and shift(month, 0) == month
                and month <= '2026-09', 'Target/future/invalid production month')
    for row in production:
        require((row['org_id'], row['table_id'], row['region_code'], row['item_id'], row['unit']) ==
                ('101', 'DT_1F02001', '00', 'T10', '2020=100'), 'Wrong production selection')
        current = values[row['industry_code']]
        require(row['period'] not in current and math.isfinite(row['value']) and row['value'] > 0, 'Duplicate/invalid index or denominator')
        current[row['period']] = row['value']
    forecasts, audits = [], []
    for code, series in values.items():
        require(sorted(series) == [shift('2022-01', i) for i in range(57)], 'Incomplete 57-month production')
        require({r['period'] for r in production if r['industry_code'] == code and r['provisional_ui_flag']}
                == {'2026-08', '2026-09'}, 'Unexpected provisional metadata')
        for target in TARGETS:
            cutoff = shift(target, -2)
            common = [shift('2023-12', i) for i in range(34) if shift('2023-12', i) <= cutoff]
            for size in (6, 12):
                months = common[-size:]
                require(len(months) == size and months == [shift(cutoff, i - size + 1) for i in range(size)], 'Wrong rolling window')
                # Only lagged training Y, never calculate target Y or load target P.
                training = [100 * (series[t] / series[shift(t, -12)] - 1) for t in months]
                prediction = statistics.mean(training)  # Same fixed definition as Round12-B.
                independent = math.fsum(100 * (series[t] - series[shift(t, -12)]) / series[shift(t, -12)] for t in months) / size
                require(math.isfinite(prediction) and math.isclose(prediction, independent, rel_tol=1e-10, abs_tol=1e-10),
                        'Independent rolling arithmetic mismatch')
                model = f'rolling_yoy_mean_{size}'
                forecasts.append({'industry_code': code, 'target': target, 'model': model,
                                  'predicted_production_yoy_pct': prediction, 'unit': 'percent_YoY',
                                  'forecast_type': 'nowcast_of_past_month_activity' if target == '2026-10' else 'within_month_forecast'})
                audits.append({'industry_code': code, 'target': target, 'model': model, 'cutoff': cutoff,
                               'common_train_months': common, 'common_train_n': len(common), 'rolling_months': months,
                               'rolling_n': size, 'input_provisional_months_used': [t for t in months if t >= '2026-08'],
                               'independent_arithmetic': 'PASS'})
    require(len(forecasts) == len({(r['industry_code'], r['target'], r['model']) for r in forecasts}) == 8, 'Expected eight unique forecasts')
    return forecasts, audits


def safe_path(folder, relative):
    part = Path(relative)
    require(isinstance(relative, str) and not part.is_absolute() and '..' not in part.parts
            and not part.drive and (folder / part).resolve().is_relative_to(folder.resolve()), 'Unsafe sealed path')
    return folder / part


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())


def write_lock(folder, payload, blobs):
    require(payload['input_manifest'] == [{'path': name, 'bytes': len(raw), 'sha256': digest(raw)}
                                         for name, raw in sorted(blobs.items())], 'Manifest/blob mismatch')
    for name in blobs:
        safe_path(folder / 'sealed_inputs', name)
    folder.mkdir(parents=True, exist_ok=False)  # No overwrite/resume/force/re-lock.
    for name, raw in blobs.items():
        write_new(safe_path(folder / 'sealed_inputs', name), raw)
    raw = canonical(payload)
    for name, content in {'forecasts.canonical.json': raw, 'forecasts.sha256': (digest(raw) + '\n').encode(),
                          'input_manifest.json': canonical(payload['input_manifest']),
                          'model_params.json': canonical(payload['training_audit'])}.items():
        write_new(folder / name, content)
    return digest(raw)


def verify_lock(folder, expected_sha):
    require(isinstance(expected_sha, str) and re.fullmatch(r'[0-9a-f]{64}', expected_sha), 'Explicit public digest required')
    require(not any(p.is_symlink() for p in [folder, *folder.rglob('*')]), 'Sealed symlink rejected')
    raw = (folder / 'forecasts.canonical.json').read_bytes()
    require(digest(raw) == expected_sha == (folder / 'forecasts.sha256').read_text().strip(), 'Forecast digest mismatch')
    payload = json.loads(raw)
    require(canonical(payload) == raw, 'Noncanonical payload')
    require((folder / 'input_manifest.json').read_bytes() == canonical(payload['input_manifest'])
            and (folder / 'model_params.json').read_bytes() == canonical(payload['training_audit']), 'Metadata changed')
    blobs = {}
    for row in payload['input_manifest']:
        require(row['path'] not in blobs, 'Duplicate manifest path')
        data = safe_path(folder / 'sealed_inputs', row['path']).read_bytes()
        require(digest(data) == row['sha256'] and len(data) == row['bytes'], 'Sealed input changed')
        blobs[row['path']] = data
    expected_files = {'forecasts.canonical.json', 'forecasts.sha256', 'input_manifest.json', 'model_params.json'}
    expected_files |= {'sealed_inputs/' + name for name in blobs}
    require(set(tree(folder)) == expected_files, 'Extra/missing lock files')
    forecasts, audits = make_forecasts(load_from_blobs(blobs), datetime.fromisoformat(payload['origin_kst']))
    require(forecasts == payload['forecasts'] and audits == payload['training_audit'], 'Sealed forecast replay mismatch')
    require(payload['performance_evaluation'] == 'NOT_PERFORMED_NO_ACTUALS', 'Scoring outside protocol')
    return {'status': 'SHADOW_LOCK_HASH_INPUTS_AND_REPLAY_VERIFIED', 'forecast_sha256': expected_sha,
            'forecast_count': len(forecasts), 'input_files': len(blobs), 'origin_kst': payload['origin_kst'],
            'source_commit_sha': payload['source_commit_sha'], 'last_production_month': '2026-09',
            'target_production_absent': True, 'independent_arithmetic_count': 8,
            'performance_evaluation': payload['performance_evaluation']}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def source_check(expected):
    require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{40}', expected), 'Explicit source commit required')
    require(git('rev-parse', 'HEAD') == expected == git('rev-parse', 'origin/main'), 'Push source commit before locking')
    git('ls-files', '--error-unmatch', '--', *SOURCES)
    require(subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *SOURCES], cwd=ROOT).returncode == 0,
            'Commit source/plan/tests before lock')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--lock', action='store_true')
    mode.add_argument('--verify', action='store_true')
    parser.add_argument('--expected-source-commit')
    parser.add_argument('--expected-sha256')
    args = parser.parse_args(argv)
    if args.verify:
        print(json.dumps(verify_lock(OUT, args.expected_sha256), indent=2))
        return
    require(not OUT.exists(), 'Shadow lock already exists; regeneration forbidden')
    source_check(args.expected_source_commit)
    origin = datetime.now(KST)  # No clock/origin override argument.
    origin_check(origin)
    protected = protected_snapshot()
    prior_lock = round10_guard()
    blobs = {name: (ROOT / name).read_bytes() for name in (RAW, DSD, PRIOR)}
    forecasts, audit = make_forecasts(load_from_blobs(blobs), origin)
    for name in SOURCES:
        blobs[name] = (ROOT / name).read_bytes()
    blobs['evidence/protected_files_before.json'] = canonical(protected)
    blobs['evidence/round10_integrity.json'] = canonical(prior_lock)
    source_check(args.expected_source_commit)
    require(protected_snapshot() == protected and round10_guard() == prior_lock, 'Protected files changed before lock')
    payload = {'experiment': 'SEPARATE_SHADOW_FORECAST_LOCK', 'origin_kst': origin.isoformat(timespec='microseconds'),
               'origin_utc': origin.astimezone(timezone.utc).isoformat(timespec='microseconds'),
               'generated_at_kst': datetime.now(KST).isoformat(timespec='microseconds'),
               'source_commit_sha': args.expected_source_commit, 'plan_git_blob_sha': git('rev-parse', args.expected_source_commit + ':' + PLAN),
               'plan_sha256': digest(blobs[PLAN]), 'plan_registration_commit_sha': git('rev-parse', 'a3c2821'),
               'config': {'industries': INDUSTRIES, 'targets': TARGETS, 'models': MODELS,
                          'cutoff': 'target_minus_2_inclusive', 'common_train_start': '2023-12', 'windows': [6, 12],
                          'target': '100*(P_t/P_(t-12)-1)', 'BSI_used': False, 'tuning': False},
               'input_manifest': [{'path': name, 'bytes': len(data), 'sha256': digest(data)} for name, data in sorted(blobs.items())],
               'input_production_range': ['2022-01', '2026-09'], 'input_rows_per_industry': 57,
               'target_production_absent': True, 'external_release_check': 'NOT_VERIFIED_NO_NEW_DATA_QUERY',
               'clock_attestation': 'LOCAL_SYSTEM_CLOCK_NOT_TRUSTED_TIMESTAMP_AUTHORITY',
               'strict_historical_gate': 'NO_VERIFIED_BACKTEST', 'historical_vintages_verified': False,
               'performance_evaluation': 'NOT_PERFORMED_NO_ACTUALS', 'round10_integrity': prior_lock,
               'protected_file_count': len(protected), 'training_audit': audit, 'forecasts': forecasts,
               'evaluation_protocol': 'Separate future action: first official release, numerator and denominator same vintage; revised scores separately; never regenerate locks'}
    sha = write_lock(OUT, payload, blobs)
    result = verify_lock(OUT, sha)
    require(protected_snapshot() == protected and round10_guard() == prior_lock, 'Protected files changed after lock')
    print(json.dumps({**result, 'protected_files_unchanged': len(protected), 'round10_integrity': prior_lock}, indent=2))


if __name__ == '__main__':
    main()
