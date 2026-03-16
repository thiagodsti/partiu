"""
IATA BCBP (Bar Coded Boarding Pass) parser — Resolution 792.

Format (mandatory fixed-width fields):
  Pos  1    : Format code ('M')
  Pos  2    : Number of legs ('1'-'9')
  Pos  3-22 : Passenger name (20 chars, LASTNAME/FIRSTNAME)
  Pos 23    : Electronic ticket indicator
  Pos 24-30 : PNR/booking reference (7 chars)
  Pos 31-33 : From city IATA (3 chars)
  Pos 34-36 : To city IATA (3 chars)
  Pos 37-39 : Operating carrier designator (3 chars)
  Pos 40-44 : Flight number (5 chars)
  Pos 45-47 : Date of flight — Julian date, day of year (3 chars)
  Pos 48    : Compartment code (cabin class)
  Pos 49-52 : Seat number (4 chars)
  Pos 53-57 : Check-in sequence number (5 chars)
  Pos 58    : Passenger status

Each additional leg repeats from position 23 with the same layout.
"""

import re
from datetime import date, timedelta
from typing import Generator

# Minimum length for a valid single-leg BCBP string
_BCBP_MIN_LEN = 58

# Cabin compartment code → cabin_class mapping
_COMPARTMENT_MAP = {
    'F': 'first', 'A': 'first', 'P': 'first',
    'J': 'business', 'C': 'business', 'D': 'business', 'I': 'business', 'Z': 'business',
    'W': 'premium_economy', 'R': 'premium_economy',
}

# Boarding pass strings are often embedded in QR/barcode text blocks in emails.
# They start with 'M' and have a digit for the leg count.
_BCBP_RE = re.compile(r'M[1-9][A-Z /]{18}[EM ][A-Z0-9 ]{7}[A-Z]{3}[A-Z]{3}[A-Z0-9 ]{3}[0-9 ]{5}[0-9]{3}[A-Z][0-9A-Z ]{4}')


def _julian_to_date(julian: int, ref_year: int | None = None) -> date | None:
    """Convert a Julian day-of-year (1-366) to a calendar date.

    We infer the year by picking the nearest upcoming date from today
    (or within the past 6 months, to handle recently-completed flights).
    """
    if not 1 <= julian <= 366:
        return None

    from datetime import date as _date
    today = _date.today()

    for year in (today.year, today.year + 1, today.year - 1):
        try:
            d = _date(year, 1, 1) + timedelta(days=julian - 1)
        except ValueError:
            continue
        # Prefer a date within ±180 days of today
        delta = abs((d - today).days)
        if delta <= 365:
            # Return the first candidate that's within the last 6 months or upcoming
            diff = (d - today).days
            if diff >= -180:
                return d

    # Fallback: use current year
    try:
        return _date(today.year, 1, 1) + timedelta(days=julian - 1)
    except ValueError:
        return None


def _parse_name(raw: str) -> tuple[str, str]:
    """Parse 'LASTNAME/FIRSTNAME' into (first_name, last_name). Returns full name if no slash."""
    raw = raw.strip()
    if '/' in raw:
        parts = raw.split('/', 1)
        last = parts[0].strip().title()
        first = parts[1].strip().title()
        return first, last
    return raw.title(), ''


def _clean_field(s: str) -> str:
    return s.strip()


