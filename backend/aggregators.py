"""Cost-optimal charging through the ReFlex service.

The load profiles of the other strategies (as fast as possible, as late as
possible, average power, minimum carbon) are computed by the vectorised engine
in backend/scenario_profiles.py for every session source.
"""

from backend.api_calls.reflex import (
    ReflexClient, aggregate_reflex_results, create_ReFlex_Query,
)
from backend.api_calls.prices import retrieve_day_ahead_prices


def simulate_cost_optimal_operation(chargers, charging_sessions, start_date):
    """Return the ReFlex schedule and instantaneous flexibility in average kW."""
    if not charging_sessions:
        return [0.0] * 288, [0.0] * 288, [0.0] * 288
    prices = retrieve_day_ahead_prices(start_date, days_ahead=2)
    query, availability = create_ReFlex_Query(
        chargers, charging_sessions, prices, start_date,
    )
    if not query["assets"]["evChargePoints"]:
        return [0.0] * 288, [0.0] * 288, [0.0] * 288
    results = ReflexClient().run(query)
    return aggregate_reflex_results(query, availability, results)
