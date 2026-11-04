"""Explicit one-shot ECOS collection/diff CLI. No training, scheduler or LLM."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collect_round07c_ecos import ROOT, local_key

STORE = ROOT / 'work/data/local_only/round11_snapshots'
BASELINE = ROOT / 'work/data/local_only/round07c_ecos/normalized_snapshot.json'
BASE_MANIFEST = BASELINE.parent / 'manifest.json'
LOCK = ROOT / 'work/data/local_only/round10_prospective'
LOCK_SHA = 'a1ffff49a5e39c89be5989bfb45387fece6e010a6de611ea8cfa4a48238f36b7'
SECTORS = {'C3000': '자동차', 'C0000': '제조업'}
SOURCE = 'https://ecos.bok.or.kr/api/'
KINDS = ('UNCHANGED', 'NEW_TARGET_MONTH', 'HISTORICAL_VALUE_CHANGED',
         'MISSING_OR_REMOVED', 'INVALID_OR_UNVERIFIED', 'OUTSIDE_QUERY_WINDOW')
KST = timezone(timedelta(hours=9))


class PipelineError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PipelineError('REDIRECT_REJECTED')


urlopen = build_opener(NoRedirect()).open


def check(condition, code):
    if not condition:
        raise PipelineError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode('utf-8') + b'\n'


def now():
    return datetime.now(KST).isoformat(timespec='microseconds')


def month(value):
    check(isinstance(value, str) and re.fullmatch(r'\d{6}', value) is not None, 'INVALID_MONTH')
    try:
        return datetime.strptime(value, '%Y%m').strftime('%Y-%m')
    except ValueError:
        raise PipelineError('INVALID_MONTH') from None


def shift(value, delta):
    date = datetime.strptime(value, '%Y-%m')
    number = date.year * 12 + date.month - 1 + delta
    return f'{number // 12:04}-{number % 12 + 1:02}'


def number(value):
    try:
        check(isinstance(value, (str, int, float)) and not isinstance(value, bool), 'INVALID_VALUE')
        result = Decimal(str(value))
        check(result.is_finite() and 0 <= result <= 200, 'INVALID_VALUE')
        return str(result.normalize())
    except (InvalidOperation, ValueError):
        raise PipelineError('INVALID_VALUE') from None


def safe_path(folder, relative):
    path = Path(relative)
    check(not path.is_absolute() and '..' not in path.parts, 'UNSAFE_ARCHIVE_PATH')
    target = folder / path
    check(target.resolve().is_relative_to(folder.resolve()), 'UNSAFE_ARCHIVE_PATH')
    return target


def save(folder, relative, raw, files, kind):
    path = safe_path(folder, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as file:
        file.write(raw)
    files.append({'path': relative, 'sha256': sha(raw), 'bytes': len(raw), 'kind': kind})


def guard():
    paths = sorted(p for p in LOCK.rglob('*') if p.is_file())
    check(bool(paths), 'ROUND10_LOCK_MISSING')
    fingerprint = {p.relative_to(LOCK).as_posix(): sha(p.read_bytes()) for p in paths}
    check(fingerprint.get('forecasts.canonical.json') == LOCK_SHA, 'ROUND10_FORECAST_HASH_MISMATCH')
    return {'forecast_sha256': LOCK_SHA, 'file_count': len(fingerprint), 'tree_sha256': sha(encoded(fingerprint))}


def fetch(service, params, key, folder, files, requests, page_size):
    rows, first, total = [], 1, None
    while total is None or first <= total:
        last = first + page_size - 1 if total is None else min(first + page_size - 1, total)
        url = SOURCE + '/'.join(quote(str(p), safe='') for p in [service, key, 'json', 'kr', first, last, *params])
        started = now()
        try:
            with urlopen(Request(url), timeout=30) as response:
                check(response.status == 200, 'HTTP_NOT_OK')
                raw = response.read()
        except PipelineError:
            raise
        except Exception:
            raise PipelineError('NETWORK_OR_HTTP_ERROR_REDACTED') from None
        received = now()
        # Some error bodies may echo the URL. Never archive such a response.
        variants = {key, quote(key, safe=''), quote(quote(key, safe=''), safe='')}
        check(not any(v.encode().lower() in raw.lower() for v in variants if v), 'CREDENTIAL_RESPONSE_BLOCKED')
        sector = params[-1] if service == 'StatisticSearch' else 'metadata'
        relative = f'raw/{service}_{sector}_{first:06}_{last:06}.json'
        save(folder, relative, raw, files, 'api_raw')
        requests.append({'service': service, 'parameters_without_key': params, 'start': first, 'end': last,
                         'request_started_at': started, 'observed_at': received, 'http_status': 200,
                         'raw_path': relative, 'raw_sha256': sha(raw)})
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise PipelineError('NON_JSON_RESPONSE') from None
        check(isinstance(body, dict), 'INVALID_RESPONSE_SHAPE')
        if service not in body:
            # Do not print server MESSAGE, URL or arbitrary error codes.
            code = body.get('RESULT', {}).get('CODE', '') if isinstance(body.get('RESULT'), dict) else ''
            check(False, 'ECOS_' + code.replace('-', '_') if re.fullmatch(r'(ERROR|INFO)-\d{3}', str(code)) else 'ECOS_RESPONSE_REJECTED')
        block = body[service]
        check(isinstance(block, dict), 'INVALID_RESPONSE_SHAPE')
        try:
            count = int(block['list_total_count'])
        except (ValueError, TypeError, KeyError):
            raise PipelineError('INVALID_PAGE_TOTAL') from None
        page = block.get('row', [])
        check(0 <= count <= 20000 and isinstance(page, list), 'INVALID_PAGE_SHAPE')
        check(total is None or total == count, 'PAGE_TOTAL_CHANGED')
        total = count
        check(len(page) == max(0, min(last, total) - first + 1), 'PAGE_ROW_COUNT_MISMATCH')
        rows.extend(page)
        first = last + 1
    check(len(rows) == total, 'PAGINATION_COUNT_MISMATCH')
    return rows


def metadata_ends(rows):
    ends = {}
    for group, code in [('Group1', 'BD'), ('Group2', 'C3000'), ('Group2', 'C0000')]:
        matches = [r for r in rows if r.get('STAT_CODE') == '512Y008' and r.get('GRP_CODE') == group
                   and r.get('ITEM_CODE') == code and r.get('CYCLE') == 'M']
        check(len(matches) == 1, 'METADATA_ITEM_MISSING_OR_DUPLICATE')
        ends[code] = month(matches[0]['END_TIME'])
    return {code: min(ends['BD'], ends[code]) for code in SECTORS}


def normalize(rows, code, observed_at, run_id):
    normalized, seen = [], set()
    for row in rows:
        check(isinstance(row, dict), 'INVALID_ROW_SHAPE')
        check((row.get('STAT_CODE'), row.get('ITEM_CODE1'), row.get('ITEM_CODE2')) == ('512Y008', 'BD', code), 'WRONG_SERIES_CODES')
        check(row.get('ITEM_CODE3') is None and row.get('ITEM_CODE4') is None, 'UNEXPECTED_EXTRA_DIMENSION')
        check('전망' in str(row.get('STAT_NAME', '')) and '신규수주' in str(row.get('ITEM_NAME1', ''))
              and '전망' in str(row.get('ITEM_NAME1', '')) and row.get('ITEM_NAME2') == SECTORS[code], 'WRONG_SERIES_LABELS')
        check(row.get('UNIT_NAME') in (None, '지수', 'index', 'Index'), 'UNVERIFIED_UNIT')
        target = month(row.get('TIME'))
        check(target not in seen, 'DUPLICATE_TARGET_MONTH')
        seen.add(target)
        normalized.append({'table_code': '512Y008', 'item_code1': 'BD', 'item_code2': code,
                           'forecast_target_month': target, 'survey_month': shift(target, -1),
                           'value': number(row.get('DATA_VALUE')), 'raw_unit_name': row.get('UNIT_NAME'),
                           'semantic_unit': 'index', 'semantic_unit_basis': 'prior BOK BSI methodology, not an invented API unit',
                           'observed_at': observed_at, 'publication_date': None, 'available_at': None,
                           'vintage_verified': False, 'snapshot_run_id': run_id, 'source': SOURCE,
                           'sample_break_at_target_month': target == '2026-11',
                           'post_2026_10_survey_reform': target >= '2026-11'})
    return sorted(normalized, key=lambda r: r['forecast_target_month'])


def baseline_rows(raw):
    source = json.loads(raw)
    rows, keys = [], set()
    for r in source:
        code, target = r['item_code2'], r['forecast_target_month']
        check(code in SECTORS and (r['table_code'], r['item_code1']) == ('512Y008', 'BD'), 'WRONG_BASELINE_CODES')
        check(month(target.replace('-', '')) == target and r['survey_month'] == shift(target, -1), 'INVALID_BASELINE_MONTH')
        check((code, target) not in keys, 'DUPLICATE_BASELINE_MONTH')
        keys.add((code, target))
        rows.append({**r, 'value': number(r['value'])})
    check(all(any(r['item_code2'] == code for r in rows) for code in SECTORS), 'INCOMPLETE_BASELINE')
    return rows


def compare(old, new, windows):
    old = {(r['item_code2'], r['forecast_target_month']): r for r in old}
    new = {(r['item_code2'], r['forecast_target_month']): r for r in new}
    events = []
    for code, target in sorted(set(old) | set(new)):
        before, after = old.get((code, target)), new.get((code, target))
        start, end = windows[code]
        if not start <= target <= end:
            kind = 'OUTSIDE_QUERY_WINDOW'
        elif after is None:
            kind = 'MISSING_OR_REMOVED'
        elif before is None:
            kind = 'NEW_TARGET_MONTH'
        else:
            kind = 'UNCHANGED' if Decimal(before['value']) == Decimal(after['value']) else 'HISTORICAL_VALUE_CHANGED'
        # Values stay in the local diff. Console/report only use counts and keys.
        events.append({'classification': kind, 'item_code2': code, 'forecast_target_month': target,
                       'old_value': before['value'] if before else None, 'new_value': after['value'] if after else None})
    return events


def validate_snapshot(old, new, windows):
    issues = []
    months = {code: sorted(r['forecast_target_month'] for r in new if r['item_code2'] == code) for code in SECTORS}
    for code, periods in months.items():
        if not periods:
            issues.append({'code': 'EMPTY_SERIES', 'item_code2': code})
        elif periods != [shift(periods[0], i) for i in range(len(periods))]:
            issues.append({'code': 'MONTHLY_GAP', 'item_code2': code})
        if any(not windows[code][0] <= t <= windows[code][1] for t in periods):
            issues.append({'code': 'OBSERVATION_OUTSIDE_REQUEST', 'item_code2': code})
    if months['C3000'] != months['C0000']:
        issues.append({'code': 'SECTOR_MONTH_RANGE_MISMATCH'})
    events = compare(old, new, windows)
    if any(e['classification'] == 'MISSING_OR_REMOVED' for e in events):
        issues.append({'code': 'BASELINE_MONTH_MISSING'})
    return events, issues


def summary(events, issues):
    counts = Counter(e['classification'] for e in events)
    counts['INVALID_OR_UNVERIFIED'] += len(issues)
    return {'counts': {k: counts[k] for k in KINDS}, 'validation_issues': issues,
            'changed_keys': [{k: e[k] for k in ('classification', 'item_code2', 'forecast_target_month')}
                             for e in events if e['classification'] != 'UNCHANGED'],
            'review_required': bool(issues or any(e['classification'] != 'UNCHANGED' for e in events)),
            'official_correction_confirmed': False, 'model_input_promoted': False}


def collect_once():
    run_id = datetime.now(KST).strftime('%Y%m%dT%H%M%S%f') + '_' + uuid.uuid4().hex[:12]
    folder = STORE / run_id
    folder.mkdir(parents=True, exist_ok=False)
    files, requests, events, issues, new, old, windows = [], [], [], [], [], [], {}
    result = {'run_id': run_id, 'started_at': now(), 'status': 'FAILED_QUARANTINED', 'source': SOURCE,
              'stat_code': '512Y008', 'item_code': 'BD', 'cycle': 'M', 'sectors': SECTORS,
              'query_strategy': 'baseline first month through max(baseline last, official metadata end)',
              'publication_date': None, 'available_at': None, 'vintage_verified': False,
              'runtime': sys.version.split()[0], 'normalization_version': 1,
              'unit_policy': 'BSI index; raw UNIT_NAME preserved including null',
              'baseline_source': BASELINE.relative_to(ROOT).as_posix(),
              'observed_at_meaning': 'Our series retrieval completion, not BOK publication or first vintage',
              'dependencies': ['Python standard library', 'collect_round07c_ecos.local_key']}
    before = None
    exit_code = 1
    try:
        before = guard()
        raw, baseline_manifest = BASELINE.read_bytes(), BASE_MANIFEST.read_bytes()
        entries = json.loads(baseline_manifest)
        expected = [r['sha256'] for r in entries if r['file'] == BASELINE.name]
        check(expected == [sha(raw)], 'BASELINE_HASH_MISMATCH')
        old = baseline_rows(raw)
        save(folder, 'baseline/normalized_snapshot.json', raw, files, 'baseline')
        save(folder, 'baseline/manifest.json', baseline_manifest, files, 'baseline_evidence')
        key = local_key()
        check(bool(key), 'LOCAL_KEY_NOT_CONFIGURED')
        ends = metadata_ends(fetch('StatisticItemList', ['512Y008'], key, folder, files, requests, 1000))
        result['metadata_reported_ends'] = ends
        for code in SECTORS:
            prior = [r['forecast_target_month'] for r in old if r['item_code2'] == code]
            start, end = min(prior), max(max(prior), ends[code])
            windows[code] = [start, end]
            rows = fetch('StatisticSearch', ['512Y008', 'M', start.replace('-', ''), end.replace('-', ''), 'BD', code],
                         key, folder, files, requests, 20)
            new.extend(normalize(rows, code, requests[-1]['observed_at'], run_id))
        events, issues = validate_snapshot(old, new, windows)
        result['status'] = 'VALIDATED_SNAPSHOT_REVIEW_NOT_PROMOTED' if not issues else 'INVALID_QUARANTINED'
        exit_code = 0 if not issues else 2
    except PipelineError as error:
        issues.append({'code': str(error)})
    except ValueError as error:
        # Existing key loader uses one specific safe message; discard all others.
        issues.append({'code': 'LOCAL_KEY_NOT_CONFIGURED' if str(error) == 'LOCAL_KEY_NOT_CONFIGURED' else 'UNEXPECTED_FAILURE_REDACTED'})
    except Exception:
        issues.append({'code': 'UNEXPECTED_FAILURE_REDACTED'})
    try:
        after = guard()
        check(before == after, 'ROUND10_LOCK_TREE_CHANGED')
        result['round10_integrity'] = {'before': before, 'after': after, 'unchanged': True}
    except Exception:
        issues.append({'code': 'ROUND10_INTEGRITY_CHECK_FAILED'})
        result['status'], exit_code = 'FAILED_QUARANTINED', 1
    if issues and exit_code == 0:
        result['status'], exit_code = 'INVALID_QUARANTINED', 2
    result.update(summary(events, issues))
    result['requests'] = requests
    result['query_windows'] = windows
    result['observed_rows'] = len(new)
    result['ranges'] = {code: {'rows': len(values), 'first': min(values) if values else None,
                              'last': max(values) if values else None}
                        for code in SECTORS
                        for values in [[r['forecast_target_month'] for r in new if r['item_code2'] == code]]}
    result['cached_pdf_reference_matches'] = sum(1 for r in old if r.get('publication_date') and
        any(n['item_code2'] == r['item_code2'] and n['forecast_target_month'] == r['forecast_target_month']
            and Decimal(n['value']) == Decimal(r['value']) for n in new))
    save(folder, 'normalized.json', encoded(new), files, 'normalized')
    save(folder, 'diff.json', encoded(events), files, 'diff')
    for relative in ('work/research/round11_ecos_snapshot_pipeline.py', 'work/research/collect_round07c_ecos.py'):
        path = ROOT / relative
        save(folder, 'source/' + path.name, path.read_bytes(), files, 'source')
    result['source_file_sha256'] = {r['path']: r['sha256'] for r in files if r['kind'] == 'source'}
    try:
        result['source_git_head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except Exception:
        result['source_git_head'] = None
    if exit_code:
        # Copy failed raw responses into explicit quarantine; never move/delete originals.
        for row in list(files):
            if row['kind'] == 'api_raw':
                save(folder, 'quarantine/' + row['path'], safe_path(folder, row['path']).read_bytes(), files, 'quarantined_raw_copy')
        save(folder, 'quarantine/review_required.json', encoded({'issues': issues, 'promotion': False}), files, 'quarantine_marker')
    result['finished_at'], result['exit_code'], result['files'] = now(), exit_code, files
    manifest = encoded(result)
    with (folder / 'manifest.json').open('xb') as file:
        file.write(manifest)
    with (folder / 'manifest.sha256').open('xb') as file:
        file.write((sha(manifest) + '\n').encode())
    return result, sha(manifest)


def validate_run(run_id, expected_sha=None):
    check(re.fullmatch(r'\d{8}T\d{12}_[0-9a-f]{12}', run_id) is not None, 'INVALID_RUN_ID')
    folder = STORE / run_id
    raw = (folder / 'manifest.json').read_bytes()
    local_digest = (folder / 'manifest.sha256').read_text().strip()
    check(sha(raw) == local_digest and (expected_sha is None or expected_sha == local_digest), 'MANIFEST_HASH_MISMATCH')
    manifest = json.loads(raw)
    for row in manifest['files']:
        blob = safe_path(folder, row['path']).read_bytes()
        check(sha(blob) == row['sha256'] and len(blob) == row['bytes'], 'ARCHIVED_FILE_HASH_MISMATCH')
    if manifest['exit_code'] == 0:
        old = baseline_rows((folder / 'baseline/normalized_snapshot.json').read_bytes())
        new = []
        for code in SECTORS:
            pages = [r for r in manifest['requests'] if r['service'] == 'StatisticSearch' and r['parameters_without_key'][-1] == code]
            rows = [row for page in pages for row in json.loads(safe_path(folder, page['raw_path']).read_bytes())['StatisticSearch']['row']]
            new.extend(normalize(rows, code, pages[-1]['observed_at'], run_id))
        check(new == json.loads((folder / 'normalized.json').read_bytes()), 'NORMALIZATION_REPLAY_MISMATCH')
        events, issues = validate_snapshot(old, new, manifest['query_windows'])
        check(events == json.loads((folder / 'diff.json').read_bytes()), 'DIFF_REPLAY_MISMATCH')
        check(summary(events, issues)['counts'] == manifest['counts'], 'CLASSIFICATION_REPLAY_MISMATCH')
    return {'run_id': run_id, 'manifest_sha256': local_digest, 'status': 'ARCHIVE_HASHES_VERIFIED_OFFLINE',
            'original_collection_status': manifest['status'], 'original_exit_code': manifest['exit_code'],
            'collection_passed': manifest['exit_code'] == 0, 'network_called': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--collect', action='store_true')
    mode.add_argument('--validate-run')
    parser.add_argument('--expected-manifest-sha256')
    args = parser.parse_args(argv)
    try:
        if args.validate_run:
            result = validate_run(args.validate_run, args.expected_manifest_sha256)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result['original_exit_code']
        result, digest_value = collect_once()
        public = {k: result[k] for k in ('run_id', 'status', 'started_at', 'finished_at', 'counts', 'ranges',
                                       'changed_keys', 'validation_issues', 'review_required', 'observed_rows')}
        public.update({'manifest_sha256': digest_value, 'round10_integrity_unchanged': result.get('round10_integrity', {}).get('unchanged', False),
                       'official_correction_confirmed': False, 'model_input_promoted': False})
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return result['exit_code']
    except Exception:
        print(json.dumps({'status': 'FAILED', 'error': 'CLI_FAILURE_REDACTED_NO_PROMOTION'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
