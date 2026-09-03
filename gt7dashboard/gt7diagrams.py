import math
from typing import List, Optional, Union

import bokeh
from bokeh.events import MouseMove
from bokeh.layouts import column, row
from bokeh.models import (
    Column,
    ColumnDataSource,
    CrosshairTool,
    CustomJS,
    DataTable,
    Div,
    Label,
    Line,
    Range1d,
    RangeTool,
    Scatter,
    Select,
    TableColumn,
)
from bokeh.plotting import figure

from gt7dashboard import gt7helper
from gt7dashboard.gt7lap import Lap


def get_throttle_braking_race_line_diagram():
    # TODO Make this work, tooltips just show breakpoint
    race_line_tooltips = [("index", "$index")]
    s_race_line = figure(
        match_aspect=True,
        active_scroll="wheel_zoom",
        tooltips=race_line_tooltips,
    )

    # We set this to true, since maps appear flipped in the game
    # compared to their actual coordinates
    s_race_line.y_range.flipped = True

    s_race_line.toolbar.autohide = True
    s_race_line.title.visible = False

    s_race_line.axis.visible = False
    s_race_line.xgrid.visible = False
    s_race_line.ygrid.visible = False

    throttle_line = s_race_line.line(
        x="raceline_x_throttle",
        y="raceline_z_throttle",
        line_width=5,
        color="green",
        source=ColumnDataSource(
            data={"raceline_z_throttle": [], "raceline_x_throttle": []}
        ),
    )
    breaking_line = s_race_line.line(
        x="raceline_x_braking",
        y="raceline_z_braking",
        line_width=5,
        color="red",
        source=ColumnDataSource(
            data={"raceline_z_braking": [], "raceline_x_braking": []}
        ),
    )

    coasting_line = s_race_line.line(
        x="raceline_x_coasting",
        y="raceline_z_coasting",
        line_width=5,
        color="blue",
        source=ColumnDataSource(
            data={"raceline_z_coasting": [], "raceline_x_coasting": []}
        ),
    )

    # Reference Lap

    reference_throttle_line = s_race_line.line(
        x="raceline_x_throttle",
        y="raceline_z_throttle",
        line_width=15,
        alpha=0.3,
        color="green",
        source=ColumnDataSource(
            data={"raceline_z_throttle": [], "raceline_x_throttle": []}
        ),
    )
    reference_breaking_line = s_race_line.line(
        x="raceline_x_braking",
        y="raceline_z_braking",
        line_width=15,
        alpha=0.3,
        color="red",
        source=ColumnDataSource(
            data={"raceline_z_braking": [], "raceline_x_braking": []}
        ),
    )

    reference_coasting_line = s_race_line.line(
        x="raceline_x_coasting",
        y="raceline_z_coasting",
        line_width=15,
        alpha=0.3,
        color="blue",
        source=ColumnDataSource(
            data={"raceline_z_coasting": [], "raceline_x_coasting": []}
        ),
    )

    return (
        s_race_line,
        throttle_line,
        breaking_line,
        coasting_line,
        reference_throttle_line,
        reference_breaking_line,
        reference_coasting_line,
    )

class RaceTimeTable(object):

    def __init__(self):

        self.columns = [
            TableColumn(field="number", title="#"),
            TableColumn(field="time", title="Time"),
            TableColumn(field="diff", title="Diff"),
            TableColumn(field="timestamp", title="Timestamp"),
            TableColumn(field="info", title="Info"),
            TableColumn(field="fuelconsumed", title="Fuel Cons."),
            TableColumn(field="fullthrottle", title="Full Throt."),
            TableColumn(field="fullbreak", title="Full Brake"),
            TableColumn(field="nothrottle", title="Coast"),
            TableColumn(field="tyrespinning", title="Tire Spin"),
            TableColumn(field="car_name", title="Car"),
        ]

        self.lap_times_source = ColumnDataSource(
            gt7helper.pd_data_frame_from_lap([], best_lap_time=0)
        )
        self.t_lap_times: DataTable

        self.t_lap_times = DataTable(
            source=self.lap_times_source, columns=self.columns, index_position=None, css_classes=["lap_times_table"]
        )
        # This will lead to not being rendered
        # self.t_lap_times.autosize_mode = "fit_columns"
        # Maybe this is related: https://github.com/bokeh/bokeh/issues/10512 ?


    def show_laps(self, laps: List[Lap]):
        best_lap = gt7helper.get_best_lap(laps)
        if best_lap == None:
            return

        new_df = gt7helper.pd_data_frame_from_lap(laps, best_lap_time=best_lap.lap_finish_time)
        self.lap_times_source.data = ColumnDataSource.from_df(new_df)

