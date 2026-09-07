"""Read-only input analysis: spatially align GT7 laps and export reproducible metrics."""
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OWN_NAME = "2026-09-05_01_47_12_Roadster_NR-A_ND_22.json"
REF_NAMES = ["1_08_943_TC2000_Roadster_NR-A_ND_22.json", "1_08_975_TC2000_Roadster_NR-A_ND_22.json", "1_09_055_TC2000_Roadster_NR-A_ND_22.json"]


def read_lap(raw, label, index):
    clock = np.asarray(raw["data_current_lap_time_ms"], dtype=float) / 1000
    reset = np.flatnonzero(np.diff(clock[:20]) < -1)
    start = int(reset[-1] + 1) if len(reset) else 0
    t = clock[start:]
    assert np.all(np.diff(t) > 0), (label, index, "clock not monotonic")
    fields = {k: np.asarray(raw[k][start:], dtype=float) for k in ["data_speed", "data_throttle", "data_braking", "data_gear", "data_rpm", "data_position_x", "data_position_z", "data_front_left_steering_angle_rad", "data_front_right_steering_angle_rad"]}
    assert all(len(v) == len(t) for v in fields.values())
    points = np.column_stack([fields["data_position_x"], fields["data_position_z"]])
    lap = dict(raw=raw, label=label, index=index, t=t, xy=points, finish=raw["lap_finish_time"] / 1000, dropped=start,
               v=fields["data_speed"], gas=fields["data_throttle"], brake=fields["data_braking"], gear=fields["data_gear"], rpm=fields["data_rpm"],
               steer=np.rad2deg((fields["data_front_left_steering_angle_rad"] + fields["data_front_right_steering_angle_rad"]) / 2))
    lap["distance"] = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    lap["dt"] = np.r_[np.diff(t), lap["finish"] - t[-1]]
    return lap


own = [read_lap(r, "own", i) for i, r in enumerate(json.loads((ROOT / "data" / OWN_NAME).read_text()))]
refs = [read_lap(json.loads((ROOT / "data" / f).read_text())[0], f, 0) for f in REF_NAMES]
best = min(own, key=lambda v: v["finish"])
ref = refs[0]

# Establish a common reference polyline; offset by the small distance before
# the first valid clock sample. The endpoint is anchored by official finish time.
ref_offset = ref["v"][0] / 3.6 * ref["t"][0]
ref_s = ref["distance"] + ref_offset
length = ref_s[-1] + ref["v"][-1] / 3.6 * (ref["finish"] - ref["t"][-1])
vertices = ref["xy"]
tree = cKDTree(vertices)
segments = np.diff(vertices, axis=0)
segment_len = np.linalg.norm(segments, axis=1)


def align(lap):
    _, nearest = tree.query(lap["xy"], k=12)
    candidates = np.clip(np.concatenate([nearest, nearest - 1], axis=1), 0, len(segments) - 1)
    a = vertices[candidates]
    b = segments[candidates]
    u = np.clip(np.sum((lap["xy"][:, None, :] - a) * b, axis=2) / np.sum(b * b, axis=2), 0, 1)
    projection = a + u[:, :, None] * b
    error = np.linalg.norm(lap["xy"][:, None, :] - projection, axis=2)
    candidate_s = ref_s[candidates] + u * segment_len[candidates]
    # Resolve the start/finish adjacency using the lap clock; interior samples
    # have no timing-based progress constraint.
    error[(lap["t"][:, None] < 2) & (candidate_s > length / 2)] = np.inf
    error[(lap["t"][:, None] > lap["finish"] - 2) & (candidate_s < length / 2)] = np.inf
    choose = np.argmin(error, axis=1)
    s = candidate_s[np.arange(len(choose)), choose]
    lap["projection_error"] = error[np.arange(len(choose)), choose]
    lap["backsteps"] = int(np.sum(np.diff(s) < -0.05))
    lap["s"] = np.maximum.accumulate(s)
    lap["timing_s"] = np.r_[0, lap["s"], length]
    lap["timing_t"] = np.r_[0, lap["t"], lap["finish"]]


