import random
import numpy as np
import datetime
import polars as pl
from itertools import compress
import json
import time
from collections import defaultdict as Dict

from backend.api_calls.reflex import create_ReFlex_Query
from backend.api_calls.prices import retrieve_day_ahead_prices
import requests


def simulate_uncontrolled_profiles_from_sessions(chargers, charging_sessions, start_date):
    time = np.arange(0, 144*2)
    profile = pl.DataFrame({"time": time, "power": 0})
    agg_up_flex = pl.DataFrame({"time": time, "power": 0})
    agg_down_flex = pl.DataFrame({"time": time, "power": 0})

    year = int(start_date.split("-")[0])
    month = int(start_date.split("-")[1])
    day = int(start_date.split("-")[2])

    for session in charging_sessions:
        cp_id = session[0]
        start = session[1]
        end = session[2]

        # skip if the session is not in the 2 day window
        if start.date() < datetime.date(year, month, day) or start.date() > datetime.date(year, month, day) + datetime.timedelta(days=1):
            continue

        if start.day == day:
            overhead = 0
        else:
            overhead = 144

        start_step = int(start.hour * 6 + start.minute / 10) + overhead
        end_step = int(end.hour * 6 + end.minute / 10) + overhead
        consumption = session[3]
        power_limit = chargers[cp_id]
        if power_limit is None or power_limit <= 0:
            power_limit = 11

        # how many 10 min intervals are required to charge the car
        n_intervals = int(consumption / (power_limit / 6))

        if start_step+n_intervals > end_step:
            n_intervals = end_step - start_step
            
        profile = profile.with_columns(
            power=pl.when(
                (pl.col("time") >= start_step) & (
                    pl.col("time") < (start_step + n_intervals))
            )
            .then(pl.col("power") + power_limit)
            .otherwise(pl.col("power"))
            .alias("power")
        )
        agg_down_flex = agg_down_flex.with_columns(
            power=pl.when(
                (pl.col("time") <= end_step) & (
                    pl.col("time") > (end_step - n_intervals))
            )
            .then(pl.col("power") - power_limit)
            .otherwise(pl.col("power"))
            .alias("power")
        )

        if start_step + n_intervals < end_step:
            profile = profile.with_columns(
                power=pl.when(
                    (pl.col("time") == (start_step+n_intervals))
                )
                .then(pl.col("power") + ((consumption % (power_limit / 6))/power_limit/6)*(power_limit))
                .otherwise(pl.col("power"))
                .alias("power")
            )
            # agg_up_flex = agg_up_flex.with_columns(
            #     power=pl.when(
            #         (pl.col("time") == (end_step - n_intervals-1))
            #     )
            #     .then(pl.col("power") + power_limit - ((consumption % (power_limit / 6))/power_limit/6)*(power_limit))
            #     .otherwise(pl.col("power"))
            #     .alias("power")
            # )
            # agg_down_flex = agg_down_flex.with_columns(
            #     power=pl.when(
            #         (pl.col("time") == (end_step - n_intervals))
            #     )
            #     .then(pl.col("power") - ((consumption % (power_limit / 6))/power_limit/6)*(power_limit))
            #     .otherwise(pl.col("power"))
            #     .alias("power")
            # )

    # return the load profile without hte time column and as a list
    return profile["power"].to_list(), agg_up_flex["power"].to_list(), agg_down_flex["power"].to_list()


