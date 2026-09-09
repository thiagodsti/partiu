"""Tests for backend.parsers.validation — the plausibility gate on extracted flights."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch


def dt(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def flight(
    fn="TP781",
    dep="ARN",
    arr="LIS",
    dep_dt=None,
    arr_dt=None,
    ref="TESTRF",
) -> dict:
    return {
        "flight_number": fn,
        "departure_airport": dep,
        "arrival_airport": arr,
        "departure_datetime": dep_dt or dt(2026, 12, 22, 14, 20),
        "arrival_datetime": arr_dt or dt(2026, 12, 22, 17, 55),
        "booking_reference": ref,
    }


# ---------------------------------------------------------------------------
# Plausibility
# ---------------------------------------------------------------------------


class TestKeepsSoundFlights:
    def test_normal_flight_survives(self):
        from backend.parsers.validation import validate_flights

        # 1,900 km in 3h35 — an ordinary short-haul
        with patch("backend.parsers.validation._airport_distance", return_value=1900.0):
            assert len(validate_flights([flight()])) == 1

    def test_empty_input_returns_empty(self):
        from backend.parsers.validation import validate_flights

        assert validate_flights([]) == []


class TestRejectsImplausibleFlights:
    def test_rejects_same_departure_and_arrival(self):
        from backend.parsers.validation import validate_flights

        assert validate_flights([flight(dep="LIS", arr="LIS")]) == []

    def test_rejects_missing_airport(self):
        from backend.parsers.validation import validate_flights

        assert validate_flights([flight(arr="")]) == []

    def test_rejects_missing_times(self):
        from backend.parsers.validation import validate_flights

        no_arrival = flight()
        no_arrival["arrival_datetime"] = None
        assert validate_flights([no_arrival]) == []

    def test_rejects_arrival_before_departure(self):
        from backend.parsers.validation import validate_flights

        bad = flight(dep_dt=dt(2026, 12, 22, 18, 0), arr_dt=dt(2026, 12, 22, 9, 0))
        assert validate_flights([bad]) == []

    def test_rejects_implausibly_short_flight(self):
        from backend.parsers.validation import validate_flights

        bad = flight(dep_dt=dt(2026, 12, 22, 14, 20), arr_dt=dt(2026, 12, 22, 14, 25))
        assert validate_flights([bad]) == []

    def test_rejects_implausibly_long_flight(self):
        from backend.parsers.validation import validate_flights

        bad = flight(dep_dt=dt(2026, 12, 22, 0, 0), arr_dt=dt(2026, 12, 23, 6, 0))
        assert validate_flights([bad]) == []

    def test_rejects_supersonic_leg(self):
        """The Ponta Delgada bug: a transatlantic distance in a short-haul slot."""
        from backend.parsers.validation import validate_flights

        bad = flight(
            fn="TP8130",
            dep="FLN",
            arr="PDL",
            dep_dt=dt(2027, 1, 15, 11, 15),
            arr_dt=dt(2027, 1, 15, 12, 35),  # 1h20
        )
        with patch("backend.parsers.validation._airport_distance", return_value=7300.0):
            assert validate_flights([bad]) == []

    def test_keeps_long_haul_at_realistic_speed(self):
        from backend.parsers.validation import validate_flights

        ok = flight(
            fn="TP82",
            dep="GRU",
            arr="LIS",
            dep_dt=dt(2027, 1, 15, 19, 20),
            arr_dt=dt(2027, 1, 16, 5, 15),  # 9h55 for ~7,900 km
        )
        with patch("backend.parsers.validation._airport_distance", return_value=7900.0):
            assert len(validate_flights([ok])) == 1

    def test_short_hop_skips_the_speed_check(self):
        """Below the distance floor, taxi and holding dominate the block time."""
        from backend.parsers.validation import validate_flights

        hop = flight(
            dep="ARN",
            arr="BMA",
            dep_dt=dt(2026, 12, 22, 14, 20),
            arr_dt=dt(2026, 12, 22, 15, 20),
        )
        with patch("backend.parsers.validation._airport_distance", return_value=40.0):
            assert len(validate_flights([hop])) == 1

    def test_drops_only_the_bad_leg(self):
        from backend.parsers.validation import validate_flights

        good = flight()
        bad = flight(fn="TP109", dep="LIS", arr="LIS")
        with patch("backend.parsers.validation._airport_distance", return_value=1900.0):
            kept = validate_flights([good, bad])
        assert [f["flight_number"] for f in kept] == ["TP781"]


# ---------------------------------------------------------------------------
# Year normalisation
# ---------------------------------------------------------------------------


class TestNormaliseItineraryYears:
    def test_rolls_return_leg_over_new_year(self):
        """A trip out on 22 Dec returns on 15 Jan of the *next* year."""
        from backend.parsers.validation import normalise_itinerary_years

        out = flight(dep_dt=dt(2026, 12, 22, 14, 20), arr_dt=dt(2026, 12, 22, 17, 55))
        back = flight(
            fn="TP780",
            dep="LIS",
            arr="ARN",
            dep_dt=dt(2026, 1, 15, 8, 5),
            arr_dt=dt(2026, 1, 15, 13, 30),
        )
        normalise_itinerary_years([out, back])
        assert back["departure_datetime"] == dt(2027, 1, 15, 8, 5)
        assert back["arrival_datetime"] == dt(2027, 1, 15, 13, 30)

    def test_leaves_a_chronological_itinerary_alone(self):
        from backend.parsers.validation import normalise_itinerary_years

        first = flight(dep_dt=dt(2026, 12, 22, 14, 20))
        second = flight(fn="TP109", dep_dt=dt(2026, 12, 23, 11, 5))
        normalise_itinerary_years([first, second])
        assert second["departure_datetime"] == dt(2026, 12, 23, 11, 5)

    def test_does_not_roll_a_few_hours_backwards(self):
        """Hours out of order means a misparse, not a missing year."""
        from backend.parsers.validation import normalise_itinerary_years

        first = flight(dep_dt=dt(2026, 9, 9, 12, 20))
        second = flight(fn="TP109", dep_dt=dt(2026, 9, 9, 9, 15))
        normalise_itinerary_years([first, second])
        assert second["departure_datetime"] == dt(2026, 9, 9, 9, 15)

    def test_ignores_legs_without_a_departure(self):
        from backend.parsers.validation import normalise_itinerary_years

        legs = [flight(), {"flight_number": "TP1", "departure_datetime": None}]
        normalise_itinerary_years(legs)  # must not raise
        assert legs[1]["departure_datetime"] is None

    def test_applied_by_validate_flights(self):
        from backend.parsers.validation import validate_flights

        out = flight(dep_dt=dt(2026, 12, 22, 14, 20), arr_dt=dt(2026, 12, 22, 17, 55))
        back = flight(
            fn="TP780",
            dep="LIS",
            arr="ARN",
            dep_dt=dt(2026, 1, 15, 8, 5),
            arr_dt=dt(2026, 1, 15, 13, 30),
        )
        with patch("backend.parsers.validation._airport_distance", return_value=1900.0):
            kept = validate_flights([out, back])
        assert kept[1]["departure_datetime"] == dt(2027, 1, 15, 8, 5)


# ---------------------------------------------------------------------------
# Route continuity
# ---------------------------------------------------------------------------


class TestRouteContinuity:
    def test_connected_itinerary_reports_nothing(self):
        from backend.parsers.validation import check_route_continuity

        legs = [
            flight(fn="TP781", dep="ARN", arr="LIS", dep_dt=dt(2026, 12, 22, 14, 20)),
            flight(fn="TP109", dep="LIS", arr="FLN", dep_dt=dt(2026, 12, 23, 11, 5)),
        ]
        assert check_route_continuity(legs) == []

    def test_broken_chain_is_reported(self):
        from backend.parsers.validation import check_route_continuity

        legs = [
            flight(fn="TP781", dep="ARN", arr="FLN", dep_dt=dt(2026, 12, 22, 14, 20)),
            flight(fn="TP109", dep="ARN", arr="LIS", dep_dt=dt(2026, 12, 23, 11, 5)),
        ]
        warnings = check_route_continuity(legs)
        assert len(warnings) == 1
        assert "TESTRF" in warnings[0]

    def test_separate_bookings_are_not_compared(self):
        from backend.parsers.validation import check_route_continuity

        legs = [
            flight(fn="TP781", dep="ARN", arr="LIS", ref="AAA111"),
            flight(fn="AY123", dep="HEL", arr="CPH", ref="BBB222"),
        ]
        assert check_route_continuity(legs) == []

    def test_legs_without_a_reference_are_skipped(self):
        from backend.parsers.validation import check_route_continuity

        assert check_route_continuity([flight(ref=""), flight(fn="TP2", ref="")]) == []


class TestThresholds:
    def test_year_roll_threshold_is_days_not_hours(self):
        from backend.parsers.validation import BACKWARDS_GAP_FOR_YEAR_ROLL

        assert BACKWARDS_GAP_FOR_YEAR_ROLL >= timedelta(days=1)

    def test_speed_bound_allows_normal_jets(self):
        from backend.parsers.validation import MAX_PLAUSIBLE_SPEED_KMH

        assert MAX_PLAUSIBLE_SPEED_KMH > 950
