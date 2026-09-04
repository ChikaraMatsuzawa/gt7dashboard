import copy
import html
import itertools
import logging
import os
import time
from typing import List

import bokeh.application
from bokeh.driving import linear
from bokeh.layouts import column, layout, row
from bokeh.models import (
    Select,
    MultiChoice,
    Paragraph,
    Button,
    ColumnDataSource,
    DataTable,
    Div,
    CheckboxGroup,
    TableColumn,
    TabPanel,
    Tabs,
)
from bokeh.palettes import Plasma11 as palette
from bokeh.plotting import curdoc
from bokeh.plotting import figure

from gt7dashboard import (
    gt7communication,
    gt7comparison,
    gt7diagrams,
    gt7help,
    gt7helper,
    gt7lap,
)
from gt7dashboard.gt7diagrams import get_speed_peak_and_valley_diagram

from gt7dashboard.gt7help import get_help_div
from gt7dashboard.gt7helper import (
    load_laps_from_pickle,
    save_laps_to_pickle,
    list_lap_files_from_path,
    calculate_time_diff_by_distance, save_laps_to_json, load_laps_from_json,
)
from gt7dashboard.gt7lap import Lap

# set logging level to debug
logger = logging.getLogger('main.py')
logger.setLevel(logging.DEBUG)

LIVE_TELEMETRY_INTERVAL_MS = 250
LIVE_TIME_DIFF_INTERVAL_SECONDS = 1.0


def update_connection_info():
    div_connection_info.text = ""
    if app.gt7comm.is_connected():
        div_connection_info.text += "<p title='Connected'>🟢</p>"
    else:
        div_connection_info.text += "<p title='Disconnected'>🔴</p>"


def update_reference_lap_select(laps):
    reference_lap_select.options = [
        tuple(("-1", "Best Lap"))
    ] + gt7helper.bokeh_tuple_for_list_of_laps(laps)


@linear()
def update_fuel_map(step):
    global g_stored_fuel_map

    if g_display_mode == "comparison":
        return

    laps = app.gt7comm.get_laps()
    if len(laps) == 0:
        div_fuel_map.text = ""
        return

    last_lap = laps[0]

    if last_lap == g_stored_fuel_map:
        return
    else:
        g_stored_fuel_map = last_lap

    # TODO Add real live data during a lap
    div_fuel_map.text = gt7diagrams.get_fuel_map_html_table(last_lap)


def _empty_time_diff_data():
    return {
        "distance": [],
        "timedelta": [],
        "reference": [],
        "comparison": [],
    }


def _live_lap_elapsed_ms(lap: Lap) -> float:
    """Prefer packet-C's live clock, with the packet-tick clock as fallback."""
    for value in reversed(getattr(lap, "data_current_lap_time_ms", [])):
        if value is not None:
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
    return max(0.0, lap.lap_live_time * 1000)


def _update_live_status(lap: Lap, last_data):
    sample_count = len(lap.data_speed)
    if sample_count == 0:
        div_live_status.text = (
            "<span style='color:#64748b;'>Live telemetry: waiting for a lap</span>"
        )
        return

    elapsed = gt7helper.seconds_to_lap_time(_live_lap_elapsed_ms(lap) / 1000)
    lap_number = getattr(last_data, "current_lap", None)
    lap_label = f"Lap {lap_number}" if lap_number is not None else "Live lap"
    fuel = getattr(last_data, "current_fuel", None)
    fuel_label = ""
    if fuel is not None:
        try:
            fuel_label = f" · {float(fuel):.1f} L"
        except (TypeError, ValueError):
            pass
    div_live_status.text = (
        "<span style='color:#b45309;'><b>● Live</b></span> "
        f"{lap_label} · {elapsed}{fuel_label}"
    )


def _stream_live_lap_data(lap_data, start_index):
    """Return complete ColumnDataSource columns for samples after start_index."""
    return {
        key: list(values[start_index:])
        for key, values in lap_data.items()
    }


def clear_live_telemetry_display():
    """Clear only the running-lap overlay and its per-session cursors."""
    global g_live_lap_generation
    global g_live_lap_revision
    global g_live_sample_count
    global g_live_time_diff_updated_at

    race_diagram.clear_live_telemetry()
    g_live_lap_generation = None
    g_live_lap_revision = -1
    g_live_sample_count = 0
    g_live_time_diff_updated_at = 0.0
    div_live_status.text = (
        "<span style='color:#64748b;'>Live telemetry: waiting for a lap</span>"
    )


def _live_reference_lap():
    laps = app.gt7comm.get_laps()
    if not laps:
        return None
    return gt7helper.get_last_reference_median_lap(
        laps, reference_lap_selected=g_reference_lap_selected
    )[1]


