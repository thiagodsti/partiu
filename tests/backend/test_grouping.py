"""Tests for auto_group_flights and parse_flight_date."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.parsers.engine import parse_flight_date


# ---------------------------------------------------------------------------
# parse_flight_date — pure function, no DB needed
# ---------------------------------------------------------------------------

class TestParseFlightDate:
    def test_iso_format(self):
        assert parse_flight_date('2026-03-14') == date(2026, 3, 14)

    def test_dd_mm_yyyy(self):
        assert parse_flight_date('14/03/2026') == date(2026, 3, 14)

    def test_english_short(self):
        assert parse_flight_date('16 Mar 2026') == date(2026, 3, 16)

    def test_portuguese_format(self):
        assert parse_flight_date('16 de mar. de 2026') == date(2026, 3, 16)

    def test_spanish_format(self):
        assert parse_flight_date('5 ene 2026') == date(2026, 1, 5)

    def test_invalid_returns_none(self):
        assert parse_flight_date('not a date') is None
        assert parse_flight_date('') is None

    def test_german_month(self):
        assert parse_flight_date('10 März 2026') == date(2026, 3, 10)


# ---------------------------------------------------------------------------
# auto_group_flights — requires a test DB (patched via test_db fixture)
# ---------------------------------------------------------------------------

def _make_flight(dep_airport, arr_airport, dep_dt, arr_dt,
                 booking_ref='', flight_number='LA001', airline_code='LA'):
    now = datetime.now(timezone.utc).isoformat()
    return {
        'id': str(uuid.uuid4()),
        'airline_code': airline_code,
        'airline_name': 'Test Airline',
        'flight_number': flight_number,
        'departure_airport': dep_airport,
        'arrival_airport': arr_airport,
        'departure_datetime': dep_dt.isoformat(),
        'arrival_datetime': arr_dt.isoformat(),
        'booking_reference': booking_ref,
        'status': 'upcoming',
        'is_manually_added': 0,
        'created_at': now,
        'updated_at': now,
    }


def _insert_flight(conn, flight):
    conn.execute("""
        INSERT INTO flights (
            id, airline_code, airline_name, flight_number,
            departure_airport, arrival_airport,
            departure_datetime, arrival_datetime,
            booking_reference, status, is_manually_added,
            created_at, updated_at
        ) VALUES (
            :id, :airline_code, :airline_name, :flight_number,
            :departure_airport, :arrival_airport,
            :departure_datetime, :arrival_datetime,
            :booking_reference, :status, :is_manually_added,
            :created_at, :updated_at
        )
    """, flight)
    conn.commit()


@pytest.fixture
def db_conn_for_test(test_db):
    """Open a connection to the test DB, yield it, then close."""
    import backend.database as db_module
    conn = db_module.get_connection(test_db)
    yield conn
    conn.close()


class TestAutoGroupFlights:
    def test_same_booking_ref_groups_together(self, db_conn_for_test, test_db, monkeypatch):
        """Two flights sharing a booking reference end up in the same trip."""
        import backend.database as db_module
        monkeypatch.setattr(db_module.settings, 'DB_PATH', test_db)

        now = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
        f1 = _make_flight('GRU', 'LIS', now, now + timedelta(hours=10), booking_ref='ABC123')
        f2 = _make_flight('LIS', 'ARN', now + timedelta(hours=12),
                          now + timedelta(hours=14), booking_ref='ABC123')
        _insert_flight(db_conn_for_test, f1)
        _insert_flight(db_conn_for_test, f2)

        from backend.grouping import auto_group_flights
        result = auto_group_flights()

        assert result['groups_created'] == 1

        rows = db_conn_for_test.execute(
            'SELECT trip_id FROM flights WHERE id IN (?, ?)', (f1['id'], f2['id'])
        ).fetchall()
        trip_ids = {r['trip_id'] for r in rows}
        assert len(trip_ids) == 1, 'Both flights should share one trip'
        assert None not in trip_ids

    def test_different_refs_far_apart_make_separate_trips(self, db_conn_for_test, test_db, monkeypatch):
        """Flights on different booking refs far apart in time → separate trips."""
        import backend.database as db_module
        monkeypatch.setattr(db_module.settings, 'DB_PATH', test_db)

        t1 = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)  # 41 days later

        f1 = _make_flight('GRU', 'LIS', t1, t1 + timedelta(hours=10), booking_ref='AAA111')
        f2 = _make_flight('LIS', 'ARN', t2, t2 + timedelta(hours=3), booking_ref='BBB222')
        _insert_flight(db_conn_for_test, f1)
        _insert_flight(db_conn_for_test, f2)

        from backend.grouping import auto_group_flights
        auto_group_flights()

        rows = db_conn_for_test.execute(
            'SELECT trip_id FROM flights WHERE id IN (?, ?)', (f1['id'], f2['id'])
        ).fetchall()
        trip_ids = {r['trip_id'] for r in rows}
        assert len(trip_ids) == 2, 'Far-apart flights with different refs should be separate'

    def test_proximity_grouping_within_48h(self, db_conn_for_test, test_db, monkeypatch):
        """Flights within 48h of each other group together even without a booking ref."""
        import backend.database as db_module
        monkeypatch.setattr(db_module.settings, 'DB_PATH', test_db)

        t = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
        f1 = _make_flight('ARN', 'CPH', t, t + timedelta(hours=1))
        f2 = _make_flight('CPH', 'LHR', t + timedelta(hours=3), t + timedelta(hours=4, minutes=30))
        _insert_flight(db_conn_for_test, f1)
        _insert_flight(db_conn_for_test, f2)

        from backend.grouping import auto_group_flights
        auto_group_flights()

        rows = db_conn_for_test.execute(
            'SELECT trip_id FROM flights WHERE id IN (?, ?)', (f1['id'], f2['id'])
        ).fetchall()
        trip_ids = {r['trip_id'] for r in rows if r['trip_id']}
        assert len(trip_ids) == 1, 'Nearby no-ref flights should be proximity-grouped'

    def test_no_ungrouped_flights_returns_zero(self, test_db, monkeypatch):
        """auto_group_flights with an empty DB should report nothing created."""
        import backend.database as db_module
        monkeypatch.setattr(db_module.settings, 'DB_PATH', test_db)

        from backend.grouping import auto_group_flights
        result = auto_group_flights()
        assert result['groups_created'] == 0
        assert result['flights_grouped'] == 0

    def test_trip_has_name_after_grouping(self, db_conn_for_test, test_db, monkeypatch):
        """Every auto-created trip should have a non-empty name."""
        import backend.database as db_module
        monkeypatch.setattr(db_module.settings, 'DB_PATH', test_db)

        t = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
        f = _make_flight('GRU', 'MIA', t, t + timedelta(hours=9), booking_ref='XYZ789')
        _insert_flight(db_conn_for_test, f)

        from backend.grouping import auto_group_flights
        auto_group_flights()

        trip_row = db_conn_for_test.execute('SELECT name FROM trips LIMIT 1').fetchone()
        assert trip_row is not None
        assert trip_row['name'].strip() != ''
