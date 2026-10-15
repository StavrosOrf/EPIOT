"""Generate the charts and diagrams used in the documentation.

The charts are produced by the application's own functions, so regenerate them
after changing a simulator, a prior or the day effects:

    uv run --with matplotlib python docs/_scripts/generate_figures.py

Figures that need ``instance/default.sqlite`` (district aggregates) are skipped
when it is absent. Output goes to ``docs/_static/figures``.
"""

import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
OUT = ROOT / "docs" / "_static" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

ZONE = ZoneInfo("Europe/Amsterdam")
DAY = dt.date(2026, 10, 14)  # a Wednesday

# Palette shared with the application's charts
BLUE, ORANGE, GREEN, PURPLE = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"
INK, INK_2, MUTED, GRID, SURFACE = "#18221c", "#35423a", "#5b6a61", "#dfe5e1", "#ffffff"
BAND = "#f3f6f4"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Inter", "Segoe UI", "DejaVu Sans"],
    "font.size": 9.5,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "axes.titlesize": 10.5, "axes.titleweight": "semibold", "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.7,
    "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "legend.frameon": False, "svg.fonttype": "path", "svg.hashsalt": "epiot",
})


def save(fig, name):
    fig.savefig(OUT / name, bbox_inches="tight", pad_inches=0.25, metadata={"Date": None})
    plt.close(fig)
    print("wrote", name)


def at(day, hour, minute=0):
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


def midnight(day):
    return at(day, 0)


def hour_ticks(ax, first=0, last=24, step=3):
    ticks = np.arange(first, last + 1, step)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{int(t) % 24:02d}:00" for t in ticks])
    ax.set_xlim(first, last)


def step_fill(ax, x, y, color, label=None, alpha=0.16, lw=1.7, **kwargs):
    ax.step(x, y, where="post", color=color, lw=lw, label=label, **kwargs)
    ax.fill_between(x, y, step="post", color=color, alpha=alpha, lw=0)


# ---------------------------------------------------------------------------
# Imports from the application (after sys.path is set)
# ---------------------------------------------------------------------------
from backend.carbon_charging import daily_profiles  # noqa: E402
from backend.flex_polytope import build_polytope, envelopes  # noqa: E402
from backend.grid_data import app_grid_hours  # noqa: E402
from backend.scenario_calendar import get_calendar  # noqa: E402
from backend.scenario_profiles import simulate_scenarios  # noqa: E402
from backend.scenario_sampling import ScenarioSession, arrival_curve, load_priors  # noqa: E402
from backend.scenario_world import DURATION_SCALE  # noqa: E402
from backend.session_sources import SessionSourceService  # noqa: E402

DATABASE = ROOT / "instance" / "default.sqlite"
GRID_STORE = ROOT / "instance" / "grid_data.sqlite"


def district_chargers(count=120):
    """Charging points in central Amsterdam, from the local database."""
    if not DATABASE.exists():
        return []
    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """SELECT cp.id, cp.power, cp.type, l.latitude, l.longitude, l.country
               FROM charging_points cp JOIN columns c ON c.id = cp.column_id JOIN locations l ON l.id = c.location_id
               WHERE l.latitude BETWEEN 52.355 AND 52.385 AND l.longitude BETWEEN 4.88 AND 4.93 AND cp.power IS NOT NULL
               ORDER BY cp.id LIMIT ?""", (count,)).fetchall()
    return [dict(id=r[0], power=r[1], type=r[2], latitude=r[3], longitude=r[4], country=r[5]) for r in rows]


def window(day):
    """Local midnight of the day before and the day after the target day."""
    return midnight(day - dt.timedelta(days=1)), midnight(day + dt.timedelta(days=1))