class RaceDiagram(object):
    DEFAULT_WINDOW_METERS = 250
    STEERING_DEFAULT_EXTENT_DEGREES = 10
    STEERING_RANGE_STEP_DEGREES = 5
    STEERING_RANGE_HEADROOM = 1.1
    WINDOW_OPTIONS = [
        ("100", "100 m"),
        ("250", "250 m"),
        ("500", "500 m"),
        ("1000", "1,000 m"),
        ("full", "Full lap"),
    ]

    def __init__(self, width=400):
        """Build the linked distance-based telemetry plots."""
        self.speed_lines = []
        self.braking_lines = []
        self.coasting_lines = []
        self.throttle_lines = []
        self.steering_lines = []
        self.tires_lines = []
        self.rpm_lines = []
        self.gears_lines = []
        self.boost_lines = []
        self.yaw_rate_lines = []

        self.source_time_diff = None
        self.source_speed_variance = None
        self.source_last_lap = None
        self.source_reference_lap = None
        self.source_median_lap = None
        self.sources_additional_laps = []
        self._renderer_groups = {}
        self._additional_source_ids = []
        self._lap_distance_max = 0.0

        self.additional_laps = []
        self.number_of_default_laps = 3

        tooltips = [
            ("Distance", "@distance{0} m"),
            ("Speed", "@speed{0} km/h"),
            ("Throttle", "@throttle{0}%"),
            ("Brake", "@brake{0}%"),
            ("Coast", "@coast{0}%"),
            ("Steering", "@steering_angle{0.0}°"),
            ("Yaw Rate", "@yaw_rate{0.00}"),
            ("Gear", "@gear"),
            ("Rev", "@rpm{0} RPM"),
            ("Boost", "@boost{0.00} x 100 kPa"),
        ]
        tooltips_timedelta = [
            ("Distance", "@distance{0} m"),
            ("Comparison − Reference", "@timedelta{0} ms"),
            ("Reference", "@reference{0} ms"),
            ("Comparison", "@comparison{0} ms"),
        ]
        self.tooltips_speed_variance = [
            ("Distance", "@distance{0} m"),
            ("Spd. Deviation", "@speed_variance{0}"),
        ]

        # The selected range is always expressed in metres. All telemetry plots
        # share this exact object, so a RangeTool interaction updates them as one.
        self.analysis_range = Range1d(
            start=0,
            end=self.DEFAULT_WINDOW_METERS,
            bounds=(0, None),
        )
        self.full_lap_range = Range1d(start=0, end=1000, bounds=(0, None))

        def telemetry_figure(y_axis_label, height, y_range=None, tooltips_override=None):
            figure_options = dict(
                y_axis_label=y_axis_label,
                x_range=self.analysis_range,
                width=width,
                height=height,
                sizing_mode="stretch_width",
                tooltips=tooltips_override or tooltips,
                active_drag="box_zoom",
            )
            if y_range is not None:
                figure_options["y_range"] = y_range
            return figure(**figure_options)

        self.f_time_diff = telemetry_figure(
            "Delta (ms)",
            110,
            tooltips_override=tooltips_timedelta,
        )
        self.f_speed = telemetry_figure("Speed (km/h)", 225)
        self.f_pedal_inputs = telemetry_figure(
            "Input (%)",
            195,
            y_range=Range1d(0, 100),
        )
        # Compatibility aliases for integrations that still refer to the old
        # separate figures. Both now intentionally point at the combined plot.
        self.f_throttle = self.f_pedal_inputs
        self.f_braking = self.f_pedal_inputs
        self.f_steering = telemetry_figure(
            "Angle (deg)",
            140,
            y_range=Range1d(
                -self.STEERING_DEFAULT_EXTENT_DEGREES,
                self.STEERING_DEFAULT_EXTENT_DEGREES,
            ),
        )

        self.f_speed_variance = telemetry_figure(
            "Spd. Dev.",
            150,
            y_range=Range1d(0, 50),
            tooltips_override=self.tooltips_speed_variance,
        )
        self.f_coasting = telemetry_figure(
            "Coasting (%)", 150, y_range=Range1d(0, 100)
        )
        self.f_tires = telemetry_figure("Ratio", 160)
        self.f_rpm = telemetry_figure("RPM", 160)
        self.f_gear = telemetry_figure("Gear", 130)
        self.f_boost = telemetry_figure("Boost", 150)
        self.f_yaw_rate = telemetry_figure("Yaw Rate / Second", 160)

        all_figures = [
            self.f_time_diff,
            self.f_speed,
            self.f_pedal_inputs,
            self.f_steering,
            self.f_speed_variance,
            self.f_coasting,
            self.f_tires,
            self.f_rpm,
            self.f_gear,
            self.f_boost,
            self.f_yaw_rate,
        ]
        for telemetry_plot in all_figures:
            telemetry_plot.toolbar.autohide = True
            telemetry_plot.min_border_left = 65
            telemetry_plot.min_border_top = 2
            telemetry_plot.min_border_bottom = 8
            telemetry_plot.title.visible = False
            telemetry_plot.xaxis.axis_label = None

        # The primary graphs share a single visible distance scale at the
        # bottom of the stack. Auxiliary-tab graphs retain ticks because they
        # are viewed one at a time.
        for telemetry_plot in [
            self.f_time_diff,
            self.f_speed,
            self.f_pedal_inputs,
        ]:
            telemetry_plot.xaxis.visible = False
            telemetry_plot.min_border_bottom = 2

        # Keep one shared vertical cursor across all of the numeric plots.
        self.shared_crosshair = bokeh.models.Span(
            dimension="height", line_color="#6b7280", line_alpha=0.65, line_width=1
        )
        for telemetry_plot in all_figures:
            telemetry_plot.add_tools(
                CrosshairTool(dimensions="height", overlay=self.shared_crosshair)
            )

        span_zero_time_diff = bokeh.models.Span(
            location=0,
            dimension="width",
            line_color="black",
            line_dash="dashed",
            line_width=1,
        )
        self.f_time_diff.add_layout(span_zero_time_diff)

        self.source_time_diff = ColumnDataSource(
            data={"distance": [], "timedelta": [], "reference": [], "comparison": []}
        )
        self.f_time_diff.line(
            x="distance",
            y="timedelta",
            source=self.source_time_diff,
            line_width=2,
            color="#2563eb",
            line_alpha=1,
        )

        self.source_last_lap = self.add_lap_to_race_diagram(
            "#2563eb", "Last Lap", True
        )
        self.source_reference_lap = self.add_lap_to_race_diagram(
            "#a21caf", "Reference Lap", True
        )
        self.source_median_lap = self.add_lap_to_race_diagram(
            "#64748b", "Median Lap", False
        )

        self.source_speed_variance = ColumnDataSource(
            data={"distance": [], "speed_variance": []}
        )
        self.f_speed_variance.line(
            x="distance",
            y="speed_variance",
            source=self.source_speed_variance,
            line_width=2,
            color="#64748b",
            line_alpha=1,
            visible=True,
        )

        self.f_overview = figure(
            x_range=self.full_lap_range,
            width=width,
            height=100,
            sizing_mode="stretch_width",
            toolbar_location=None,
            tools="",
        )
        overview_renderer = self.f_overview.line(
            x="distance",
            y="speed",
            source=self.source_last_lap,
            line_width=2,
            color="#2563eb",
        )
        self._register_renderer(
            self.source_last_lap, self.f_overview, overview_renderer
        )
        overview_reference_renderer = self.f_overview.line(
            x="distance",
            y="speed",
            source=self.source_reference_lap,
            line_width=2,
            color="#a21caf",
            line_dash="dashed",
        )
        self._register_renderer(
            self.source_reference_lap,
            self.f_overview,
            overview_reference_renderer,
        )
        self.f_overview.yaxis.visible = False
        self.f_overview.ygrid.visible = False
        self.f_overview.min_border_left = 65
        self.f_overview.min_border_top = 2
        self.f_overview.min_border_bottom = 8
        self.f_overview.title.visible = False
        self.f_overview.xaxis.axis_label = None

        self.range_tool = RangeTool(x_range=self.analysis_range)
        self.range_tool.overlay.fill_color = "#2563eb"
        self.range_tool.overlay.fill_alpha = 0.18
        self.f_overview.add_tools(self.range_tool)

        self.window_select = Select(
            title="Analysis window",
            value=str(self.DEFAULT_WINDOW_METERS),
            options=self.WINDOW_OPTIONS,
            width=150,
        )
        self.window_label = Div(text="0–250 m · 250 m window", width=300)
        self.window_select.on_change("value", self._on_window_size_change)
        label_callback = CustomJS(
            args=dict(selected_range=self.analysis_range, label=self.window_label),
            code="""
                const start = Math.max(0, Number(selected_range.start) || 0)
                const end = Math.max(start, Number(selected_range.end) || start)
                const roundedStart = Math.round(start).toLocaleString()
                const roundedEnd = Math.round(end).toLocaleString()
                const width = Math.round(end - start).toLocaleString()
                label.text = `${roundedStart}–${roundedEnd} m · ${width} m window`
            """,
        )
        self.analysis_range.js_on_change("start", label_callback)
        self.analysis_range.js_on_change("end", label_callback)

        self.steering_empty_state = Div(
            text=(
                "<div style='padding:28px 16px;text-align:center;color:#64748b;'>"
                "Steering angle is unavailable for these laps. Record with packet format C."
                "</div>"
            ),
            visible=True,
            height=90,
            sizing_mode="stretch_width",
        )
        self.f_steering.visible = False
        self.steering_view = column(
            self.f_steering,
            self.steering_empty_state,
            sizing_mode="stretch_width",
        )

        self.navigator_layout = column(
            row(self.window_select, self.window_label, sizing_mode="stretch_width"),
            self.f_overview,
            sizing_mode="stretch_width",
            spacing=4,
        )
        self.primary_layout = column(
            self.navigator_layout,
            self.f_time_diff,
            self.f_speed,
            self.f_pedal_inputs,
            self.steering_view,
            sizing_mode="stretch_width",
            spacing=4,
        )
        self.secondary_layout = column(
            self.f_speed_variance,
            self.f_yaw_rate,
            self.f_coasting,
            self.f_gear,
            self.f_rpm,
            self.f_boost,
            self.f_tires,
            sizing_mode="stretch_width",
            spacing=4,
        )
        self.layout = column(
            self.primary_layout,
            self.secondary_layout,
            sizing_mode="stretch_width",
            spacing=8,
        )

    @staticmethod
    def _line_dash_for_legend(legend):
        if legend == "Reference Lap":
            return "dashed"
        if legend == "Median Lap":
            return "dotted"
        if legend == "Last Lap":
            return "solid"
        return "dotdash"

    def _register_renderer(self, source, telemetry_plot, renderer):
        self._renderer_groups.setdefault(source.id, []).append(
            (telemetry_plot, renderer)
        )

    def _add_renderer(self, source, telemetry_plot, collection, **kwargs):
        renderer = telemetry_plot.line(source=source, **kwargs)
        collection.append(renderer)
        self._register_renderer(source, telemetry_plot, renderer)
        return renderer

    def _on_window_size_change(self, attr, old, new):
        if new == "full":
            requested_width = self._lap_distance_max
        else:
            requested_width = float(new)

        if self._lap_distance_max <= 0:
            return

        requested_width = min(requested_width, self._lap_distance_max)
        center = (self.analysis_range.start + self.analysis_range.end) / 2
        start = max(0, center - requested_width / 2)
        end = min(self._lap_distance_max, start + requested_width)
        start = max(0, end - requested_width)
        self._set_analysis_range(start, end)

    def _set_analysis_range(self, start, end):
        self.analysis_range.start = start
        self.analysis_range.end = end
        self.analysis_range.reset_start = start
        self.analysis_range.reset_end = end
        self._update_window_label()

    def _update_window_label(self):
        start = max(0, float(self.analysis_range.start or 0))
        end = max(start, float(self.analysis_range.end or start))
        self.window_label.text = (
            f"{start:,.0f}–{end:,.0f} m · {end - start:,.0f} m window"
        )

    def update_analysis_domain(self, distances):
        valid_distances = []
        for distance in distances:
            try:
                numeric_distance = float(distance)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric_distance) and numeric_distance >= 0:
                valid_distances.append(numeric_distance)
        if not valid_distances:
            return

        previous_max = self._lap_distance_max
        previous_width = self.analysis_range.end - self.analysis_range.start
        was_full_lap = previous_max > 0 and previous_width >= previous_max - 1
        self._lap_distance_max = max(valid_distances)

        self.full_lap_range.bounds = (0, self._lap_distance_max)
        self.analysis_range.bounds = (0, self._lap_distance_max)
        self.full_lap_range.start = 0
        self.full_lap_range.end = self._lap_distance_max
        self.full_lap_range.reset_start = 0
        self.full_lap_range.reset_end = self._lap_distance_max

        if previous_max <= 0:
            requested_width = min(
                self.DEFAULT_WINDOW_METERS, self._lap_distance_max
            )
            self._set_analysis_range(0, requested_width)
        elif was_full_lap or self.window_select.value == "full":
            self._set_analysis_range(0, self._lap_distance_max)
        else:
            requested_width = min(previous_width, self._lap_distance_max)
            start = min(self.analysis_range.start, self._lap_distance_max - requested_width)
            self._set_analysis_range(max(0, start), max(0, start) + requested_width)

    def clear_analysis_domain(self):
        self._lap_distance_max = 0.0
        self.full_lap_range.bounds = (0, None)
        self.analysis_range.bounds = (0, None)
        self.full_lap_range.start = 0
        self.full_lap_range.end = 1000
        self.full_lap_range.reset_start = 0
        self.full_lap_range.reset_end = 1000
        self.window_select.value = str(self.DEFAULT_WINDOW_METERS)
        self._set_analysis_range(0, self.DEFAULT_WINDOW_METERS)

    def update_steering_visibility(self):
        sources = [
            self.source_last_lap,
            self.source_reference_lap,
            *self.sources_additional_laps,
        ]
        steering_values = []
        for source in sources:
            if source is None:
                continue
            for value in source.data.get("steering_angle", []):
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(numeric_value):
                    steering_values.append(numeric_value)

        self.f_steering.visible = bool(steering_values)
        self.steering_empty_state.visible = not steering_values
        self._update_steering_range(steering_values)

    def _update_steering_range(self, steering_values):
        """Keep a compact symmetric steering scale without clipping real data."""
        maximum_observed_extent = max(
            (abs(value) for value in steering_values), default=0
        )
        required_extent = max(
            self.STEERING_DEFAULT_EXTENT_DEGREES,
            maximum_observed_extent * self.STEERING_RANGE_HEADROOM,
        )
        extent = math.ceil(
            required_extent / self.STEERING_RANGE_STEP_DEGREES
        ) * self.STEERING_RANGE_STEP_DEGREES

        self.f_steering.y_range.start = -extent
        self.f_steering.y_range.end = extent
        self.f_steering.y_range.reset_start = -extent
        self.f_steering.y_range.reset_end = extent

    def add_additional_lap_to_race_diagram(
        self,
        color: str,
        lap: Lap,
        visible: bool = True,
        line_dash: Optional[Union[str, List[int]]] = None,
    ):
        source = self.add_lap_to_race_diagram(
            color,
            lap.title,
            visible,
            additional=True,
            line_dash=line_dash,
        )
        source.data = lap.get_data_dict()
        self.sources_additional_laps.append(source)
        self.update_steering_visibility()
        return source

    def update_fastest_laps_variance(self, laps):
        variance, fastest_laps = gt7helper.get_variance_for_fastest_laps(laps)
        self.source_speed_variance.data = variance
        return fastest_laps

    def add_lap_to_race_diagram(
        self,
        color: str,
        legend: str,
        visible: bool = True,
        additional=False,
        line_dash: Optional[Union[str, List[int]]] = None,
    ):
        source = ColumnDataSource(data=Lap().get_data_dict())
        if line_dash is None:
            line_dash = self._line_dash_for_legend(legend)

        self._add_renderer(
            source,
            self.f_speed,
            self.speed_lines,
            x="distance",
            y="speed",
            line_width=2,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.95,
            visible=visible,
        )
        throttle_options = dict(
            x="distance",
            y="throttle",
            line_width=2,
            line_color="#16a34a",
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )
        brake_options = dict(
            x="distance",
            y="brake",
            line_width=2,
            line_color="#dc2626",
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )
        steering_options = dict(
            x="distance",
            y="steering_angle",
            line_width=2,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.95,
            visible=visible,
        )
        self._add_renderer(
            source,
            self.f_pedal_inputs,
            self.throttle_lines,
            **throttle_options,
        )
        self._add_renderer(
            source,
            self.f_pedal_inputs,
            self.braking_lines,
            **brake_options,
        )
        self._add_renderer(
            source,
            self.f_steering,
            self.steering_lines,
            **steering_options,
        )
        self._add_renderer(
            source,
            self.f_coasting,
            self.coasting_lines,
            x="distance",
            y="coast",
            line_width=1,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )
        self._add_renderer(
            source,
            self.f_tires,
            self.tires_lines,
            x="distance",
            y="tires",
            line_width=1,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )
        self._add_renderer(
            source,
            self.f_gear,
            self.gears_lines,
            x="distance",
            y="gear",
            line_width=1,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )
        self._add_renderer(
            source,
            self.f_rpm,
            self.rpm_lines,
            x="distance",
            y="rpm",
            line_width=1,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )
        self._add_renderer(
            source,
            self.f_boost,
            self.boost_lines,
            x="distance",
            y="boost",
            line_width=1,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )
        self._add_renderer(
            source,
            self.f_yaw_rate,
            self.yaw_rate_lines,
            x="distance",
            y="yaw_rate",
            line_width=1,
            line_color=color,
            line_dash=line_dash,
            line_alpha=0.9,
            visible=visible,
        )

        if additional:
            self._additional_source_ids.append(source.id)
        return source

    def get_layout(self) -> Column:
        return self.layout

    def delete_all_additional_laps(self):
        removed_renderers = set()
        for source_id in self._additional_source_ids:
            for telemetry_plot, renderer in self._renderer_groups.pop(source_id, []):
                if renderer in telemetry_plot.renderers:
                    telemetry_plot.renderers.remove(renderer)
                removed_renderers.add(renderer)

        for collection in [
            self.speed_lines,
            self.throttle_lines,
            self.braking_lines,
            self.steering_lines,
            self.coasting_lines,
            self.tires_lines,
            self.gears_lines,
            self.rpm_lines,
            self.boost_lines,
            self.yaw_rate_lines,
        ]:
            collection[:] = [
                renderer for renderer in collection if renderer not in removed_renderers
            ]

        self.sources_additional_laps = []
        self._additional_source_ids = []
        self.update_steering_visibility()


