"""Request arguments shared by the load-profile and KPI endpoints.

Each helper raises ValueError with a message that is safe to show the client.
"""
from backend.session_sources import SOURCE_LABELS

DEMAND_ASSUMPTIONS = {"low", "base", "high"}
MAX_SEED = 2**32 - 1
# Scenario cost grows with charging points x days: about 25 s on a development
# machine at this size. Override with FLASK_MAX_POINT_DAYS.
DEFAULT_MAX_POINT_DAYS = 1_000_000
# Most session draws one load-profile request may combine (FLASK_MAX_ENSEMBLE)
DEFAULT_MAX_ENSEMBLE = 30


class RequestTooLarge(ValueError):
    """The selection and range would take too long to compute on request."""


def request_arguments(request):
    """The JSON body of a POST, or the query string of a GET."""
    arguments = request.get_json(silent=True) if request.method == "POST" else request.args
    if arguments is None or not hasattr(arguments, "get"):
        raise ValueError("Expected a JSON object")
    return arguments


def session_source(arguments):
    """'database' (stored sessions) or one of the on-request scenario sources."""
    source = str(arguments.get("session_source", "database")).strip()
    if source not in {"database", *SOURCE_LABELS}:
        raise ValueError("Unknown session source")
    return source


def demand_assumption(arguments):
    assumption = arguments.get("demand_assumption", "base")
    if assumption not in DEMAND_ASSUMPTIONS:
        raise ValueError("Unknown demand assumption")
    return assumption


def check_point_days(config, points, days):
    """Refuse requests whose cost (charging points x days) exceeds the configured limit."""
    limit = int(config.get("MAX_POINT_DAYS", DEFAULT_MAX_POINT_DAYS))
    if limit > 0 and points*days > limit:
        raise RequestTooLarge(
            f"This request covers {points*days:,} point-days ({points:,} charging points over {days} "
            f"day{'s' if days != 1 else ''}); the limit is {limit:,}. Select fewer charging points or a shorter range.")


def ensemble_size(arguments, config):
    """How many seeded session draws to combine into an uncertainty band (1 = a single draw)."""
    limit = int(config.get("MAX_ENSEMBLE", DEFAULT_MAX_ENSEMBLE))
    try:
        size = int(arguments.get("ensemble", 1))
    except (TypeError, ValueError):
        raise ValueError("ensemble must be a whole number of draws") from None
    if not 1 <= size <= limit:
        raise ValueError(f"ensemble must be between 1 and {limit} draws")
    return size


def scenario_seed(arguments):
    seed = int(arguments.get("seed", 42))
    if not 0 <= seed <= MAX_SEED:
        raise ValueError(f"Seed must be an integer between 0 and {MAX_SEED}")
    return seed