# ---------------------------------------------------------------------------
# 1. One session under each strategy, and its headroom signals
# ---------------------------------------------------------------------------
def single_session():
    chargers = [dict(id=1, power=11.0)]
    session = ScenarioSession(1, at(DAY, 8), at(DAY, 17), 22.0)
    start, end = midnight(DAY), midnight(DAY + dt.timedelta(days=1))
    hours = np.arange(24)
    # An illustrative day: cleaner around the solar peak, dirtier in the evening
    intensity = 380 - 170 * np.exp(-((hours - 13) / 3) ** 2) + 70 * np.exp(-((hours - 19) / 2) ** 2)
    costs = np.repeat(intensity, 6).tolist()
    x = np.arange(144) / 6
    runs = {s: simulate_scenarios(chargers, [session], start, end, s, carbon_intensity=costs)
            for s in ("afap", "alap", "avg", "mincarbon")}
    labels = {"afap": "As Fast As Possible", "alap": "As Late As Possible", "avg": "Average Power",
              "mincarbon": "Min. Carbon Footprint"}
    colors = {"afap": BLUE, "alap": ORANGE, "avg": GREEN, "mincarbon": PURPLE}

    fig, axes = plt.subplots(4, 1, figsize=(8.6, 7.4), sharex=True, sharey=True)
    for ax, strategy in zip(axes, runs):
        load = np.asarray(runs[strategy][0])
        ax.axvspan(8, 17, color=BAND, lw=0)
        if strategy == "mincarbon":
            twin = ax.twinx()
            twin.step(x, np.asarray(costs), where="post", color=MUTED, lw=1, ls=(0, (3, 2)))
            twin.set_ylim(0, 520)
            twin.set_yticks([])
            twin.spines["right"].set_visible(False)
            twin.grid(False)
            twin.text(5.7, 440, "grid carbon intensity (illustrative)", color=MUTED, fontsize=8, va="center")
        step_fill(ax, x, load, colors[strategy])
        ax.set_title(f"{labels[strategy]}  ·  {load.sum() / 6:.1f} kWh", fontsize=10)
        ax.set_ylabel("kW")
        ax.set_ylim(0, 13.5)
    axes[0].text(8.1, 12.2, "arrives 08:00", color=MUTED, fontsize=8.5)
    axes[0].text(16.9, 12.2, "departs 17:00", color=MUTED, fontsize=8.5, ha="right")
    hour_ticks(axes[-1], 6, 19, 1)
    axes[-1].set_xlabel("Local time on the target day")
    fig.suptitle("One 22 kWh session on an 11 kW charger, plugged in from 08:00 to 17:00",
                 x=0.06, ha="left", fontsize=11.5, fontweight="semibold")
    fig.tight_layout()
    save(fig, "strategies-single-session.svg")

    fig, axes = plt.subplots(3, 1, figsize=(8.6, 5.9), sharex=True, sharey=True)
    for ax, strategy in zip(axes, ("afap", "alap", "avg")):
        load, up, down = (np.asarray(v) for v in runs[strategy])
        ax.axvspan(8, 17, color=BAND, lw=0)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.fill_between(x, up, step="post", color=BLUE, alpha=0.32, lw=0, label="upward headroom")
        ax.step(x, up, where="post", color=BLUE, lw=1.5)
        ax.fill_between(x, down, step="post", color=ORANGE, alpha=0.32, lw=0, label="downward headroom")
        ax.step(x, down, where="post", color=ORANGE, lw=1.5)
        ax.step(x, load, where="post", color=INK, lw=1.3, ls=(0, (2, 2)), label="scheduled load")
        ax.set_title(labels[strategy], fontsize=10)
        ax.set_ylabel("kW")
        ax.set_ylim(-13.5, 13.5)
    axes[0].legend(loc="upper right", ncols=3, fontsize=8.5)
    hour_ticks(axes[-1], 6, 19, 1)
    axes[-1].set_xlabel("Local time on the target day")
    fig.suptitle("Headroom signals for the same session", x=0.06, ha="left", fontsize=11.5, fontweight="semibold")
    fig.tight_layout()
    save(fig, "flexibility-headroom.svg")


# ---------------------------------------------------------------------------
# 2. Aggregates for a district
# ---------------------------------------------------------------------------
def district(chargers):
    service = SessionSourceService()
    start, end = window(DAY)
    sessions, meta = service.get(chargers, DAY, source="spatial", assumption="base", seed=42)
    return service, sessions, start, end


def window_axes(ax, ylabel="Power (kW)"):
    ax.axvspan(0, 24, color=ORANGE, alpha=0.045, lw=0)
    ax.axvspan(24, 48, color=BLUE, alpha=0.045, lw=0)
    ax.set_xticks(np.arange(0, 49, 6))
    ax.set_xticklabels([f"{int(t) % 24:02d}:00" for t in np.arange(0, 49, 6)])
    ax.set_xlim(0, 48)
    ax.set_ylabel(ylabel)
    ymax = ax.get_ylim()[1]
    ax.text(0.5, ymax * 0.97, "Previous day", color=MUTED, fontsize=8.5, va="top")
    ax.text(24.5, ymax * 0.97, "Target day", color=MUTED, fontsize=8.5, va="top")


def split_line(ax, x, y, **kwargs):
    step_fill(ax, x[:144], y[:144], ORANGE, **kwargs)
    step_fill(ax, x[144:], y[144:], BLUE, **kwargs)


