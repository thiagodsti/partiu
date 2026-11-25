"""Could this email describe a flight? A cheap gate in front of the LLM.

Every structural reader decides for itself whether it applies: an airline rule
matches its own senders, the GDS parser needs a ticket-receipt marker, the
schema.org reader needs typed markup. The LLM fallback has no such test. Fed a
hotel confirmation or a concert ticket, it spends about a minute on a CPU and
returns nothing — or, rarely, a leg its validation then has to catch.

That gate used to be a list of blocked sender domains (`non_flight_domains`,
dropped in migration 0042). A list only knows the senders someone has already
added, and it had become a misleading label: Airbnb sat on it while its stays
were being imported, because the lodging and car-rental readers ran ahead of
the skip. This module asks of the email itself what the list asked of its
sender.

The test: a token shaped like a flight number (subject or body), plus either a
subject that talks about a booking, a ticket, a check-in or a flight, or a
booking-reference label in the body — and no marketing words in the subject.

It is tuned for **recall**, because a false negative means a real booking from
an airline with no rule never reaches the only reader that could have taken
it. Measured on the 372-email corpus (2026-11-25):

* real flight bookings (mails the airline rules import legs from): 88 of 90
  pass. The two misses are an Azul confirmation that prints its flight numbers
  without the AD prefix — and Azul has a rule;
* mails no reader extracted a flight from (the pipeline's condition for
  calling the LLM): 69 of 282 pass, where the blocked-domain list let 211
  through, so the LLM sees about a third of the mail it used to;
* mails from the formerly blocked senders: 8 of 71 pass (an Airbnb reminder, a
  Hertz booking, meeting confirmations). Each costs one LLM call, and the LLM's
  own grounding check rejects any leg whose flight number and airports are not
  in the mail.

An email that fails this test is still read by every structural reader; it is
only not sent to the LLM. Mail a person sends in on purpose (an uploaded .eml,
a forward to the SMTP inbox) skips the test.
"""

import re

# A flight number: a two-character IATA designator (letters, or a letter and a
# digit either way round), an optional space, then 1-4 digits.
_FLIGHT_NUMBER = re.compile(r"\b(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])\s?\d{1,4}\b")

_FLIGHT_SUBJECT = re.compile(
    r"confirm|booking|itinerar|e-?ticket|ticket|receipt|reserv|rezerv|"
    r"flight|trip|journey|check-?in|boarding|travel documents|"
    # pt / es
    r"passagem|bilhete|recibo|viagem|voo\b|vuelo|billete|embarque|"
    # sv / no / da
    r"bokning|kvitto|resehandling|incheckning|flyg|reise|"
    # de / fr / it / tr
    r"buchung|flug|réservation|vol\b|billet|prenotazione|volo\b|biglietto|"
    r"bilet|uçuş|seyahat",
    re.IGNORECASE,
)

_REFERENCE_LABEL = re.compile(
    r"\bPNR\b|record locator|e-?ticket|ticket (?:number|no)|"
    r"(?:booking|reservation|confirmation)\s*(?:ref|reference|code|number|no)|"
    r"c[oó]digo (?:da|de|do) (?:reserva|localizador)|localizador|"
    r"bokningsnummer|bokningsreferens|referansenummer|"
    r"buchungs(?:code|nummer)|r[ée]f[ée]rence de (?:r[ée]servation|dossier)|"
    r"codice (?:di )?prenotazione|rezervasyon (?:kodu|numarası)",
    re.IGNORECASE,
)

# Mail that mentions a flight to sell something: an upgrade, miles, an offer.
_MARKETING_SUBJECT = re.compile(
    r"newsletter|unsubscribe|\boffer|oferta|\bsale\b|\bdeal|promo|% off|"
    # Whole words only: "Smiles" is GOL's loyalty programme, and its
    # "Smiles - Sua passagem foi emitida" is a booking, not marketing.
    r"upgrade|\bmiles\b|milhas|\bpoints\b|\bpontos\b|\btips\b|dicas|rate your|avalie|"
    r"survey|pesquisa|how was|como foi",
    re.IGNORECASE,
)

# The flight details sit near the top of a confirmation; a long tail of terms
# and footers only adds false flight-number matches.
_BODY_WINDOW = 20_000


def may_describe_a_flight(subject: str | None, body: str | None) -> bool:
    """True when the email is worth an LLM call (see the module docstring)."""
    subject = subject or ""
    if _MARKETING_SUBJECT.search(subject):
        return False
    text = f"{subject}\n{(body or '')[:_BODY_WINDOW]}"
    if not _FLIGHT_NUMBER.search(text):
        return False
    return bool(_FLIGHT_SUBJECT.search(subject) or _REFERENCE_LABEL.search(text))


# A subject that is about a booking itself, not a check-in or boarding reminder
# for one (those are about a flight that, in practice, is already stored).
_BOOKING_SUBJECT = re.compile(
    r"confirm|booking|itinerar|e-?ticket|ticket|receipt|reserv|rezerv|"
    r"passagem|bilhete|recibo|viagem|voo\b|vuelo|billete|"
    r"bokning|kvitto|resehandling|buchung|réservation|billet|prenotazione|"
    r"biglietto|bilet",
    re.IGNORECASE,
)


def looks_like_flight_booking(subject: str | None, body: str | None) -> bool:
    """The strict test for the review list (email_review): could this be a
    booking that nothing managed to read?

    Stricter than ``may_describe_a_flight`` because its cost is the traveller's
    attention, not a CPU minute: all three signals are required — a subject
    about a booking, a flight number, a booking-reference label — and no
    marketing words. Measured on the 372-email corpus (2026-11-25): of 201
    mails nothing imported, 14 pass; after dropping those about a flight
    already stored (the service's job), 5 remain, 4 of them real missed
    bookings (MaxMilhas, GOL, a LATAM order).
    """
    subject = subject or ""
    if not _BOOKING_SUBJECT.search(subject) or _MARKETING_SUBJECT.search(subject):
        return False
    text = f"{subject}\n{(body or '')[:_BODY_WINDOW]}"
    return bool(_FLIGHT_NUMBER.search(text) and _REFERENCE_LABEL.search(text))
