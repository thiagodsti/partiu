"""
Ryanair flight extractor.

Parses Ryanair "Travel Itinerary" HTML confirmation emails.
Uses the generic ``scan_flights`` scanner — no custom regex needed.

Email structure (after BS4 text extraction):
  Reservation:
  K1QU3R
  ...
  FR2878
  Milan (Bergamo)  -
  ARN
  Wed, 23 Apr 25
  Departure time - 17:55
  Arrival time - 20:35
  (BGY) -
  (ARN)

scan_flights handles this via:
  - Flight number: standalone "FR2878" line
  - IATA codes: "(BGY)" / "(ARN)" parenthesised markers (Strategy A-IATA)
  - Datetimes: date-only "Wed, 23 Apr 25" + labeled times Strategy B-DT
"""

from ..shared import enrich_flights, get_email_text, get_ref_year, scan_flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Ryanair email."""
    text = get_email_text(email_msg)
    flights = scan_flights(text, rule, get_ref_year(email_msg))
    return enrich_flights(flights, text, email_msg.subject)
