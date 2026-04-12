import os
import pickle
import unittest
import math

from bokeh.io import output_file, show
from bokeh.layouts import layout
from bokeh.models import Div, Plot, Scatter, Label
from bokeh.plotting import save, figure

import gt7dashboard.gt7diagrams
import gt7dashboard.gt7helper
from gt7dashboard import gt7diagrams, gt7helper
from gt7dashboard.gt7diagrams import (
    get_throttle_braking_race_line_diagram,
)
from gt7dashboard.gt7lap import Lap


class TestHelper(unittest.TestCase):
    def setUp(self) -> None:
        self.test_laps = gt7helper.load_laps_from_json("test_data/broad_bean_raceway_time_trial_4laps.json")

    def test_get_throttle_braking_race_line_diagram(self):
        (
            race_line,
            throttle_line_data,
            breaking_line_data,
            coasting_line_data,
            reference_throttle_line_data,
            reference_breaking_line_data,
            reference_coasting_line_data,
        ) = get_throttle_braking_race_line_diagram()

        reference_lap = self.test_laps[0]
        last_lap = self.test_laps[1]

        lap_data = last_lap.get_data_dict()
        reference_lap_data = reference_lap.get_data_dict()

        throttle_line_data.data_source.data = lap_data
        breaking_line_data.data_source.data = lap_data
        coasting_line_data.data_source.data = lap_data

        reference_throttle_line_data.data_source.data = reference_lap_data
        reference_breaking_line_data.data_source.data = reference_lap_data
        reference_coasting_line_data.data_source.data = reference_lap_data

        gt7diagrams.add_annotations_to_race_line(race_line, last_lap, reference_lap)

        out_file = "test_out/test_get_throttle_braking_race_line_diagram.html"
        output_file(out_file)
        save(race_line)
        print("View file for reference at %s" % out_file)

        file_size = os.path.getsize(out_file)
        self.assertAlmostEqual(file_size, 3000000, delta=1000000)

    def helper_get_race_diagram(self):
        rd = gt7diagrams.RaceDiagram(600)

        lap_data_1 = self.test_laps[0].get_data_dict()
        lap_data_2 = self.test_laps[1].get_data_dict()

        median_lap_data = gt7helper.get_median_lap(self.test_laps).get_data_dict()

        rd.source_time_diff.data = gt7helper.calculate_time_diff_by_distance(
            self.test_laps[0], self.test_laps[1]
        )
        rd.source_last_lap.data = lap_data_2
        rd.source_reference_lap.data = lap_data_1
        rd.source_median_lap.data = median_lap_data

        return rd

    def test_race_diagram(self):

        rd = self.helper_get_race_diagram()

        out_file = "test_out/test_race_diagram.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(rd.get_layout())

        # get file size, should be about 5MB
        file_size = os.path.getsize(out_file)
        self.assertAlmostEqual(file_size, 2500000, delta=1000000)

    def test_add_5_additional_laps_to_race_diagram(self):

        rd = self.helper_get_race_diagram()

        # Add a random new lap to the mix
        # TODO Unfortunately, we have only 2 to pick from. Maybe improve this later
        gray_lap_source = rd.add_additional_lap_to_race_diagram("gray", self.test_laps[1], True)

        # Should now contain 1 source
        self.assertEqual(1, len(rd.sources_additional_laps))

        out_file = "test_out/test_add_5_additional_laps_to_race_diagram_with_additional_lap.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(rd.get_layout())

        rd.delete_all_additional_laps()
        self.assertEqual(0, len(rd.sources_additional_laps))

        out_file = "test_out/test_add_5_additional_laps_to_race_diagram_without_additional_lap.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(rd.get_layout())

        # get file size, should be about 5MB
        file_size = os.path.getsize(out_file)
        self.assertAlmostEqual(file_size, 2600000, delta=1000000)

        with open(out_file, 'r') as fp:
            data = fp.read()
            self.assertNotIn("1:28.465", data)


    def test_get_fuel_map_html_table(self):
        d = Div()
        lap = Lap()
        lap.fuel_at_start = 100
        lap.fuel_at_end = 80
        lap.lap_finish_time = 90 * 1000

        fuel_map_html_table = gt7diagrams.get_fuel_map_html_table(lap)
        d.text = fuel_map_html_table
        out_file = "test_out/test_get_fuel_map_html_table.html"
        output_file(out_file)
        save(d)
        print("View file for reference at %s" % out_file)

    def test_get_fuel_map_html_table_negative_fuel_consumption(self):
        d = Div()
        lap = Lap()
        lap.fuel_at_start = 0
        lap.fuel_at_end = 100
        lap.lap_finish_time = 90 * 1000

        fuel_map_html_table = gt7diagrams.get_fuel_map_html_table(lap)
        d.text = fuel_map_html_table
        out_file = "test_out/test_get_fuel_map_html_table_negative_fuel_consumption.html"
        output_file(out_file)
        save(d)
        print("View file for reference at %s" % out_file)

        with open(out_file, 'r') as fp:
            data = fp.read()
            self.assertIn("No Fuel", data)

    def test_get_fuel_map_html_table_with_no_consumption(self):
        d = Div()
        fuel_map_html_table = gt7diagrams.get_fuel_map_html_table(self.test_laps[0])
        d.text = fuel_map_html_table
        out_file = "test_out/test_get_fuel_map_html_table_with_no_consumption.html"
        output_file(out_file)
        save(d)
        print("View file for reference at %s" % out_file)


    def test_race_table(self):
        rt = gt7diagrams.RaceTimeTable()
        rt.show_laps(self.test_laps)

        out_file = "test_out/test_race_table.html"
        output_file(out_file)
        save(rt.t_lap_times)

    def test_display_variance(self):
        rd = self.helper_get_race_diagram()
        rd.update_fastest_laps_variance(self.test_laps)

        out_file = "test_out/test_get_last_variance.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(rd.get_layout())

        # get file size, should be about 5MB
        file_size = os.path.getsize(out_file)
        self.assertAlmostEqual(file_size, 3000000, delta=1000000)

    def test_display_flat_line_variance(self):
        rd = self.helper_get_race_diagram()
        # three times the same lap should result in a flat line
        rd.update_fastest_laps_variance([self.test_laps[0], self.test_laps[0], self.test_laps[0]])

        out_file = "test_out/test_display_flat_line_variance.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(layout(rd.f_speed_variance))

        # get file size, should be about 5MB
        file_size = os.path.getsize(out_file)
        self.assertAlmostEqual(file_size, 140000, delta=1000000)

    def test_get_speed_peak_and_valley_diagram_different_size(self):
        last_lap = self.test_laps[0]
        reference_lap = self.test_laps[3]
        div = Div()
        div.text = gt7diagrams.get_speed_peak_and_valley_diagram(last_lap, reference_lap)

        out_file = "test_out/test_get_speed_peak_and_valley_diagram_different_size.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(layout(div))

    def test_get_speed_peak_and_valley_diagram_same_size(self):
        last_lap = self.test_laps[0]
        reference_lap = self.test_laps[1]
        div = Div()
        div.text = gt7diagrams.get_speed_peak_and_valley_diagram(last_lap, reference_lap)

        out_file = "test_out/test_get_speed_peak_and_valley_diagram_same_size.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(layout(div))

    def test_friction_circle_diagram_updates_current_and_trail(self):
        diagram = gt7diagrams.FrictionCircleDiagram(history_seconds=2, tick_rate_hz=10)
        lap = Lap()

        lap.data_accel_longitudinal_g = [0.10, 0.25, 0.45]
        lap.data_accel_lateral_g = [0.05, -0.10, -0.30]
        lap.data_accel_total_g = [0.11, 0.27, 0.54]

        diagram.update_from_lap(lap)

        self.assertEqual(3, len(diagram.source_trail.data["accel_lateral_g"]))
        self.assertEqual(-0.30, diagram.source_current.data["accel_lateral_g"][0])
        self.assertEqual(0.45, diagram.source_current.data["accel_longitudinal_g"][0])
        self.assertIn("0.54 g", diagram.div_current_total_g.text)
        self.assertNotIn("Zone:", diagram.div_current_total_g.text)

    def test_friction_circle_diagram_respects_history_window(self):
        diagram = gt7diagrams.FrictionCircleDiagram(history_seconds=1, tick_rate_hz=5)
        lap = Lap()

        lap.data_accel_longitudinal_g = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        lap.data_accel_lateral_g = [0.0, -0.1, -0.2, -0.3, -0.4, -0.5]
        lap.data_accel_total_g = [0.1, 0.22, 0.36, 0.50, 0.64, 0.78]

        diagram.update_from_lap(lap)

        self.assertEqual(5, len(diagram.source_trail.data["accel_lateral_g"]))
        self.assertEqual(-0.5, diagram.source_current.data["accel_lateral_g"][0])

    def test_friction_circle_diagram_html_output_for_visual_check(self):
        diagram = gt7diagrams.FrictionCircleDiagram(width=1200, height=900, history_seconds=2, tick_rate_hz=10)
        lap = Lap()

        lap.data_accel_longitudinal_g = [0.00, 0.12, 0.30, 0.58, 0.22, -0.18, -0.42, -0.10]
        lap.data_accel_lateral_g = [0.00, 0.35, 0.60, 0.42, -0.25, -0.52, -0.20, 0.10]
        lap.data_accel_total_g = [
            0.00,
            0.37,
            0.67,
            0.72,
            0.33,
            0.55,
            0.47,
            0.14,
        ]

        diagram.update_from_lap(lap)

        out_file = "test_out/test_friction_circle_diagram.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(diagram.get_layout())

        file_size = os.path.getsize(out_file)
        self.assertGreater(file_size, 10000)

    def test_friction_circle_diagram_html_output_for_vector_scenarios(self):
        scenarios = [
            {
                "name": "SAFE: gentle acceleration",
                "vectors": [
                    (0.05, 0.03),
                    (0.10, 0.08),
                    (0.18, 0.10),
                ],
            },
            {
                "name": "PUSH: medium cornering",
                "vectors": [
                    (0.22, 0.20),
                    (0.30, 0.35),
                    (0.28, 0.40),
                ],
            },
            {
                "name": "Threshold band: around 0.7g",
                "vectors": [
                    (0.40, 0.57),
                    (0.50, 0.55),
                    (0.58, 0.50),
                ],
            },
            {
                "name": "Threshold band: around 1.0g",
                "vectors": [
                    (0.70, 0.71),
                    (0.78, 0.67),
                    (0.84, 0.58),
                ],
            },
            {
                "name": "Threshold band: around 1.3g",
                "vectors": [
                    (0.92, 0.92),
                    (1.00, 0.84),
                    (1.10, 0.72),
                ],
            },
            {
                "name": "LIMIT: heavy braking + turn-in",
                "vectors": [
                    (-0.45, 0.55),
                    (-0.62, 0.58),
                    (-0.72, 0.60),
                ],
            },
            {
                "name": "OVER: combined high load",
                "vectors": [
                    (0.80, 0.85),
                    (0.95, 0.90),
                    (1.05, 0.92),
                ],
            },
            {
                "name": "Direction check: pure lateral",
                "vectors": [
                    (0.00, -0.30),
                    (0.00, -0.60),
                    (0.00, -0.90),
                ],
            },
            {
                "name": "Direction check: pure longitudinal",
                "vectors": [
                    (-0.20, 0.00),
                    (-0.50, 0.00),
                    (-0.85, 0.00),
                ],
            },
        ]

        rows = []

        for scenario in scenarios:
            lap = Lap()
            lap.data_accel_longitudinal_g = [vector[0] for vector in scenario["vectors"]]
            lap.data_accel_lateral_g = [vector[1] for vector in scenario["vectors"]]
            lap.data_accel_total_g = [
                math.sqrt((longitudinal * longitudinal) + (lateral * lateral))
                for longitudinal, lateral in scenario["vectors"]
            ]

            diagram = gt7diagrams.FrictionCircleDiagram(width=1200, height=900, history_seconds=2, tick_rate_hz=10)
            diagram.update_from_lap(lap)

            scenario_title = Div(
                text=f"<h3 style='margin-bottom:8px'>{scenario['name']}</h3>",
                width=1200,
            )
            rows.append([scenario_title])
            rows.append([diagram.get_layout()])

        out_file = "test_out/test_friction_circle_vector_scenarios.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(layout(children=rows, sizing_mode="stretch_width"))

        file_size = os.path.getsize(out_file)
        self.assertGreater(file_size, 30000)

        with open(out_file, 'r') as fp:
            html = fp.read()
            self.assertIn("SAFE: gentle acceleration", html)
            self.assertIn("OVER: combined high load", html)
            self.assertIn("Threshold band: around 0.7g", html)
            self.assertIn("Threshold band: around 1.0g", html)
            self.assertIn("Threshold band: around 1.3g", html)
            self.assertNotIn("Peripheral view mode", html)

    def test_friction_circle_color_thresholds(self):
        diagram = gt7diagrams.FrictionCircleDiagram(history_seconds=2, tick_rate_hz=10)

        # Inside limit should stay green.
        lap_safe = Lap()
        lap_safe.data_accel_longitudinal_g = [0.50]
        lap_safe.data_accel_lateral_g = [0.50]
        lap_safe.data_accel_total_g = [0.71]
        diagram.update_from_lap(lap_safe)
        self.assertEqual("#dcfce7", diagram.f_friction.background_fill_color)

        # Above limit (1.00g ring) should turn yellow.
        lap_limit = Lap()
        lap_limit.data_accel_longitudinal_g = [0.72]
        lap_limit.data_accel_lateral_g = [0.74]
        lap_limit.data_accel_total_g = [1.03]
        diagram.update_from_lap(lap_limit)
        self.assertEqual("#fef3c7", diagram.f_friction.background_fill_color)

        # Above over (1.30g ring) should turn red immediately.
        lap_over = Lap()
        lap_over.data_accel_longitudinal_g = [1.00]
        lap_over.data_accel_lateral_g = [0.98]
        lap_over.data_accel_total_g = [1.40]
        diagram.update_from_lap(lap_over)
        self.assertEqual("#fee2e2", diagram.f_friction.background_fill_color)