def source_comparison(chargers):
    service = SessionSourceService()
    start, end = window(DAY)
    x = np.arange(288) / 6
    fig, axes = plt.subplots(3, 1, figsize=(9, 7.4), sharex=True)
    notes = {
        "simple": "Simple",
        "spatial": "Spatial",
        "cpft": "CPFT: synthetic history to 18:00 the evening before, forecast afterwards",
    }
    loads = {}
    for source in ("simple", "spatial", "cpft"):
        sessions, _ = service.get(chargers, DAY, source=source, assumption="base", seed=42)
        loads[source] = np.asarray(simulate_scenarios(chargers, sessions, start, end, "afap")[0])
    for ax, source in zip(axes, loads):
        load = loads[source]
        split_line(ax, x, load)
        ax.set_ylim(0, 1.12 * max(load.max(), 1))  # each panel has its own scale
        ax.set_title(f"{notes[source]}  ·  target day {load[144:].sum() / 6:,.0f} kWh", fontsize=10)
        window_axes(ax)
    axes[-1].set_xlabel("Local time (D − 1 and D)")
    fig.suptitle(f"The same {len(chargers)} central Amsterdam chargers under each session source, "
                 "As Fast As Possible, base demand", x=0.06, ha="left", fontsize=11.5, fontweight="semibold")
    fig.tight_layout()
    save(fig, "source-comparison.svg")


def strategies_district(chargers):
    service = SessionSourceService()
    start, end = window(DAY)
    sessions, _ = service.get(chargers, DAY, source="spatial", assumption="base", seed=42)
    hours = app_grid_hours(start, end, None, cache_path=GRID_STORE) if GRID_STORE.exists() else []
    target_start = midnight(DAY)
    x = np.arange(144) / 6
    fig, ax = plt.subplots(figsize=(9, 4.4))
    style = [("afap", "As Fast As Possible", BLUE), ("alap", "As Late As Possible", ORANGE),
             ("avg", "Average Power", GREEN), ("mincarbon", "Min. Carbon Footprint", PURPLE)]
    for strategy, label, color in style:
        if strategy == "mincarbon" and not hours:
            continue
        load = np.asarray(daily_profiles(chargers, sessions, start, end, strategy, "Europe/Amsterdam", hours)[0])
        today = load[144:]
        ax.step(x, today, where="post", color=color, lw=1.7, label=f"{label} ({today.sum() / 6:,.0f} kWh)")
    ax.set_xlim(0, 24)
    hour_ticks(ax, 0, 24, 3)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Power (kW)")
    ax.set_xlabel("Local time on the target day")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_title(f"{len(chargers)} chargers, spatial source: the strategies place the same sessions differently")
    fig.text(0.0, -0.03, "Energy inside the window differs slightly because connections that cross midnight "
             "are cropped differently by each strategy.", fontsize=8.2, color=MUTED)
    fig.tight_layout()
    save(fig, "strategies-district.svg")


def time_window(chargers):
    service = SessionSourceService()
    start, end = window(DAY)
    points = chargers[:9]
    sessions, _ = service.get(points, DAY, source="spatial", assumption="high", seed=7)
    left, right = start.timestamp(), end.timestamp()
    rows = {p["id"]: i for i, p in enumerate(points)}
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True, gridspec_kw=dict(height_ratios=[1.35, 1]))
    for ts, te, cp in zip(sessions.start, sessions.end, sessions.cp_id):
        a, b = max(ts, left), min(te, right)
        if b <= a:
            continue
        row = rows[int(cp)]
        crossing = ts < left or te > right
        top.barh(row, (b - a) / 3600, left=(a - left) / 3600, height=0.62,
                 color=BLUE if (a - left) / 3600 >= 24 else ORANGE, alpha=0.85, edgecolor="white", lw=0.8)
        if crossing:
            top.text((a - left) / 3600 + 0.25, row, "crosses the window edge", fontsize=6.8, va="center", color="white")
    top.set_yticks(range(len(points)))
    top.set_yticklabels([f"charger {p['id']}" for p in points], fontsize=7.5)
    top.invert_yaxis()
    top.set_title("Sessions of nine chargers inside the two-day window (one row per charger)")
    top.grid(axis="y", visible=False)
    x = np.arange(288) / 6
    load = np.asarray(simulate_scenarios(points, sessions, start, end, "afap")[0])
    split_line(bottom, x, load)
    window_axes(bottom, "Aggregated kW")
    bottom.set_title("Aggregated load: 288 steps of 10 minutes")
    bottom.set_xlabel("Local time (D − 1 and D)")
    for ax in (top, bottom):
        ax.axvline(24, color=MUTED, lw=1, ls=(0, (3, 3)))
    fig.tight_layout()
    save(fig, "time-window.svg")