def simulate_delayed_profiles_from_sessions(chargers, charging_sessions, start_date):
    time = np.arange(0, 144*2)

    profile = pl.DataFrame({"time": time, "power": 0})
    agg_up_flex = pl.DataFrame({"time": time, "power": 0})
    agg_down_flex = pl.DataFrame({"time": time, "power": 0})

    year = int(start_date.split("-")[0])
    month = int(start_date.split("-")[1])
    day = int(start_date.split("-")[2])

    for session in charging_sessions:
        cp_id = session[0]
        start = session[1]
        end = session[2]

        # skip if the session is not in the 2 day window
        if start.date() < datetime.date(year, month, day) or start.date() > datetime.date(year, month, day) + datetime.timedelta(days=1):
            continue

        if start.day == day:
            overhead = 0
        else:
            overhead = 144

        start_step = int(start.hour * 6 + start.minute / 10) + overhead
        end_step = int(end.hour * 6 + end.minute / 10) + overhead
        consumption = session[3]
        power_limit = chargers[cp_id]
        if power_limit is None or power_limit <= 0:
            power_limit = 11

        # how many 10 min intervals are required to charge the car
        n_intervals = int(consumption / (power_limit / 6))
        if start_step > end_step - n_intervals:
            n_intervals = end_step - start_step
        profile = profile.with_columns(
            power=pl.when(
                (pl.col("time") <= end_step) & (
                    pl.col("time") > (end_step - n_intervals))
            )
            .then(pl.col("power") + power_limit)
            .otherwise(pl.col("power"))
            .alias("power")
        )
        agg_down_flex = agg_down_flex.with_columns(
            power=pl.when(
                (pl.col("time") <= end_step) & (
                    pl.col("time") > (end_step - n_intervals))
            )
            .then(pl.col("power") - power_limit)
            .otherwise(pl.col("power"))
            .alias("power")
        )
        
        agg_up_flex = agg_up_flex.with_columns(
            power=pl.when(
                (pl.col("time") == (end_step - n_intervals))
            )
            .then(pl.col("power") + power_limit - ((consumption % (power_limit / 6))/power_limit/6)*(power_limit))
            .otherwise(pl.col("power"))
            .alias("power")
        )

        if start_step < end_step - n_intervals:
            profile = profile.with_columns(
                power=pl.when(
                    (pl.col("time") == (end_step - n_intervals))
                )
                .then(pl.col("power") + ((consumption % (power_limit / 6))/power_limit/6)*(power_limit))
                .otherwise(pl.col("power"))
                .alias("power")
            )
            # agg_up_flex = agg_up_flex.with_columns(
            #     power=pl.when(
            #         (pl.col("time") == (end_step - n_intervals))
            #     )
            #     .then(pl.col("power") + power_limit - ((consumption % (power_limit / 6))/power_limit/6)*(power_limit))
            #     .otherwise(pl.col("power"))
            #     .alias("power")
            # )
            # agg_down_flex = agg_down_flex.with_columns(
            #     power=pl.when(
            #         (pl.col("time") == (end_step - n_intervals-1))
            #     )
            #     .then(pl.col("power") - ((consumption % (power_limit / 6))/power_limit/6)*(power_limit))
            #     .otherwise(pl.col("power"))
            #     .alias("power")
            # )

    return profile["power"].to_list(), agg_up_flex["power"].to_list(), agg_down_flex["power"].to_list()


def simulate_avg_charging_profiles_from_sessions(chargers, charging_sessions, start_date):
    time = np.arange(0, 144*2)

    profile = pl.DataFrame({"time": time, "power": 0})
    agg_up_flex = pl.DataFrame({"time": time, "power": 0})
    agg_down_flex = pl.DataFrame({"time": time, "power": 0})
    year = int(start_date.split("-")[0])
    month = int(start_date.split("-")[1])
    day = int(start_date.split("-")[2])

    for session in charging_sessions:
        cp_id = session[0]
        start = session[1]
        end = session[2]

        # skip if the session is not in the 2 day window
        if start.date() < datetime.date(year, month, day) or start.date() > datetime.date(year, month, day) + datetime.timedelta(days=1):
            continue

        if start.day == day:
            overhead = 0
        else:
            overhead = 144

        start_step = int(start.hour * 6 + start.minute / 10) + overhead
        end_step = int(end.hour * 6 + end.minute / 10) + overhead
        consumption = session[3]
        power_limit = chargers[cp_id]
        if power_limit is None or power_limit <= 0:
            power_limit = 11

        # how many 10 min intervals are required to charge the car
        n_intervals = int(consumption / ((power_limit/2) / 6))

        if start_step + n_intervals > end_step:
            n_intervals = end_step - start_step

        profile = profile.with_columns(
            power=pl.when(
                (pl.col("time") >= start_step) & (
                    pl.col("time") < (start_step + n_intervals))
            )
            .then(pl.col("power") + (power_limit/2))
            .otherwise(pl.col("power"))
            .alias("power")
        )
        agg_down_flex = agg_down_flex.with_columns(
            power=pl.when(
                (pl.col("time") >= start_step) & (
                    pl.col("time") < (start_step + n_intervals))
            )
            .then(pl.col("power") - (power_limit/2))
            .otherwise(pl.col("power"))
            .alias("power")
        )
        agg_up_flex = agg_up_flex.with_columns(
            power=pl.when(
                (pl.col("time") >= start_step) & (
                    pl.col("time") < (start_step + n_intervals))
            )
            .then(pl.col("power") + power_limit-(power_limit/2))
            .otherwise(pl.col("power"))
            .alias("power")
        )

    return profile["power"].to_list(), agg_up_flex["power"].to_list(), agg_down_flex["power"].to_list()


