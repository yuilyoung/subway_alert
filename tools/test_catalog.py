import copy
import unittest
from import_catalog import validate


def fixture():
    return {
        'version': 1,
        'lines': [{'id': '1002', 'name': 'TEST ONLY', 'topisName': 'TEST ONLY', 'upLabel': 'UP', 'downLabel': 'DOWN'}],
        'stations': [
            {'id': f'test-{n}', 'lineId': '1002', 'topisId': f'100200000{n}', 'name': f'TEST {n}',
             'latitude': 37.5, 'longitude': 127.0, 'source': 'UNIT TEST FIXTURE',
             'sourceUrl': 'https://example.org/test-only', 'verifiedAt': '2026-10-27T00:00:00Z'} for n in [1, 2]
        ],
        'edges': [{'lineId': '1002', 'direction': '0', 'from': 'test-1', 'to': 'test-2'}],
        'facilities': [],
    }


class CatalogTests(unittest.TestCase):
    def test_valid_structure(self):
        self.assertEqual(2, validate(fixture())['stations'])

    def test_duplicate_station(self):
        data = fixture(); data['stations'].append(copy.deepcopy(data['stations'][0]))
        with self.assertRaises(ValueError): validate(data)

    def test_unknown_edge(self):
        data = fixture(); data['edges'][0]['to'] = 'unknown'
        with self.assertRaises(ValueError): validate(data)

    def test_coordinate_range(self):
        data = fixture(); data['stations'][0]['latitude'] = 100
        with self.assertRaises(ValueError): validate(data)

    def test_missing_provenance(self):
        data = fixture(); del data['stations'][0]['sourceUrl']
        with self.assertRaises(ValueError): validate(data)

    def test_rejects_demo_as_live_data(self):
        data = fixture(); data['stations'][0]['source'] = 'SYNTHETIC_DEMO'
        with self.assertRaises(ValueError): validate(data)

    def test_transfer_requires_direction_and_car_door(self):
        data = fixture(); data['facilities'] = [{'stationId': 'test-1', 'kind': 'TRANSFER', 'title': 'test', 'location': 'test',
            'sourceUrl': 'https://example.org/test-only', 'verifiedAt': '2026-10-27T00:00:00Z'}]
        with self.assertRaises(ValueError): validate(data)

    def test_unknown_facility_type(self):
        data = fixture(); data['facilities'] = [{'stationId': 'test-1', 'kind': 'UNKNOWN', 'title': 'test', 'location': 'test',
            'sourceUrl': 'https://example.org/test-only', 'verifiedAt': '2026-10-27T00:00:00Z'}]
        with self.assertRaises(ValueError): validate(data)


if __name__ == '__main__':
    unittest.main()