def envelope(chargers):
    service = SessionSourceService()
    start, end = window(DAY)
    sessions, _ = service.get(chargers[:60], DAY, source="spatial", assumption="base", seed=42)
    points = chargers[:60]
    poly = build_polytope(points, sessions, start, end)
    env = envelopes(poly)
    load = np.asarray(simulate_scenarios(points, sessions, start, end, "afap")[0])
    x = np.arange(288) / 6
    scheduled = np.cumsum(load / 6)
    fig, (power, energy) = plt.subplots(1, 2, figsize=(11, 4.4))
    power.fill_between(x, env["power_min_kw"], env["power_max_kw"], step="post", color=BLUE, alpha=0.16, lw=0)
    power.step(x, env["power_max_kw"], where="post", color=BLUE, lw=1.5, label="most power that can run")
    power.step(x, env["power_min_kw"], where="post", color=BLUE, lw=1.2, ls=(0, (1.5, 2)), label="least power that must run")
    power.step(x, load, where="post", color=INK, lw=1.8, label="scheduled load")
    energy.fill_between(x, env["cumulative_min_kwh"], env["cumulative_max_kwh"], step="post", color=BLUE, alpha=0.16, lw=0)
    energy.step(x, env["cumulative_max_kwh"], where="post", color=BLUE, lw=1.5)
    energy.step(x, env["cumulative_min_kwh"], where="post", color=BLUE, lw=1.2, ls=(0, (1.5, 2)))
    energy.step(x, scheduled, where="post", color=INK, lw=1.8)
    for ax in (power, energy):
        ax.axvspan(0, 24, color=ORANGE, alpha=0.045, lw=0)
        ax.axvspan(24, 48, color=BLUE, alpha=0.045, lw=0)
        ax.set_xticks(np.arange(0, 49, 6))
        ax.set_xticklabels([f"{int(t) % 24:02d}:00" for t in np.arange(0, 49, 6)])
        ax.set_xlim(0, 48)
        ax.set_ylim(bottom=0)
    # Read-off at 18:00 on the target day
    t = 24 + 18
    i = int(t * 6)
    power.annotate("", xy=(t, env["power_max_kw"][i]), xytext=(t, load[i]),
                   arrowprops=dict(arrowstyle="<->", color=GREEN, lw=1.5))
    label = dict(fontsize=8.5, va="center", bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5))
    power.text(t - 0.5, (env["power_max_kw"][i] + load[i]) / 2, "could absorb", color=GREEN, ha="right", **label)
    if load[i] - env["power_min_kw"][i] > 0.04 * max(env["power_max_kw"]):
        shed_x = t + 0.9
        power.annotate("", xy=(shed_x, env["power_min_kw"][i]), xytext=(shed_x, load[i]),
                       arrowprops=dict(arrowstyle="<->", color=ORANGE, lw=1.5))
        power.text(shed_x - 0.4, load[i] + 0.06 * max(env["power_max_kw"]), "could shed", color=ORANGE, ha="right", **label)
    power.set_title("Power (kW)")
    energy.set_title("Cumulative energy (kWh)")
    power.legend(loc="upper left", fontsize=8.2)
    fig.suptitle(f"Feasible envelope of {len(points)} chargers, As Fast As Possible schedule",
                 x=0.06, ha="left", fontsize=11.5, fontweight="semibold")
    fig.tight_layout()
    save(fig, "flexibility-envelope.svg")


# ---------------------------------------------------------------------------
# 3. Priors and day effects
# ---------------------------------------------------------------------------
def priors():
    tables = load_priors()
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.7))
    clock = np.arange(96) / 4
    ax = axes[0]
    for label, table, column, color, style in [
        ("weekday, public", tables["weekday"], "public", BLUE, "-"),
        ("weekday, workplace", tables["weekday"], "workplace", GREEN, "-"),
        ("weekend, public", tables["weekend"], "public", ORANGE, "-"),
    ]:
        mass = table[column].to_numpy(float).clip(min=0)
        ax.step(clock, mass / mass.sum() * 100, where="post", color=color, lw=1.6, ls=style, label=label)
    ax.set_title("Arrival time")
    ax.set_ylabel("Share of arrivals per quarter-hour (%)")
    hour_ticks(ax, 0, 24, 6)
    ax.legend(fontsize=8)
    for ax, key, unit, title in ((axes[1], "duration", "hours connected", "Connection time"),
                                 (axes[2], "energy", "kWh per session", "Energy per session")):
        table = tables[key]
        share = table["Percentage of charging events"].to_numpy(float)
        for column, color in (("public", BLUE), ("workplace", GREEN)):
            if column in table:
                ax.plot(table[column].to_numpy(float), share, color=color, lw=1.7, label=column)
        ax.set_title(title)
        ax.set_xlabel(unit)
        ax.set_ylabel("Share of sessions exceeding (%)")
        ax.set_ylim(0, 100)
        ax.set_xlim(left=0)
        ax.legend(fontsize=8)
    fig.tight_layout()
    save(fig, "session-priors.svg")