def parse_bcbp(bcbp: str) -> list[dict]:
    """
    Parse a BCBP string and return a list of flight dicts (one per leg).

    Each dict contains:
      flight_number, departure_airport, arrival_airport,
      airline_code, booking_reference, passenger_name,
      seat, cabin_class, julian_date (int), departure_date (date | None)
    """
    bcbp = bcbp.strip()
    if len(bcbp) < _BCBP_MIN_LEN:
        return []
    if bcbp[0] != 'M':
        return []

    try:
        num_legs = int(bcbp[1])
    except ValueError:
        return []

    if num_legs < 1 or num_legs > 9:
        return []

    passenger_name_raw = bcbp[2:22]
    first_name, last_name = _parse_name(passenger_name_raw)
    passenger_name = f"{first_name} {last_name}".strip() if last_name else first_name

    legs = []
    # First leg starts at offset 22 (0-indexed), subsequent legs at 22 + 36*(n-1)
    # Each repeated segment is 36 chars (positions 23-58 in 1-indexed = 36 chars)
    leg_offset = 22

    for i in range(num_legs):
        seg_start = leg_offset + i * 36
        seg_end = seg_start + 36

        if len(bcbp) < seg_end:
            break

        seg = bcbp[seg_start:seg_end]

        # seg[0]    = e-ticket indicator (pos 23 in 1-indexed)
        # seg[1:8]  = PNR (pos 24-30)
        # seg[8:11] = from airport (pos 31-33)
        # seg[11:14]= to airport (pos 34-36)
        # seg[14:17]= carrier (pos 37-39)
        # seg[17:22]= flight number (pos 40-44)
        # seg[22:25]= julian date (pos 45-47)
        # seg[25]   = compartment (pos 48)
        # seg[26:30]= seat (pos 49-52)
        # seg[30:35]= sequence (pos 53-57)
        # seg[35]   = pax status (pos 58)

        pnr = _clean_field(seg[1:8])
        dep_airport = _clean_field(seg[8:11]).upper()
        arr_airport = _clean_field(seg[11:14]).upper()
        carrier = _clean_field(seg[14:17]).upper()
        flight_num_raw = _clean_field(seg[17:22])
        julian_raw = _clean_field(seg[22:25])
        compartment = seg[25].upper()
        seat_raw = _clean_field(seg[26:30])
        # seg[35] = pax status (unused for now)

        # Validate airports (must be 3 alpha chars)
        if not (dep_airport.isalpha() and len(dep_airport) == 3):
            continue
        if not (arr_airport.isalpha() and len(arr_airport) == 3):
            continue

        # Parse flight number: carrier (2-3 chars) + numeric part
        # carrier field is 3 chars; strip trailing space from 2-char codes
        airline_code = carrier.rstrip()
        try:
            flight_num_digits = int(flight_num_raw)
            flight_number = f"{airline_code}{flight_num_digits}"
        except ValueError:
            # Sometimes includes a letter suffix (e.g., "1234A")
            flight_number = f"{airline_code}{flight_num_raw.strip()}"

        # Parse Julian date
        departure_date = None
        julian_int = None
        try:
            julian_int = int(julian_raw)
            departure_date = _julian_to_date(julian_int)
        except ValueError:
            pass

        # Cabin class
        cabin_class = _COMPARTMENT_MAP.get(compartment, 'economy')

        # Seat: strip trailing letters sometimes mean "no seat assigned"
        seat = seat_raw.strip()
        if seat in ('', '   ', '0000'):
            seat = ''

        leg = {
            'flight_number': flight_number,
            'airline_code': airline_code,
            'departure_airport': dep_airport,
            'arrival_airport': arr_airport,
            'booking_reference': pnr,
            'passenger_name': passenger_name,
            'seat': seat,
            'cabin_class': cabin_class,
            'julian_date': julian_int,
            'departure_date': departure_date,  # date object or None
        }
        legs.append(leg)

    return legs


def find_bcbp_in_text(text: str) -> list[str]:
    """
    Scan a text blob (e.g. email plain-text body or PDF content) for BCBP strings.
    Returns a list of candidate BCBP strings found.
    """
    if not text:
        return []

    candidates = []

    # Strategy 1: regex match on the text
    for m in _BCBP_RE.finditer(text):
        candidate = m.group(0)
        # Extend greedily: BCBP can be longer for conditional fields
        start = m.start()
        end = m.end()
        # Try to grab up to 300 chars from start (multi-leg boarding passes)
        extended = text[start:start + 300].split('\n')[0].split('\r')[0]
        candidates.append(extended)

    # Strategy 2: look for lines that start with 'M' and are long enough
    for line in text.splitlines():
        line = line.strip()
        if (
            len(line) >= _BCBP_MIN_LEN
            and line[0] == 'M'
            and line[1:2].isdigit()
        ):
            # Quick sanity: next 20 chars should be mostly alpha/space (passenger name)
            name_part = line[2:22]
            alpha_count = sum(1 for c in name_part if c.isalpha() or c == ' ' or c == '/')
            if alpha_count >= 10:
                candidates.append(line)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for c in candidates:
        key = c[:60]  # first 60 chars is enough to identify
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique
