import copy
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
    Paragraph,
    Button,
    Div, CheckboxGroup, TabPanel, Tabs,
)
from bokeh.palettes import Plasma11 as palette
from bokeh.plotting import curdoc
from bokeh.plotting import figure

from gt7dashboard import gt7communication, gt7diagrams, gt7help, gt7helper, gt7lap
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

    if len(app.gt7comm.laps) == 0:
        div_fuel_map.text = ""
        return

    last_lap = app.gt7comm.laps[0]

    if last_lap == g_stored_fuel_map:
        return
    else:
        g_stored_fuel_map = last_lap

    # TODO Add real live data during a lap
    div_fuel_map.text = gt7diagrams.get_fuel_map_html_table(last_lap)


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


def update_header_line(div: Div, last_lap: Lap, reference_lap: Lap):
    div.text = f"<p><b>Last Lap: {last_lap.title} ({last_lap.car_name()})<b></p>" \
               f"<p><b>Reference Lap: {reference_lap.title} ({reference_lap.car_name()})<b></p>"

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

    update_start_time = time.time()

    laps = app.gt7comm.get_laps()

    if app.gt7comm.session != g_session_stored:
        update_tuning_info()
        g_session_stored = copy.copy(app.gt7comm.session)

    if app.gt7comm.is_connected() != g_connection_status_stored:
        update_connection_info()
        g_connection_status_stored = copy.copy(app.gt7comm.is_connected())

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
    race_diagram.delete_all_additional_laps()

    app.gt7comm.load_laps([], replace_other_laps=True)
    app.gt7comm.reset()
    g_telemetry_update_needed = True


def always_record_checkbox_handler(event, old, new):
    if len(new) == 2:
        logger.info("Set always record data to True")
        app.gt7comm.always_record_data = True
    else:
        logger.info("Set always record data to False")
        app.gt7comm.always_record_data = False


def log_lap_button_handler(event):
    app.gt7comm.finish_lap(manual=True)
    logger.info("Added a lap manually to the list of laps: %s" % app.gt7comm.laps[0])


def save_button_handler(event):
    if len(app.gt7comm.laps) > 0:
        path = save_laps_to_json(app.gt7comm.laps)
        logger.info("Saved %d laps as %s" % (len(app.gt7comm.laps), path))


def load_laps_handler(attr, old, new):
    logger.info("Loading %s" % new)
    race_diagram.delete_all_additional_laps()
    app.gt7comm.load_laps(load_laps_from_json(new), replace_other_laps=True)


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



def update_tuning_info():
    div_tuning_info.text = """<h4>Tuning Info</h4>
    <p>Max Speed: <b>%d</b> kph</p>
    <p>Min Body Height: <b>%d</b> mm</p>""" % (
        app.gt7comm.session.max_speed,
        app.gt7comm.session.min_body_height,
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
div_connection_info = Div(width=30, height=30)
div_deviance_laps_on_display = Div(width=200, height=race_diagram.f_speed_variance.height)

div_fuel_map = Div(width=200, height=125, css_classes=["fuel_map"])

div_gt7_dashboard.text = f"<a href='https://github.com/snipem/gt7dashboard' target='_blank'>GT7 Dashboard</a>"

LABELS = ["Record Replays"]

checkbox_group = CheckboxGroup(labels=LABELS, active=[1])
checkbox_group.on_change("active", always_record_checkbox_handler)

race_time_table.t_lap_times.sizing_mode = "stretch_width"

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

# This will only trigger once per lap, but we check every second if anything happened
curdoc().add_periodic_callback(update_lap_change, 1000)
curdoc().add_periodic_callback(update_fuel_map, 5000)
