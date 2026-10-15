"""The cost-optimal path through ReFlex, the one strategy that is not computed locally.

The other strategies (and their hand-built-session tests) live in
tests/test_scenario_profiles.py: every session source shares that engine.
"""

import datetime

import pytest

from backend import aggregators

ROWS = [(1, datetime.datetime(2025, 1, 15, 10), datetime.datetime(2025, 1, 15, 14), 5.0)]
ZEROS = [0.0]*288


class Services:
    """Stands in for the price feed and the ReFlex service, and records what was called."""

    def __init__(self, charge_points=1):
        self.calls = []
        self.charge_points = charge_points

    def install(self, monkeypatch):
        def prices(start_date, days_ahead):
            self.calls.append(("prices", start_date, days_ahead))
            return "prices"

        def query(chargers, sessions, price_data, start_date):
            self.calls.append(("query", chargers, len(sessions)))
            return {"assets": {"evChargePoints": ["point"]*self.charge_points}}, "availability"

        class Client:
            def run(_, request):
                self.calls.append(("run",))
                return "results"

        def aggregate(request, availability, results):
            self.calls.append(("aggregate", availability, results))
            return [1.0]*288, [2.0]*288, [3.0]*288

        monkeypatch.setattr(aggregators, "retrieve_day_ahead_prices", prices)
        monkeypatch.setattr(aggregators, "create_ReFlex_Query", query)
        monkeypatch.setattr(aggregators, "ReflexClient", Client)
        monkeypatch.setattr(aggregators, "aggregate_reflex_results", aggregate)


def test_without_sessions_nothing_is_requested(monkeypatch):
    services = Services()
    services.install(monkeypatch)
    assert aggregators.simulate_cost_optimal_operation({1: 6.0}, [], "2025-01-14") == (ZEROS, ZEROS, ZEROS)
    assert services.calls == []


def test_sessions_are_priced_optimised_and_aggregated(monkeypatch):
    services = Services()
    services.install(monkeypatch)
    load, up, down = aggregators.simulate_cost_optimal_operation({1: 6.0}, ROWS, "2025-01-14")
    assert (load[0], up[0], down[0]) == (1.0, 2.0, 3.0)
    assert [call[0] for call in services.calls] == ["prices", "query", "run", "aggregate"]
    assert services.calls[0] == ("prices", "2025-01-14", 2)
    assert services.calls[-1] == ("aggregate", "availability", "results")


def test_a_query_without_charge_points_skips_the_service(monkeypatch):
    services = Services(charge_points=0)
    services.install(monkeypatch)
    assert aggregators.simulate_cost_optimal_operation({1: 6.0}, ROWS, "2025-01-14") == (ZEROS, ZEROS, ZEROS)
    assert ("run",) not in services.calls
