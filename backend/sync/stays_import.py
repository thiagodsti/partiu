"""Import accommodation declared in schema.org markup into trips.

The parser (``parsers/schema_org.py``) turns a booking email into typed fields;
this module decides which trip those fields belong to, creating one when no
trip fits. It is the accommodation counterpart of ``grouping.py`` and lives
beside it for the same reason: deciding what a booking belongs to is a sync
concern, not something the stays feature should know about.

**The matching rule was measured, not guessed.** Against nine years of real
mail (six bookings, 74 flights), a stay matches the trip whose flights fall
within its own span — outbound arriving on the check-in day, return departing
on the check-out day — and `STAY_TRIP_WINDOW_DAYS` of slack around it. Five of six
bookings found exactly one trip that way, and the answer did not change
anywhere between ±0 and ±21 days; only at ±30 did a stay start touching two
trips. The window is therefore small on purpose: the slack buys nothing that ±0
did not already find, and every extra day is a chance to swallow a neighbouring
trip. The sixth booking had no flights within a month in either direction — a
drive to Italy — which is the case trip creation exists for.

**Bracketing was considered and dropped.** The intuition is that a stay sits
between an outbound and a return, so a stay-trip should adopt flights falling
*outside* its span. Real itineraries do not look like that: the traveller flies
in on the day they check in and out on the day they check out, so the flights
are *inside* the stay, and plain span overlap finds them.

**The country gate is free insurance.** The markup names the property's country
and the airports table names each airport's, so a stay only joins a trip that
touched its country. It never once blocked a true match in the corpus, and it
is what stops a Lisbon weekend being absorbed by a Tokyo trip that happens to
straddle the same fortnight.

What this cannot do is **remove** a booking. No cancellation or alteration mail
appeared anywhere in the corpus, so there is nothing to parse for it; in the
one case where a booking was clearly cancelled and rebooked, the only evidence
was a second confirmation for the same nights at a different property. Imports
therefore create stays and never delete them, and two overlapping stays on one
trip is a visible row the traveller can remove rather than silent corruption.
"""

import logging
import uuid
from datetime import date, timedelta

from ..database import db_conn, db_write
from ..parsers.schema_org import extract_lodging_reservations
from ..utils import now_iso

logger = logging.getLogger(__name__)

__all__ = ["STAY_TRIP_WINDOW_DAYS", "import_lodging_from_email"]

# Days of slack either side of the stay's own span when looking for its trip.
# See the module docstring: ±0 already found every match, so this is deliberately
# tight rather than generous. Public because `grouping.py` matches in the
# opposite direction — flights arriving after the stay — and the two must agree
# or a booking would find a trip going one way but not coming back.
STAY_TRIP_WINDOW_DAYS = 2

# Which stay kind an email implies. Everything unrecognised is a hotel, which is
# the common case and the neutral one — `STAY_KINDS` has no "unknown".
_KIND_BY_DOMAIN = (
    ("airbnb.", "airbnb"),
    ("hostelworld.", "hostel"),
)


def _kind_for_sender(sender: str) -> str:
    lowered = (sender or "").lower()
    for needle, kind in _KIND_BY_DOMAIN:
        if needle in lowered:
            return kind
    return "hotel"