for lap in own + refs:
    align(lap)


def at(lap, s, key="t"):
    if key == "t":
        return np.interp(s, lap["timing_s"], lap["timing_t"])
    return np.interp(s, lap["s"], lap[key])


def lap_summary(lap):
    return dict(label=lap["label"], index=lap["index"], lap_number=lap["raw"]["number"], finish=lap["finish"], start_timestamp=lap["raw"]["lap_start_timestamp"],
                samples=len(lap["t"]), stale_samples_dropped=lap["dropped"], max_clock_gap=float(np.max(np.diff(lap["t"]))),
                path_length=float(lap["distance"][-1]), projection_error_m_p95=float(np.percentile(lap["projection_error"], 95)), projection_backsteps=lap["backsteps"],
                full_throttle_seconds=float(np.sum(lap["dt"][lap["gas"] >= 99])), braking_seconds=float(np.sum(lap["dt"][lap["brake"] > 5])),
                coasting_seconds=float(np.sum(lap["dt"][(lap["gas"] < 1) & (lap["brake"] < 1)])),
                start_speed=float(lap["v"][0]), max_speed=float(lap["v"].max()))


grid = np.arange(0, length, 1)
v_ref = at(ref, grid, "v")
minima, _ = find_peaks(-v_ref, prominence=8, distance=100)
initial = {"reference_length": length, "own": [lap_summary(l) for l in own], "refs": [lap_summary(l) for l in refs],
           "best_index": best["index"], "minima": [{"s": float(grid[i]), "v": float(v_ref[i])} for i in minima]}
(OUT / "initial.json").write_text(json.dumps(initial, indent=2))
BOUNDS = [0, 150, 500, 800, 1120, 1750, length]
NAMES = ["Start to T1 braking", "T1 and S bends", "First hairpin", "Dunlop and 80R", "Second hairpin and back straight", "Final corner"]
section_times = np.array([[at(l, b) - at(l, a) for a, b in zip(BOUNDS[:-1], BOUNDS[1:])] for l in own])
ref_section = np.diff(at(ref, BOUNDS))
best_section = np.diff(at(best, BOUNDS))


def runs(lap, mask, minimum=0.1):
    edges = np.diff(np.r_[False, mask, False].astype(int))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    output = []
    for a, b in zip(starts, ends):
        duration = float(np.sum(lap["dt"][a:b]))
        if duration >= minimum:
            output.append(dict(s0=round(float(lap["s"][a]), 1), s1=round(float(lap["s"][min(b, len(lap["s"]) - 1)]), 1),
                               duration=round(duration, 3), v0=round(float(lap["v"][a]), 2), v1=round(float(lap["v"][b - 1]), 2)))
    return output


corners = [("T1", 140, 400), ("HP1", 500, 800), ("Dunlop", 800, 1120), ("HP2", 1120, 1450), ("Final", 1750, length)]


def corner_summary(lap, name, lo, hi):
    idx = np.flatnonzero((lap["s"] >= lo) & (lap["s"] < hi))
    minimum = idx[np.argmin(lap["v"][idx])]
    mask = (lap["s"] >= lo) & (lap["s"] < hi)
    brake_runs = runs(lap, mask & (lap["brake"] > 5))
    full_runs = runs(lap, mask & (lap["gas"] >= 95))
    return dict(name=name, minimum_speed=round(float(lap["v"][minimum]), 2), minimum_s=round(float(lap["s"][minimum]), 1),
                gear_at_min=int(lap["gear"][minimum]), steering_at_min=round(float(lap["steer"][minimum]), 2),
                braking_runs=brake_runs, full_throttle_runs=full_runs,
                partial_throttle_seconds=round(float(np.sum(lap["dt"][mask & (lap["gas"] >= 5) & (lap["gas"] < 95) & (lap["brake"] < 1)])), 3))


