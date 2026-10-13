import datetime

from backend.aggregators import simulate_uncontrolled_profiles_from_sessions

# The profiles cover two days at 10-minute resolution.
STEPS_PER_DAY = 144
PROFILE_LEN = STEPS_PER_DAY * 2


def make_session(cp_id, start, end, consumption):
    """Build a session row shaped like the query result the views pass in."""
    return (cp_id, start, end, consumption)


def test_uncontrolled_profile_charges_at_full_power_from_arrival():
    # 6 kW over a 10-minute step is exactly 1 kWh, so 5 kWh needs 5 steps.
    chargers = {1: 6.0}
    sessions = [
        make_session(
            1,
            datetime.datetime(2025, 1, 15, 10, 0),
            datetime.datetime(2025, 1, 15, 14, 0),
            5.0,
        )
    ]

    profile, up_flex, down_flex = simulate_uncontrolled_profiles_from_sessions(
        chargers, sessions, start_date="2025-01-15"
    )

    assert len(profile) == PROFILE_LEN
    start_step = 10 * 6  # 10:00 on the first day

    # Uncontrolled charging starts on arrival and runs at the connection limit.
    assert profile[start_step : start_step + 5] == [6.0] * 5
    assert profile[start_step - 1] == 0
    assert profile[start_step + 5] == 0

    # Energy is conserved: each step is a sixth of an hour.
    assert sum(profile) / 6 == 5.0

    # Downward flexibility is the same block shifted to the departure time.
    end_step = 14 * 6
    assert down_flex[end_step - 4 : end_step + 1] == [-6.0] * 5
    assert up_flex == [0] * PROFILE_LEN


def test_uncontrolled_profile_skips_sessions_outside_the_window():
    chargers = {1: 6.0}
    sessions = [
        make_session(
            1,
            datetime.datetime(2025, 1, 20, 10, 0),
            datetime.datetime(2025, 1, 20, 14, 0),
            5.0,
        )
    ]

    profile, _, down_flex = simulate_uncontrolled_profiles_from_sessions(
        chargers, sessions, start_date="2025-01-15"
    )

    assert profile == [0] * PROFILE_LEN
    assert down_flex == [0] * PROFILE_LEN


def test_uncontrolled_profile_falls_back_to_11kw_for_unknown_limit():
    chargers = {1: None}
    sessions = [
        make_session(
            1,
            datetime.datetime(2025, 1, 15, 0, 0),
            datetime.datetime(2025, 1, 15, 6, 0),
            11.0,
        )
    ]

    profile, _, _ = simulate_uncontrolled_profiles_from_sessions(
        chargers, sessions, start_date="2025-01-15"
    )

    assert max(profile) == 11.0
