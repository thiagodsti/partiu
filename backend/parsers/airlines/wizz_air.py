"""
Wizz Air flight extractor.

Parses "Your travel itinerary" HTML confirmation emails from Wizz Air
(direct and Gmail-forwarded).
Uses the generic ``scan_flights`` scanner — no custom regex needed.

Plain-text structure produced by BS4 (one table cell per line):

  Flight confirmation code: GW8PSD
  ...
  GOING OUT
  Flight Number: W9 5362        ← NBSP between code and number
  Departs from:
  Arrives to:
  Barcelona El Prat - Terminal 2 (BCN)
  London Luton (LTN)
  14/05/2026 09:35              ← NBSP between date and time
  14/05/2026 11:00

Return legs appear after a "RETURN" / "GOING BACK" header with the same layout.
"""

from ..shared import enrich_flights, get_email_text, get_ref_year, scan_flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Wizz Air email."""
    text = get_email_text(email_msg)
    flights = scan_flights(text, rule, get_ref_year(email_msg))
    return enrich_flights(flights, text, email_msg.subject)
