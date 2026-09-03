import math
import os
import pickle
import unittest

from bokeh.io import output_file, show
from bokeh.layouts import layout
from bokeh.models import Div, Plot, Scatter, Label
from bokeh.plotting import save, figure

import gt7dashboard.gt7diagrams
import gt7dashboard.gt7helper
from gt7dashboard import gt7diagrams, gt7helper
from gt7dashboard.gt7diagrams import (
    LinkedRaceLine,
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

        self.assertFalse(race_line.title.visible)
        self.assertEqual(0, len(race_line.legend))

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

    def test_primary_plots_share_a_distance_window(self):
        rd = gt7diagrams.RaceDiagram(600)
        rd.update_analysis_domain([0, 500, 1000, 1500])

        self.assertIs(rd.analysis_range, rd.f_time_diff.x_range)
        self.assertIs(rd.analysis_range, rd.f_speed.x_range)
        self.assertIs(rd.analysis_range, rd.f_pedal_inputs.x_range)
        self.assertIs(rd.analysis_range, rd.f_steering.x_range)
        self.assertIs(rd.analysis_range, rd.range_tool.x_range)
        self.assertEqual(1500, rd.full_lap_range.end)
        self.assertEqual(0, rd.analysis_range.start)
        self.assertEqual(250, rd.analysis_range.end)

        rd.window_select.value = "500"
        self.assertEqual(500, rd.analysis_range.end - rd.analysis_range.start)

    def test_throttle_and_brake_share_positive_axis(self):
        rd = gt7diagrams.RaceDiagram(600)

        self.assertIs(rd.f_throttle, rd.f_braking)
        self.assertEqual(0, rd.f_pedal_inputs.y_range.start)
        self.assertEqual(100, rd.f_pedal_inputs.y_range.end)
        self.assertEqual("throttle", rd.throttle_lines[0].glyph.y)
        self.assertEqual("brake", rd.braking_lines[0].glyph.y)

    def test_compact_plot_chrome_uses_one_primary_distance_axis(self):
        rd = gt7diagrams.RaceDiagram(600)
        primary_plots = [
            rd.f_time_diff,
            rd.f_speed,
            rd.f_pedal_inputs,
            rd.f_steering,
        ]
        auxiliary_plots = [
            rd.f_speed_variance,
            rd.f_yaw_rate,
            rd.f_coasting,
            rd.f_gear,
            rd.f_rpm,
            rd.f_boost,
            rd.f_tires,
        ]

        for telemetry_plot in primary_plots + auxiliary_plots:
            self.assertFalse(telemetry_plot.title.visible)
            self.assertIsNone(telemetry_plot.xaxis[0].axis_label)
            self.assertEqual(0, len(telemetry_plot.legend))

        for telemetry_plot in primary_plots[:-1]:
            self.assertFalse(telemetry_plot.xaxis[0].visible)
        self.assertTrue(rd.f_steering.xaxis[0].visible)
        self.assertTrue(rd.f_speed_variance.xaxis[0].visible)
        self.assertFalse(rd.f_overview.title.visible)
        self.assertIsNone(rd.f_overview.xaxis[0].axis_label)

        race_line = LinkedRaceLine(rd.analysis_range)
        self.assertFalse(race_line.figure.title.visible)
        self.assertFalse(race_line.context_figure.title.visible)
        self.assertEqual(0, len(race_line.figure.legend))

    def test_steering_visibility_follows_available_data(self):
        rd = gt7diagrams.RaceDiagram(600)
        self.assertFalse(rd.f_steering.visible)
        self.assertTrue(rd.steering_empty_state.visible)
        self.assertEqual(-10, rd.f_steering.y_range.start)
        self.assertEqual(10, rd.f_steering.y_range.end)

        lap = self.test_laps[0]
        sample_count = len(lap.data_speed)
        lap.data_front_left_steering_angle_rad = [0.1] * sample_count
        lap.data_front_right_steering_angle_rad = [0.1] * sample_count
        rd.source_last_lap.data = lap.get_data_dict()
        rd.update_steering_visibility()

        self.assertTrue(rd.f_steering.visible)
        self.assertFalse(rd.steering_empty_state.visible)

    def test_steering_range_is_compact_and_expands_in_steps(self):
        rd = gt7diagrams.RaceDiagram(600)
        lap = self.test_laps[0]
        sample_count = len(lap.data_speed)

        lap.data_front_left_steering_angle_rad = [math.radians(7)] * sample_count
        lap.data_front_right_steering_angle_rad = [math.radians(7)] * sample_count
        rd.source_last_lap.data = lap.get_data_dict()
        rd.update_steering_visibility()

        self.assertEqual(-10, rd.f_steering.y_range.start)
        self.assertEqual(10, rd.f_steering.y_range.end)

        lap.data_front_left_steering_angle_rad = [math.radians(12)] * sample_count
        lap.data_front_right_steering_angle_rad = [math.radians(12)] * sample_count
        rd.source_reference_lap.data = lap.get_data_dict()
        rd.update_steering_visibility()

        self.assertEqual(-15, rd.f_steering.y_range.start)
        self.assertEqual(15, rd.f_steering.y_range.end)

        rd.update_analysis_domain([0, 500])
        rd._set_analysis_range(100, 500)
        self.assertEqual(-15, rd.f_steering.y_range.start)
        self.assertEqual(15, rd.f_steering.y_range.end)

    def test_linked_race_line_uses_selected_distance(self):
        rd = gt7diagrams.RaceDiagram(600)
        rd.update_analysis_domain([0, 100, 200, 300, 400])
        rd._set_analysis_range(100, 300)
        race_line = LinkedRaceLine(rd.analysis_range)
        lap_data = {
            "distance": [0, 100, 200, 300, 400],
            "raceline_x": [0, 1, 2, 3, 4],
            "raceline_z": [0, 2, 4, 2, 0],
        }

        race_line.update_laps(lap_data)

        self.assertEqual(
            [100.0, 200.0, 300.0],
            race_line.last_segment_source.data["distance"],
        )
        self.assertEqual([200.0], race_line.cursor_source.data["distance"])
        self.assertGreater(race_line.y_range.start, race_line.y_range.end)

    def test_add_5_additional_laps_to_race_diagram(self):

        rd = self.helper_get_race_diagram()

        # Add a random new lap to the mix
        # TODO Unfortunately, we have only 2 to pick from. Maybe improve this later
        pedal_renderers_before = len(rd.f_pedal_inputs.renderers)
        gray_lap_source = rd.add_additional_lap_to_race_diagram("gray", self.test_laps[1], True)

        # Should now contain 1 source
        self.assertEqual(1, len(rd.sources_additional_laps))
        self.assertEqual(
            pedal_renderers_before + 2, len(rd.f_pedal_inputs.renderers)
        )

        out_file = "test_out/test_add_5_additional_laps_to_race_diagram_with_additional_lap.html"
        print("View file for reference at %s" % out_file)
        output_file(out_file)
        save(rd.get_layout())

        rd.delete_all_additional_laps()
        self.assertEqual(0, len(rd.sources_additional_laps))
        self.assertEqual(pedal_renderers_before, len(rd.f_pedal_inputs.renderers))

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

    def test_additional_lap_can_use_a_distinct_line_dash(self):
        rd = self.helper_get_race_diagram()

        rd.add_additional_lap_to_race_diagram(
            "orange", self.test_laps[1], line_dash="dotted"
        )

        self.assertEqual([2, 4], rd.speed_lines[-1].glyph.line_dash)
        self.assertEqual([2, 4], rd.throttle_lines[-1].glyph.line_dash)


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
