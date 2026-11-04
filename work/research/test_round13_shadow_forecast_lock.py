"""Synthetic fixtures only. Never touches the actual Round13 or Round10 lock."""
import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import round13_shadow_forecast_lock as s
from test_round09 import fixture as structure_fixture

ORIGIN = datetime(2026, 11, 4, 12, tzinfo=s.KST)


def fixture():
    data, dsd = structure_fixture()
    for index, series in enumerate(data.findall(f'.//{s.G}Series')):
        for obs in series.findall(s.G + 'Obs'):
            series.remove(obs)
        for i in range(57):
            obs = ET.SubElement(series, s.G + 'Obs')
            ET.SubElement(obs, s.G + 'Time').text = s.shift('2022-01', i).replace('-', '')
            ET.SubElement(obs, s.G + 'ObsValue', value=str(80 + i * (index + 1) + i % 5))
    blobs = {s.RAW: ET.tostring(data), s.DSD: ET.tostring(dsd)}
    blobs[s.PRIOR] = s.canonical({'input_manifest': [{'file': name, 'sha256': s.digest(raw)} for name, raw in blobs.items()]})
    return blobs


def payload(blobs):
    forecasts, audits = s.make_forecasts(s.load_from_blobs(blobs), ORIGIN)
    return {'origin_kst': ORIGIN.isoformat(), 'source_commit_sha': 'a' * 40,
            'performance_evaluation': 'NOT_PERFORMED_NO_ACTUALS', 'forecasts': forecasts, 'training_audit': audits,
            'input_manifest': [{'path': name, 'bytes': len(raw), 'sha256': s.digest(raw)} for name, raw in sorted(blobs.items())]}


