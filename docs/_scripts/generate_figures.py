"""Regenerate the data-driven figures used in the documentation.

The figures are produced by the same functions the web application uses
(``backend.aggregators``), applied either to a hand-made example session or to
real sessions read from the local SQLite database, so the docs stay faithful to
the code. Run from the repository root:

    uv run --with matplotlib python docs/_scripts/generate_figures.py

Outputs are written to ``docs/_static/figures``. Figures that need the
database (``instance/default.sqlite``) or the distribution CSVs in ``./seed_data``
are skipped with a message when those files are missing.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from scipy.stats import gamma  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.aggregators import (  # noqa: E402
    simulate_avg_charging_profiles_from_sessions,
    simulate_delayed_profiles_from_sessions,
    simulate_uncontrolled_profiles_from_sessions,
)

OUT = ROOT / "docs" / "_static" / "figures"
DB = ROOT / "instance" / "default.sqlite"
DATA = ROOT / "seed_data"

# Reference categorical palette, first three slots (validated all-pairs).
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SURFACE = "#fcfcfb"
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"

STRATEGIES = [
    ("afap", "As Fast As Possible", BLUE, simulate_uncontrolled_profiles_from_sessions),
    ("alap", "As Late As Possible", ORANGE, simulate_delayed_profiles_from_sessions),
    ("avg", "Average Power", AQUA, simulate_avg_charging_profiles_from_sessions),
]

plt.rcParams.update(
    {
        "font.family": ["Segoe UI", "DejaVu Sans"],
        "font.size": 10,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK_2,
        "ytick.labelcolor": INK_2,
        "legend.frameon": False,
        "legend.labelcolor": INK_2,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "svg.fonttype": "path",
        "lines.linewidth": 2,
    }
)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print(f"wrote {name}")


def hours_axis(ax, steps=288):
    """Label a 10-minute step axis in hours across the two-day window."""
    ticks = np.arange(0, steps + 1, 36)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{(t // 6) % 24:02d}:00" for t in ticks])
    ax.set_xlim(0, steps)


def day_split(ax, ymax):
    ax.axvline(144, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.text(72, ymax, "Day D-1  (\"Yesterday\")", ha="center", va="bottom", color=INK_2, fontsize=9)
    ax.text(216, ymax, "Day D  (\"Today\")", ha="center", va="bottom", color=INK_2, fontsize=9)


# ---------------------------------------------------------------------------
# 1. One session under each strategy
# ---------------------------------------------------------------------------
def single_session():
    chargers = {1: 11.0}
    arrive = dt.datetime(2025, 10, 15, 8, 0)
    depart = dt.datetime(2025, 10, 15, 17, 0)
    sessions = [(1, arrive, depart, 22.0)]
    start = "2025-10-14"
    a, d = 144 + 8 * 6, 144 + 17 * 6

    fig, axes = plt.subplots(3, 1, figsize=(9, 6.4), sharex=True, sharey=True)
    for ax, (_, label, color, fn) in zip(axes, STRATEGIES):
        load, _, _ = fn(chargers, sessions, start)
        load = np.asarray(load)
        ax.axvspan(a, d, color=GRID, alpha=0.55, lw=0)
        ax.step(np.arange(288), load, where="post", color=color)
        ax.fill_between(np.arange(288), load, step="post", color=color, alpha=0.18, lw=0)
        energy = load.sum() / 6
        ax.set_title(f"{label}  ·  {energy:.1f} kWh delivered", fontsize=10)
        ax.set_ylabel("kW")
        ax.set_ylim(0, 13.5)
        ax.set_xlim(a - 18, d + 18)
    axes[0].annotate("arrival 08:00", (a, 12.4), xytext=(4, 0), textcoords="offset points", color=INK_2, fontsize=8.5, va="center")
    axes[0].annotate("departure 17:00", (d, 12.4), xytext=(-4, 0), textcoords="offset points", color=INK_2, fontsize=8.5, va="center", ha="right")
    ticks = np.arange(a - 12, d + 13, 12)
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels([f"{(t // 6) % 24:02d}:00" for t in ticks])
    axes[-1].set_xlabel("Time of day D  (10-minute steps)")
    fig.suptitle("One session: 22 kWh on an 11 kW charger, plugged in 08:00–17:00", x=0.065, ha="left", fontsize=12, fontweight="semibold", color=INK)
    fig.tight_layout()
    save(fig, "strategy-single-session.svg")

    # Flexibility for the same session
    fig, axes = plt.subplots(3, 1, figsize=(9, 6.4), sharex=True, sharey=True)
    for ax, (_, label, color, fn) in zip(axes, STRATEGIES):
        load, up, down = (np.asarray(v) for v in fn(chargers, sessions, start))
        x = np.arange(288)
        ax.axvspan(a, d, color=GRID, alpha=0.55, lw=0)
        ax.axhline(0, color=MUTED, lw=1)
        ax.step(x, load, where="post", color=INK_2, lw=1.2, ls=(0, (2, 2)), label="load")
        ax.fill_between(x, up, step="post", color=BLUE, alpha=0.35, lw=0, label="upward flexibility")
        ax.step(x, up, where="post", color=BLUE, lw=1.6)
        ax.fill_between(x, down, step="post", color=ORANGE, alpha=0.35, lw=0, label="downward flexibility")
        ax.step(x, down, where="post", color=ORANGE, lw=1.6)
        ax.set_title(label, fontsize=10)
        ax.set_ylabel("kW")
        ax.set_xlim(a - 18, d + 18)
        ax.set_ylim(-13.5, 13.5)
    axes[0].legend(loc="upper right", ncols=3, fontsize=8.5)
    ticks = np.arange(a - 12, d + 13, 12)
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels([f"{(t // 6) % 24:02d}:00" for t in ticks])
    axes[-1].set_xlabel("Time of day D  (10-minute steps)")
    fig.suptitle("Flexibility signals returned for the same session", x=0.065, ha="left", fontsize=12, fontweight="semibold", color=INK)
    fig.tight_layout()
    save(fig, "strategy-flexibility.svg")


# ---------------------------------------------------------------------------
# 2. Real aggregate for a district (needs the database)
# ---------------------------------------------------------------------------
def parse_ts(s):
    return dt.datetime.fromisoformat(s)


def district_aggregate(date="2025-10-15", bbox=(4.885, 52.355, 4.93, 52.375)):
    if not DB.exists():
        print("skip district aggregate: no database")
        return
    con = sqlite3.connect(DB)
    lon0, lat0, lon1, lat1 = bbox
    chargers = dict(
        con.execute(
            """SELECT cp.id, cp.power FROM charging_points cp
               JOIN columns c ON cp.column_id = c.id
               JOIN locations l ON c.location_id = l.id
               WHERE l.longitude BETWEEN ? AND ? AND l.latitude BETWEEN ? AND ?""",
            (lon0, lon1, lat0, lat1),
        ).fetchall()
    )
    day = dt.date.fromisoformat(date)
    prev = (day - dt.timedelta(days=1)).isoformat()
    ids = ",".join(str(i) for i in chargers)
    rows = con.execute(
        f"""SELECT cp_id, start, "end", consumption FROM sessions
            WHERE cp_id IN ({ids}) AND (date(start) = ? OR date("end") = ?)""",
        (date, prev),
    ).fetchall()
    sessions = [(r[0], parse_ts(r[1]), parse_ts(r[2]), r[3]) for r in rows]

    fig, ax = plt.subplots(figsize=(10, 4.2))
    x = np.arange(288)
    top = 0
    for _, label, color, fn in STRATEGIES:
        load = np.asarray(fn(chargers, sessions, prev)[0])
        top = max(top, load.max())
        ax.step(x, load, where="post", color=color, label=f"{label}  ({load.sum() / 6:,.0f} kWh)")
    ax.set_ylim(0, top * 1.15)
    day_split(ax, top * 1.16)
    hours_axis(ax)
    ax.set_ylabel("Aggregated power (kW)")
    ax.set_xlabel("Time (10-minute steps, two-day window)")
    ax.legend(loc="upper left", fontsize=9)
    fig.suptitle(
        f"Amsterdam city centre · {len(chargers)} charging points · {len(sessions)} sessions · D = {date}",
        x=0.065, ha="left", y=1.04, fontsize=12, fontweight="semibold", color=INK,
    )
    fig.tight_layout()
    save(fig, "district-strategies.svg")


# ---------------------------------------------------------------------------
# 3. Session generator inputs
# ---------------------------------------------------------------------------
def config_distributions():
    cfg = yaml.safe_load((ROOT / "backend" / "config.yaml").read_text())
    probs = cfg["session_probabilities"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 3.6), gridspec_kw={"width_ratios": [1, 1.5]})
    k = np.array(list(probs.keys()))
    p = np.array(list(probs.values()))
    ax1.bar(k[:8], p[:8] * 100, color=BLUE, width=0.7)
    for kk, pp in zip(k[:4], p[:4]):
        ax1.text(kk, pp * 100 + 1.2, f"{pp * 100:.0f}%", ha="center", color=INK_2, fontsize=8.5)
    ax1.set_xticks(k[:8])
    ax1.set_xlabel("Sessions per charger per day")
    ax1.set_ylabel("Probability (%)")
    ax1.set_title("Sessions-per-day probability")
    ax1.grid(axis="x", visible=False)

    dists = cfg["charging_demand_distributions"]
    hours = np.arange(24)
    for day_type, label, color in [(0, "weekday", BLUE), (1, "weekend", ORANGE)]:
        params = [dists[f"weekday_{day_type}_hour_{h}"] for h in hours]
        mean = np.array([q["shape"] * q["scale"] for q in params])
        lo = np.array([gamma.ppf(0.25, q["shape"], scale=q["scale"]) for q in params])
        hi = np.array([gamma.ppf(0.75, q["shape"], scale=q["scale"]) for q in params])
        ax2.fill_between(hours, lo, hi, color=color, alpha=0.15, lw=0)
        ax2.plot(hours, mean, color=color, marker="o", ms=4, label=f"{label} mean (band: IQR)")
    ax2.set_xticks(range(0, 24, 3))
    ax2.set_xlabel("Hour of arrival")
    ax2.set_ylabel("Energy demand (kWh)")
    ax2.set_title("Gamma energy-demand model by arrival hour")
    ax2.legend(fontsize=8.5, loc="upper right")
    fig.tight_layout()
    save(fig, "config-distributions.svg")


def ev2gym_inputs():
    needed = [
        "distribution-of-arrival.csv",
        "distribution-of-arrival-weekend.csv",
        "distribution-of-connection-time.csv",
        "distribution-of-energy-demand.csv",
    ]
    if not all((DATA / n).exists() for n in needed):
        print("skip EV2Gym inputs: distribution CSVs missing from ./seed_data")
        return
    wd = pd.read_csv(DATA / needed[0], encoding="utf-8-sig")
    we = pd.read_csv(DATA / needed[1], encoding="utf-8-sig")
    conn = pd.read_csv(DATA / needed[2], encoding="utf-8-sig")
    energy = pd.read_csv(DATA / needed[3], encoding="utf-8-sig")

    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    x = np.arange(len(wd)) / 4
    for df, label, color in [(wd, "weekday", BLUE), (we, "weekend", ORANGE)]:
        mass = df["public"].clip(lower=0)
        axes[0].plot(np.arange(len(df)) / 4, mass / mass.sum() * 100, color=color, label=label)
    axes[0].set_xticks(range(0, 25, 6))
    axes[0].set_xlabel("Arrival time (h)")
    axes[0].set_ylabel("Share of arrivals per 15 min (%)")
    axes[0].set_title("Arrival mass (public)")
    axes[0].legend(fontsize=8.5)

    axes[1].plot(conn["Percentage of charging events"], conn["public"], color=BLUE)
    axes[1].set_xlabel("Charging events exceeding value (%)")
    axes[1].set_ylabel("Connection time (h)")
    axes[1].set_title("Connection-time curve (public)")

    axes[2].plot(energy["Percentage of charging events"], energy["public"], color=BLUE)
    axes[2].set_xlabel("Charging events exceeding value (%)")
    axes[2].set_ylabel("Energy demand (kWh)")
    axes[2].set_title("Energy-demand curve (public)")
    fig.tight_layout()
    save(fig, "ev2gym-inputs.svg")


# ---------------------------------------------------------------------------
# 4. Database overview figures
# ---------------------------------------------------------------------------
def database_figures():
    if not DB.exists():
        print("skip database figures: no database")
        return
    con = sqlite3.connect(DB)

    power = pd.read_sql("SELECT power, type FROM charging_points WHERE power IS NOT NULL", con)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    counts = power.assign(p=power["power"].round(1)).groupby(["p"]).size().sort_index()
    labels = [f"{p:g}" for p in counts.index]
    ax.bar(labels, counts.values, color=BLUE, width=0.7)
    for i, v in enumerate(counts.values):
        ax.text(i, v + counts.max() * 0.015, f"{v}", ha="center", fontsize=8, color=INK_2)
    ax.set_xlabel("Rated connector power (kW)")
    ax.set_ylabel("Charging points")
    ax.set_title(f"Charging points by rated power  ·  {len(power)} points in the Amsterdam dataset")
    ax.grid(axis="x", visible=False)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    fig.tight_layout()
    save(fig, "db-charger-power.svg")

    pm = pd.read_sql(
        "SELECT datetime, co2_intensity, renewable_percentage FROM power_mixes WHERE country_zone='NL' ORDER BY datetime",
        con,
        parse_dates=["datetime"],
    )
    if len(pm):
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 4.6), sharex=True)
        a1.plot(pm["datetime"], pm["co2_intensity"], color=BLUE, marker="o", ms=3, lw=1.5)
        a1.set_ylabel("gCO₂eq/kWh")
        a1.set_title("Grid carbon intensity (NL)")
        a2.plot(pm["datetime"], pm["renewable_percentage"], color=AQUA, marker="o", ms=3, lw=1.5)
        a2.set_ylabel("%")
        a2.set_title("Renewable share of consumption (NL)")
        fig.autofmt_xdate()
        fig.tight_layout()
        save(fig, "db-power-mix.svg")

    sessions = pd.read_sql(
        "SELECT start, \"end\", consumption FROM sessions WHERE start >= '2025-09-08' AND start < '2025-10-20'",
        con,
        parse_dates=["start", "end"],
    )
    sessions["dur"] = (sessions["end"] - sessions["start"]).dt.total_seconds() / 3600
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.4))
    axes[0].hist(sessions["start"].dt.hour + sessions["start"].dt.minute / 60, bins=96, color=BLUE)
    axes[0].set_xlabel("Arrival time (h)")
    axes[0].set_ylabel("Sessions")
    axes[0].set_title("Arrival time")
    axes[1].hist(sessions["dur"].clip(upper=30), bins=60, color=ORANGE)
    axes[1].set_xlabel("Connection duration (h, clipped at 30)")
    axes[1].set_title("Connection duration")
    axes[2].hist(sessions["consumption"].clip(upper=80), bins=60, color=AQUA)
    axes[2].set_xlabel("Energy per session (kWh, clipped at 80)")
    axes[2].set_title("Energy per session")
    for ax in axes:
        ax.grid(axis="x", visible=False)
    fig.suptitle(
        f"Stored sessions, 8 Sep – 19 Oct 2025  ·  n = {len(sessions):,}",
        x=0.05, ha="left", fontsize=12, fontweight="semibold", color=INK,
    )
    fig.tight_layout()
    save(fig, "db-session-stats.svg")


# ---------------------------------------------------------------------------
# 5. Time grid schematic
# ---------------------------------------------------------------------------
def time_grid():
    fig, ax = plt.subplots(figsize=(10, 1.9))
    ax.set_xlim(-4, 292)
    ax.set_ylim(0, 3)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 1), 144, 1, color="#cde2fb", lw=0))
    ax.add_patch(plt.Rectangle((144, 1), 144, 1, color="#86b6ef", lw=0))
    for s in range(0, 289, 6):
        ax.plot([s, s], [1, 1.12 if s % 36 else 1.25], color="#184f95", lw=0.6)
    ax.text(72, 1.5, "Day D-1 · steps 0–143", ha="center", va="center", color=INK, fontsize=10, fontweight="semibold")
    ax.text(216, 1.5, "Day D · steps 144–287", ha="center", va="center", color=INK, fontsize=10, fontweight="semibold")
    for s in range(0, 289, 36):
        ax.text(s, 0.7, f"{(s // 6) % 24:02d}:00", ha="center", color=INK_2, fontsize=8.5)
    ax.text(0, 2.45, "step = ⌊hour·6 + minute/10⌋ + 144·[session starts on day D]", color=INK_2, fontsize=9.5)
    ax.text(288, 2.45, "Δt = 10 min · 288 steps", color=INK_2, fontsize=9.5, ha="right")
    save(fig, "time-grid.svg")


if __name__ == "__main__":
    single_session()
    district_aggregate()
    config_distributions()
    ev2gym_inputs()
    database_figures()
    time_grid()
