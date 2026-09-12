"""Builds the iCalendar (.ics) export for a trip — a self-contained concern
kept out of service.py (which owns trip CRUD, not calendar formatting).

The export covers everything on the trip's timeline:

* **flights** and **ground segments** as timed events, both with a 1h alarm;
* **stays** as an all-day block covering the nights, plus a timed check-out
  reminder — see `_stay_events` for why it is split in two;
* **day-planner content** as all-day events, one per day that has a note or a
  checklist. Planner entries carry no time of their own, so an all-day event is
  the honest representation — inventing a clock time would put "buy tickets" at
  an arbitrary hour.
"""

import json
from datetime import UTC, date, datetime, timedelta

from .errors import TripError
from .repository import TripRepository

# RFC 5545 caps a content line at 75 octets, continuation lines starting with a
# space. Day-planner notes run to 10,000 characters, so folding is not optional
# here the way it nearly was for flight-sized fields.
_MAX_LINE_OCTETS = 75


def _escape(text: str) -> str:
    """Escape a value for an iCalendar TEXT field (RFC 5545 §3.3.11).

    Backslash first, or it would double-escape the ones added afterwards.
    Unescaped commas and semicolons silently split a field into a value list,
    which is how a note reading "Beijing, then Xi'an" would corrupt the file.
    """
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold one content line to 75 octets per RFC 5545 §3.1.

    Splitting counts octets but must not cut a multi-byte character in half, so
    the encoded form is walked rather than the string.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= _MAX_LINE_OCTETS:
        return line

    chunks: list[str] = []
    start = 0
    limit = _MAX_LINE_OCTETS
    while start < len(encoded):
        end = min(start + limit, len(encoded))
        # Back off while `end` sits *inside* a character — that is, while the
        # byte the next chunk would start with is a continuation byte (10xxxxxx).
        # Testing encoded[end - 1] instead looks equivalent and is not: it stops
        # on a lead byte, leaving that character's tail bytes behind and eating
        # the character.
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        if end <= start:  # a single character wider than the remaining budget
            end = min(start + limit, len(encoded))
            while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
                end += 1
        chunks.append(encoded[start:end].decode("utf-8"))
        start = end
        limit = _MAX_LINE_OCTETS - 1  # continuation lines lose one octet to the space
    return "\r\n ".join(chunks)