def _shift(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def _find_existing_stay(user_id: int, stay: dict) -> str | None:
    """Return the id of an already-imported copy of this booking, if any.

    Idempotency is keyed on the booking reference where there is one, because
    that is the booking's identity and survives the platform restating it in a
    reminder. Where there is none — one real record in six had neither a
    reference nor a property name — the fallback is the property name plus the
    check-in date, which is the next best thing the traveller would recognise as
    "the same booking".
    """
    check_in_date = stay["check_in_datetime"][:10]
    with db_conn() as conn:
        if stay.get("booking_reference"):
            row = conn.execute(
                """SELECT s.id FROM trip_stays s JOIN trips t ON t.id = s.trip_id
                   WHERE t.user_id = ? AND s.booking_reference = ?""",
                (user_id, stay["booking_reference"]),
            ).fetchone()
            if row:
                return row["id"]
        row = conn.execute(
            """SELECT s.id FROM trip_stays s JOIN trips t ON t.id = s.trip_id
               WHERE t.user_id = ? AND s.name = ? AND s.check_in_date = ?""",
            (user_id, stay["name"], check_in_date),
        ).fetchone()
        return row["id"] if row else None


def _find_trip_for_stay(user_id: int, stay: dict) -> str | None:
    """The trip whose flights sit inside this stay's span, or None.

    Ambiguity is resolved by flight count rather than refused: at this window
    two trips never both matched in the measured corpus, but if it ever happens
    the trip contributing more of the itinerary is the better guess, and picking
    one beats creating a duplicate trip beside a perfectly good one.
    """
    lo = _shift(stay["check_in_datetime"][:10], -STAY_TRIP_WINDOW_DAYS)
    hi = _shift(stay["check_out_datetime"][:10], STAY_TRIP_WINDOW_DAYS)
    country = stay.get("country_code")
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT f.trip_id AS trip_id, COUNT(*) AS n
                 FROM flights f
                 LEFT JOIN airports da ON da.iata_code = f.departure_airport
                 LEFT JOIN airports aa ON aa.iata_code = f.arrival_airport
                WHERE f.user_id = ?
                  AND f.trip_id IS NOT NULL
                  AND DATE(f.departure_datetime) BETWEEN ? AND ?
                  AND (? IS NULL OR da.country_code = ? OR aa.country_code = ?)
                GROUP BY f.trip_id
                ORDER BY n DESC, MIN(f.departure_datetime)""",
            (user_id, lo, hi, country, country, country),
        ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        logger.info(
            "Lodging import: %d trips match stay '%s'; taking the one with most flights",
            len(rows),
            stay["name"][:40],
        )
    return rows[0]["trip_id"]


def _trip_name_for_stay(stay: dict) -> str:
    """Name a trip after where it goes and when, matching grouping.py's shape."""
    where = stay.get("city") or stay["name"]
    try:
        when = date.fromisoformat(stay["check_in_datetime"][:10]).strftime("%b %Y")
    except ValueError:
        when = ""
    return f"{where} ({when})" if when else where


def _create_trip_for_stay(user_id: int, stay: dict) -> str:
    """Open an auto-generated trip for a booking that matched no existing one.

    No `planned_start_date` / `planned_end_date` is written: an auto-generated
    trip declares nothing and is described entirely by its contents, so the span
    comes from `_recompute_span` once the stay is attached. That is also what
    lets a flight arriving months later widen it rather than fight a declared
    pair — which is not hypothetical, as two of the measured bookings were made
    four and seven months before their flights were.
    """
    trip_id = str(uuid.uuid4())
    now = now_iso()
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, is_auto_generated,
                                  user_id, created_at, updated_at)
               VALUES (?, ?, '[]', 1, ?, ?, ?)""",
            (trip_id, _trip_name_for_stay(stay), user_id, now, now),
        )
    logger.info("Lodging import: created trip '%s' (id=%s)", _trip_name_for_stay(stay), trip_id)
    return trip_id


def _geocode(stay: dict) -> tuple[float | None, float | None, str | None]:
    """Resolve the property's coordinates so the stay gets a map pin and a zone.

    The markup carries no coordinates — none of the six measured bookings had
    any, nor a static map URL to scrape one from — but it does carry a street
    address, which is exactly what the stay picker already geocodes. Without a
    geocoder the stay still saves; it simply has no pin and its times are stored
    as typed, which is the documented behaviour for a hand-entered place.
    """
    from ..integrations.photon import client as photon

    query = stay.get("address") or (
        f"{stay['name']}, {stay['city']}" if stay.get("city") else stay["name"]
    )
    try:
        results = photon.search_places(query, kind="stay", limit=1)
    except Exception as exc:  # noqa: BLE001 - a geocoder outage must not lose the booking
        logger.warning("Lodging import: geocoding failed for %r: %s", query[:60], exc)
        return None, None, None
    if not results:
        return None, None, None
    top = results[0]
    return top.get("lat"), top.get("lon"), (top.get("countrycode") or "").upper() or None


def import_lodging_from_email(email_msg, user_id: int) -> list[str]:
    """Create stays for every lodging reservation this email declares.

    Returns the ids created — empty for the overwhelming majority of mail, which
    carries no markup at all.
    """
    from ..stays.service import stay_service

    reservations = extract_lodging_reservations(email_msg)
    if not reservations:
        return []

    kind = _kind_for_sender(getattr(email_msg, "sender", "") or "")
    created: list[str] = []

    for stay in reservations:
        try:
            if _find_existing_stay(user_id, stay):
                logger.debug("Lodging import: '%s' already imported", stay["name"][:40])
                continue

            lat, lon, geo_country = _geocode(stay)
            trip_id = _find_trip_for_stay(user_id, stay) or _create_trip_for_stay(user_id, stay)

            stay_id = stay_service.create_stay(
                trip_id,
                user_id,
                {
                    "kind": kind,
                    "place": {
                        "name": stay["name"],
                        "address": stay.get("address"),
                        "lat": lat,
                        "lon": lon,
                        # The platform's own country wins over the geocoder's:
                        # it is a fact the booking carries, not a lookup.
                        "country_code": stay.get("country_code") or geo_country,
                    },
                    "check_in_datetime": stay["check_in_datetime"],
                    "check_out_datetime": stay["check_out_datetime"],
                    "booking_reference": stay.get("booking_reference"),
                    "contact": stay.get("contact"),
                },
            )
            created.append(stay_id)
            logger.info(
                "User %d: imported stay '%s' (%s → %s) into trip %s",
                user_id,
                stay["name"][:40],
                stay["check_in_datetime"][:10],
                stay["check_out_datetime"][:10],
                trip_id,
            )
        except Exception as exc:  # noqa: BLE001 - one bad booking must not stop the sync
            logger.error(
                "User %d: failed to import lodging '%s': %s",
                user_id,
                str(stay.get("name"))[:40],
                exc,
                exc_info=True,
            )

    return created
