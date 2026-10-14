from sqlalchemy import select, and_
from typing import Dict, List, Tuple, Optional, Callable, Any
import datetime as dt
from backend.models import (
    Session,
    ChargingPoint,
    Location,
    Operator
)

from sqlalchemy import select, func, extract
from scipy.stats import gamma
from backend.aggregators import time_forecast, sample_timestamps

# from backend.ml.predictor import PredictiveModel, DataScaler
# from backend.ml.preprocessing import Processing
from backend.ml.utils import generate_array_with_multiple_sequences, find_sequences

import json
import re
import os
from pathlib import Path
import yaml
import pandas as pd
import numpy as np
import datetime

NL_BOUNDARIES = """
                POLYGON((
                    3.3702 51.4457, 4.9736 51.2675, 5.7766 51.3468,
                    6.1567 50.8037, 6.6428 51.8503, 7.2165 53.1321,
                    6.0741 53.5104, 5.4245 53.4822, 4.8328 53.1028,
                    4.1010 53.4034, 3.3454 53.4822, 3.1321 53.1440,
                    3.2030 52.4241, 3.3702 51.4457
                ))
                """

AMS_BOUNDARIES = """
                POLYGON((
                4.7285 52.3011, 4.9578 52.3011, 4.9578 52.4312,
                4.7285 52.4312, 4.7285 52.3011
                ))
                """


def load_daily_charging_sessions(app, db, date, method="ML", scope="NL"):
    with app.app_context():

        if scope == "NL":
            boundaries = NL_BOUNDARIES
        else:
            raise ValueError(f"Scope {scope} not supported yet!!!")

        statement = (
            select(
                ChargingPoint.id,
                ChargingPoint.power,
                ChargingPoint.type,
                Location.latitude,
                Location.longitude,
                Location.street,
            )
            .join(ChargingPoint.column)
            .join(Location)
        ).filter(func.ST_Within(Location.geom,
                                func.ST_GeomFromText(boundaries)))

        query_result = db.session.execute(statement)
        charger_data = []
        for _, row in enumerate(query_result):
            charger_data.append({
                "id": row[0],
                "power": row[1],
                "type": row[2],
                "latitude": row[3],
                "longitude": row[4],
                "street": row[5],
            })

        print(f'Generating charging sessions for {len(charger_data)}' +
              f' charging points for date {date} using the {method} method .')

        if method == "ML":
            print(f'!!!! THE ML METHOD IS NOT IMPLEMENTED YET !!!!')
            print(f'!!!! USING RANDOM METHOD INSTEAD !!!!')
            charging_sessions = predict_charging_sessions(charger_data, date)
            db.session.add_all(charging_sessions)
        elif method == "MC":
            # charger_data  = charger_data[:2]
            # # set random seed for reproducibility
            # np.random.seed(42)
            
            charging_sessions = sample_charging_sessions_ev2gym(
                app, db,
                charger_data=charger_data,
                date=date,
                step_minutes=15,
                sessions_per_charger_per_day=2,  # tune per site/type
                allow_overrun=True,
            )
            db.session.add_all(charging_sessions)
        else:
            raise ValueError(f"Method {method} not supported yet!!!")

        db.session.commit()


def reset_charging_session_db(app, db):
    with app.app_context():
        db.session.query(Session).delete()
        db.session.commit()


def charging_sessions_overview(app, db):
    with app.app_context():
        statement = (
            select(
                Session.cp_id,
                Session.start,
                Session.end,
                Session.consumption
            )
        ).filter(
            Session.cp_id.in_([306650]),
            extract('year', Session.start) == 2025,
            extract('month', Session.start) == 1,
            extract('day', Session.start) == 21
        )
        query_result = db.session.execute(statement)
        i = 0
        for i, row in enumerate(query_result):
            print(row)
        print(f"Total number of charging sessions: {i}")