class ShadowChecks(unittest.TestCase):
    def test_eight_unique_forecasts_and_exact_windows(self):
        forecasts, audit = s.make_forecasts(s.load_from_blobs(fixture()), ORIGIN)
        self.assertEqual(len({(r['industry_code'], r['target'], r['model']) for r in forecasts}), 8)
        self.assertEqual(len(audit), 8)
        for r in audit:
            cutoff = '2026-08' if r['target'] == '2026-10' else '2026-09'
            self.assertEqual(r['cutoff'], cutoff)
            self.assertEqual(r['common_train_n'], 33 if r['target'] == '2026-10' else 34)
            self.assertEqual(r['common_train_months'][0], '2023-12')
            self.assertEqual(r['rolling_months'], [s.shift(cutoff, i - r['rolling_n'] + 1) for i in range(r['rolling_n'])])
            if r['rolling_n'] == 6:
                self.assertEqual(r['rolling_months'][0], '2026-03' if r['target'] == '2026-10' else '2026-04')
            else:
                self.assertEqual(r['rolling_months'][0], '2025-09' if r['target'] == '2026-10' else '2025-10')

    def test_independent_direct_sum(self):
        rows = s.load_from_blobs(fixture())
        forecasts, audit = s.make_forecasts(rows, ORIGIN)
        for f, r in zip(forecasts, audit):
            values = {v['period']: v['value'] for v in rows if v['industry_code'] == f['industry_code']}
            expected = sum((values[t] - values[s.shift(t, -12)]) / values[s.shift(t, -12)] * 100
                           for t in r['rolling_months']) / r['rolling_n']
            self.assertAlmostEqual(f['predicted_production_yoy_pct'], expected, places=10)

    def test_october_ignores_september_november_uses_it(self):
        rows = s.load_from_blobs(fixture())
        before, _ = s.make_forecasts(rows, ORIGIN)
        changed = copy.deepcopy(rows)
        for r in changed:
            if r['period'] == '2026-09':
                r['value'] *= 3
        after, _ = s.make_forecasts(changed, ORIGIN)
        self.assertEqual([r for r in before if r['target'] == '2026-10'], [r for r in after if r['target'] == '2026-10'])
        self.assertNotEqual([r for r in before if r['target'] == '2026-11'], [r for r in after if r['target'] == '2026-11'])

    def test_target_production_blocks_before_numeric_values(self):
        for month in ('2026-10', '2026-11', '2026-12'):
            rows = s.load_from_blobs(fixture()) + [{'industry_code': 'C222', 'period': month, 'value': object()}]
            with self.assertRaisesRegex(ValueError, 'Target/future'):
                s.make_forecasts(rows, ORIGIN)
            raw = f'<root xmlns:g="{s.G[1:-1]}"><g:Obs><g:Time>{month.replace("-", "")}</g:Time><g:ObsValue value="not-a-number"/></g:Obs></root>'.encode()
            with self.assertRaisesRegex(ValueError, 'Target/future'):
                s.precheck_production(raw)

    def test_hash_modification_duplicate_short_and_invalid_inputs(self):
        blobs = fixture()
        blobs[s.RAW] += b'changed'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            s.load_from_blobs(blobs)
        rows = s.load_from_blobs(fixture())
        for invalid in (rows + [rows[0]], rows[1:], [r for r in rows if r['period'] != '2024-12']):
            with self.assertRaises(ValueError):
                s.make_forecasts(invalid, ORIGIN)
        for key, value in [('value', 0), ('value', float('nan')), ('value', float('inf')),
                           ('industry_code', 'C30'), ('item_id', 'T20'), ('period', '2026-13'),
                           ('provisional_ui_flag', True)]:
            changed = copy.deepcopy(rows)
            changed[0][key] = value
            with self.assertRaises(ValueError):
                s.make_forecasts(changed, ORIGIN)

    def test_illegal_clock_and_no_origin_override(self):
        for origin in (datetime(2026, 11, 4), datetime(2026, 11, 4, tzinfo=timezone.utc),
                       datetime(2026, 11, 3, tzinfo=s.KST), datetime(2026, 12, 1, tzinfo=s.KST)):
            with self.assertRaises(ValueError):
                s.origin_check(origin)
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            s.main(['--lock', '--origin', ORIGIN.isoformat()])

    def test_source_must_be_pushed_and_clean(self):
        with patch.object(s, 'git', return_value='a' * 40), patch.object(s.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            s.source_check('a' * 40)
            with self.assertRaises(ValueError):
                s.source_check('b' * 40)
        with patch.object(s, 'git', return_value='a' * 40), patch.object(s.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'Commit source'):
                s.source_check('a' * 40)

    def test_canonical_digest_replay_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='round13_synthetic_', dir=s.LOCAL) as temp:
            self.assertTrue(Path(temp).resolve().is_relative_to(s.LOCAL.resolve()))
            folder = Path(temp) / 'synthetic_lock'
            blobs = fixture()
            sha = s.write_lock(folder, payload(blobs), blobs)
            self.assertEqual(s.verify_lock(folder, sha)['forecast_count'], 8)
            original = s.tree(folder)
            with self.assertRaises(FileExistsError):
                s.write_lock(folder, payload(blobs), blobs)
            self.assertEqual(original, s.tree(folder))
            with self.assertRaises(ValueError):
                s.verify_lock(folder, '0' * 64)
            self.assertEqual(s.canonical({'z': 1, 'a': 2}), s.canonical({'a': 2, 'z': 1}))
            with self.assertRaises(ValueError):
                s.canonical({'value': float('nan')})

    def test_sealed_source_metadata_extra_files_and_prediction_tampering(self):
        for mutation in ('input', 'metadata', 'extra', 'prediction'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(prefix='round13_synthetic_', dir=s.LOCAL) as temp:
                self.assertTrue(Path(temp).resolve().is_relative_to(s.LOCAL.resolve()))
                folder, blobs = Path(temp) / 'synthetic_lock', fixture()
                p = payload(blobs)
                sha = s.write_lock(folder, p, blobs)
                if mutation == 'input':
                    (folder / 'sealed_inputs' / s.RAW).write_bytes(b'changed')
                elif mutation == 'metadata':
                    (folder / 'model_params.json').write_bytes(b'[]')
                elif mutation == 'extra':
                    (folder / 'extra.txt').write_bytes(b'extra')
                else:
                    p['forecasts'][0]['predicted_production_yoy_pct'] += 1
                    raw = s.canonical(p)
                    sha = s.digest(raw)
                    (folder / 'forecasts.canonical.json').write_bytes(raw)
                    (folder / 'forecasts.sha256').write_text(sha + '\n')
                with self.assertRaises(ValueError):
                    s.verify_lock(folder, sha)

    def test_round10_guard_read_only_and_bad_tree_rejected(self):
        # Synthetic checks, not a new read of the actual lock in this test.
        with patch.object(s, 'tree', return_value={str(i): 'a' * 64 for i in range(22)}):
            with self.assertRaisesRegex(ValueError, 'Round10 integrity'):
                s.round10_guard()
        with patch.object(s, 'tree', return_value={'forecast': s.ROUND10_SHA}):
            with self.assertRaises(ValueError):
                s.round10_guard()

    def test_path_escape_and_manifest_mismatch_rejected_before_writes(self):
        with tempfile.TemporaryDirectory(prefix='round13_synthetic_', dir=s.LOCAL) as temp:
            self.assertTrue(Path(temp).resolve().is_relative_to(s.LOCAL.resolve()))
            folder = Path(temp) / 'synthetic_lock'
            with self.assertRaises(ValueError):
                s.safe_path(folder, '../outside')
            blobs = fixture()
            p = payload(blobs)
            p['input_manifest'][0]['sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                s.write_lock(folder, p, blobs)
            self.assertFalse(folder.exists())


if __name__ == '__main__':
    unittest.main()