def update_live_telemetry():
    """Stream a detached current-lap snapshot into the Bokeh session.

    The UDP worker never touches Bokeh objects. Each browser session polls a
    consistent snapshot and sends only telemetry samples it has not rendered.
    """
    global g_live_lap_generation
    global g_live_lap_revision
    global g_live_sample_count
    global g_live_time_diff_updated_at

    if g_display_mode != "live":
        return

    generation, revision, live_lap, last_data = app.gt7comm.get_live_lap_snapshot()
    if generation != g_live_lap_generation or revision < g_live_lap_revision:
        race_diagram.clear_live_telemetry()
        g_live_lap_generation = generation
        g_live_lap_revision = -1
        g_live_sample_count = 0
        g_live_time_diff_updated_at = 0.0

    if revision == g_live_lap_revision:
        return

    live_lap_data = live_lap.get_data_dict()
    sample_count = len(live_lap_data["speed"])
    if sample_count < g_live_sample_count:
        race_diagram.clear_live_telemetry()
        g_live_sample_count = 0
        g_live_time_diff_updated_at = 0.0

    if sample_count > g_live_sample_count:
        new_samples = _stream_live_lap_data(live_lap_data, g_live_sample_count)
        race_diagram.source_live_lap.stream(new_samples)
        # Keep a completed lap's full-course navigator available while the
        # current lap starts again at zero distance.
        analysis_distances = list(
            race_diagram.source_last_lap.data["distance"]
        ) + list(race_diagram.source_live_lap.data["distance"])
        race_diagram.update_analysis_domain(
            analysis_distances
        )
        race_diagram.update_steering_visibility()
        linked_race_line.update_laps(
            race_diagram.source_live_lap.data,
            race_diagram.source_reference_lap.data,
        )
        g_live_sample_count = sample_count

    now = time.monotonic()
    if now - g_live_time_diff_updated_at >= LIVE_TIME_DIFF_INTERVAL_SECONDS:
        reference_lap = _live_reference_lap()
        if reference_lap and sample_count > 1 and len(reference_lap.data_speed) > 1:
            live_distance = live_lap_data["distance"][-1]
            race_diagram.source_live_time_diff.data = (
                calculate_time_diff_by_distance(
                    reference_lap, live_lap, max_distance=live_distance
                )
            )
        else:
            race_diagram.source_live_time_diff.data = _empty_time_diff_data()
        g_live_time_diff_updated_at = now

    _update_live_status(live_lap, last_data)
    g_live_lap_revision = revision


def update_race_lines(laps: List[Lap], reference_lap: Lap):
    """
    This function updates the race lines on the second tab with the amount of laps
    that the race line tab can hold
    """
    global race_lines, race_lines_data


    reference_lap_data = reference_lap.get_data_dict()

    for i, lap in enumerate(laps[:len(race_lines)]):
        logger.info(f"Updating Race Line for Lap {len(laps) -i} - {lap.title} and reference lap {reference_lap.title}")

        lap_data = lap.get_data_dict()
        race_lines_data[i][0].data_source.data = lap_data
        race_lines_data[i][1].data_source.data = lap_data
        race_lines_data[i][2].data_source.data = lap_data

        race_lines_data[i][3].data_source.data = reference_lap_data
        race_lines_data[i][4].data_source.data = reference_lap_data
        race_lines_data[i][5].data_source.data = reference_lap_data

        race_lines[i].axis.visible = False

        gt7diagrams.add_annotations_to_race_line(race_lines[i], lap, reference_lap)

        # Fixme not working
        race_lines[i].x_range = race_lines[0].x_range

    # The live session may have fewer laps than the previously rendered view.
    # Empty the remaining race-line panels instead of retaining stale traces.
    empty_lap_data = Lap().get_data_dict()
    for i in range(min(len(laps), len(race_lines)), len(race_lines)):
        for renderer in race_lines_data[i]:
            renderer.data_source.data = empty_lap_data
        gt7diagrams.remove_all_annotation_text_from_figure(race_lines[i])


def update_header_line(
    div: Div,
    comparison_lap: Lap,
    reference_lap: Lap,
    comparison_heading: str = "Last Lap",
):
    comparison_title = html.escape(str(comparison_lap.title))
    reference_title = html.escape(str(reference_lap.title))
    div.text = (
        f"<b>{html.escape(comparison_heading)}:</b> {comparison_title}"
        f"&nbsp;&nbsp;<b>Reference Lap:</b> {reference_title}"
    )

def update_lap_change():
    """
    Is called whenever a lap changes.
    It detects if the telemetry date retrieved is the same as the data displayed.
    If true, it updates all the visual elements.
    """
    global g_laps_stored
    global g_session_stored
    global g_connection_status_stored
    global g_telemetry_update_needed
    global g_reference_lap_selected
    global g_stored_fuel_map

    update_start_time = time.time()

    laps = app.gt7comm.get_laps()

    session = app.gt7comm.get_session_snapshot()
    if session != g_session_stored:
        update_tuning_info(session)
        g_session_stored = session

    if app.gt7comm.is_connected() != g_connection_status_stored:
        update_connection_info()
        g_connection_status_stored = copy.copy(app.gt7comm.is_connected())

    # Saved-file comparison intentionally owns the diagrams until it is
    # cleared. Incoming live packets must not overwrite that selection.
    if g_display_mode == "comparison":
        return

    # This saves on cpu time, 99.9% of the time this is true
    if laps == g_laps_stored and not g_telemetry_update_needed:
        return

    logger.debug("Rerendering laps")

    reference_lap = Lap()

    if len(laps) > 0:

        last_lap = laps[0]

        if len(laps) > 1:
            reference_lap = gt7helper.get_last_reference_median_lap(
                laps, reference_lap_selected=g_reference_lap_selected
            )[1]

            div_speed_peak_valley_diagram.text = get_speed_peak_and_valley_diagram(last_lap, reference_lap)

        update_header_line(div_header_line, last_lap, reference_lap)
    else:
        # A saved-file comparison may have been cleared while no live laps are
        # available yet. Do not leave its labels or fuel table on screen.
        div_header_line.text = ""
        div_speed_peak_valley_diagram.text = ""
        div_deviance_laps_on_display.text = ""
        div_fuel_map.text = ""
        g_stored_fuel_map = None

    logger.debug("Updating of %d laps" % len(laps))

    start_time = time.time()
    update_time_table(laps)
    logger.debug("Updating time table took %dms" % ((time.time() - start_time) * 1000))

    start_time = time.time()
    update_reference_lap_select(laps)
    logger.debug("Updating reference lap select took %dms" % ((time.time() - start_time) * 1000))

    start_time = time.time()
    update_speed_velocity_graph(laps)
    logger.debug("Updating speed velocity graph took %dms" % ((time.time() - start_time) * 1000))

    start_time = time.time()
    update_race_lines(laps, reference_lap)
    logger.debug("Updating race lines took %dms" % ((time.time() - start_time) * 1000))

    logger.debug("End of updating laps, whole Update took %dms" % ((time.time() - update_start_time) * 1000))

    g_laps_stored = laps.copy()
    g_telemetry_update_needed = False


