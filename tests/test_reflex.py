"""ReFlex contracts using EPIOT session rows; no network or application DB."""

from datetime import datetime

import numpy as np
import pytest

from backend.api_calls.reflex import create_ReFlex_Query


START = "2025-01-15"


def session(cp=1, start="2025-01-15T10:00", end="2025-01-15T11:00", kwh=2):
    return cp, datetime.fromisoformat(start), datetime.fromisoformat(end), kwh


def test_query_uses_epiot_units_and_two_day_horizon():
    query, availability = create_ReFlex_Query({1: 6}, [session()], [50.0] * 288, START)
    target = query["globalTarget"]
    assert target["start"] == "2025-01-15T00:00:00Z"
    assert target["timeStepDuration"] == "PT10M"
    assert len(target["elements"]) == 288
    point = query["assets"]["evChargePoints"][0]
    assert point["id"] == "1"
    assert point["maxChargePower"] == 6000
    assert point["chargeSessions"][0]["energyToCharge"] == 7_200_000
    assert np.flatnonzero(availability[1]).tolist() == list(range(60, 66))


def test_second_day_availability_does_not_wrap_to_first_day():
    row = session(start="2025-01-16T10:00", end="2025-01-16T11:00")
    _, availability = create_ReFlex_Query({1: 6}, [row], [50.0] * 288, START)
    assert np.flatnonzero(availability[1]).tolist() == list(range(204, 210))


def test_overnight_availability_crosses_midnight():
    row = session(start="2025-01-15T23:00", end="2025-01-16T01:00")
    _, availability = create_ReFlex_Query({1: 6}, [row], [50.0] * 288, START)
    assert np.flatnonzero(availability[1]).tolist() == list(range(138, 150))
