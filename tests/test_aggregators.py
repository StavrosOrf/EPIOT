import sys

sys.path.insert(0, "backend")

from aggregators import simulate_uncontrolled_profiles


def test_simulate_uncontrolled_profile():
    # Test with a simple case where the profile is known and can be compared to expected results
    stations = [
        (1, 12, "type", "name", 1, 1, "street"),
        (2, 12, "type", "name", 1, 1, "street"),
    ]
    config = {
        "session_probabilities": {
            1: 0.5717016003696391,
            2: 0.2651671077134176,
            3: 0.10165777572422677,
            4: 0.03740496492628219,
            5: 0.014120496772657901,
            6: 0.005502583273827025,
            7: 0.0023522493384298734,
            8: 0.0010081068593270886,
            9: 0.00045504823511292197,
            10: 0.00034303636185435655,
            11: 0.00017501855196650845,
            12: 6.300667870794304e-05,
            13: 2.1002226235981016e-05,
            14: 2.1002226235981016e-05,
            15: 7.000742078660338e-06,
        }
    }

    result = simulate_uncontrolled_profiles(stations, config)

    return