def update_speed_velocity_graph(laps: List[Lap]):
    last_lap, reference_lap, median_lap = gt7helper.get_last_reference_median_lap(
        laps, reference_lap_selected=g_reference_lap_selected
    )

    last_lap_data = None
    reference_lap_data = None

    if last_lap:
        last_lap_data = last_lap.get_data_dict()
        race_diagram.source_last_lap.data = last_lap_data
        race_diagram.update_analysis_domain(last_lap_data["distance"])

        if reference_lap and len(reference_lap.data_speed) > 0:
            reference_lap_data = reference_lap.get_data_dict()
            race_diagram.source_time_diff.data = calculate_time_diff_by_distance(reference_lap, last_lap)
            race_diagram.source_reference_lap.data = reference_lap_data
        else:
            race_diagram.source_time_diff.data = {
                "distance": [],
                "timedelta": [],
                "reference": [],
                "comparison": [],
            }
            race_diagram.source_reference_lap.data = Lap().get_data_dict()
    else:
        race_diagram.source_last_lap.data = Lap().get_data_dict()
        race_diagram.source_reference_lap.data = Lap().get_data_dict()
        race_diagram.clear_analysis_domain()
        race_diagram.source_time_diff.data = {
            "distance": [],
            "timedelta": [],
            "reference": [],
            "comparison": [],
        }

    if median_lap:
        race_diagram.source_median_lap.data = median_lap.get_data_dict()
    else:
        race_diagram.source_median_lap.data = Lap().get_data_dict()

    race_diagram.update_steering_visibility()
    linked_race_line.update_laps(last_lap_data, reference_lap_data)

    s_race_line.axis.visible = False

    fastest_laps = race_diagram.update_fastest_laps_variance(laps)
    logger.info("Updating Speed Deviance with %d fastest laps" % len(fastest_laps))
    div_deviance_laps_on_display.text = ""
    for fastest_lap in fastest_laps:
        div_deviance_laps_on_display.text += f"<b>Lap {fastest_lap.number}:</b> {fastest_lap.title}<br>"

    # Update breakpoints
    # Adding Brake Points is slow when rendering, this is on Bokehs side about 3s
    brake_points_enabled = os.environ.get("GT7_ADD_BRAKEPOINTS") == "true"

    if brake_points_enabled and last_lap and len(last_lap.data_braking) > 0:
        update_break_points(last_lap, s_race_line, "blue")

    if brake_points_enabled and reference_lap and len(reference_lap.data_braking) > 0:
        update_break_points(reference_lap, s_race_line, "magenta")


def clear_comparison_diagrams():
    """Clear comparison artifacts before returning diagram ownership to live data."""
    global g_stored_fuel_map

    empty_lap_data = Lap().get_data_dict()
    race_diagram.delete_all_additional_laps()
    race_diagram.source_last_lap.data = empty_lap_data
    race_diagram.source_reference_lap.data = empty_lap_data
    race_diagram.source_median_lap.data = empty_lap_data
    race_diagram.source_time_diff.data = _empty_time_diff_data()
    clear_live_telemetry_display()
    race_diagram.clear_analysis_domain()
    race_diagram.update_steering_visibility()
    linked_race_line.update_laps(None, None)
    for i, renderer_group in enumerate(race_lines_data):
        for renderer in renderer_group:
            renderer.data_source.data = empty_lap_data
        gt7diagrams.remove_all_annotation_text_from_figure(race_lines[i])
    div_header_line.text = ""
    div_speed_peak_valley_diagram.text = ""
    div_deviance_laps_on_display.text = ""
    div_fuel_map.text = ""
    g_stored_fuel_map = None


def restore_live_display():
    """Give the live session ownership of the diagrams after a comparison."""
    global g_display_mode
    global g_telemetry_update_needed

    clear_comparison_diagrams()
    g_display_mode = "live"
    g_telemetry_update_needed = True
    update_lap_change()
    update_live_telemetry()