class LinkedRaceLine(object):
    """Race-line detail and context plots linked to a distance Range1d."""

    def __init__(self, analysis_range: Range1d, width=360):
        self.analysis_range = analysis_range
        empty_data = {"distance": [], "raceline_x": [], "raceline_z": []}
        self.full_last_source = ColumnDataSource(data=empty_data.copy())
        self.full_reference_source = ColumnDataSource(data=empty_data.copy())
        self.last_segment_source = ColumnDataSource(data=empty_data.copy())
        self.reference_segment_source = ColumnDataSource(data=empty_data.copy())
        self.cursor_source = ColumnDataSource(
            data={"raceline_x": [], "raceline_z": [], "distance": []}
        )

        self.x_range = Range1d(start=-1, end=1)
        # A reversed range matches the in-game orientation used by the existing map.
        self.y_range = Range1d(start=1, end=-1)
        self.figure = figure(
            x_range=self.x_range,
            y_range=self.y_range,
            match_aspect=True,
            width=width,
            height=390,
            sizing_mode="stretch_width",
            tools="pan,wheel_zoom,box_zoom,reset,save",
            active_scroll="wheel_zoom",
        )
        self.last_renderer = self.figure.line(
            x="raceline_x",
            y="raceline_z",
            source=self.last_segment_source,
            line_width=3,
            line_color="#2563eb",
        )
        self.reference_renderer = self.figure.line(
            x="raceline_x",
            y="raceline_z",
            source=self.reference_segment_source,
            line_width=3,
            line_color="#a21caf",
            line_dash="dashed",
        )
        self.figure.scatter(
            x="raceline_x",
            y="raceline_z",
            source=self.cursor_source,
            marker="circle",
            size=9,
            fill_color="#f59e0b",
            line_color="white",
            line_width=2,
        )
        self.figure.axis.visible = False
        self.figure.grid.visible = False
        self.figure.toolbar.autohide = True
        self.figure.title.visible = False

        self.context_figure = figure(
            match_aspect=True,
            width=width,
            height=170,
            sizing_mode="stretch_width",
            toolbar_location=None,
            tools="",
        )
        self.context_figure.line(
            x="raceline_x",
            y="raceline_z",
            source=self.full_last_source,
            line_width=2,
            line_color="#94a3b8",
            line_alpha=0.7,
        )
        self.context_figure.line(
            x="raceline_x",
            y="raceline_z",
            source=self.last_segment_source,
            line_width=4,
            line_color="#2563eb",
        )
        self.context_figure.line(
            x="raceline_x",
            y="raceline_z",
            source=self.reference_segment_source,
            line_width=3,
            line_color="#a21caf",
            line_dash="dashed",
        )
        self.context_figure.y_range.flipped = True
        self.context_figure.axis.visible = False
        self.context_figure.grid.visible = False
        self.context_figure.title.visible = False

        self.layout = column(
            self.figure,
            self.context_figure,
            width=width,
            sizing_mode="stretch_width",
            spacing=4,
        )

        self.range_callback = CustomJS(
            args=dict(
                selected_range=self.analysis_range,
                full_last=self.full_last_source,
                full_reference=self.full_reference_source,
                last_segment=self.last_segment_source,
                reference_segment=self.reference_segment_source,
                cursor=self.cursor_source,
                map_x_range=self.x_range,
                map_y_range=self.y_range,
            ),
            code="""
                const start = Math.min(selected_range.start, selected_range.end)
                const end = Math.max(selected_range.start, selected_range.end)

                function selectedData(source) {
                    const distances = source.data.distance || []
                    const xs = source.data.raceline_x || []
                    const zs = source.data.raceline_z || []
                    const result = {distance: [], raceline_x: [], raceline_z: []}
                    const count = Math.min(distances.length, xs.length, zs.length)
                    for (let index = 0; index < count; index++) {
                        const distance = distances[index]
                        if (distance >= start && distance <= end && xs[index] != null && zs[index] != null) {
                            result.distance.push(distance)
                            result.raceline_x.push(xs[index])
                            result.raceline_z.push(zs[index])
                        }
                    }
                    return result
                }

                const lastData = selectedData(full_last)
                const referenceData = selectedData(full_reference)
                last_segment.data = lastData
                reference_segment.data = referenceData

                const allX = lastData.raceline_x.concat(referenceData.raceline_x)
                const allZ = lastData.raceline_z.concat(referenceData.raceline_z)
                if (allX.length > 0 && allZ.length > 0) {
                    let minX = allX[0]
                    let maxX = allX[0]
                    let minZ = allZ[0]
                    let maxZ = allZ[0]
                    for (let index = 1; index < allX.length; index++) {
                        minX = Math.min(minX, allX[index])
                        maxX = Math.max(maxX, allX[index])
                    }
                    for (let index = 1; index < allZ.length; index++) {
                        minZ = Math.min(minZ, allZ[index])
                        maxZ = Math.max(maxZ, allZ[index])
                    }
                    const span = Math.max(maxX - minX, maxZ - minZ, 1) * 1.16
                    const centerX = (minX + maxX) / 2
                    const centerZ = (minZ + maxZ) / 2
                    map_x_range.start = centerX - span / 2
                    map_x_range.end = centerX + span / 2
                    map_y_range.start = centerZ + span / 2
                    map_y_range.end = centerZ - span / 2
                    map_x_range.reset_start = map_x_range.start
                    map_x_range.reset_end = map_x_range.end
                    map_y_range.reset_start = map_y_range.start
                    map_y_range.reset_end = map_y_range.end
                }

                if (lastData.distance.length > 0) {
                    const target = (start + end) / 2
                    let nearest = 0
                    let nearestDelta = Math.abs(lastData.distance[0] - target)
                    for (let index = 1; index < lastData.distance.length; index++) {
                        const delta = Math.abs(lastData.distance[index] - target)
                        if (delta < nearestDelta) {
                            nearest = index
                            nearestDelta = delta
                        }
                    }
                    cursor.data = {
                        distance: [lastData.distance[nearest]],
                        raceline_x: [lastData.raceline_x[nearest]],
                        raceline_z: [lastData.raceline_z[nearest]],
                    }
                } else {
                    cursor.data = {distance: [], raceline_x: [], raceline_z: []}
                }
            """,
        )
        self.analysis_range.js_on_change("start", self.range_callback)
        self.analysis_range.js_on_change("end", self.range_callback)

    @staticmethod
    def _race_line_data(lap_data):
        if not lap_data:
            return {"distance": [], "raceline_x": [], "raceline_z": []}

        distances = lap_data.get("distance", [])
        xs = lap_data.get("raceline_x", [])
        zs = lap_data.get("raceline_z", [])
        count = min(len(distances), len(xs), len(zs))
        result = {"distance": [], "raceline_x": [], "raceline_z": []}
        for index in range(count):
            distance = distances[index]
            x = xs[index]
            z = zs[index]
            if distance is None or x is None or z is None:
                continue
            result["distance"].append(float(distance))
            result["raceline_x"].append(float(x))
            result["raceline_z"].append(float(z))
        return result

    @staticmethod
    def _selected_data(source_data, start, end):
        selected = {"distance": [], "raceline_x": [], "raceline_z": []}
        for distance, x, z in zip(
            source_data["distance"],
            source_data["raceline_x"],
            source_data["raceline_z"],
        ):
            if start <= distance <= end:
                selected["distance"].append(distance)
                selected["raceline_x"].append(x)
                selected["raceline_z"].append(z)
        return selected

    def update_laps(self, last_lap_data, reference_lap_data=None):
        self.full_last_source.data = self._race_line_data(last_lap_data)
        self.full_reference_source.data = self._race_line_data(reference_lap_data)
        self.update_selected_segment()

    def link_cursor_to_plots(self, plots):
        cursor_callback = CustomJS(
            args=dict(full_last=self.full_last_source, cursor=self.cursor_source),
            code="""
                const distances = full_last.data.distance || []
                const xs = full_last.data.raceline_x || []
                const zs = full_last.data.raceline_z || []
                const count = Math.min(distances.length, xs.length, zs.length)
                if (count === 0 || cb_obj.x == null) {
                    return
                }

                const target = cb_obj.x
                let low = 0
                let high = count - 1
                while (low < high) {
                    const middle = Math.floor((low + high) / 2)
                    if (distances[middle] < target) {
                        low = middle + 1
                    } else {
                        high = middle
                    }
                }
                let nearest = low
                if (nearest > 0 && Math.abs(distances[nearest - 1] - target) < Math.abs(distances[nearest] - target)) {
                    nearest -= 1
                }
                cursor.data = {
                    distance: [distances[nearest]],
                    raceline_x: [xs[nearest]],
                    raceline_z: [zs[nearest]],
                }
            """,
        )
        for telemetry_plot in plots:
            telemetry_plot.js_on_event(MouseMove, cursor_callback)

    def update_selected_segment(self):
        start = min(self.analysis_range.start, self.analysis_range.end)
        end = max(self.analysis_range.start, self.analysis_range.end)
        last_data = self._selected_data(self.full_last_source.data, start, end)
        reference_data = self._selected_data(
            self.full_reference_source.data, start, end
        )
        self.last_segment_source.data = last_data
        self.reference_segment_source.data = reference_data

        all_x = last_data["raceline_x"] + reference_data["raceline_x"]
        all_z = last_data["raceline_z"] + reference_data["raceline_z"]
        if all_x and all_z:
            min_x, max_x = min(all_x), max(all_x)
            min_z, max_z = min(all_z), max(all_z)
            span = max(max_x - min_x, max_z - min_z, 1) * 1.16
            center_x = (min_x + max_x) / 2
            center_z = (min_z + max_z) / 2
            self.x_range.start = center_x - span / 2
            self.x_range.end = center_x + span / 2
            self.y_range.start = center_z + span / 2
            self.y_range.end = center_z - span / 2
            self.x_range.reset_start = self.x_range.start
            self.x_range.reset_end = self.x_range.end
            self.y_range.reset_start = self.y_range.start
            self.y_range.reset_end = self.y_range.end

        if last_data["distance"]:
            center_distance = (start + end) / 2
            nearest_index = min(
                range(len(last_data["distance"])),
                key=lambda index: abs(
                    last_data["distance"][index] - center_distance
                ),
            )
            self.cursor_source.data = {
                "distance": [last_data["distance"][nearest_index]],
                "raceline_x": [last_data["raceline_x"][nearest_index]],
                "raceline_z": [last_data["raceline_z"][nearest_index]],
            }
        else:
            self.cursor_source.data = {
                "distance": [],
                "raceline_x": [],
                "raceline_z": [],
            }

    def get_layout(self):
        return self.layout