def predict_charging_sessions(charger_data, date):
    '''
    This function is used to predict the charging sessions for a day using the LSTM ML model.
    '''

    '''
    TESTING CODE
    root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
    historical_data_source = os.path.join(
        root_path, 'data/historical_data.csv')
    historical_data = pd.read_csv(historical_data_source)

    processing = Processing()
    processed_data = processing.process(historical_data)
    data_scaler = DataScaler()
    data_scaler.fit_update(processed_data)

    sequence = processing.create_input_sequence(processed_data, 24)

    model_path = os.path.join(root_path, 'data/dummy_model.pth')
    predictive_module = PredictiveModel(model_path, data_scaler)
    # predictions = predictive_module.predict(sequence)
    '''

    # TODO: predictions are random right now not providing any useful information.
    # for every charging point in charger_data, predict the charging sessions for a day.

    # Example usage
    N = len(charger_data)  # Number of sequences
    t_min = 25  # Minimum number of sequential ones in each sequence
    t_max = 70  # Maximum number of sequential ones in each sequence
    T = 144
    results = generate_array_with_multiple_sequences(N, t_min, t_max, T)
    sessions = find_sequences(results)

    date = datetime.datetime.combine(date, datetime.time(0, 0))

    session_list = []
    for i, charger in enumerate(charger_data):
        for session in sessions[i]:
            if session[1] - session[0] > 0:
                session_list.append(
                    Session(
                        cp_id=charger['id'],
                        start=date +
                        datetime.timedelta(minutes=int(session[0]*10)),
                        end=date +
                        datetime.timedelta(minutes=int(session[1]*10)),
                        consumption=np.random.uniform(5, 50, 1)[0]
                    )
                )

    return session_list


def sample_charging_sessions(charger_data, date):
    '''
    This function is used to sample the charging sessions for a day using the Monte Carlo method from historic data distribution.
    '''
    fp_config = Path("./backend/config.yaml")
    with open(fp_config) as ipf:
        config = yaml.load(ipf, Loader=yaml.SafeLoader)

    time = time_forecast(date)

    session_list = []
    for station in charger_data:
        id = station['id']

        n_sessions = np.random.choice(
            list(config["session_probabilities"].keys()),
            p=list(config["session_probabilities"].values()),
        )
        # print(f"Generating {n_sessions} charging sessions for {id}.")
        if n_sessions > 0:
            start_ts, end_ts = sample_timestamps(time, n_sessions)

            for i in range(n_sessions):
                session_start = start_ts[i]
                session_end = end_ts[i]

                # Determine day type: 0 for weekday, 1 for weekend
                day_type = (
                    1 if session_start.weekday() >= 5 else 0
                )  # 5 = Saturday, 6 = Sunday

                # Determine the hour of the day (0-23)
                session_hour = session_start.hour

                # Create the key for the distribution based on day type and hour
                # dist_key = f"{'weekend' if day_type == 1 else 'weekday'}_{day_type}_hour_{session_hour}"
                dist_key = f"weekday_{day_type}_hour_{session_hour}"

                # Retrieve distribution parameters
                dist_params = config["charging_demand_distributions"].get(
                    dist_key)

                if not dist_params:
                    # Handle missing distribution parameters
                    raise ValueError(
                        f"No distribution parameters found for key: {dist_key}"
                    )

                # Sample the required energy from the gamma distribution
                energy_required = gamma.rvs(
                    a=dist_params["shape"],
                    loc=dist_params["loc"],
                    scale=dist_params["scale"],
                )

                # print(f"   -start: {datetime.datetime.fromisoformat(session_start.isoformat())}, end: {datetime.datetime.fromisoformat(session_end.isoformat())}, energy: {energy_required:.2f} kWh")
                session_list.append(
                    Session(
                        cp_id=id,
                        start=datetime.datetime.fromisoformat(
                            session_start.isoformat()),
                        end=datetime.datetime.fromisoformat(
                            session_end.isoformat()),
                        consumption=energy_required
                    )
                )
                # input("Press Enter to continue...")
    return session_list


# sample_charging_sessions_ev2gym that *does not skip* busy chargers;
# it generates new sessions right after each charger becomes free (no overlaps).