def render_saved_lap_comparison(
    reference_record: gt7comparison.ComparisonLap,
    comparison_record: gt7comparison.ComparisonLap,
    overlay_records: List[gt7comparison.ComparisonLap],
    shared_distance_m: float,
):
    """Render one explicit pair and optional overlays from saved files."""
    global g_stored_fuel_map

    reference_lap = reference_record.lap
    comparison_lap = comparison_record.lap
    comparison_data = comparison_lap.get_data_dict()
    reference_data = reference_lap.get_data_dict()

    race_diagram.delete_all_additional_laps()
    race_diagram.source_last_lap.data = comparison_data
    race_diagram.source_reference_lap.data = reference_data
    race_diagram.source_median_lap.data = Lap().get_data_dict()
    clear_live_telemetry_display()
    div_live_status.text = (
        "<span style='color:#64748b;'>Live telemetry: paused during saved-lap comparison</span>"
    )
    race_diagram.source_time_diff.data = calculate_time_diff_by_distance(
        reference_lap,
        comparison_lap,
        max_distance=shared_distance_m,
    )
    race_diagram.update_analysis_domain([0, shared_distance_m])

    for style, overlay_record in zip(COMPARISON_OVERLAY_STYLES, overlay_records):
        color, line_dash = style
        race_diagram.add_additional_lap_to_race_diagram(
            color,
            overlay_record.lap,
            visible=True,
            line_dash=line_dash,
        )

    race_diagram.update_steering_visibility()
    linked_race_line.update_laps(comparison_data, reference_data)
    s_race_line.axis.visible = False

    update_header_line(
        div_header_line,
        comparison_lap,
        reference_lap,
        comparison_heading="Comparison Lap",
    )
    div_speed_peak_valley_diagram.text = get_speed_peak_and_valley_diagram(
        comparison_lap, reference_lap
    )

    variance_laps = [reference_lap, comparison_lap] + [
        record.lap for record in overlay_records
    ]
    fastest_laps = race_diagram.update_fastest_laps_variance(variance_laps)
    div_deviance_laps_on_display.text = "".join(
        f"<b>Lap {lap.number}:</b> {html.escape(str(lap.title))}<br>"
        for lap in fastest_laps
    )

    update_race_lines([comparison_lap], reference_lap)
    g_stored_fuel_map = comparison_lap
    div_fuel_map.text = gt7diagrams.get_fuel_map_html_table(comparison_lap)


def update_break_points(lap: Lap, race_line: figure, color: str):
    brake_points_x, brake_points_y = gt7helper.get_brake_points(lap)

    for i, _ in enumerate(brake_points_x):
        race_line.scatter(
            brake_points_x[i],
            brake_points_y[i],
            marker="circle",
            size=10,
            fill_color=color,
        )


def update_time_table(laps: List[Lap]):
    global race_time_table
    global lap_times_source
    # FIXME time table is not updating
    logger.info("Adding %d laps to table" % len(laps))
    race_time_table.show_laps(laps)

    # t_lap_times.trigger("source", t_lap_times.source, t_lap_times.source)


def reset_button_handler(event):
    global g_telemetry_update_needed
    logger.info("reset button clicked")
    if g_display_mode != "comparison":
        race_diagram.delete_all_additional_laps()

    app.gt7comm.load_laps([], replace_other_laps=True)
    app.gt7comm.reset()
    clear_live_telemetry_display()
    g_telemetry_update_needed = True


def always_record_checkbox_handler(event, old, new):
    enabled = 0 in new
    logger.info("Set always record data to %s", enabled)
    app.gt7comm.set_always_record_data(enabled)


def log_lap_button_handler(event):
    app.gt7comm.finish_lap(manual=True)
    laps = app.gt7comm.get_laps()
    if laps:
        logger.info("Added a lap manually to the list of laps: %s" % laps[0])


def save_button_handler(event):
    laps = app.gt7comm.get_laps()
    if laps:
        path = save_laps_to_json(laps)
        logger.info("Saved %d laps as %s" % (len(laps), path))
        refresh_saved_lap_file_options()


def load_laps_handler(attr, old, new):
    global g_display_mode
    global g_telemetry_update_needed

    if not new:
        return
    logger.info("Loading %s" % new)
    was_comparison = g_display_mode == "comparison"
    g_display_mode = "live"
    if was_comparison:
        clear_comparison_diagrams()
    else:
        race_diagram.delete_all_additional_laps()
    app.gt7comm.load_laps(load_laps_from_json(new), replace_other_laps=True)
    g_telemetry_update_needed = True
    update_lap_change()


def load_reference_lap_handler(attr, old, new):
    global g_reference_lap_selected
    global reference_lap_select
    global g_telemetry_update_needed

    if int(new) == -1:
        # Set no reference lap
        g_reference_lap_selected = None
    else:
        g_reference_lap_selected = g_laps_stored[int(new)]
        logger.info("Loading %s as reference" % g_laps_stored[int(new)].format())

    g_telemetry_update_needed = True
    update_lap_change()


def refresh_saved_lap_file_options():
    """Refresh both saved-file pickers after a new recording is saved."""
    global stored_lap_files

    stored_lap_files = gt7helper.bokeh_tuple_for_list_of_lapfiles(
        list_lap_files_from_path(os.path.join(os.getcwd(), "data"))
    )
    select.options = stored_lap_files
    comparison_file_select.options = [option for option in stored_lap_files if option]


