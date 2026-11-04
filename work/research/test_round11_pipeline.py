"""Offline synthetic fixtures; no official values or network/credential access."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit, quote
from urllib.request import Request

import round11_ecos_snapshot_pipeline as p

KEY = 'synthetic/private+key_for_offline_checks'


def row(code, time, value):
    return {'STAT_CODE': '512Y008', 'STAT_NAME': 'synthetic 전망', 'ITEM_CODE1': 'BD',
            'ITEM_NAME1': '신규수주전망BSI', 'ITEM_CODE2': code, 'ITEM_NAME2': p.SECTORS[code],
            'ITEM_CODE3': None, 'ITEM_CODE4': None, 'UNIT_NAME': None, 'TIME': time, 'DATA_VALUE': str(value)}


def rows():
    return {code: [row(code, '202610', 10 + i), row(code, '202611', 20 + i)]
            for i, code in enumerate(p.SECTORS)}


class Response:
    status = 200

    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


class Server:
    def __init__(self, data=None):
        self.data = rows() if data is None else data
        self.calls = 0
        self.bad_total = False
        self.echo_key = False

    def __call__(self, request, timeout):
        self.calls += 1
        parts = urlsplit(request.full_url).path.strip('/').split('/')
        service, first, last, args = parts[1], int(parts[5]), int(parts[6]), parts[7:]
        if self.echo_key:
            return Response(p.encoded({'RESULT': {'CODE': 'ERROR-100', 'MESSAGE': request.full_url}}))
        if service == 'StatisticItemList':
            latest = max(r['TIME'] for group in self.data.values() for r in group)
            records = [{'STAT_CODE': '512Y008', 'GRP_CODE': group, 'ITEM_CODE': code, 'CYCLE': 'M', 'END_TIME': latest}
                       for group, code in [('Group1', 'BD'), ('Group2', 'C3000'), ('Group2', 'C0000')]]
        else:
            records = self.data[args[-1]]
        total = len(records) + (1 if self.bad_total else 0)
        return Response(p.encoded({service: {'list_total_count': total, 'row': records[first-1:last]}}))


def fingerprint(folder):
    return {r.relative_to(folder).as_posix(): p.sha(r.read_bytes()) for r in folder.rglob('*') if r.is_file()}


class PipelineChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='round11_synthetic_', dir=p.ROOT / 'work/data/local_only')
        self.root = Path(self.tmp.name)
        # Explicit containment verification before TemporaryDirectory recursive cleanup.
        self.assertTrue(self.root.resolve().is_relative_to((p.ROOT / 'work/data/local_only').resolve()))
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        base = []
        for code, group in rows().items():
            for raw in group:
                target = p.month(raw['TIME'])
                base.append({'table_code': '512Y008', 'item_code1': 'BD', 'item_code2': code,
                             'forecast_target_month': target, 'survey_month': p.shift(target, -1),
                             'value': raw['DATA_VALUE'], 'publication_date': None})
        baseline = self.root / 'baseline.json'
        baseline.write_bytes(p.encoded(base))
        manifest = self.root / 'baseline_manifest.json'
        manifest.write_bytes(p.encoded([{'file': baseline.name, 'sha256': p.sha(baseline.read_bytes())}]))
        lock = self.root / 'round10_synthetic'
        lock.mkdir()
        (lock / 'forecasts.canonical.json').write_bytes(b'{"synthetic_forecast_only":1}')
        (lock / 'synthetic_params.json').write_bytes(b'{}')
        for name, value in [('STORE', self.root / 'runs'), ('BASELINE', baseline), ('BASE_MANIFEST', manifest),
                            ('LOCK', lock), ('LOCK_SHA', p.sha((lock / 'forecasts.canonical.json').read_bytes()))]:
            self.stack.enter_context(patch.object(p, name, value))
        self.stack.enter_context(patch.object(p, 'local_key', return_value=KEY))
        self.baseline_before, self.lock_before = baseline.read_bytes(), fingerprint(lock)

    def collect(self, server):
        with patch.object(p, 'urlopen', side_effect=server):
            return p.collect_once()

    def test_first_baseline_and_identical_format_only_requery(self):
        normalized = [r for code, group in rows().items() for r in p.normalize(group, code, 'synthetic_time', 'synthetic_run')]
        windows = {code: ['2026-10', '2026-11'] for code in p.SECTORS}
        self.assertEqual([r['classification'] for r in p.compare([], normalized, windows)], ['NEW_TARGET_MONTH'] * 4)
        server = Server()
        server.data['C3000'][0]['DATA_VALUE'] = '10.0'
        result, _ = self.collect(server)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['counts']['UNCHANGED'], 4)
        self.assertFalse(result['review_required'])

    def test_new_month_and_historical_change(self):
        server = Server()
        for code in p.SECTORS:
            server.data[code].append(row(code, '202612', 30))
        server.data['C3000'][0]['DATA_VALUE'] = '11'
        result, _ = self.collect(server)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['counts']['NEW_TARGET_MONTH'], 2)
        self.assertEqual(result['counts']['HISTORICAL_VALUE_CHANGED'], 1)
        self.assertTrue(result['review_required'])
        self.assertFalse(result['official_correction_confirmed'])
        data = json.loads((p.STORE / result['run_id'] / 'normalized.json').read_bytes())
        self.assertTrue(all(r['publication_date'] is None and r['available_at'] is None and not r['vintage_verified'] for r in data))
        self.assertTrue(all(r['post_2026_10_survey_reform'] for r in data if r['forecast_target_month'] >= '2026-11'))

    def test_missing_month_is_quarantined_and_window_shrink_is_distinct(self):
        server = Server()
        for code in p.SECTORS:
            server.data[code] = [row(code, '202610', 10), row(code, '202612', 30)]
        result, _ = self.collect(server)
        self.assertEqual(result['exit_code'], 2)
        self.assertEqual(result['counts']['MISSING_OR_REMOVED'], 2)
        self.assertTrue((p.STORE / result['run_id'] / 'quarantine/review_required.json').is_file())
        old = p.baseline_rows(p.BASELINE.read_bytes())
        current = [r for code, group in rows().items() for r in p.normalize(group[:1], code, 'time', 'run')]
        events = p.compare(old, current, {code: ['2026-10', '2026-10'] for code in p.SECTORS})
        self.assertEqual(sum(r['classification'] == 'OUTSIDE_QUERY_WINDOW' for r in events), 2)
        self.assertFalse(any(r['classification'] == 'MISSING_OR_REMOVED' for r in events))

    def test_duplicate_wrong_codes_and_sector_range_mismatch(self):
        for failure in ('duplicate', 'wrong_code', 'sector_range', 'nonfinite'):
            server = Server()
            if failure == 'duplicate':
                server.data['C3000'].append(copy.deepcopy(server.data['C3000'][0]))
            elif failure == 'wrong_code':
                server.data['C3000'][0]['ITEM_CODE1'] = 'WRONG'
            elif failure == 'sector_range':
                server.data['C3000'].append(row('C3000', '202612', 30))
            else:
                server.data['C3000'][0]['DATA_VALUE'] = 'NaN'
            result, _ = self.collect(server)
            self.assertNotEqual(result['exit_code'], 0)
            self.assertGreater(result['counts']['INVALID_OR_UNVERIFIED'], 0)
            self.assertFalse(result['model_input_promoted'])

    def test_pagination_raw_byte_hash_and_total_mismatch(self):
        server = Server({'C3000': [row('C3000', p.shift('2026-01', i).replace('-', ''), i) for i in range(5)]})
        folder = self.root / 'pages'
        folder.mkdir()
        files, requests = [], []
        with patch.object(p, 'urlopen', side_effect=server):
            received = p.fetch('StatisticSearch', ['512Y008', 'M', '202601', '202605', 'BD', 'C3000'], KEY, folder, files, requests, 2)
        self.assertEqual(len(received), 5)
        self.assertEqual([(r['start'], r['end']) for r in requests], [(1, 2), (3, 4), (5, 5)])
        self.assertTrue(all(p.sha((folder / r['path']).read_bytes()) == r['sha256'] for r in files))
        server = Server()
        server.bad_total = True
        result, _ = self.collect(server)
        self.assertNotEqual(result['exit_code'], 0)
        self.assertIn('PAGE_ROW_COUNT_MISMATCH', [r['code'] for r in result['validation_issues']])

    def test_key_url_exception_and_echo_never_logged_or_archived(self):
        with self.assertRaises(p.PipelineError):
            p.NoRedirect().redirect_request(Request('https://ecos.bok.or.kr/api/synthetic'), None,
                                           302, 'Found', {}, 'https://example.invalid/')
        def fail(request, timeout):
            raise HTTPError(request.full_url, 403, 'sensitive ' + KEY, None, None)
        for transport in [fail, Server()]:
            if isinstance(transport, Server):
                transport.echo_key = True
            output = io.StringIO()
            with patch.object(p, 'urlopen', side_effect=transport), redirect_stdout(output), redirect_stderr(output):
                exit_code = p.main(['--collect'])
            self.assertNotEqual(exit_code, 0)
            self.assertNotIn(KEY, output.getvalue())
            self.assertNotIn(quote(KEY, safe=''), output.getvalue())
        for path in p.STORE.rglob('*'):
            if path.is_file():
                self.assertNotIn(KEY.encode(), path.read_bytes())
                self.assertNotIn(quote(KEY, safe='').encode(), path.read_bytes())

    def test_append_only_baseline_and_round10_immutable(self):
        first, _ = self.collect(Server())
        before = fingerprint(p.STORE / first['run_id'])
        second, _ = self.collect(Server())
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(before, fingerprint(p.STORE / first['run_id']))
        self.assertEqual(self.baseline_before, p.BASELINE.read_bytes())
        self.assertEqual(self.lock_before, fingerprint(p.LOCK))
        self.assertTrue(second['round10_integrity']['unchanged'])

    def test_offline_validation_no_network_no_key_read_and_tamper_detection(self):
        result, digest = self.collect(Server())
        folder = p.STORE / result['run_id']
        before = fingerprint(folder)
        output = io.StringIO()
        with patch.object(p, 'urlopen', side_effect=AssertionError('NO NETWORK')) as network, \
             patch.object(p, 'local_key', side_effect=AssertionError('NO KEY READ')) as key, redirect_stdout(output):
            self.assertEqual(p.main(['--validate-run', result['run_id'], '--expected-manifest-sha256', digest]), 0)
            network.assert_not_called()
            key.assert_not_called()
        self.assertEqual(before, fingerprint(folder))
        (folder / 'normalized.json').write_bytes(b'[]')  # Synthetic archive only.
        with self.assertRaises(p.PipelineError):
            p.validate_run(result['run_id'], digest)

    def test_missing_key_archived_failure_without_transport(self):
        with patch.object(p, 'local_key', side_effect=ValueError('LOCAL_KEY_NOT_CONFIGURED')), \
             patch.object(p, 'urlopen', side_effect=AssertionError('NO NETWORK')) as network:
            result, _ = p.collect_once()
            network.assert_not_called()
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('LOCAL_KEY_NOT_CONFIGURED', [r['code'] for r in result['validation_issues']])


if __name__ == '__main__':
    unittest.main()