sections = [dict(name=NAMES[i], start_m=BOUNDS[i], end_m=BOUNDS[i+1], ref_s=round(float(ref_section[i]), 3),
                 own_best_s=round(float(best_section[i]), 3), loss_s=round(float(best_section[i]-ref_section[i]), 3),
                 own_median_s=round(float(np.median(section_times[:, i])), 3),
                 own_best_piece_s=round(float(section_times[:, i].min()), 3), best_piece_index=int(np.argmin(section_times[:, i])),
                 own_std_s=round(float(section_times[:, i].std()), 3)) for i in range(len(NAMES))]
summary = dict(initial, sections=sections, theoretical_best=float(section_times.min(axis=0).sum()),
               best_piece_indices=section_times.argmin(axis=0).tolist(),
               controls=[dict(label=l["label"], finish=l["finish"], corners=[corner_summary(l, *c) for c in corners]) for l in [best]+refs])
(OUT / "metrics.json").write_text(json.dumps(summary, indent=2))


def make_chart():
    from bokeh.io import output_file, save
    from bokeh.layouts import column
    from bokeh.models import HoverTool, Span, ColumnDataSource, Range1d, Label
    from bokeh.plotting import figure
    from bokeh.resources import INLINE
    show_s = np.r_[np.arange(0, length, 2), length]
    color_own, color_ref = "#1670b5", "#bd3578"
    common = dict(width=1100, height=270, tools="pan,wheel_zoom,box_zoom,reset,save", active_scroll="wheel_zoom")
    shared_range = Range1d(0, length)
    figures = []
    for field, title, ylabel in [("t", "位置を揃えた累積タイム差（あなたのベスト − 上位最速）", "差（秒）"),
                                  ("v", "速度", "速度（km/h）"), ("gas", "アクセル入力", "入力（%）"),
                                  ("brake", "ブレーキ入力", "入力（%）"), ("steer", "左右前輪の平均舵角", "前輪舵角（度）")]:
        p = figure(title=title, x_range=shared_range, x_axis_label="上位最速の走行軌跡に沿った位置（m）", y_axis_label=ylabel, **common)
        if field == "t":
            deltas = np.array([at(l, show_s) - at(ref, show_s) for l in own])
            p.varea(x=show_s, y1=np.percentile(deltas, 25, axis=0), y2=np.percentile(deltas, 75, axis=0), fill_color=color_own, fill_alpha=.12, legend_label="あなた18周の中央50%")
            source=ColumnDataSource(dict(s=show_s, v=at(best,show_s)-at(ref,show_s)))
            rr=p.line("s","v",source=source,color=color_own,line_width=2.5,legend_label="あなた 1:10.597")
            p.add_tools(HoverTool(renderers=[rr],tooltips=[("位置", "@s{0} m"),("タイム差", "@v{0.000} s")],mode="vline"))
            for i in range(len(NAMES)):
                p.add_layout(Label(x=BOUNDS[i]+8, y=0.03, text=["開始","1コーナー/S字","第1ヘアピン","ダンロップ/80R","第2ヘアピン/裏直線","最終"][i],text_font_size="10px",text_color="#555555"))
        else:
            for lap, color, label in [(ref,color_ref,"上位 1:08.943"),(best,color_own,"あなた 1:10.597")]:
                source=ColumnDataSource(dict(s=show_s,v=at(lap,show_s,field)))
                rr=p.line("s","v",source=source,color=color,line_width=2,legend_label=label)
                p.add_tools(HoverTool(renderers=[rr],tooltips=[("走行",label),("位置","@s{0} m"),(ylabel,"@v{0.0}")],mode="vline"))
        for b in BOUNDS[1:-1]:
            p.add_layout(Span(location=b,dimension="height",line_color="#aaaaaa",line_alpha=.4,line_dash="dotted"))
        p.legend.location="top_left"
        p.legend.click_policy="hide"
        p.toolbar.logo=None
        figures.append(p)
    output_file(OUT/"comparison.html",title="筑波 ロードスター：上位走行との比較")
    save(column(*figures),resources=INLINE)


if __name__ == "__main__":
    make_chart()
    print(json.dumps({"sections":sections,"theoretical_best":summary["theoretical_best"],"best_index":best["index"]}, indent=2))
