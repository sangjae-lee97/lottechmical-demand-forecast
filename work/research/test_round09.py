"""Synthetic checks only; never embeds official observation values."""
import copy
from io import BytesIO
import unittest
import xml.etree.ElementTree as ET

from analyze_round09 import G, S, M, KO, PROXIES, read_proxies, pair_stats, summarize, shift


def fixture():
    data, dsd = ET.Element(M + 'GenericData'), ET.Element(S + 'Structure')
    ET.SubElement(ET.SubElement(data, M + 'Header'), M + 'DataSetID').text = '101_DT_1F02001'
    dataset = ET.SubElement(data, M + 'DataSet')
    ET.SubElement(dsd, S + 'KeyFamily', id='101_DT_1F02001')
    for name, entries in [('CL_A', [('00', '전국', None)]),
                          ('CL_ITEM', [('T10', '생산지수(원지수)', None)]),
                          ('CL_UNIT', [('14101.ausgabe', '2020=100', None)]),
                          ('CL_B', [(c, label, parent) for c, (label, parent) in PROXIES.items()])]:
        block = ET.SubElement(dsd, S + 'CodeList', id=name)
        for code, label, parent in entries:
            item = ET.SubElement(block, S + 'Code', value=code)
            if parent:
                item.set('parentCode', parent)
            ET.SubElement(item, S + 'Description', {KO: 'ko'}).text = label
    for code in PROXIES:
        series = ET.SubElement(dataset, G + 'Series')
        key = ET.SubElement(series, G + 'SeriesKey')
        for concept, value in [('FREQ', 'M'), ('A', '00'), ('B', code)]:
            ET.SubElement(key, G + 'Value', concept=concept, value=value)
        for time, value in [('202201', '10'), ('202202', '20')]:
            obs = ET.SubElement(series, G + 'Obs')
            ET.SubElement(obs, G + 'Time').text = time
            ET.SubElement(obs, G + 'ObsValue', value=value)
    return data, dsd


def read(data, dsd):
    return read_proxies(BytesIO(ET.tostring(data)), BytesIO(ET.tostring(dsd)))


class ProxyChecks(unittest.TestCase):
    def test_mapping_and_unverified_asof_metadata(self):
        rows = read(*fixture())
        self.assertEqual(len(rows), 4)
        self.assertEqual({r['industry_code'] for r in rows}, {'C222', 'C303'})
        self.assertTrue(all(r['item_id'] == 'T10' and r['unit'] == '2020=100' for r in rows))
        self.assertTrue(all(r['available_at'] is None and not r['vintage_verified_for_origin'] for r in rows))

    def test_wrong_item_and_parent_are_rejected(self):
        for list_id, attribute, replacement in [('CL_ITEM', 'value', 'T20'), ('CL_B', 'parentCode', 'WRONG')]:
            data, dsd = fixture()
            dsd.find(f'.//{S}CodeList[@id="{list_id}"]/{S}Code').set(attribute, replacement)
            with self.assertRaises(ValueError):
                read(data, dsd)

    def test_region_and_duplicate_series_are_rejected(self):
        data, dsd = fixture()
        data.find(f'.//{G}Value[@concept="A"]').set('value', '11')
        with self.assertRaises(ValueError):
            read(data, dsd)
        data, dsd = fixture()
        data.find(M + 'DataSet').append(copy.deepcopy(data.find(f'.//{G}Series')))
        with self.assertRaises(ValueError):
            read(data, dsd)

    def test_missing_duplicate_months_and_nonfinite_values(self):
        for mutation in ('missing', 'duplicate', 'nonfinite'):
            data, dsd = fixture()
            series = data.find(f'.//{G}Series')
            if mutation == 'missing':
                series.findall(f'{G}Obs/{G}Time')[-1].text = '202203'
            elif mutation == 'duplicate':
                series.append(copy.deepcopy(series.find(G + 'Obs')))
            else:
                series.find(f'{G}Obs/{G}ObsValue').set('value', 'nan')
            with self.assertRaises(ValueError):
                read(data, dsd)

    def test_known_level_and_yoy_correlations_and_target_exclusion(self):
        series = {code: {shift('2022-01', i): scale * (10 + i) for i in range(27)}
                  for code, scale in [('C30', 1), ('C222', 2), ('C303', 3)]}
        result = pair_stats(series, 'C30', 'C222')
        self.assertEqual(result['original_index']['n'], 27)
        self.assertEqual(result['yoy_percent']['n'], 15)
        self.assertAlmostEqual(result['original_index']['pearson_r'], 1)
        self.assertAlmostEqual(result['yoy_percent']['pearson_r'], 1)
        excluded = [t for t in series['C30'] if not t.startswith('2023')]
        self.assertEqual(pair_stats(series, 'C30', 'C222', excluded)['yoy_percent']['n'], 12)
        shorter = pair_stats(series, 'C30', 'C222', ('2024-02', '2024-03'))
        self.assertEqual(shorter['original_index']['n'], 25)
        self.assertEqual(shorter['yoy_percent']['n'], 13)

    def test_duplicate_normalized_rows_stop(self):
        rows = [{'industry_code': code, 'period': shift('2022-01', i), 'value': 10 + i,
                 'provisional_ui_flag': False} for code in ('C30', 'C222', 'C303') for i in range(13)]
        summary = summarize(rows)
        self.assertEqual(summary['quality']['C303']['yoy_n'], 1)
        self.assertEqual(summary['strict_gate_status'], 'NO_VERIFIED_BACKTEST')
        with self.assertRaises(ValueError):
            summarize(rows + [rows[0]])


if __name__ == '__main__':
    unittest.main()
