"""Synthetic fixtures only; no official observation values or keys."""
from io import BytesIO
import unittest

from analyze_round08 import G, S, M, KO, align, consecutive, correlation, read_production, verified_input


class Round08Checks(unittest.TestCase):
    def test_missing_duplicate_months_fail(self):
        for periods in [['2023-01', '2023-01'], ['2023-01', '2023-03']]:
            with self.assertRaises(ValueError):
                consecutive(periods)
        consecutive(['2022-12', '2023-01'])

    def test_target_month_join_not_survey_month(self):
        production = [{'period': p, 'value': v} for p, v in
                      [('2022-01', 10), ('2022-12', 30), ('2023-01', 20)]]
        bsi = [{'forecast_target_month': '2023-01', 'survey_month': '2022-12', 'value': 100},
               {'forecast_target_month': '2023-02', 'survey_month': '2023-01', 'value': 100}]
        rows = align(bsi, production)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['production_index'], 20)
        self.assertEqual(rows[0]['production_yoy_pct'], 100)
        self.assertEqual(rows[0]['origin'], '2023-01-01T00:00:00+09:00')
        self.assertFalse(rows[0]['baseline_input_verified'])

    def test_asof_gate_rejects_future_missing_and_unverified_vintage(self):
        origin = '2023-01-01T00:00:00+09:00'
        row = {'publication_date': '2022-12-30', 'available_at': '2022-12-31T00:00:00+09:00',
               'asof_evidence': 'synthetic_test_evidence', 'vintage_verified_for_origin': True}
        self.assertTrue(verified_input(row, origin))
        for changed in [{'available_at': '2023-01-02T00:00:00+09:00'},
                        {'available_at': None}, {'available_at': '2022-12-31T00:00:00'},
                        {'publication_date': None}, {'vintage_verified_for_origin': False},
                        {'asof_evidence': None}, {'publication_date': '2023-01-02'}]:
            self.assertFalse(verified_input({**row, **changed}, origin))

    def test_pearson_and_small_sample(self):
        self.assertAlmostEqual(correlation([(1, 2), (2, 4), (3, 6)])['pearson_r'], 1)
        self.assertIsNone(correlation([(1, 2)])['pearson_r'])
        self.assertIsNone(correlation([(1, 2), (1, 3), (1, 4)])['pearson_r'])

    def test_sdmx_metadata_and_wrong_item(self):
        import xml.etree.ElementTree as ET
        data = ET.Element(M + 'GenericData')
        header = ET.SubElement(data, M + 'Header')
        ET.SubElement(header, M + 'DataSetID').text = '101_DT_1F02001'
        series = ET.SubElement(ET.SubElement(data, M + 'DataSet'), G + 'Series')
        key = ET.SubElement(series, G + 'SeriesKey')
        for concept, value in [('FREQ', 'M'), ('A', '00'), ('B', 'C30')]:
            ET.SubElement(key, G + 'Value', concept=concept, value=value)
        for time, value in [('202301', '10'), ('202302', '20'), ('202303', '30')]:
            obs = ET.SubElement(series, G + 'Obs')
            ET.SubElement(obs, G + 'Time').text = time
            ET.SubElement(obs, G + 'ObsValue', value=value)
        dsd = ET.Element(S + 'Structure')
        ET.SubElement(dsd, S + 'KeyFamily', id='101_DT_1F02001')
        for list_id, code, label in [('CL_A', '00', '전국'), ('CL_B', 'C30', '자동차 및 트레일러 제조업'),
                                     ('CL_ITEM', 'T10', '생산지수(원지수)'), ('CL_UNIT', '14101.ausgabe', '2020=100')]:
            block = ET.SubElement(dsd, S + 'CodeList', id=list_id)
            item = ET.SubElement(block, S + 'Code', value=code)
            ET.SubElement(item, S + 'Description', {KO: 'ko'}).text = label
        self.assertEqual(len(read_production(BytesIO(ET.tostring(data)), BytesIO(ET.tostring(dsd)))), 3)
        dsd.find(f'.//{S}CodeList[@id="CL_ITEM"]/{S}Code').set('value', 'T20')
        with self.assertRaises(ValueError):
            read_production(BytesIO(ET.tostring(data)), BytesIO(ET.tostring(dsd)))


if __name__ == '__main__':
    unittest.main()
