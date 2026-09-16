"""Cancellation records — what an airline's cancellation mail says is off.

Every parser in this package answers "what flights does this email describe?".
This module answers a different question: "what flights does this email say are
**no longer happening**?" — and the answer has to be applied to rows the
pipeline stored weeks earlier, from a different email.

Until this existed, a cancellation was handled purely by *suppressing*
extraction: `austrian.extract` returns [] when the subject says cancellation,
`finnair.extract` bails on its cancellation notice, `lufthansa` skips a leg
printed as `Estatuto: Cancelada`. That keeps a dead leg from being *created*,
which is necessary and not sufficient — the flight is normally already stored
from its booking confirmation, and nothing ever went back to it. Measured
across the 372-email corpus, six cancellation mails matched an airline rule,
produced nothing, and left six phantom flights in their trips.

**Two shapes, because the mail comes in two shapes.** SAS, Lufthansa and
Finnair confirm that a *booking* is off and name only its reference; Austrian
announces that one *leg* is off and names the flight number and date. Neither
can be expressed as the other: a booking reference covers legs the email never
lists, and a leg cancellation must not take its siblings with it — a
cancelled OS318 out of Stockholm says nothing about the return.

**A cancellation marks; it never deletes.** `status = 'cancelled'` keeps the
row readable, keeps the trip's history honest, and is reversible by hand if the
airline reinstates the flight. Deleting would be unrecoverable, would silently
change a trip the traveller may be looking at, and would break the same rule
`sync/stays_import.py` already follows for accommodation: imports create and
mark, and leave removal to the person.
"""

import re

__all__ = ["booking_cancellation", "leg_cancellation"]

# Same shape a PNR takes everywhere else in this package (see
# shared._extract_booking_ref_text): uppercase alphanumeric, 5-8 characters.
_REF_RE = re.compile(r"^[A-Z0-9]{5,8}$")
_FLIGHT_NUM_RE = re.compile(r"^[A-Z0-9]{2}\d{1,4}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def booking_cancellation(booking_reference: str) -> dict | None:
    """Every leg held under this booking reference is off.

    Returns None for anything that is not reference-shaped, so a parser that
    matched its cancellation marker but failed to find a reference reports
    nothing rather than a record the pipeline would have to second-guess. A
    cancellation that names no booking is not actionable: there is no safe way
    to guess which of the traveller's flights it meant.
    """
    ref = (booking_reference or "").strip().upper()
    return {"booking_reference": ref} if _REF_RE.match(ref) else None


def leg_cancellation(flight_number: str, departure_date: str) -> dict | None:
    """One leg is off — this flight number, on this local departure date.

    ``departure_date`` is an ISO date (YYYY-MM-DD) in the *departure airport's*
    local time, matching how `flights.departure_datetime` is keyed by
    `FlightRepository.find_by_number_and_date` and how boarding-pass enrichment
    already addresses a stored leg. Both fields are required: a flight number
    with no date would cancel every instance of a route the traveller has ever
    flown.
    """
    fn = (flight_number or "").strip().upper().replace(" ", "")
    date = (departure_date or "").strip()
    if not _FLIGHT_NUM_RE.match(fn) or not _ISO_DATE_RE.match(date):
        return None
    return {"flight_number": fn, "departure_date": date}
