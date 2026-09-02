from json import JSONDecodeError
from flask import abort, jsonify, request
import geojson as gj
from shapely.geometry import shape
from shapely.errors import GeometryTypeError
from backend.models import ChargingPoint, Location, Operator
from backend.utils import stations_to_geojson
from flask import current_app, Blueprint
from backend.views import get_day_before

from sqlalchemy import select, func, extract, and_
import numpy as np
from backend.models import ChargingPoint, Location, Operator, Session, PowerMix
from backend.utils import find_charger_availability
from datetime import datetime, timedelta

from backend.aggregators import (
    simulate_uncontrolled_profiles_from_sessions,
    simulate_delayed_profiles_from_sessions,
    simulate_avg_charging_profiles_from_sessions
)

kpi_data = Blueprint("kpi", "kpi")


@kpi_data.route("/user", methods=["GET"])
def get_user_kpi():
    db = current_app.config["station_data.db"]
    cfg = current_app.config["aggregator_config"]
    selected_markers = request.args.get("selected_markers", "")
    selected_markers = selected_markers.strip()

    if selected_markers == "undefined":
        print("No markers selected!!!")
        return jsonify({"x": np.arange(144).tolist()})

    selected_markers = selected_markers.split(
        ",") if selected_markers != "" else []
    if len(selected_markers) > 0:
        selected_markers = tuple(selected_markers)
        statement = (
            select(
                ChargingPoint.id,
                ChargingPoint.power,
                ChargingPoint.type,
                Operator.name,
                Location.latitude,
                Location.longitude,
                Location.street,
            )
            .join(ChargingPoint.column)
            .join(Location)
            .join(Operator)
        ).filter(ChargingPoint.id.in_(selected_markers))
        query_result = db.session.execute(statement)
        # make diuctionary from query_result with id as key and power as value
        chargers = {row[0]: row[1] for row in query_result}

        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")

        # Parse datetime strings to extract just the date part
        if start_date:
            # Handle ISO datetime strings like "2025-09-02T22:00:00.000Z"
            if 'T' in start_date:
                # Extract just the date part
                start_date = start_date.split('T')[0]
        if end_date:
            if 'T' in end_date:
                end_date = end_date.split('T')[0]  # Extract just the date part

        statement = (
            select(
                Session.cp_id,
                Session.start,
                Session.end,
                Session.consumption
            )
            .filter(
                and_(
                    Session.start >= start_date,  # Sessions starting on or after start_date
                    Session.end <= end_date,  # Sessions ending on or before end_date
                    # Filter by cp_id in selected_markers
                    Session.cp_id.in_(selected_markers)
                )
            )
        )

        # Execute the query
        charging_sessions = db.session.execute(statement).all()
        charging_sessions = [s for s in charging_sessions]

        print(f'Analyzing {len(charging_sessions)} charging sessions')
        # print(f'Chargers: {chargers}')
        print(f'Start date: {start_date}, end date: {end_date}')

        # Convert date strings to datetime objects for calculations
        start_date_obj = datetime.fromisoformat(start_date)
        end_date_obj = datetime.fromisoformat(end_date)

        print(f'Number of days: {(end_date_obj - start_date_obj).days}')
        # iterate over all days between start_date and end_date

        co2_intensities_uncontrolled = np.zeros(24)
        co2_intensities_delayed = np.zeros(24)
        co2_intensities_avg = np.zeros(24)

        renewable_energy_uncontrolled = 0
        renewable_energy_delayed = 0
        renewable_energy_avg = 0

        total_energy_consumed_uncontrolled = 0
        total_energy_consumed_delayed = 0
        total_energy_consumed_avg = 0

        #Calculate CO2 intensities for each day in the range
        for day in range(0, (end_date_obj - start_date_obj).days, 2):

            current_date = start_date_obj + timedelta(days=day)
            current_date_str = current_date.strftime('%Y-%m-%d')
            next_date = current_date + timedelta(days=2)
            next_date_str = next_date.strftime('%Y-%m-%d')
            # print(f'Analyzing day: {current_date_str}')

            # Query the database and find PowerMixes for the current day and the next day
            current_day_start = datetime.combine(
                current_date.date(), datetime.min.time())
            next_day_end = datetime.combine(
                next_date.date(), datetime.max.time())
            # print(f'Querying PowerMix from {current_day_start} to {next_day_end}')

            power_mix_statement = (
                select(
                    PowerMix.datetime,
                    PowerMix.renewable_percentage,
                    PowerMix.co2_intensity,
                    PowerMix.fossil_free_percentage,
                    PowerMix.power_consumption_total
                )
                .filter(
                    and_(
                        PowerMix.country_zone == "NL",  # Netherlands
                        PowerMix.datetime >= current_day_start,
                        PowerMix.datetime <= next_day_end
                    )
                )
                .order_by(PowerMix.datetime)
            )

            power_mix_data = db.session.execute(power_mix_statement).all()

            if power_mix_data:
                print(
                    f'Found {len(power_mix_data)} PowerMix entries for {current_date_str} to {next_date_str}')

                # Extract data for analysis
                renewable_percentages = [pm[1] for pm in power_mix_data]
                co2_intensities = [pm[2] for pm in power_mix_data]
                fossil_free_percentages = [pm[3]
                                           for pm in power_mix_data if pm[3] is not None]
                total_power_consumption = [pm[4]
                                           for pm in power_mix_data if pm[4] is not None]
                if len(renewable_percentages) <= 24:

                    renewable_percentages = [0]*24 + renewable_percentages
                    co2_intensities = [0]*24 + co2_intensities
                    fossil_free_percentages = [0]*24 + fossil_free_percentages
                    total_power_consumption = [0]*24 + total_power_consumption
                    
                if len(renewable_percentages) < 48:
                    renewable_percentages = renewable_percentages + [0]*(48 - len(renewable_percentages))
                    co2_intensities = co2_intensities + [0]*(48 - len(co2_intensities))
                    fossil_free_percentages = fossil_free_percentages + [0]*(48 - len(fossil_free_percentages))
                    total_power_consumption = total_power_consumption + [0]*(48 - len(total_power_consumption))

            else:
                continue

            load_profile, _, _ = simulate_uncontrolled_profiles_from_sessions(
                chargers,
                charging_sessions,
                start_date=current_date_str)
            # print(f'Uncontrolled load profile sum: {np.sum(load_profile)} kWh')

            # calculate total energy per hour
            total_energy_per_hour_afap = np.zeros(48)
            for i in range(48):
                total_energy_per_hour_afap[i] = np.sum(
                    np.array(load_profile[i*6:(i+1)*6])/6)

            co2_intensities_uncontrolled += np.array(
                co2_intensities[:24]) * total_energy_per_hour_afap[:24]
            co2_intensities_uncontrolled += np.array(
                co2_intensities[24:]) * total_energy_per_hour_afap[24:]
            
            # print(f'Renewable percentages: {renewable_percentages}')
            # print(f'Total energy per hour AFAP: {total_energy_per_hour_afap}')
            # print(f'Sum total energy per hour AFAP: {np.sum(total_energy_per_hour_afap)} kWh')
            
            renewable_energy_uncontrolled += np.sum(np.array(renewable_percentages)/100 * total_energy_per_hour_afap)                        
            if np.sum(np.array(renewable_percentages)) != 0:
                total_energy_consumed_uncontrolled += np.sum(total_energy_per_hour_afap)
            
            
            # print(f'Renewable percentages: {renewable_percentages}')
            # print(f'Sum total energy per hour AFAP: {np.sum(total_energy_per_hour_afap)} kWh')

            load_profile, _, _ = simulate_delayed_profiles_from_sessions(
                chargers,
                charging_sessions,
                start_date=current_date_str)
            # print(f'Delayed load profile sum: {np.sum(load_profile)} kWh')
            # calculate total energy per hour
            total_energy_per_hour_delayed = np.zeros(48)
            for i in range(48):
                total_energy_per_hour_delayed[i] = np.sum(
                    np.array(load_profile[i*6:(i+1)*6])/6)
            co2_intensities_delayed += np.array(
                co2_intensities[:24]) * total_energy_per_hour_delayed[:24]
            co2_intensities_delayed += np.array(
                co2_intensities[24:]) * total_energy_per_hour_delayed[24:]
            renewable_energy_delayed += np.sum(np.array(renewable_percentages)/100 * total_energy_per_hour_delayed)
            if np.sum(np.array(renewable_percentages)) != 0:
                total_energy_consumed_delayed += np.sum(total_energy_per_hour_delayed)
            
            load_profile, _, _ = simulate_avg_charging_profiles_from_sessions(
                chargers,
                charging_sessions,
                start_date=current_date_str)
            # print(f'Average load profile sum: {np.sum(load_profile)} kWh')
            # calculate total energy per hour
            total_energy_per_hour_avg = np.zeros(48)
            for i in range(48):
                total_energy_per_hour_avg[i] = np.sum(
                    np.array(load_profile[i*6:(i+1)*6])/6)
            co2_intensities_avg += np.array(
                co2_intensities[:24]) * total_energy_per_hour_avg[:24]
            co2_intensities_avg += np.array(
                co2_intensities[24:]) * total_energy_per_hour_avg[24:]
            renewable_energy_avg += np.sum(np.array(renewable_percentages)/100 * total_energy_per_hour_avg)
            if np.sum(np.array(renewable_percentages)) != 0:
                total_energy_consumed_avg += np.sum(total_energy_per_hour_avg)

        ####################################################################

        start_times = [s[1].hour for s in charging_sessions]
        # find the duration of each session in minutes
        durations = [(s[2] - s[1]).seconds/60 for s in charging_sessions]
        departure_times = [s[2].hour for s in charging_sessions]
        energy_consumed = [s[3] for s in charging_sessions]
        day_of_week = [s[1].weekday() for s in charging_sessions]
        # season = [s[1].month for s in charging_sessions]
        # # 0 = winter, 1 = spring, 2 = summer, 3 = fall
        # season = [0 if s in [12, 1, 2] else 1 if s in [3, 4, 5]
        #           else 2 if s in [6, 7, 8] else 3 for s in season]

        # daily energy consumption (kWh) per charging station (when the station is used)
        daily_consumption_we = {}
        daily_consumption_wd = {}
        for i, s in enumerate(charging_sessions):
            if day_of_week[i] >= 5:
                pair = (s[1].date(), s[3])
                if pair not in daily_consumption_we:
                    daily_consumption_we[pair] = 0
                daily_consumption_we[pair] += s[3]
            else:
                pair = (s[1].date(), s[3])
                if pair not in daily_consumption_wd:
                    daily_consumption_wd[pair] = 0
                daily_consumption_wd[pair] += s[3]

        daily_consumption_dist = {}
        for day_type in ['weekday', 'weekend']:
            if day_type == 'weekday':
                daily_consumption_dist[day_type], _ = np.histogram(
                    [e for e in daily_consumption_wd.values()],
                    bins=10,
                    density=False,
                    range=(0, 200)
                )
            else:
                daily_consumption_dist[day_type], _ = np.histogram(
                    [e for e in daily_consumption_we.values()],
                    bins=10,
                    density=False,
                    range=(0, 200)
                )
        hour_of_arrival_consumption_wd = np.array([0]*24)
        hour_counter_wd = np.array([1]*24)
        hour_of_arrival_consumption_we = np.array([0]*24)
        hour_counter_we = np.array([1]*24)
        for day_type in ['weekday', 'weekend']:
            for i, s in enumerate(charging_sessions):
                if day_of_week[i] < 5:
                    hour_of_arrival_consumption_wd[s[1].hour] += s[3]
                    hour_counter_wd[s[1].hour] += 1
                else:
                    hour_of_arrival_consumption_we[s[1].hour] += s[3]
                    hour_counter_we[s[1].hour] += 1

        # use numpy to calculate the histogram of the start times
        start_times_dist = {}

        for day_type in ['weekday', 'weekend']:
            if day_type == 'weekday':
                start_times_dist[day_type], _ = np.histogram(
                    [s for i, s in enumerate(
                        start_times) if day_of_week[i] < 5],
                    bins=24,
                    density=False,
                    range=(0, 24)
                )
            else:
                start_times_dist[day_type], _ = np.histogram(
                    [s for i, s in enumerate(
                        start_times) if day_of_week[i] >= 5],
                    bins=24,
                    density=False,
                    range=(0, 24)
                )

        durations_dist = {}
        durations = [d/60 for d in durations]  # convert to hours
        for day_type in ['weekday', 'weekend']:
            if day_type == 'weekday':
                durations_dist[day_type], _ = np.histogram(
                    [d for i, d in enumerate(
                        durations) if day_of_week[i] < 5],
                    bins=24,
                    density=False,
                    range=(0, 24)
                )
            else:
                durations_dist[day_type], _ = np.histogram(
                    [d for i, d in enumerate(
                        durations) if day_of_week[i] >= 5],
                    bins=24,
                    density=False,
                    range=(0, 24)
                )

        consumption_dist = {}
        for day_type in ['weekday', 'weekend']:
            if day_type == 'weekday':
                consumption_dist[day_type], _ = np.histogram(
                    [e for i, e in enumerate(
                        energy_consumed) if day_of_week[i] < 5],
                    bins=10,
                    density=False,
                    range=(0, 100)
                )
            else:
                consumption_dist[day_type], _ = np.histogram(
                    [e for i, e in enumerate(
                        energy_consumed) if day_of_week[i] >= 5],
                    bins=10,
                    density=False,
                    range=(0, 100)
                )

        # calculate daily aggreagetd consumption per charging station
        daily_consumption = {}
        for day_type in ['weekday', 'weekend']:
            if day_type == 'weekday':
                daily_consumption[day_type] = np.zeros(24)
                for i, e in enumerate(energy_consumed):
                    daily_consumption[day_type][day_of_week[i]] += e
            else:
                daily_consumption[day_type] = np.zeros(24)
                for i, e in enumerate(energy_consumed):
                    daily_consumption[day_type][day_of_week[i]] += e

        departure_times_dist = {}
        for day_type in ['weekday', 'weekend']:
            if day_type == 'weekday':
                departure_times_dist[day_type], _ = np.histogram(
                    [s for i, s in enumerate(
                        departure_times) if day_of_week[i] < 5],
                    bins=24,
                    density=False,
                    range=(0, 24)
                )
            else:
                departure_times_dist[day_type], _ = np.histogram(
                    [s for i, s in enumerate(
                        departure_times) if day_of_week[i] >= 5],
                    bins=24,
                    density=False,
                    range=(0, 24)
                )

        start_datetime = datetime.fromisoformat(
            start_date.replace("Z", "+01:00"))
        end_datetime = datetime.fromisoformat(end_date.replace("Z", "+01:00"))

        number_of_days = (end_datetime - start_datetime).days + 1
        if start_datetime.tzinfo is not None:
            start_datetime = start_datetime.replace(tzinfo=None)
            end_datetime = end_datetime.replace(tzinfo=None)

        number_of_charging_stations = len(selected_markers)
        daily_number_of_sessions = np.zeros(
            (number_of_days, number_of_charging_stations))

        for i, s in enumerate(charging_sessions):
            day = (s[1] - start_datetime).days
            daily_number_of_sessions[day][selected_markers.index(
                f'{s[0]}')] += 1

        starting_day = start_datetime.weekday()
        print(f'starting day: {starting_day}')
        day_of_the_week_sessions = {}
        day_of_the_week_sessions_dist = {}
        for i in range(7):
            day_of_the_week_sessions[starting_day] = daily_number_of_sessions[starting_day::7].tolist(
            )
            day_of_the_week_sessions[starting_day] = [
                item for sublist in day_of_the_week_sessions[starting_day] for item in sublist]

            day_of_the_week_sessions_dist[starting_day], _ = np.histogram(
                day_of_the_week_sessions[starting_day],
                bins=5,
                density=True,
                range=(0, 5)
            )
            starting_day = (starting_day + 1) % 7
        # sort the dictionary by key
        day_of_the_week_sessions_dist = dict(
            sorted(day_of_the_week_sessions_dist.items()))

        weekday_availability, weekend_availability, occupation_ratio = find_charger_availability(
            charging_sessions, start_datetime, end_datetime)

        # weekday_availability turn to weekly occupancy
        weekday_availability = np.array(weekday_availability)
        weekday_availability = (np.max(
            weekday_availability)+0.1*np.max(weekday_availability) - weekday_availability)

        weekend_availability = np.array(weekend_availability)
        weekend_availability = (
            np.max(weekend_availability) + 0.1*np.max(weekend_availability) - weekend_availability)

        occupation_ratio = np.array(occupation_ratio)
        occupation_ratio_dist, _ = np.histogram(
            occupation_ratio,
            bins=20,
            density=True,
            range=(0, 1)
        )
        
        return jsonify({"arrival_dist_wd": start_times_dist['weekday'].tolist(),
                        "arrival_dist_we": start_times_dist['weekend'].tolist(),
                        "duration_dist_wd": durations_dist['weekday'].tolist(),
                        "duration_dist_we": durations_dist['weekend'].tolist(),
                        "consumption_dist_wd": consumption_dist['weekday'].tolist(),
                        "consumption_dist_we": consumption_dist['weekend'].tolist(),
                        "departure_dist_wd": departure_times_dist['weekday'].tolist(),
                        "departure_dist_we": departure_times_dist['weekend'].tolist(),
                        "daily_consumption_dist_wd": daily_consumption_dist['weekday'].tolist(),
                        "daily_consumption_dist_we": daily_consumption_dist['weekend'].tolist(),
                        "hour_of_arrival_consumption_wd": (hour_of_arrival_consumption_wd/hour_counter_wd).tolist(),
                        "hour_of_arrival_consumption_we": (hour_of_arrival_consumption_we/hour_counter_we).tolist(),
                        "sessions_per_day_0": day_of_the_week_sessions_dist[0].tolist(),
                        "sessions_per_day_1": day_of_the_week_sessions_dist[1].tolist(),
                        "sessions_per_day_2": day_of_the_week_sessions_dist[2].tolist(),
                        "sessions_per_day_3": day_of_the_week_sessions_dist[3].tolist(),
                        "sessions_per_day_4": day_of_the_week_sessions_dist[4].tolist(),
                        "sessions_per_day_5": day_of_the_week_sessions_dist[5].tolist(),
                        "sessions_per_day_6": day_of_the_week_sessions_dist[6].tolist(),
                        "weekday_availability": weekday_availability.tolist(),
                        "weekend_availability": weekend_availability.tolist(),
                        "occupation_ratio_dist": occupation_ratio_dist.tolist(),
                        "co2_intensities_uncontrolled": (co2_intensities_uncontrolled).tolist(),
                        "co2_intensities_delayed": (co2_intensities_delayed).tolist(),
                        "co2_intensities_avg": (co2_intensities_avg).tolist(),
                        "renewable_energy_shared_uncontrolled": renewable_energy_uncontrolled * 100 / (total_energy_consumed_uncontrolled if total_energy_consumed_uncontrolled > 0 else 1),
                        "renewable_energy_shared_delayed": renewable_energy_delayed * 100 / (total_energy_consumed_delayed if total_energy_consumed_delayed > 0 else 1),
                        "renewable_energy_shared_avg": renewable_energy_avg * 100 / (total_energy_consumed_avg if total_energy_consumed_avg > 0 else 1)
                    })