def set_comparison_status(message: str, tone: str = "neutral"):
    colors = {
        "neutral": "#475569",
        "success": "#166534",
        "warning": "#92400e",
        "error": "#b91c1c",
    }
    color = colors.get(tone, colors["neutral"])
    comparison_status.text = (
        f"<span style='color:{color};'>{html.escape(message)}</span>"
    )


def _comparison_record(record_id: str):
    return g_comparison_records_by_id.get(record_id)


def _clear_active_comparison_if_needed():
    if g_display_mode == "comparison":
        clear_comparison_diagrams()


def update_saved_lap_comparison():
    """Validate the selected saved laps and refresh the comparison display."""
    global g_display_mode

    reference_record = _comparison_record(comparison_reference_select.value)
    comparison_record = _comparison_record(comparison_lap_select.value)

    if reference_record is None or comparison_record is None:
        _clear_active_comparison_if_needed()
        set_comparison_status(
            "Choose one reference lap and one comparison lap to start.",
            "neutral",
        )
        return

    if reference_record.identifier == comparison_record.identifier:
        _clear_active_comparison_if_needed()
        set_comparison_status(
            "Reference and comparison must be different laps.", "error"
        )
        return

    compatibility = gt7comparison.assess_lap_compatibility(
        reference_record.lap, comparison_record.lap
    )
    if not compatibility.compatible:
        _clear_active_comparison_if_needed()
        set_comparison_status(compatibility.message, "error")
        return

    overlays = []
    skipped_overlays = []
    for record_id in g_comparison_overlay_ids:
        overlay_record = _comparison_record(record_id)
        if overlay_record is None:
            continue
        overlay_compatibility = gt7comparison.assess_lap_compatibility(
            reference_record.lap, overlay_record.lap
        )
        if overlay_compatibility.compatible:
            overlays.append(overlay_record)
        else:
            skipped_overlays.append(overlay_record.select_label)

    g_display_mode = "comparison"
    render_saved_lap_comparison(
        reference_record,
        comparison_record,
        overlays,
        compatibility.shared_distance_m,
    )

    message = compatibility.message
    if overlays:
        message += f" Showing {len(overlays)} overlay lap(s)."
    if skipped_overlays:
        message += " Some selected overlays were skipped because they are incompatible."
    set_comparison_status(
        message,
        "warning" if compatibility.warning or skipped_overlays else "success",
    )


def comparison_role_handler(attr, old, new):
    if g_comparison_widgets_updating:
        return
    update_saved_lap_comparison()


def comparison_table_selection_handler(attr, old, new):
    global g_comparison_overlay_ids
    global g_comparison_widgets_updating

    if g_comparison_widgets_updating:
        return

    selected_ids = []
    retained_indices = []
    for index in comparison_lap_source.selected.indices:
        identifiers = comparison_lap_source.data.get("identifier", [])
        if index >= len(identifiers):
            continue
        record_id = identifiers[index]
        if record_id in {
            comparison_reference_select.value,
            comparison_lap_select.value,
        }:
            continue
        if len(selected_ids) < MAX_COMPARISON_OVERLAYS:
            selected_ids.append(record_id)
            retained_indices.append(index)

    if comparison_lap_source.selected.indices != retained_indices:
        g_comparison_widgets_updating = True
        comparison_lap_source.selected.indices = retained_indices
        g_comparison_widgets_updating = False

    g_comparison_overlay_ids = selected_ids
    update_saved_lap_comparison()


def _reset_comparison_role_widgets():
    global g_comparison_widgets_updating

    g_comparison_widgets_updating = True
    options = [("", "Choose a lap")] + [
        (record.identifier, record.select_label)
        for record in g_comparison_records
    ]
    comparison_reference_select.options = options
    comparison_lap_select.options = options
    comparison_reference_select.value = ""
    comparison_lap_select.value = ""
    comparison_lap_source.selected.indices = []
    g_comparison_widgets_updating = False


def load_comparison_files_handler():
    global g_comparison_records
    global g_comparison_records_by_id
    global g_comparison_overlay_ids
    global g_display_mode
    global g_telemetry_update_needed

    selected_paths = list(comparison_file_select.value)
    if not selected_paths:
        set_comparison_status("Choose one or more saved JSON files first.", "warning")
        return

    result = gt7comparison.load_comparison_laps(selected_paths)
    g_comparison_records = result.records
    g_comparison_records_by_id = {
        record.identifier: record for record in g_comparison_records
    }
    g_comparison_overlay_ids = []
    comparison_lap_source.data = gt7comparison.comparison_table_data(
        g_comparison_records
    )
    _reset_comparison_role_widgets()

    if g_display_mode == "comparison":
        restore_live_display()

    if not g_comparison_records:
        detail = " ".join(result.errors) if result.errors else "No laps were found."
        set_comparison_status(detail, "error")
        return

    message = (
        f"Loaded {len(g_comparison_records)} lap(s) from "
        f"{len(selected_paths)} file(s). Choose the reference and comparison laps."
    )
    if result.errors:
        message += " Some files could not be read."
    set_comparison_status(message, "success")