def _plus_minutes(ical_utc: str, minutes: int) -> str:
    """Shift an ``YYYYMMDDTHHMMSSZ`` stamp forward, for a zero-length event that
    several clients would otherwise render as nothing at all."""
    try:
        parsed = datetime.strptime(ical_utc, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return ical_utc
    return (parsed + timedelta(minutes=minutes)).strftime("%Y%m%dT%H%M%SZ")


def _parse_day_content(raw: str) -> tuple[str, list[dict]]:
    """Return (note, items) from a stored day-note payload.

    Mirrors the frontend's parseContent, including the legacy shapes: the
    current format is ``{"note": ..., "items": [...]}``, older rows hold a block
    array, and the oldest hold plain text.
    """
    if not raw:
        return "", []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return raw, []

    if isinstance(parsed, dict):
        items = parsed.get("items")
        return parsed.get("note") or "", items if isinstance(items, list) else []
    if isinstance(parsed, list):
        note = ""
        items: list[dict] = []
        for block in parsed:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                note = block.get("value") or ""
            elif block.get("type") == "checklist" and isinstance(block.get("items"), list):
                items = block["items"]
        return note, items
    return "", []


class IcalService:
    def __init__(self, repository: TripRepository | None = None):
        self._repository = repository or TripRepository()

    def export_ical(self, trip_id: str, user_id: int) -> tuple[str, str]:
        """Return (ics_content, filename)."""
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)

        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripError("Trip not found", 404)

        from ..day_notes.repository import DayNoteRepository
        from ..segments.repository import SegmentRepository
        from ..stays.repository import StayRepository

        flights = self._repository.get_flights_for_trip(trip_id)
        segments = SegmentRepository().list_for_trip(trip_id)
        stays = StayRepository().list_for_trip(trip_id)
        day_notes = DayNoteRepository().list_for_trip(trip_id)

        now_utc = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        trip_name = trip.name or "Trip"
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in trip_name).strip()

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Partiu//Trip Export//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{_escape(trip_name)}",
        ]

        def _to_ical_dt(dt_str: str) -> str:
            try:
                dt = datetime.fromisoformat(dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            except (ValueError, TypeError):
                return now_utc

        # Trip span — every dated thing on the trip, so a trip whose middle is a
        # train is not cut short at its last flight.
        all_dates = [f["departure_datetime"] for f in flights if f["departure_datetime"]]
        all_dates += [f["arrival_datetime"] for f in flights if f["arrival_datetime"]]
        all_dates += [s.departure_datetime for s in segments if s.departure_datetime]
        all_dates += [s.arrival_datetime for s in segments if s.arrival_datetime]
        all_dates += [s.check_in_datetime for s in stays if s.check_in_datetime]
        all_dates += [s.check_out_datetime for s in stays if s.check_out_datetime]
        if all_dates:
            try:
                parsed = [datetime.fromisoformat(d) for d in all_dates]
                parsed = [d.replace(tzinfo=UTC) if d.tzinfo is None else d for d in parsed]
                span_start = (
                    min(parsed).astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                )
                span_end = (
                    max(parsed)
                    .astimezone(UTC)
                    .replace(hour=23, minute=59, second=59, microsecond=0)
                )
                lines += [
                    "BEGIN:VEVENT",
                    f"UID:{trip_id}-span@partiu",
                    f"DTSTAMP:{now_utc}",
                    f"DTSTART:{span_start.strftime('%Y%m%dT%H%M%SZ')}",
                    f"DTEND:{span_end.strftime('%Y%m%dT%H%M%SZ')}",
                    f"SUMMARY:{_escape(trip_name)}",
                    "TRANSP:TRANSPARENT",
                    "END:VEVENT",
                ]
            except (ValueError, TypeError):
                pass

        for flight in flights:
            dep_str = flight["departure_datetime"]
            arr_str = flight["arrival_datetime"]

            dep_ical = _to_ical_dt(dep_str) if dep_str else now_utc
            arr_ical = _to_ical_dt(arr_str) if arr_str else now_utc

            flight_number = flight["flight_number"] or ""
            dep_airport = flight["departure_airport"] or ""
            arr_airport = flight["arrival_airport"] or ""

            desc_parts = []
            for label, value in (
                ("Booking Ref", flight["booking_reference"]),
                ("Passenger", flight["passenger_name"]),
                ("Seat", flight["seat"]),
                ("Class", flight["cabin_class"]),
                ("Aircraft", flight["aircraft_type"]),
            ):
                if value:
                    desc_parts.append(f"{label}: {value}")

            lines += [
                "BEGIN:VEVENT",
                f"UID:{flight['id']}@partiu",
                f"DTSTAMP:{now_utc}",
                f"DTSTART:{dep_ical}",
                f"DTEND:{arr_ical}",
                f"SUMMARY:{_escape(f'{flight_number}: {dep_airport} → {arr_airport}')}",
                f"LOCATION:{_escape(f'{dep_airport} → {arr_airport}')}",
            ]
            if desc_parts:
                lines.append(f"DESCRIPTION:{_escape(chr(10).join(desc_parts))}")
            lines += [
                "BEGIN:VALARM",
                "TRIGGER:-PT1H",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(f'{flight_number} departs in 1 hour')}",
                "END:VALARM",
                "END:VEVENT",
            ]

        lines += self._segment_events(segments, now_utc, _to_ical_dt)
        lines += self._stay_events(stays, now_utc, _to_ical_dt)
        lines += self._day_note_events(trip_id, day_notes, now_utc)

        lines.append("END:VCALENDAR")

        content = "\r\n".join(_fold(line) for line in lines) + "\r\n"
        filename = f"{safe_name or trip_id}.ics"
        return content, filename

    @staticmethod
    def _segment_events(segments, now_utc: str, to_ical_dt) -> list[str]:
        """Timed events for train/bus/ferry/car legs."""
        lines: list[str] = []
        for s in segments:
            label = " ".join(p for p in (s.operator, s.number) if p) or s.type.capitalize()
            route = f"{s.departure.name} → {s.arrival.name}"

            desc_parts = [f"Type: {s.type.capitalize()}"]
            for field_label, value in (
                ("Booking Ref", s.booking_reference),
                ("Seat", s.seat),
                ("Notes", s.notes),
            ):
                if value:
                    desc_parts.append(f"{field_label}: {value}")

            lines += [
                "BEGIN:VEVENT",
                f"UID:{s.id}@partiu",
                f"DTSTAMP:{now_utc}",
                f"DTSTART:{to_ical_dt(s.departure_datetime) if s.departure_datetime else now_utc}",
                f"DTEND:{to_ical_dt(s.arrival_datetime) if s.arrival_datetime else now_utc}",
                f"SUMMARY:{_escape(f'{label}: {route}')}",
                f"LOCATION:{_escape(route)}",
                f"DESCRIPTION:{_escape(chr(10).join(desc_parts))}",
                "BEGIN:VALARM",
                "TRIGGER:-PT1H",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(f'{label} departs in 1 hour')}",
                "END:VALARM",
                "END:VEVENT",
            ]
        return lines

    @staticmethod
    def _stay_events(stays, now_utc: str, to_ical_dt) -> list[str]:
        """Two events per stay: an all-day block, and a timed check-out reminder.

        The block is all-day rather than a single timed event spanning several
        nights, because that is what a booking is — "14-18 October" at the
        property, not an instant-to-instant interval a viewer in another zone
        would see shifted. Its ``DTEND`` is the check-out date **plus one day**:
        DTEND is exclusive on an all-day event, so without the extra day the
        block stops the night before check-out and the morning you are still
        there falls outside it.

        The reminder is separate because the block cannot carry a useful alarm —
        an alarm on an all-day event fires at midnight in whatever zone the
        client picks. Check-out is the deadline people actually miss, so it gets
        its own 30-minute timed event an hour ahead of which the alarm fires.

        ``LOCATION`` prefers the street address over the property name: it is
        what makes the entry tappable through to a maps app, which is most of
        the value of having the stay in the calendar at all.
        """
        lines: list[str] = []
        for stay in stays:
            where = stay.place.address or stay.place.name
            nights = stay.nights

            desc_parts = [f"Type: {stay.kind.capitalize()}"]
            if nights is not None:
                desc_parts.append(f"Nights: {nights}")
            for field_label, value in (
                ("Address", stay.place.address),
                ("Booking Ref", stay.booking_reference),
                ("Confirmation", stay.confirmation),
                ("Contact", stay.contact),
                ("Room", stay.room_type),
                ("Guests", stay.guests),
                ("Notes", stay.notes),
            ):
                if value:
                    desc_parts.append(f"{field_label}: {value}")
            description = _escape(chr(10).join(desc_parts))

            try:
                check_in_day = date.fromisoformat(stay.check_in_date)
                check_out_day = date.fromisoformat(stay.check_out_date)
            except (ValueError, TypeError):
                continue

            block = [
                "BEGIN:VEVENT",
                f"UID:{stay.id}@partiu",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;VALUE=DATE:{check_in_day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(check_out_day + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{_escape(stay.place.name)}",
                f"LOCATION:{_escape(where)}",
                f"DESCRIPTION:{description}",
            ]
            # GEO is only meaningful with real coordinates; a hand-typed place
            # has none and must not be pinned at (0, 0) off West Africa.
            if stay.place.lat is not None and stay.place.lon is not None:
                block.append(f"GEO:{stay.place.lat};{stay.place.lon}")
            block += ["TRANSP:TRANSPARENT", "END:VEVENT"]
            lines += block

            if stay.check_out_datetime:
                check_out_utc = to_ical_dt(stay.check_out_datetime)
                lines += [
                    "BEGIN:VEVENT",
                    f"UID:{stay.id}-checkout@partiu",
                    f"DTSTAMP:{now_utc}",
                    f"DTSTART:{check_out_utc}",
                    f"DTEND:{_plus_minutes(check_out_utc, 30)}",
                    f"SUMMARY:{_escape(f'Check out: {stay.place.name}')}",
                    f"LOCATION:{_escape(where)}",
                    "BEGIN:VALARM",
                    "TRIGGER:-PT1H",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:{_escape(f'Check out of {stay.place.name} in 1 hour')}",
                    "END:VALARM",
                    "END:VEVENT",
                ]
        return lines

    @staticmethod
    def _day_note_events(trip_id: str, day_notes, now_utc: str) -> list[str]:
        """All-day events for day-planner content.

        Planner entries have no time of their own, so they become all-day
        events rather than being pinned to an invented hour. DTEND on an
        all-day event is *exclusive* — it has to be the following day, or the
        event renders as zero-length and disappears in most clients.
        """
        lines: list[str] = []
        for row in day_notes:
            note, items = _parse_day_content(row.content)
            note = note.strip()
            texts = [str(i.get("text", "")).strip() for i in items if isinstance(i, dict)]
            texts = [t for t in texts if t]
            if not note and not texts:
                continue

            try:
                day = date.fromisoformat(row.date)
            except (ValueError, TypeError):
                continue

            # The summary is the first line of the note, falling back to the
            # first checklist item, so the calendar shows something meaningful
            # without opening the event.
            headline = note.splitlines()[0].strip() if note else texts[0]
            if len(headline) > 60:
                headline = headline[:57].rstrip() + "…"

            body: list[str] = []
            if note:
                body.append(note)
            if texts:
                if body:
                    body.append("")
                body.extend(
                    ("☑ " if item.get("checked") else "☐ ") + str(item.get("text", "")).strip()
                    for item in items
                    if isinstance(item, dict) and str(item.get("text", "")).strip()
                )

            lines += [
                "BEGIN:VEVENT",
                f"UID:{trip_id}-day-{row.date}@partiu",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{_escape(headline)}",
                f"DESCRIPTION:{_escape(chr(10).join(body))}",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        return lines

    def _can_access(self, trip_id: str, user_id: int) -> bool:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)


ical_service = IcalService()