def archetypes():
    tables = load_priors()
    clock = np.arange(96) / 4
    colors = {"residential": PURPLE, "workplace": GREEN, "retail": ORANGE, "mixed": BLUE}
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 3.8), gridspec_kw=dict(width_ratios=[1.7, 1]))
    for kind, color in colors.items():
        curve = arrival_curve(tables, kind, weekend=False)
        left.step(clock, curve * 100, where="post", color=color, lw=1.7, label=kind)
    left.set_title("Weekday arrival profile by neighbourhood type")
    left.set_ylabel("Share of arrivals per quarter-hour (%)")
    hour_ticks(left, 0, 24, 3)
    left.legend(ncols=2, fontsize=8.5)
    names = list(colors)
    scales = [DURATION_SCALE[n] for n in names]
    energy = [0.75 if n == "retail" else 1.0 for n in names]
    pos = np.arange(len(names))
    right.bar(pos - 0.2, scales, width=0.38, color=[colors[n] for n in names], label="stay duration")
    right.bar(pos + 0.2, energy, width=0.38, color=[colors[n] for n in names], alpha=0.45, label="energy per session")
    right.set_xticks(pos)
    right.set_xticklabels(names, fontsize=8.5)
    right.axhline(1, color=MUTED, lw=0.8, ls=(0, (3, 3)))
    right.set_title("Scale against the public prior")
    right.legend(fontsize=8.2)
    fig.tight_layout()
    save(fig, "spatial-archetypes.svg")


def day_effects(chargers):
    first, last = dt.date(2026, 12, 7), dt.date(2027, 1, 10)
    days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    effects = get_calendar().effects("NL", first, last, 42)
    palette = {"workday": BLUE, "weekend": "#9aa7a0", "holiday": ORANGE, "partial": "#f3b08f"}
    x = np.arange(len(days))
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9.5, 6.2), sharex=True)
    top.bar(x, effects.volume, color=[palette[k] for k in effects.kind], width=0.8)
    top.axhline(1, color=MUTED, lw=0.8, ls=(0, (3, 3)))
    top.set_ylabel("Arrival volume factor")
    top.set_title("Day effects of the Netherlands, seed 42")
    twin = top.twinx()
    twin.plot(x, effects.temperature, color=INK, lw=1.4)
    twin.set_ylabel("Synthetic daily mean temperature (°C)")
    twin.grid(False)
    twin.spines["right"].set_visible(True)
    names = {"workday": "workday", "weekend": "weekend", "holiday": "public holiday", "partial": "bridge or partial holiday"}
    present = [kind for kind in names if kind in effects.kind]
    top.legend([Rectangle((0, 0), 1, 1, color=palette[kind]) for kind in present], [names[kind] for kind in present],
               ncols=len(present), loc="upper center", bbox_to_anchor=(0.5, -0.02), fontsize=8)
    service = SessionSourceService()
    for assumption, color in (("low", GREEN), ("base", BLUE), ("high", ORANGE)):
        daily, _ = service.days(chargers, first, last, source="simple", assumption=assumption, seed=42)
        counts = []
        for day, frame in daily:
            left, right = midnight(day).timestamp(), midnight(day + dt.timedelta(days=1)).timestamp()
            counts.append(int(((frame.start >= left) & (frame.start < right)).sum()))
        bottom.plot(x, counts, color=color, lw=1.7, marker="o", ms=3, label=f"{assumption} demand")
    bottom.set_ylabel(f"Sessions per day, {len(chargers)} chargers")
    bottom.legend(ncols=3, fontsize=8.5)
    ticks = [i for i, d in enumerate(days) if d.weekday() == 0]
    bottom.set_xticks(ticks)
    bottom.set_xticklabels([days[i].strftime("%d %b") for i in ticks])
    bottom.set_title("Sessions generated from the Simple source")
    fig.tight_layout()
    save(fig, "day-effects.svg")