def add_annotations_to_race_line(
    race_line: figure, last_lap: Lap, reference_lap: Lap
):
    """ Adds annotations such as speed peaks and valleys and the starting line to the racing line"""

    remove_all_annotation_text_from_figure(race_line)

    decorations = []
    decorations.extend(
        _add_peaks_and_valley_decorations_for_lap(
            last_lap, race_line, color="blue", offset=0
        )
    )
    decorations.extend(
        _add_peaks_and_valley_decorations_for_lap(
            reference_lap, race_line, color="magenta", offset=0
        )
    )
    add_starting_line_to_diagram(race_line, last_lap)

    # This is multiple times faster by adding all texts at once rather than adding them above
    # With around 20 positions, this took 27s before.
    # Maybe this has something to do with every text being transmitted over network
    race_line.center.extend(decorations)

    # Add peaks and valleys of last lap


def _add_peaks_and_valley_decorations_for_lap(
    lap: Lap, race_line: figure, color, offset
):
    (
        peak_speed_data_x,
        peak_speed_data_y,
        valley_speed_data_x,
        valley_speed_data_y,
    ) = lap.get_speed_peaks_and_valleys()

    decorations = []

    for i in range(len(peak_speed_data_x)):
        # shift 10 px to the left
        position_x = lap.data_position_x[peak_speed_data_y[i]]
        position_y = lap.data_position_z[peak_speed_data_y[i]]

        mytext = Label(
            x=position_x,
            y=position_y,
            text_color=color,
            text_font_size="10pt",
            text_font_style="bold",
            x_offset=offset,
            background_fill_color="white",
            background_fill_alpha=0.75,
        )
        mytext.text = "▴%.0f" % peak_speed_data_x[i]

        decorations.append(mytext)

    for i in range(len(valley_speed_data_x)):
        position_x = lap.data_position_x[valley_speed_data_y[i]]
        position_y = lap.data_position_z[valley_speed_data_y[i]]

        mytext = Label(
            x=position_x,
            y=position_y,
            text_color=color,
            text_font_size="10pt",
            x_offset=offset,
            text_font_style="bold",
            background_fill_color="white",
            background_fill_alpha=0.75,
            text_align="right",
        )
        mytext.text = "%.0f▾" % valley_speed_data_x[i]

        decorations.append(mytext)

    return decorations


