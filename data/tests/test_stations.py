import json
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "stations.sample.json"


class StationDatasetTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(DATA.read_text(encoding="utf-8"))

    def test_five_unique_contiguous_stations(self):
        stations = self.data["stations"]
        self.assertEqual([s["name"] for s in stations], ["삼성", "선릉", "역삼", "강남", "교대"])
        self.assertEqual(len({s["id"] for s in stations}), len(stations))
        self.assertEqual([s["order"] for s in stations], list(range(5)))
        self.assertTrue(all(s["lineId"] == "2" for s in stations))

    def test_incomplete_segment_is_not_a_circular_route(self):
        self.assertFalse(self.data["route"]["isComplete"])
        self.assertFalse(self.data["route"]["isCircular"])

    def test_unverified_facilities_are_explicitly_unavailable(self):
        expected = {"fastTransfer", "restrooms", "amenities", "ticketGates", "exits"}
        for station in self.data["stations"]:
            self.assertEqual(set(station["facilities"]), expected)
            self.assertTrue(all(value is None for value in station["facilities"].values()))

    def test_unknown_coordinates_are_not_mistaken_for_real_positions(self):
        for station in self.data["stations"]:
            self.assertIsNone(station["latitude"])
            self.assertIsNone(station["longitude"])


if __name__ == "__main__":
    unittest.main()
