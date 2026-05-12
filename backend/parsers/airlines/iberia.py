"""
Iberia (IB) booking confirmation email parser.

Email structure after html_to_text:

  Outward
  IB0828
  Iberia
  IB0828          ← duplicate flight number
  Iberia          ← duplicate airline name
  Departure
  ARN
  ARN             ← duplicate IATA
  Stockholm,
  Sweden
  Terminal 2
  4h 5m           ← optional duration
  Arrival
  MAD
  MAD             ← duplicate IATA
  Madrid,
  Spain
  Terminal 4
  18:35           ← departure time
  Thursday 17 September 2026
  22:40           ← arrival time
  Thursday 17 September 2026

Times appear after both airport sections, in departure-then-arrival order.
All IATA codes appear twice due to the email's responsive-layout table structure.
"""

import logging
import re

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    html_to_text,
    make_flight_dict,
)

logger = logging.getLogger(__name__)

# Matches one outward or return flight block in the html_to_text output.
# Uses non-greedy quantifiers on city/terminal lines so the parser does not
# accidentally consume "Arrival" or time tokens.
_BLOCK_RE = re.compile(
    r"^(?:Outward|Return|Vuelta|Ida|Oneway)\n"
    r"([A-Z]{1,3}\d{3,4})\n"  # group 1: flight number
    r"(?:[^\n]+\n){1,3}"  # airline name + optional duplicate fn/airline
    r"Departure\n"
    r"([A-Z]{3})\n"  # group 2: departure IATA (first of two)
    r"[A-Z]{3}\n"  # departure IATA duplicate
    r"(?:[^\n]+\n){2,5}?"  # city / country / terminal lines (non-greedy)
    r"(?:\d+h\s*\d+m\n)?"  # optional flight duration
    r"Arrival\n"
    r"([A-Z]{3})\n"  # group 3: arrival IATA (first of two)
    r"[A-Z]{3}\n"  # arrival IATA duplicate
    r"(?:[^\n]+\n){2,5}?"  # city / country / terminal lines (non-greedy)
    r"(\d{2}:\d{2})\n"  # group 4: departure time
    r"([^\n]+)\n"  # group 5: departure date (may have day-of-week prefix)
    r"(\d{2}:\d{2})\n"  # group 6: arrival time
    r"([^\n]+)",  # group 7: arrival date
    re.MULTILINE,
)


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from an Iberia booking confirmation email."""
    html = email_msg.html_body or ""
    if not html:
        return []

    text = html_to_text(html)
    flights = []

    for m in _BLOCK_RE.finditer(text):
        fn = m.group(1)
        dep_iata = m.group(2)
        arr_iata = m.group(3)
        dep_time = m.group(4)
        dep_date_raw = m.group(5).strip()
        arr_time = m.group(6)
        arr_date_raw = m.group(7).strip()

        dep_date = parse_flight_date(dep_date_raw)
        arr_date = parse_flight_date(arr_date_raw)
        if not dep_date or not arr_date:
            logger.debug("Iberia: could not parse dates %r / %r", dep_date_raw, arr_date_raw)
            continue

        dep_dt = _build_datetime(dep_date, dep_time)
        arr_dt = _build_datetime(arr_date, arr_time)
        if dep_dt and arr_dt:
            arr_dt = fix_overnight(dep_dt, arr_dt)

        flight = make_flight_dict(rule, fn, dep_iata, arr_iata, dep_dt, arr_dt)
        if flight:
            flights.append(flight)

    return enrich_flights(flights, text, email_msg.subject)