def idle_time():
    chargers = [dict(id=1, power=11.0)]
    session = ScenarioSession(1, at(DAY, 8), at(DAY, 17), 22.0)
    start, end = midnight(DAY), midnight(DAY + dt.timedelta(days=1))
    load = np.asarray(simulate_scenarios(chargers, [session], start, end, "afap")[0])
    x = np.arange(144) / 6
    fig, ax = plt.subplots(figsize=(8.6, 2.9))
    ax.axvspan(8, 17, color=BAND, lw=0)
    step_fill(ax, x, load, BLUE)
    ax.annotate("", xy=(8, 12.2), xytext=(17, 12.2), arrowprops=dict(arrowstyle="<->", color=MUTED))
    ax.text(12.5, 12.6, "connection time 9 h", ha="center", color=INK_2, fontsize=9)
    ax.annotate("", xy=(8, 6), xytext=(10, 6), arrowprops=dict(arrowstyle="<->", color=BLUE))
    ax.text(9, 6.6, "charging 2 h\n22 kWh ÷ 11 kW", ha="center", color=BLUE, fontsize=8.5)
    ax.annotate("", xy=(10, 3), xytext=(17, 3), arrowprops=dict(arrowstyle="<->", color=ORANGE))
    ax.text(13.5, 3.6, "idle while plugged in 7 h", ha="center", color=ORANGE, fontsize=9)
    ax.set_ylim(0, 14)
    ax.set_ylabel("kW")
    hour_ticks(ax, 6, 19, 1)
    ax.set_title("Idle time is the connection time that charging at rated power does not need")
    fig.tight_layout()
    save(fig, "idle-time.svg")


# ---------------------------------------------------------------------------
# 4. Diagrams
# ---------------------------------------------------------------------------
ROW = 0.3  # height of one column row in a table box
HEAD = 0.52  # height of a table header


def table_box(ax, x, top, name, rows, width, color):
    """Draw one table and return its (left, bottom, right, top) rectangle."""
    height = HEAD + ROW * len(rows) + 0.08
    ax.add_patch(FancyBboxPatch((x, top - height), width, height, boxstyle="round,pad=0,rounding_size=0.12",
                                fc=SURFACE, ec=color, lw=1.4, zorder=2))
    ax.add_patch(FancyBboxPatch((x, top - HEAD), width, HEAD, boxstyle="round,pad=0,rounding_size=0.12",
                                fc=color, ec=color, lw=1.4, zorder=3))
    ax.text(x + 0.16, top - HEAD / 2, name, color="white", fontsize=9.5, fontweight="bold", va="center", zorder=4)
    for i, (column, kind) in enumerate(rows):
        y = top - HEAD - ROW * (i + 0.65)
        ax.text(x + 0.16, y, column, fontsize=8.2, va="center", zorder=4,
                color=PURPLE if kind == "fk" else INK, fontweight="semibold" if kind == "pk" else "normal")
        if kind:
            ax.text(x + width - 0.14, y, kind.upper(), fontsize=7, va="center", ha="right", color=MUTED, zorder=4)
    return x, top - height, x + width, top


def relation(ax, points, one_at, many_at):
    """A polyline from the 'one' side to the 'many' side, with its cardinality marked."""
    ax.plot(*zip(*points), color=MUTED, lw=1.3, zorder=1, solid_capstyle="round", solid_joinstyle="round")
    ax.text(*one_at, "1", fontsize=8.5, fontweight="bold", color=INK_2, ha="center", va="center", zorder=5,
            bbox=dict(fc="white", ec="none", pad=0.8))
    ax.text(*many_at, "n", fontsize=8.5, fontweight="bold", color=INK_2, ha="center", va="center", zorder=5,
            bbox=dict(fc="white", ec="none", pad=0.8))