def clear_comparison_files_handler():
    global g_comparison_records
    global g_comparison_records_by_id
    global g_comparison_overlay_ids
    global g_display_mode
    global g_telemetry_update_needed

    was_comparison = g_display_mode == "comparison"
    g_comparison_records = []
    g_comparison_records_by_id = {}
    g_comparison_overlay_ids = []
    comparison_file_select.value = []
    comparison_lap_source.data = gt7comparison.comparison_table_data([])
    _reset_comparison_role_widgets()

    if was_comparison:
        restore_live_display()
    else:
        g_display_mode = "live"
    set_comparison_status("Saved-file comparison cleared. Live session display restored.")


def toggle_comparison_panel_handler():
    comparison_panel.visible = not comparison_panel.visible
    comparison_panel_toggle.label = (
        "Hide Saved-file Comparison"
        if comparison_panel.visible
        else "Compare Saved Files"
    )
    if comparison_panel.visible:
        refresh_saved_lap_file_options()



def update_tuning_info(session):
    div_tuning_info.text = """<h4>Tuning Info</h4>
    <p>Max Speed: <b>%d</b> kph</p>
    <p>Min Body Height: <b>%d</b> mm</p>""" % (
        session.max_speed,
        session.min_body_height,
    )

def get_race_lines_layout(number_of_race_lines):
    """
    This function returns the race lines layout.
    It returns a grid of 3x3 race lines. Red is braking.
    Green is throttling.
    """
    i = 0
    race_line_diagrams = []
    race_lines_data = []

    sizing_mode = "scale_height"

    while i < number_of_race_lines:
        s_race_line, throttle_line, breaking_line, coasting_line, reference_throttle_line, reference_breaking_line, reference_coasting_line = gt7diagrams.get_throttle_braking_race_line_diagram()
        s_race_line.sizing_mode = sizing_mode
        race_line_diagrams.append(s_race_line)
        race_lines_data.append([throttle_line, breaking_line, coasting_line, reference_throttle_line, reference_breaking_line, reference_coasting_line])
        i+=1

    l = layout(children=race_line_diagrams)
    l.sizing_mode = sizing_mode

    return l, race_line_diagrams, race_lines_data

app = bokeh.application.Application

# Share the gt7comm connection between sessions by storing them as an application attribute
if not hasattr(app, "gt7comm"):
    playstation_ip = os.environ.get("GT7_PLAYSTATION_IP")
    packet_format = os.environ.get("GT7_PACKET_FORMAT", "A")
    load_laps_path = os.environ.get("GT7_LOAD_LAPS_PATH")

    if not playstation_ip:
        playstation_ip = "255.255.255.255"
        logger.info(f"No IP set in env var GT7_PLAYSTATION_IP using broadcast at {playstation_ip}")

    app.gt7comm = gt7communication.GT7Communication(
        playstation_ip, packet_format=packet_format
    )

    if load_laps_path:
        app.gt7comm.load_laps(
            load_laps_from_pickle(load_laps_path), replace_other_laps=True
        )

    app.gt7comm.start()
else:
    # Reuse existing thread
    if not app.gt7comm.is_connected():
        logger.info("Restarting gt7communcation because of no connection")
        app.gt7comm.restart()
    else:
        # Existing thread has connection, proceed
        pass


# def init_lap_times_source():
#     global lap_times_source
#     lap_times_source.data = gt7helper.pd_data_frame_from_lap([], best_lap_time=app.gt7comm.session.last_lap)
#
# init_lap_times_source()

g_laps_stored = []
g_session_stored = None
g_connection_status_stored = None
g_reference_lap_selected = None
g_stored_fuel_map = None
g_telemetry_update_needed = False
g_display_mode = "live"
g_live_lap_generation = None
g_live_lap_revision = -1
g_live_sample_count = 0
g_live_time_diff_updated_at = 0.0
g_comparison_records: List[gt7comparison.ComparisonLap] = []
g_comparison_records_by_id: dict[str, gt7comparison.ComparisonLap] = {}
g_comparison_overlay_ids: List[str] = []
g_comparison_widgets_updating = False

MAX_COMPARISON_OVERLAYS = 2
COMPARISON_OVERLAY_STYLES = [
    ("#ea580c", "dotdash"),
    ("#475569", "dotted"),
]

stored_lap_files = gt7helper.bokeh_tuple_for_list_of_lapfiles(
    list_lap_files_from_path(os.path.join(os.getcwd(), "data"))
)

race_diagram = gt7diagrams.RaceDiagram(width=1000)
race_time_table = gt7diagrams.RaceTimeTable()
colors = itertools.cycle(palette)


def table_row_selection_callback(attrname, old, new):
    global g_laps_stored
    global race_diagram
    global race_time_table
    global colors

    if g_display_mode == "comparison":
        return

    selectionIndex=race_time_table.lap_times_source.selected.indices
    logger.info("you have selected the row nr "+str(selectionIndex))

    colors = ["orange", "black", "purple", "brown", "gray", "teal"]
    race_diagram.delete_all_additional_laps()

    for color_index, index in enumerate(selectionIndex):
        if index >= len(g_laps_stored):
            continue
        color = colors[color_index % len(colors)]
        lap_to_add = g_laps_stored[index]
        race_diagram.add_additional_lap_to_race_diagram(
            color, lap_to_add, visible=True
        )


race_time_table.lap_times_source.selected.on_change('indices', table_row_selection_callback)