# ---------- CSV helpers ----------
def _load_distributions(csv_dir: Path):
    df_arr_wd = pd.read_csv(csv_dir / "distribution-of-arrival.csv")
    df_arr_we = pd.read_csv(csv_dir / "distribution-of-arrival-weekend.csv")
    df_conn = pd.read_csv(csv_dir / "distribution-of-connection-time.csv")
    df_energy = pd.read_csv(csv_dir / "distribution-of-energy-demand.csv")
    return df_arr_wd, df_arr_we, df_conn, df_energy


def _arrival_mass(series: pd.Series) -> np.ndarray:
    vals = np.clip(series.to_numpy(dtype=float), 0.0, None)
    s = vals.sum()
    return (vals / s) if s > 0 else np.ones_like(vals) / len(vals)


def _quantile_from_desc_table(df: pd.DataFrame, col: str, u: np.ndarray) -> np.ndarray:
    # Interprets CSV as descending quantile curve vs "Percentage of charging events" 0..100 (asc)
    p = df["Percentage of charging events"].to_numpy(dtype=float)
    y = (df[col].to_numpy(dtype=float)
         if col in df.columns else df["public"].to_numpy(dtype=float))
    x = (1.0 - u) * 100.0
    return np.interp(x, p, y)

# Map your charger "type" to a site-type column used by the CSVs.
# If your CSVs only have ['public','private','workplace'], default to 'public'.


def _site_type_from_charger(station: Dict[str, Any]) -> str:
    chg_type = str(station.get("type", "")).lower()
    if chg_type in ("fast", "regular"):
        return "public"
    return "public"

# Optional: shorter connections on fast chargers


def _connection_time_scale(station: Dict[str, Any]) -> float:
    return 0.6 if str(station.get("type", "")).lower() == "fast" else 1.0

# ---------- main ----------