def er_diagram():
    fig, ax = plt.subplots(figsize=(13.4, 8.2))
    ax.set_xlim(0, 17.0)
    ax.set_ylim(0.2, 9.4)
    ax.axis("off")
    t = lambda *args, **kwargs: table_box(ax, *args, **kwargs)  # noqa: E731
    t(0.3, 9.0, "operators", [("id", "pk"), ("name", "")], 3.2, PURPLE)
    t(5.0, 9.0, "columns", [("id", "pk"), ("operator_id", "fk"), ("location_id", "fk"), ("source, external_id", ""),
                            ("net_capacity", ""), ("comissioning_date", "")], 3.4, BLUE)
    t(9.8, 9.0, "charging_points", [("id", "pk"), ("column_id", "fk"), ("type", ""), ("power", ""),
                                    ("source, external_id", "")], 3.2, BLUE)
    t(0.3, 6.2, "locations", [("id", "pk"), ("street, zip_code, postal_name", ""), ("state, country", ""),
                              ("latitude, longitude", ""), ("geom  (POINT, 4326)", ""), ("source, external_id", "")], 3.6, BLUE)
    t(9.8, 5.5, "sessions", [("id", "pk"), ("cp_id", "fk"), ("start", ""), ("end", ""), ("consumption", "")], 3.2, GREEN)
    t(0.3, 2.7, "transformers", [("id", "pk"), ("location_id", "fk"), ("type", "")], 3.2, ORANGE)
    t(5.0, 2.7, "grid_connections", [("id", "pk"), ("transformer_id", "fk"), ("column_id", "fk")], 3.4, ORANGE)
    t(13.7, 9.0, "power_mixes", [("id", "pk"), ("country_zone", ""), ("datetime", ""), ("renewable_percentage", ""),
                                 ("co2_intensity", "")], 3.1, PURPLE)
    t(13.7, 5.5, "forecast_runs", [("id", "pk"), ("target_date", ""), ("timezone", ""), ("issued_at", ""),
                                   ("model_version", "")], 3.1, MUTED)
    t(13.7, 2.7, "forecast_hourly", [("run_id", "fk"), ("cp_id", "fk"), ("timestamp", ""), ("occupied, energy_kwh", "")], 3.1, MUTED)

    relation(ax, [(3.5, 8.4), (5.0, 8.4)], (3.75, 8.62), (4.75, 8.62))                         # operators -> columns
    relation(ax, [(8.4, 8.0), (9.8, 8.0)], (8.65, 8.22), (9.55, 8.22))                         # columns -> charging_points
    relation(ax, [(3.9, 5.0), (4.45, 5.0), (4.45, 7.2), (5.0, 7.2)], (4.15, 5.22), (4.75, 7.42))  # locations -> columns
    relation(ax, [(11.4, 6.98), (11.4, 5.5)], (11.65, 6.75), (11.65, 5.75))                    # charging_points -> sessions
    relation(ax, [(1.9, 3.88), (1.9, 2.7)], (2.15, 3.65), (2.15, 2.95))                        # locations -> transformers
    relation(ax, [(3.5, 1.95), (5.0, 1.95)], (3.75, 2.17), (4.75, 2.17))                       # transformers -> grid_connections
    relation(ax, [(6.7, 6.68), (6.7, 2.7)], (6.95, 6.43), (6.95, 2.95))                        # columns -> grid_connections
    relation(ax, [(15.25, 5.5 - 1.6), (15.25, 2.7)], (15.5, 3.62), (15.5, 2.95))               # forecast_runs -> forecast_hourly

    ax.text(0.3, 0.55, "forecast_sessions has the same keys as forecast_hourly (run_id, cp_id) and holds approximate sessions "
            "derived from CPFT occupancy.\npower_mixes is the legacy grid mix of the Netherlands and has no foreign keys; "
            "gamma_distributions (legacy, empty) is not drawn.", fontsize=8.5, color=MUTED, va="center")
    legend = [(BLUE, "charging infrastructure"), (GREEN, "stored sessions"), (ORANGE, "grid topology"),
              (PURPLE, "operators and grid mix"), (MUTED, "CPFT forecasts")]
    x0 = 9.8
    for i, (color, label) in enumerate(legend):
        ax.add_patch(Rectangle((x0, 2.9 - 0.34 * i - 0.1), 0.22, 0.2, color=color))
        ax.text(x0 + 0.35, 2.9 - 0.34 * i, label, fontsize=8.2, va="center", color=INK_2)
    fig.tight_layout()
    save(fig, "er-diagram.svg")


