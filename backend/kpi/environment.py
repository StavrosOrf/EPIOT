"""Energy-weighted, equal-energy environmental scenario comparisons."""

from zoneinfo import ZoneInfo

import numpy as np

from backend.carbon_charging import CarbonScheduleUnavailable, arrival_cohort
from backend.grid_data import GridHour, legacy_hour
from backend.scenario_profiles import grid, simulate_scenarios

STRATEGIES = {"afap": "As fast as possible", "alap": "As late as possible",
              "avg": "Average power", "mincarbon": "Minimum carbon"}


def normalize_hours(values):
    return {hour.timestamp: hour for value in values
            for hour in [value if isinstance(value, GridHour) else legacy_hour(*value)]}


class EnvironmentalComparison:
    def __init__(self, hours, timezone_name):
        self.hours, self.zone = normalize_hours(hours), ZoneInfo(timezone_name)
        self.data = {strategy: dict(energy=0., carbon_energy=0., carbon=0., renewable_energy=0., renewable=0.,
            actual_carbon_energy=0., actual_renewable_energy=0., estimated_energy=0., unknown_flag_energy=0.,
            carbon_by_hour=np.zeros(24), energy_by_hour=np.zeros(24), available=True, reason=None)
            for strategy in STRATEGIES}
        self.covered_steps, self.total_steps, self.reference_steps = 0, 0, 0
        self.required_energy, self.connection_windows = 0., 0
        self.sources, self.reference_origins = set(), set()

    def add_day(self, chargers, records, left, right, horizon=None):
        """Count the day's arrivals, followed until they leave or `horizon` (the range end)."""
        horizon = max(right, horizon or right)
        timeline, _ = grid(left, right, left)
        matches = [self.hours.get(timestamp.replace(minute=0, second=0, microsecond=0)) for timestamp in timeline]
        self.total_steps += len(timeline)
        self.covered_steps += sum(hour is not None and hour.co2_intensity is not None for hour in matches)
        self.reference_steps += sum(bool(hour and hour.carbon_is_stale and hour.co2_intensity is not None) for hour in matches)
        for hour in matches:
            if hour is None:
                continue
            if hour.co2_intensity is not None:
                if hour.carbon_source:
                    self.sources.add(hour.carbon_source)
                if hour.carbon_is_stale and hour.carbon_source_timestamp:
                    self.reference_origins.add(hour.carbon_source_timestamp)
            if hour.renewable_percentage is not None:
                if hour.renewable_source:
                    self.sources.add(hour.renewable_source)
                if hour.renewable_is_stale and hour.renewable_source_timestamp:
                    self.reference_origins.add(hour.renewable_source_timestamp)
        # Scheduling continues past midnight, so look up the hours up to the horizon
        timeline, _ = grid(left, horizon, left)
        matches = [self.hours.get(timestamp.replace(minute=0, second=0, microsecond=0)) for timestamp in timeline]
        costs = [hour.co2_intensity if hour is not None else None for hour in matches]
        # Sessions arriving this day, charged from their true arrival
        cohort = arrival_cohort(chargers, records, left, right, horizon)
        self.required_energy += sum(record.energy_kwh for record in cohort)
        self.connection_windows += len(cohort)
        day_energy = {}
        for strategy, values in self.data.items():
            try:
                profile = np.asarray(simulate_scenarios(chargers, cohort, left, horizon, strategy, carbon_intensity=costs)[0])/6
            except CarbonScheduleUnavailable as exc:
                values["available"], values["reason"] = False, str(exc)
                continue
            day_energy[strategy] = float(profile.sum())
            if not values["available"]:
                continue
            values["energy"] += float(profile.sum())
            for timestamp, energy, hour in zip(timeline, profile, matches):
                energy = float(energy)
                if energy <= 1e-12 or hour is None:
                    continue
                if hour.co2_intensity is not None:
                    local_hour = timestamp.astimezone(self.zone).hour
                    values["carbon_energy"] += energy
                    values["carbon"] += hour.co2_intensity*energy
                    values["carbon_by_hour"][local_hour] += hour.co2_intensity*energy
                    values["energy_by_hour"][local_hour] += energy
                    if not hour.carbon_is_stale:
                        values["actual_carbon_energy"] += energy
                    if hour.carbon_is_estimated is True:
                        values["estimated_energy"] += energy
                    if hour.carbon_is_estimated is None:
                        values["unknown_flag_energy"] += energy
                if hour.renewable_percentage is not None:
                    values["renewable_energy"] += energy
                    values["renewable"] += hour.renewable_percentage*energy
                    if not hour.renewable_is_stale:
                        values["actual_renewable_energy"] += energy
        return day_energy

    def result(self):
        strategies = {}
        for strategy, values in self.data.items():
            available, energy = values["available"], values["energy"]
            carbon_energy, renewable_energy = values["carbon_energy"], values["renewable_energy"]
            pct = lambda value: min(100., max(0., 100*value/energy)) if energy > 1e-12 and available else None
            carbon_complete = available and abs(carbon_energy-energy) <= 1e-8
            renewable_complete = available and abs(renewable_energy-energy) <= 1e-8
            reference = values["actual_carbon_energy"]+1e-8 < carbon_energy or values["actual_renewable_energy"]+1e-8 < renewable_energy
            if not available:
                status = "unavailable"
            elif energy <= 1e-12:
                status = "no_charging"
            elif not carbon_energy and not renewable_energy:
                status = "unavailable"
            elif not carbon_complete or not renewable_complete:
                status = "partial_reference" if reference else "partial"
            else:
                status = "historical_reference" if reference else "complete"
            strategies[strategy] = dict(label=STRATEGIES[strategy], available=available, reason=values["reason"], status=status,
                energy_kwh=energy if available else None,
                emissions_kg=(values["carbon"]/1000 if carbon_energy or energy <= 1e-12 else None) if available else None,
                average_intensity_g_per_kwh=values["carbon"]/carbon_energy if carbon_energy and available else None,
                renewable_share_pct=values["renewable"]/renewable_energy if renewable_energy and available else None,
                carbon_energy_coverage_pct=pct(carbon_energy), renewable_energy_coverage_pct=pct(renewable_energy),
                matching_date_carbon_coverage_pct=pct(values["actual_carbon_energy"]),
                matching_date_renewable_coverage_pct=pct(values["actual_renewable_energy"]),
                estimated_carbon_energy_pct=pct(values["estimated_energy"]),
                unknown_estimation_flag_energy_pct=pct(values["unknown_flag_energy"]),
                carbon_complete=carbon_complete, renewable_complete=renewable_complete,
                same_energy=available and abs(energy-self.required_energy) <= max(1e-8, self.required_energy*1e-10),
                intensity_by_hour=[float(total/weight) if weight and available else None for total, weight in
                    zip(values["carbon_by_hour"], values["energy_by_hour"])])
        baseline = strategies["afap"]
        for strategy, value in strategies.items():
            eligible = value["available"] and value["same_energy"] and baseline["same_energy"] and value["carbon_complete"] and baseline["carbon_complete"]
            difference = value["emissions_kg"]-baseline["emissions_kg"] if eligible and value["emissions_kg"] is not None and baseline["emissions_kg"] is not None else None
            value["footprint_difference_vs_afap_kg"] = difference
            value["footprint_difference_vs_afap_pct"] = 100*difference/baseline["emissions_kg"] if difference is not None and baseline["emissions_kg"] else None
        return dict(strategies=strategies, baseline="afap", required_energy_kwh=self.required_energy,
            connection_windows=self.connection_windows, covered_steps=self.covered_steps, total_steps=self.total_steps,
            coverage_fraction=self.covered_steps/self.total_steps if self.total_steps else 0.,
            reference_steps=self.reference_steps, uses_historical_reference=bool(self.reference_origins), sources=sorted(self.sources),
            reference_source_start=min(self.reference_origins).isoformat() if self.reference_origins else None,
            reference_source_end=max(self.reference_origins).isoformat() if self.reference_origins else None,
            note="Estimated scenario footprint, not demonstrated avoided emissions. All strategies receive identical energy: sessions count on their arrival day and are charged from their true arrival; a connection still running at the end of the range keeps its in-range share. Minimum carbon uses historical/reference information within connection and plug-power limits.")
