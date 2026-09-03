import copy
import os
import unittest

from gt7dashboard import gt7comparison, gt7helper
from gt7dashboard.gt7lap import Lap


class TestComparisonLaps(unittest.TestCase):
    def setUp(self):
        self.path = os.path.abspath(
            "test_data/broad_bean_raceway_time_trial_4laps.json"
        )
        self.laps = gt7helper.load_laps_from_json(self.path)

    def test_load_comparison_laps_keeps_file_provenance(self):
        result = gt7comparison.load_comparison_laps([self.path, self.path])

        self.assertEqual(4, len(result.records))
        self.assertEqual([], result.errors)
        first_record = result.records[0]
        self.assertEqual(os.path.basename(self.path), first_record.source_name)
        self.assertEqual(0, first_record.lap_index)
        self.assertIn("::0", first_record.identifier)
        self.assertIn("Lap", first_record.select_label)
        self.assertIn("Saved #1", first_record.select_label)

        table_data = gt7comparison.comparison_table_data(result.records)
        self.assertEqual(4, len(table_data["identifier"]))
        self.assertEqual(os.path.basename(self.path), table_data["source"][0])
        self.assertEqual("Ready", table_data["status"][0])

    def test_assess_lap_compatibility_uses_shared_distance(self):
        result = gt7comparison.assess_lap_compatibility(
            self.laps[0], self.laps[1]
        )

        self.assertTrue(result.compatible)
        self.assertGreater(result.shared_distance_m, 0)
        self.assertLessEqual(
            result.shared_distance_m,
            min(
                gt7comparison.get_lap_distance(self.laps[0]),
                gt7comparison.get_lap_distance(self.laps[1]),
            ),
        )

    def test_assess_lap_compatibility_rejects_large_length_mismatch(self):
        long_lap = Lap()
        long_lap.data_speed = [360] * 1000
        long_lap.data_time = list(range(1000))
        short_lap = Lap()
        short_lap.data_speed = [360] * 100
        short_lap.data_time = list(range(100))

        result = gt7comparison.assess_lap_compatibility(long_lap, short_lap)

        self.assertFalse(result.compatible)
        self.assertIn("total distance", result.message)

    def test_assess_lap_compatibility_warns_when_position_edges_differ(self):
        shifted_lap = copy.deepcopy(self.laps[1])
        shifted_lap.data_position_x = [
            value + 1000 for value in shifted_lap.data_position_x
        ]

        result = gt7comparison.assess_lap_compatibility(
            self.laps[0], shifted_lap
        )

        self.assertTrue(result.compatible)
        self.assertTrue(result.warning)