def block(ax, x, y, w, h, title, lines, color, columns=1):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12", fc=SURFACE, ec=color, lw=1.6, zorder=2))
    ax.add_patch(FancyBboxPatch((x, y + h - 0.5), w, 0.5, boxstyle="round,pad=0,rounding_size=0.12", fc=color, ec=color, zorder=3))
    ax.text(x + 0.15, y + h - 0.25, title, color="white", fontsize=9.5, fontweight="bold", va="center", zorder=4)
    per_column = -(-len(lines) // columns)
    for i, line in enumerate(lines):
        column, row = divmod(i, per_column)
        ax.text(x + 0.15 + column * (w / columns), y + h - 0.82 - 0.31 * row, line, fontsize=8.2, va="center",
                color=INK_2, zorder=4)


def architecture():
    fig, ax = plt.subplots(figsize=(12.6, 7.6))
    ax.set_xlim(0, 12.6)
    ax.set_ylim(-0.4, 7.6)
    ax.axis("off")
    block(ax, 0.2, 6.0, 12.2, 1.4, "Browser", ["Leaflet map and drawing tools", "Plotly charts in one card per area",
                                               "SheetJS Excel export", "bounded in-page request cache"], BLUE, columns=2)
    block(ax, 0.2, 4.0, 12.2, 1.4, "Flask application", ["/stations, /features and /kpi blueprints (views.py, features.py, kpi/user.py)",
                                                         "request validation and error mapping", "analysis_versions.py: revisions for cache freshness",
                                                         "station and density caches (station_cache.py, map_density.py)"],
          GREEN, columns=2)
    block(ax, 0.2, 1.8, 3.9, 1.7, "Session sources", ["session_sources.py", "scenario_world.py: Simple, Spatial",
                                                      "cpft_library.py: CPFT"], PURPLE)
    block(ax, 4.4, 1.8, 3.9, 1.7, "Calculation", ["scenario_profiles.py: strategies", "carbon_charging.py: min. carbon",
                                                  "flex_polytope.py, kpi/statistics.py"], PURPLE)
    block(ax, 8.5, 1.8, 3.9, 1.7, "Stored data", ["instance/default.sqlite (SpatiaLite)", "instance/grid_data.sqlite"], ORANGE)
    block(ax, 0.2, -0.3, 3.9, 1.6, "Bundled inputs", ["seed_data: priors, atlas", "calendar_effects.json", "cpft_library.npz"], ORANGE)
    block(ax, 4.4, -0.3, 3.9, 1.6, "External services (optional)", ["ReFlex, Energy-Charts: Min. Charging Cost",
                                                                    "PDOK, Photon: location search"], MUTED)

    def arrow(p, q, label=None, both=False):
        ax.annotate("", xy=q, xytext=p, arrowprops=dict(arrowstyle="<->" if both else "->", color=MUTED, lw=1.4), zorder=1)
        if label:
            ax.text(p[0] + 0.12, (p[1] + q[1]) / 2, label, fontsize=8, color=INK_2, va="center")

    arrow((6.3, 6.0), (6.3, 5.4), "JSON over HTTP", both=True)
    arrow((2.15, 4.0), (2.15, 3.5), "sessions")
    arrow((6.35, 4.0), (6.35, 3.5), "profiles, KPIs")
    arrow((10.45, 4.0), (10.45, 3.5), "chargers, grid")
    arrow((4.1, 2.65), (4.4, 2.65))
    arrow((2.15, 1.8), (2.15, 1.3))
    arrow((6.35, 1.8), (6.35, 1.3), "cost strategy")
    fig.tight_layout()
    save(fig, "architecture.svg")


def report_workbook():
    fig, ax = plt.subplots(figsize=(12.6, 3.7))
    ax.set_xlim(0, 12.6)
    ax.set_ylim(1.3, 4.9)
    ax.axis("off")
    table_box(ax, 0.1, 4.7, "Load Data   (one row per area and step)",
              [("Area Name", ""), ("Timestamp (UTC)", ""), ("EV Load (kW)", ""), ("Upward Flexibility (kW)", ""),
               ("Downward Flexibility (kW)", ""), ("Session source", ""), ("Demand assumption", ""),
               ("Synthetic", ""), ("Charging strategy", "")], 4.1, BLUE)
    table_box(ax, 4.5, 4.7, "Charger IDs", [("Area Name", ""), ("Charger IDs", "")], 3.0, GREEN)
    table_box(ax, 7.9, 4.7, "<Area>_KPIs   (one sheet per area)",
              [("Session source, demand, range, time zone", ""), ("Environmental method and strategy table", ""),
               ("arrival_dist_wd, arrival_dist_we, ...", ""), ("... one row per distribution", ""),
               ("sessions_per_day_0 ... sessions_per_day_6", ""), ("Charger | Occupancy | Utilisation | ...", ""),
               ("Headline figures", "")], 4.6, ORANGE)
    ax.text(4.5, 2.9, "Exported from the Load profiles or Flexibility tab:\nLoad Data and Charger IDs.\n\n"
            "Exported from the KPIs tab:\nCharger IDs and one KPI sheet per area.", fontsize=8.8, color=MUTED, va="top")
    fig.tight_layout()
    save(fig, "report-workbook.svg")


def main():
    single_session()
    priors()
    archetypes()
    idle_time()
    er_diagram()
    architecture()
    report_workbook()
    chargers = district_chargers()
    if not chargers:
        print("instance/default.sqlite not found: district figures skipped")
        return
    source_comparison(chargers)
    strategies_district(chargers)
    time_window(chargers)
    envelope(chargers)
    day_effects(chargers)


if __name__ == "__main__":
    main()