# Race line
linked_race_line = gt7diagrams.LinkedRaceLine(
    race_diagram.analysis_range, width=360
)
linked_race_line.link_cursor_to_plots(
    [
        race_diagram.f_time_diff,
        race_diagram.f_speed,
        race_diagram.f_pedal_inputs,
        race_diagram.f_steering,
    ]
)
s_race_line = linked_race_line.figure

select_title = Paragraph(text="Load Laps:", align="center")
select = Select(value="laps", options=stored_lap_files)
select.on_change("value", load_laps_handler)

reference_lap_select = Select(value="laps")
reference_lap_select.on_change("value", load_reference_lap_handler)

comparison_panel_toggle = Button(label="Compare Saved Files")
comparison_panel_toggle.on_click(toggle_comparison_panel_handler)

comparison_file_select = MultiChoice(
    title="Saved files to compare",
    options=[option for option in stored_lap_files if option],
    placeholder="Choose one or more saved JSON files",
    sizing_mode="stretch_width",
)
comparison_load_button = Button(label="Load Selected Files")
comparison_load_button.on_click(load_comparison_files_handler)
comparison_clear_button = Button(label="Clear Comparison")
comparison_clear_button.on_click(clear_comparison_files_handler)

comparison_reference_select = Select(
    title="Reference lap",
    value="",
    options=[("", "Choose a lap")],
    sizing_mode="stretch_width",
)
comparison_reference_select.on_change("value", comparison_role_handler)
comparison_lap_select = Select(
    title="Comparison lap",
    value="",
    options=[("", "Choose a lap")],
    sizing_mode="stretch_width",
)
comparison_lap_select.on_change("value", comparison_role_handler)

comparison_lap_source = ColumnDataSource(
    data=gt7comparison.comparison_table_data([])
)
comparison_lap_table = DataTable(
    source=comparison_lap_source,
    columns=[
        TableColumn(field="source", title="File"),
        TableColumn(field="number", title="Lap"),
        TableColumn(field="time", title="Time"),
        TableColumn(field="car_name", title="Car"),
        TableColumn(field="timestamp", title="Recorded"),
        TableColumn(field="distance", title="Distance"),
        TableColumn(field="status", title="Status"),
    ],
    index_position=None,
    height=230,
    sizing_mode="stretch_width",
)
comparison_lap_source.selected.on_change(
    "indices", comparison_table_selection_handler
)

comparison_key = Div(
    text=(
        "<span style='color:#2563eb;'>● solid</span> comparison · "
        "<span style='color:#a21caf;'>● dashed</span> reference · "
        "<span style='color:#ea580c;'>● dot-dash</span> overlay 1 · "
        "<span style='color:#475569;'>● dotted</span> overlay 2"
    ),
    sizing_mode="stretch_width",
)
comparison_status = Div(
    text="Choose saved files, then assign a reference and comparison lap.",
    sizing_mode="stretch_width",
)

RESPONSIVE_WRAP_STYLESHEET = """
@media (max-width: 1100px) {
  :host {
    flex-wrap: wrap !important;
    height: fit-content !important;
  }
}
"""
RESPONSIVE_FULL_WIDTH_STYLESHEET = """
@media (max-width: 1100px) {
  :host {
    width: 100% !important;
    min-width: 100% !important;
    flex-basis: 100% !important;
  }
}
"""

comparison_panel = column(
    row(
        comparison_file_select,
        comparison_load_button,
        comparison_clear_button,
        sizing_mode="stretch_width",
        spacing=6,
        stylesheets=[RESPONSIVE_WRAP_STYLESHEET],
    ),
    row(
        comparison_reference_select,
        comparison_lap_select,
        sizing_mode="stretch_width",
        spacing=6,
        stylesheets=[RESPONSIVE_WRAP_STYLESHEET],
    ),
    comparison_key,
    comparison_status,
    Div(
        text=(
            "Select up to two additional rows below to overlay them on the "
            "telemetry graphs."
        ),
        sizing_mode="stretch_width",
    ),
    comparison_lap_table,
    visible=False,
    sizing_mode="stretch_width",
    spacing=4,
)

manual_log_button = Button(label="Log Lap Now")
manual_log_button.on_click(log_lap_button_handler)

save_button = Button(label="Save Laps")
save_button.on_click(save_button_handler)

reset_button = Button(label="Reset Laps")
reset_button.on_click(reset_button_handler)

div_tuning_info = Div(width=200, height=100)

# div_last_lap = Div(width=200, height=125)
# div_reference_lap = Div(width=200, height=125)
div_speed_peak_valley_diagram = Div(width=200, height=125)
div_gt7_dashboard = Div(width=120, height=30)
div_header_line = Div(width=400, height=30)
div_live_status = Div(
    text="<span style='color:#64748b;'>Live telemetry: waiting for a lap</span>",
    width=240,
    height=30,
)
div_connection_info = Div(width=30, height=30)
div_deviance_laps_on_display = Div(width=200, height=race_diagram.f_speed_variance.height)

div_fuel_map = Div(width=200, height=125, css_classes=["fuel_map"])

div_gt7_dashboard.text = f"<a href='https://github.com/snipem/gt7dashboard' target='_blank'>GT7 Dashboard</a>"

LABELS = ["Record Replays"]

checkbox_group = CheckboxGroup(labels=LABELS, active=[])
checkbox_group.on_change("active", always_record_checkbox_handler)