def remove_all_annotation_text_from_figure(f: figure):
    f.center = [r for r in f.center if not isinstance(r, Label)]


def get_fuel_map_html_table(last_lap: Lap) -> str:
    """
    Returns a html table of relative fuel map.
    :param last_lap:
    :return: html table
    """

    fuel_maps = gt7helper.get_fuel_on_consumption_by_relative_fuel_levels(last_lap)
    table = (
        "<table><tr>"
        "<th title='The fuel level relative to the current one'>Fuel Lvl.</th>"
        "<th title='Fuel consumed'>Fuel Cons.</th>"
        "<th title='Laps remaining with this setting'>Laps Rem.</th>"
        "<th title='Time remaining with this setting' >Time Rem.</th>"
        "<th title='Time Diff to last lap with this setting'>Time Diff</th></tr>"
    )
    for fuel_map in fuel_maps:
        no_fuel_consumption = fuel_map.fuel_consumed_per_lap <= 0
        line_style = ""
        if fuel_map.mixture_setting == 0 and not no_fuel_consumption:
            line_style = "background-color:rgba(0,255,0,0.5)"
        table += (
                "<tr id='fuel_map_row_%d' style='%s'>"
                "<td style='text-align:center'>%d</td>"
                "<td style='text-align:center'>%d</td>"
                "<td style='text-align:center'>%.1f</td>"
                "<td style='text-align:center'>%s</td>"
                "<td style='text-align:center'>%s</td>"
                "</tr>"
                % (
                    fuel_map.mixture_setting,
                    line_style,
                    fuel_map.mixture_setting,
                    0 if no_fuel_consumption else fuel_map.fuel_consumed_per_lap,
                    0 if no_fuel_consumption else fuel_map.laps_remaining_on_current_fuel,
                    "No Fuel" if no_fuel_consumption else (gt7helper.seconds_to_lap_time(
                        fuel_map.time_remaining_on_current_fuel / 1000
                    )),
                    "Consumption" if no_fuel_consumption else (gt7helper.seconds_to_lap_time(fuel_map.lap_time_diff / 1000)),
                )
        )
    table += "</table>"
    table += "<p>Fuel Remaining: <b>%d</b></p>" % last_lap.fuel_at_end
    return table