def sample_charging_sessions_ev2gym(
    app,
    db,
    charger_data: List[Dict[str, Any]],
    date: dt.date,
    *,
    step_minutes: int = 15,
    sessions_per_charger_per_day: float = 4,
    csv_dir: Optional[Path] = None,
    site_type_resolver: Optional[Callable[[Dict[str, Any]], str]] = None,
    rng: Optional[np.random.Generator] = None,
    allow_overrun: bool = True,      # if False: require end < day-end
    cap_energy_by_power: bool = True  # if True: E <= power_kW * hours
) -> List[Session]:
    """
    Generate non-overlapping sessions inside the given DATE (00:00→24:00).
    *Does not skip chargers that are busy* — it waits until they are free and
    continues generating thereafter, without overlapping existing or newly created sessions.
    Includes debug prints.
    """
    if rng is None:
        rng = np.random.default_rng()

    day_start = dt.datetime.combine(date, dt.time.min)
    day_end = day_start + dt.timedelta(days=1)
    step = dt.timedelta(minutes=step_minutes)

    # Locate CSVs
    if csv_dir is None:
        for cand in (Path("./seed_data"), Path("./backend/data"), Path("/mnt/data")):
            if (cand / "distribution-of-arrival.csv").exists():
                csv_dir = cand
                break
        else:
            raise FileNotFoundError(
                "Distributions not found in ./seed_data, ./backend/data, or /mnt/data")

    df_arr_wd, df_arr_we, df_conn, df_energy = _load_distributions(csv_dir)

    # Build per-step timeline for this day
    step_times = []
    t = day_start
    while t < day_end:
        step_times.append(t)
        t += step

    # ---------- 1) Pull existing intervals that intersect the day ----------
    with app.app_context():
        cp_ids = [int(s["id"]) for s in charger_data]
        rows = db.session.execute(
            select(Session.cp_id, Session.start, Session.end)
            .where(Session.cp_id.in_(cp_ids))
            .where(and_(Session.start < day_end, Session.end > day_start))
        ).all()

    existing_by_cp: Dict[int, List[Tuple[dt.datetime, dt.datetime]]] = {}
    for cp_id, s_start, s_end in rows:
        existing_by_cp.setdefault(int(cp_id), []).append((s_start, s_end))
    for k in existing_by_cp:
        existing_by_cp[k].sort(key=lambda ab: (ab[0], ab[1]))

    # Helper: first free time ≥ day_start (skip through any leading overlaps)
    def first_free_time(cp_id: int) -> dt.datetime:
        t0 = day_start
        for a, b in existing_by_cp.get(cp_id, []):
            if b <= t0:
                continue
            if a <= t0 < b:
                t0 = b  # occupied; becomes free at b
            elif a > t0:
                break   # already free at t0
        return t0

    # Helper: next busy interval start ≥ t_now (from existing only)
    def next_busy_start(cp_id: int, t_now: dt.datetime) -> Optional[dt.datetime]:
        for a, b in existing_by_cp.get(cp_id, []):
            if b <= t_now:
                continue
            if a >= t_now:
                return a
        return None

    # Overlap checker vs existing + scheduled
    scheduled: Dict[int, List[Tuple[dt.datetime, dt.datetime]]] = {}

    def interval_free(cp_id: int, a: dt.datetime, b: dt.datetime) -> bool:
        # existing
        for x, y in existing_by_cp.get(cp_id, []):
            if (a < y) and (b > x):
                return False
        # scheduled
        for x, y in scheduled.get(cp_id, []):
            if (a < y) and (b > x):
                return False
        return True

    # ---------- 2) Arrival mass & samplers ----------
    is_weekend = date.weekday() >= 5

    def mass_for_site(site: str) -> np.ndarray:
        df = df_arr_we if is_weekend else df_arr_wd
        series = df[site] if site in df.columns else df["public"]
        mass_day = _arrival_mass(series)
        out = np.empty(len(step_times), dtype=float)
        for i, ts in enumerate(step_times):
            minutes = ts.hour * 60 + ts.minute
            idx = (minutes // step_minutes) % len(mass_day)
            out[i] = mass_day[idx]
        s = out.sum()
        return out / s if s > 0 else np.ones_like(out) / len(out)

    def sample_conn_hours(site: str, u: float, scale: float = 1.0) -> float:
        base = float(_quantile_from_desc_table(
            df_conn, site, np.array([u]))[0])
        return max(base * scale, step_minutes / 60.0)

    def sample_energy(site: str, u: float) -> float:
        return max(float(_quantile_from_desc_table(df_energy, site, np.array([u]))[0]), 0.1)

    target_sessions = sessions_per_charger_per_day  # for a one-day window
    sessions: List[Session] = []

    # print(f"[spawn] date={date.isoformat()} | chargers={len(charger_data)} | step={step_minutes}min")

    # ---------- 3) Main EV2Gym-style per-step spawn loop ----------
    # Precompute per-charger state: site column, conn scale, probabilities, and initial free time
    per_cp = {}
    for st in charger_data:
        cp_id = int(st["id"])
        site = (site_type_resolver(st)
                if site_type_resolver else _site_type_from_charger(st))
        mass_vec = mass_for_site(site)
        p_vec = target_sessions * mass_vec
        free_at = first_free_time(cp_id)
        per_cp[cp_id] = {
            "site": site,
            "p_vec": p_vec,
            "free_at": free_at,
            "conn_scale": _connection_time_scale(st),
            "power": float(st.get("power") or 0.0),
        }
        # if free_at > day_start:
        #     print(f"[spawn] cp {cp_id} busy at day start; first free at {free_at.isoformat()} "
        #           f"(blocked intervals={len(existing_by_cp.get(cp_id, []))})")

    for i, t_now in enumerate(step_times):
        for st in charger_data:
            cp_id = int(st["id"])
            state = per_cp[cp_id]
            if t_now < state["free_at"]:
                # Uncomment for very verbose logs:
                # print(f"[spawn] cp {cp_id} @ {t_now.time()} still busy until {state['free_at'].time()}")
                continue

            p = state["p_vec"][i]
            if p <= 0:
                continue

            u = rng.random()
            # Debug: planned spawn probability vs RNG
            # if u < min(p * 3, 1.0):  # print more often when it's close to spawning
            #     print(f"[spawn?] cp {cp_id} @ {t_now.time()}  p={p:.4f}  u={u:.4f}")
            mult = 2
            stay_mult = 1.2
            
            if u < p * mult:
                site = state["site"]
                hours = sample_conn_hours(
                    site, rng.random(), state["conn_scale"])
                # print(f"[sample] cp {cp_id} conn_hours={hours:.2f}")
                hours *= stay_mult  # bias towards longer stays
                # print(f'hours={hours:.2f}')
                end_time = t_now + dt.timedelta(hours=hours)

                # Optional: require end inside the day
                # if not allow_overrun and end_time > day_end:
                #     print(f"[skip]  cp {cp_id} @ {t_now.time()} -> end {end_time.time()} exceeds day_end")
                #     continue

                # Ensure no overlap with existing/scheduled
                # if not interval_free(cp_id, t_now, end_time):
                #     # If overlap, we can try to shorten to the next busy start (stay within free gap)
                #     next_busy = next_busy_start(cp_id, t_now)
                #     if next_busy and next_busy > t_now and next_busy > t_now + step:
                #         # end_time = min(end_time, next_busy)
                #         if not interval_free(cp_id, t_now, end_time):
                #             # print(f"[conflict] cp {cp_id} interval {t_now.time()}–{end_time.time()} still overlaps; skipping")
                #             continue
                #         else:
                #             continue
                #             # print(f"[adjust]  cp {cp_id} clipped to free gap: end={end_time.time()}")
                #     else:
                #         # print(f"[conflict] cp {cp_id} overlaps with existing; skipping")
                #         continue

                energy_kwh = sample_energy(site, rng.random())
                if cap_energy_by_power and state["power"] > 0:
                    max_e = state["power"] * hours  # kW * h = kWh
                    if energy_kwh > max_e:
                        # print(f"[cap]   cp {cp_id} energy {energy_kwh:.1f} kWh > {max_e:.1f} kWh (P*hours); capping")
                        energy_kwh = max_e

                # Record and advance free_at
                scheduled.setdefault(cp_id, []).append((t_now, end_time))
                # next chance is after this finishes
                state["free_at"] = end_time

                sessions.append(Session(cp_id=cp_id, start=t_now,
                                end=end_time, consumption=energy_kwh))
                # print(f"[new]   cp {cp_id} {t_now.isoformat()} → {end_time.isoformat()}  E={energy_kwh:.1f} kWh")

    print(f"[done] generated {len(sessions)} sessions for {date.isoformat()}")

    # plot_sessions(sessions, date)
    return sessions


# plot sessions with matplotlib (for testing)
def plot_sessions(sessions: List[Session], date: dt.date):
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    if not sessions:
        print("No sessions to plot.")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    for sess in sessions:
        ax.plot([sess.start, sess.end], [sess.cp_id, sess.cp_id], marker='o')

    ax.set_title('Charging Sessions')
    ax.set_xlabel('Time')
    ax.set_ylabel('Charging Point ID')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    plt.xticks(rotation=45)
    plt.grid(True)
    plt.tight_layout()
    plt.show()


# create a function that querries the database and finds all sessions for a given charger id and plots it
def plot_sessions_for_charger(app, db, charger_id: int):
    with app.app_context():
        statement = (
            select(
                Session.start,
                Session.end,
                Session.consumption
            )
        ).filter(
            Session.cp_id == charger_id
        )
        query_result = db.session.execute(statement)
        sessions = []
        for row in query_result:
            sessions.append(Session(
                cp_id=charger_id,
                start=row[0],
                end=row[1],
                consumption=row[2]
            ))
        if sessions:
            date = sessions[0].start.date()
            plot_sessions(sessions, date)
        else:
            print(f"No sessions found for charger ID {charger_id}.")
            return