race_time_table.t_lap_times.sizing_mode = "stretch_width"
RESPONSIVE_MAP_STYLESHEET = """
@media (max-width: 1100px) {
  :host {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    flex-basis: 100% !important;
  }
}
"""


def with_help(help_text, content):
    return row(
        get_help_div(help_text),
        content,
        sizing_mode="stretch_width",
        spacing=4,
    )


header_controls = row(
    get_help_div(gt7help.HEADER),
    div_connection_info,
    div_gt7_dashboard,
    div_header_line,
    div_live_status,
    reset_button,
    save_button,
    select_title,
    select,
    get_help_div(gt7help.LAP_CONTROLS),
    sizing_mode="stretch_width",
    stylesheets=[RESPONSIVE_WRAP_STYLESHEET],
)

manual_controls = row(
    manual_log_button,
    checkbox_group,
    reference_lap_select,
    comparison_panel_toggle,
    get_help_div(gt7help.MANUAL_CONTROLS),
    sizing_mode="stretch_width",
    stylesheets=[RESPONSIVE_WRAP_STYLESHEET],
)

secondary_tabs = Tabs(
    tabs=[
        TabPanel(
            title="Consistency",
            child=column(
                with_help(gt7help.SPEED_VARIANCE, race_diagram.f_speed_variance),
                row(
                    div_deviance_laps_on_display,
                    div_speed_peak_valley_diagram,
                    sizing_mode="stretch_width",
                    spacing=12,
                ),
                sizing_mode="stretch_width",
                spacing=4,
            ),
        ),
        TabPanel(
            title="Yaw",
            child=with_help(gt7help.YAW_RATE_DIAGRAM, race_diagram.f_yaw_rate),
        ),
        TabPanel(
            title="Coasting",
            child=with_help(gt7help.COASTING_DIAGRAM, race_diagram.f_coasting),
        ),
        TabPanel(
            title="Gear / RPM",
            child=column(
                with_help(gt7help.GEAR_DIAGRAM, race_diagram.f_gear),
                with_help(gt7help.RPM_DIAGRAM, race_diagram.f_rpm),
                sizing_mode="stretch_width",
                spacing=4,
            ),
        ),
        TabPanel(
            title="Boost",
            child=with_help(gt7help.BOOST_DIAGRAM, race_diagram.f_boost),
        ),
        TabPanel(
            title="Tires",
            child=with_help(gt7help.TIRE_DIAGRAM, race_diagram.f_tires),
        ),
    ],
    sizing_mode="stretch_width",
)

analysis_plots = column(
    with_help(gt7help.ANALYSIS_WINDOW, race_diagram.navigator_layout),
    with_help(gt7help.TIME_DIFF, race_diagram.f_time_diff),
    with_help(gt7help.SPEED_DIAGRAM, race_diagram.f_speed),
    with_help(gt7help.PEDAL_INPUTS_DIAGRAM, race_diagram.f_pedal_inputs),
    with_help(gt7help.STEERING_DIAGRAM, race_diagram.steering_view),
    secondary_tabs,
    sizing_mode="stretch_width",
    spacing=4,
    stylesheets=[RESPONSIVE_FULL_WIDTH_STYLESHEET],
)

race_line_panel = column(
    get_help_div(gt7help.RACE_LINE_MINI),
    linked_race_line.get_layout(),
    width=360,
    max_width=360,
    sizing_mode="stretch_width",
    spacing=4,
    stylesheets=[RESPONSIVE_MAP_STYLESHEET],
)

analysis_workspace = row(
    analysis_plots,
    race_line_panel,
    sizing_mode="stretch_width",
    stylesheets=[RESPONSIVE_WRAP_STYLESHEET],
)

lap_summary = row(
    with_help(gt7help.TIME_TABLE, race_time_table.t_lap_times),
    column(
        with_help(gt7help.FUEL_MAP, div_fuel_map),
        with_help(gt7help.TUNING_INFO, div_tuning_info),
        width=240,
    ),
    sizing_mode="stretch_width",
    stylesheets=[RESPONSIVE_WRAP_STYLESHEET],
)

l1 = column(
    header_controls,
    manual_controls,
    comparison_panel,
    analysis_workspace,
    lap_summary,
    sizing_mode="stretch_width",
)




l2, race_lines, race_lines_data = get_race_lines_layout(number_of_race_lines=1)

l3 = Div(
    text=(
        "<p>Session controls and lap summaries are available in the "
        "<b>Get Faster</b> tab.</p>"
    ),
    sizing_mode="stretch_width",
)

#  Setup the tabs
tab1 = TabPanel(child=l1, title="Get Faster")
tab2 = TabPanel(child=l2, title="Race Lines")
tab3 = TabPanel(child=l3, title="Race")
tabs = Tabs(tabs=[tab1, tab2, tab3])

curdoc().add_root(tabs)
curdoc().title = "GT7 Dashboard"

# Finished-lap analysis remains low-frequency; live telemetry is streamed
# separately so the dashboard reacts during a lap without blocking reception.
curdoc().add_periodic_callback(update_lap_change, 1000)
curdoc().add_periodic_callback(update_fuel_map, 5000)
curdoc().add_periodic_callback(update_live_telemetry, LIVE_TELEMETRY_INTERVAL_MS)
