"""Day-ahead prices from the Energy-Charts API (Fraunhofer ISE), no credentials needed."""

import requests

BASE_URL = "https://api.energy-charts.info/price"


class PriceFeedError(RuntimeError):
    """Energy-Charts failed or answered with something that is not a price series."""


def fetch_day_ahead_prices(zone, start, end, *, timeout=20, transport=requests):
    """(unix seconds, EUR/MWh) points of bidding zone `zone` between two aware datetimes.

    Energy-Charts publishes hourly prices before October 2025 and quarter-hourly
    prices after, and a day only once the auction has cleared (about 13:00 CET
    the day before). Missing values are dropped, never filled here.
    """
    params = {"bzn": zone, "start": start.strftime("%Y-%m-%dT%H:%MZ"), "end": end.strftime("%Y-%m-%dT%H:%MZ")}
    try:
        response = transport.get(BASE_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise PriceFeedError(f"Energy-Charts is unreachable: {type(exc).__name__}") from exc
    if response.status_code == 404:
        return []  # no data published for this range
    if response.status_code == 429:
        raise PriceFeedError("Energy-Charts is rate limiting requests; try again in a minute")
    if response.status_code != 200:
        raise PriceFeedError(f"Energy-Charts answered HTTP {response.status_code}")
    try:
        data = response.json()
        stamps, prices = data["unix_seconds"], data["price"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PriceFeedError("Energy-Charts returned no price series") from exc
    return [(int(stamp), float(price)) for stamp, price in zip(stamps or [], prices or [])
            if stamp is not None and price is not None]