def simulate_cost_optimal_operation(chargers, charging_sessions, start_date):
    prices = retrieve_day_ahead_prices(start_date, days_ahead=2)

    # print(prices)
    # print(f'len prices: {len(prices)}')

    agg_load_profile = np.zeros(288)
    agg_up_flex = np.zeros(288)
    agg_down_flex = np.zeros(288)

    # return prices.tolist(), agg_up_flex.tolist(), agg_down_flex.tolist()

    query_body, availability = create_ReFlex_Query(chargers,
                                                   charging_sessions,
                                                   prices, 
                                                   start_date)
    # save query_body to a file
    # with open('query_body.json', 'w') as f:
    #     json.dump(query_body, f)

    headers = {
        "Content-Type": "application/json"
    }
    
    api_url = "https://drive2x-reflex.hesi.energy/services/run/single"

    response = requests.post(api_url,
                             headers=headers,
                             verify=False,
                             data=json.dumps(query_body))
    # print(f'Response: {response}')
    run_id = response.json()["id"]
    # print(f'Run ID: {run_id}')

    api_run_status_url = "https://drive2x-reflex.hesi.energy/services/run/info/:id"

    status_response = requests.get(api_run_status_url.replace(":id", run_id),
                                   headers=headers,
                                   verify=False)
    while status_response.json()["runStatus"] != "completed":
        status_response = requests.get(api_run_status_url.replace(":id", run_id),
                                       headers=headers,
                                       verify=False)
        # print(f'Status: {status_response.json()["runStatus"]}')
        time.sleep(1)  # Think about async implementation

    api_get_results_url = "https://drive2x-reflex.hesi.energy/services/run/results/:id"
    results = requests.get(api_get_results_url.replace(":id", run_id),
                           headers=headers,
                           verify=False)
    print(f'Results: {results}')

    keys = results.json()['devicePlans'].keys()

    agg_load_profile = np.zeros(288)
    agg_up_flex = np.zeros(288)
    agg_down_flex = np.zeros(288)

    for key in keys:
        load_profile = list(results.json()['devicePlans'][key])
        power_limit = chargers[int(key)]
        if power_limit is None or power_limit <= 0:
            power_limit = 11

        load_profile = np.array(load_profile)

        assert (load_profile >= 0).all(), "Load profile must be positive"
        # convert to kWh/10min from joules
        load_profile = load_profile / 3.6e6
        agg_load_profile += load_profile  # / 6

        ch_availability = availability[int(key)]
        agg_up_flex += np.ones(len(load_profile)) * \
            power_limit*ch_availability - load_profile
        agg_down_flex += - load_profile

    return agg_load_profile.tolist(), agg_up_flex.tolist(), agg_down_flex.tolist()


def time_forecast(date=None):

    next = date + datetime.timedelta(days=1)
    dt = datetime.datetime.combine(next, datetime.datetime.min.time())
    return [dt + datetime.timedelta(minutes=10 * x) for x in range(144)]


def sample_timestamps(time, n: int = 1):
    start_timestamps = random.sample(time[:-1], n)
    start_timestamps.sort()
    end_timestamps = []

    for i, ts_start in enumerate(start_timestamps):
        if i + 1 < len(start_timestamps):  # As long there are more timestamps
            max_end = start_timestamps[i + 1]
        else:  # Last timestamp in list
            s_time = pl.Series(time)
            later_timestamps = list(compress(time, s_time > ts_start))
            if len(later_timestamps) > 0:
                max_end = random.sample(later_timestamps, 1)[0]
            else:  # If ts_start is the last timestamp, i.e. 23:50
                max_end = time[-1]

        # Calculate number of 10 min intervals until next session start
        n_ts = int((max_end - ts_start).total_seconds() / 600)
        sample_range = [
            ts_start + datetime.timedelta(minutes=10 * x) for x in range(n_ts)
        ]
        end_timestamp = random.sample(sample_range, 1)[0]
        end_timestamps.append(end_timestamp)

    return start_timestamps, end_timestamps