def add_starting_line_to_diagram(race_line: figure, last_lap: Lap):

    if len(last_lap.data_position_z) == 0:
        return

    x = last_lap.data_position_x[0]
    y = last_lap.data_position_z[0]

    # We use a text because scatters are too memory consuming
    # and cannot be easily removed from the diagram
    mytext = Label(
        x=x,
        y=y,
        text_font_size="10pt",
        text_font_style="bold",
        background_fill_color="white",
        background_fill_alpha=0.25,
        text_align="center",
    )
    mytext.text = "===="
    race_line.center.append(mytext)

def get_speed_peak_and_valley_diagram(last_lap: Lap, reference_lap: Lap) -> str:
    """
    Returns a html div with the speed peaks and valleys of the last lap and the reference lap
    as a formatted html table
    :param last_lap: Lap
    :param reference_lap: Lap
    :return: html table with peaks and valleys
    """
    table = """<table style='border-spacing: 10px; text-align:center'>"""

    table += """<colgroup>
    <col/>
    <col style='border-left: 1px solid #cdd0d4;'/>
    <col/>
    <col/>
    <col style="background-color: lightblue;"/>
    <col/>
    <col/>
    <col/>
    <col style="background-color: thistle;"/>
    <col/>
  </colgroup>"""

    ll_tuple_list = gt7helper.get_peaks_and_valleys_sorted_tuple_list(last_lap)
    rl_tuple_list = gt7helper.get_peaks_and_valleys_sorted_tuple_list(reference_lap)

    max_data = max(len(ll_tuple_list), len(rl_tuple_list))

    table += '<tr>'

    table += '<th></th>'
    table += '<th colspan="4">%s - %s</th>' % ("Last", last_lap.title)
    table += '<th colspan="4">%s - %s</th>' % ("Ref.", reference_lap.title)
    table += '<th colspan="2">Diff</th>'

    table += '</tr>'

    table += """<tr>
    <td></td><td>#</td><td></td><td>Pos.</td><td>Speed</td>
    <td>#</td><td></td><td>Pos.</td><td>Speed</td>
    <td>Pos.</td><td>Speed</td>
    </tr>"""

    rl_and_ll_are_same_size = len(ll_tuple_list) == len(rl_tuple_list)

    i = 0
    while i < max_data:
        diff_pos = 0
        diff_speed = 0

        if rl_and_ll_are_same_size:
            diff_pos = ll_tuple_list[i][1] - rl_tuple_list[i][1]
            diff_speed = ll_tuple_list[i][0] - rl_tuple_list[i][0]

            if diff_speed > 0:
                diff_style = f"color: rgba(0, 0, 255, .3)" # Blue
            elif diff_speed >= -3:
                diff_style = f"color: rgba(0, 255, 0, .3)" # Green
            elif diff_speed >= -10:
                diff_style = f"color: rgba(251, 192, 147, .3)" # Orange
            else:
                diff_style = f"color: rgba(255, 0, 0, .3)" # Red

        else:
            diff_style = f"text-color: rgba(255, 0, 0, .3)" # Red

        table += '<tr>'
        table += f'<td style="width:15px; text-opacity:0.5; {diff_style}">█</td>'

        if len(ll_tuple_list) > i:
            table += f"""<td>{i+1}</td>
                <td>{"S" if ll_tuple_list[i][2] == gt7helper.PEAK else "T"}</td>
                <td>{ll_tuple_list[i][1]:d}</td>
                <td>{ll_tuple_list[i][0]:.0f}</td>
            """

        if len(rl_tuple_list) > i:
            table += f"""<td>{i+1}</td>
                <td>{"S" if rl_tuple_list[i][2] == gt7helper.PEAK else "T"}</td>
                <td>{rl_tuple_list[i][1]:d}</td>
                <td>{rl_tuple_list[i][0]:.0f}</td>
            """

        if rl_and_ll_are_same_size:
            table += f"""
                <td>{diff_pos:d}</td>
                <td>{diff_speed:.0f}</td>
            """
        else:
            table += f"""
                <td>-</td>
                <td>-</td>
            """



        table += '</tr>'
        i+=1



    table += '</td>'
    table += '<td>'

    table += '</td>'

    table = table + """</table>"""
    return table


def get_speed_peak_and_valley_diagram_row(peak_speed_data_x, peak_speed_data_y, table, valley_speed_data_x,
                                          valley_speed_data_y):
    row = ""

    row += "<tr><th>#</th><th>Peak</th><th>Position</th></tr>"
    for i, dx in enumerate(peak_speed_data_x):
        row += "<tr><td>%d.</td><td>%d kph</td><td>%d</td></tr>" % (
            i + 1,
            peak_speed_data_x[i],
            peak_speed_data_y[i],
        )
    row += "<tr><th>#</th><th>Valley</th><th>Position</th></tr>"
    for i, dx in enumerate(valley_speed_data_x):
        row += "<tr><td>%d.</td><td>%d kph</td><td>%d</td></tr>" % (
            i + 1,
            valley_speed_data_x[i],
            valley_speed_data_y[i],
        )
    return row
