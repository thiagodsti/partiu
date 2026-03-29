"""
Built-in airline parsing rules (code-only, not stored in the database).

Adapted from AdventureLog — Django dependencies removed.
Added Norwegian Air Shuttle (DY).
"""

from dataclasses import dataclass, field

# Increment this version whenever rules, extractors, or PDF logic are added or modified.
# When a sync detects a version mismatch, it performs a full rescan
# instead of an incremental one (deduplication prevents duplicate flights).
# Also triggers auto-retry of all failed_emails for the user.
PARSER_VERSION = "23"  # fix: SAS Berlin Brandenburg → BER (was resolving to Trollenhagen/FNB)

# ---------------------------------------------------------------------------
# Flexible date sub-pattern (reusable)
# ---------------------------------------------------------------------------
_DATE = r"\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4}"
_TIME = r"\d{1,2}:\d{2}"

BUILTIN_AIRLINE_RULES = [
    # =========================================================================
    # LATAM Airlines (LA / JJ / 4C / 4M)
    # =========================================================================
    {
        "airline_name": "LATAM Airlines",
        "airline_code": "LA",
        "sender_pattern": r"(latam\.com|latamairlines\.com|info\.latam\.|@latam\.)",
        "subject_pattern": (
            r"(itinerar|confirm|reserv|booking|e-?ticket|"
            r"compr|viage|viaje|vuelo|voo|trip|travel|"
            r"embarque|hor[aá]rios?|check.?in|cart[aã]o)"
        ),
        "body_pattern": (
            r"\((?P<departure_airport>[A-Z]{3})\)"
            r"\s+"
            r"(?P<flight_number>[A-Z0-9]{2}\s*\d{3,5})(?!\w)"
            r".*?"
            r"\((?P<arrival_airport>[A-Z]{3})\)"
        ),
        "date_format": "%d %b %Y",
        "time_format": "%H:%M",
        "custom_extractor": "latam",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # SAS Scandinavian Airlines (SK)
    # =========================================================================
    {
        "airline_name": "SAS Scandinavian Airlines",
        "airline_code": "SK",
        "sender_pattern": r"(flysas\.com|sas\.se|sas\.dk|sas\.no|@sas\.)",
        "subject_pattern": (
            r"(booking\s*confirm|itinerary|e-?ticket|receipt|"
            r"reservation|billet|resa|rejse|reise|trip|travel|"
            r"flight|flygning|bokningsbek|bokning|Din\s+resa|Your\s+Flight)"
        ),
        "body_pattern": (
            r"(?P<departure_airport>[A-Z]{3})"
            r"\s*[-–]\s*"
            r"(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?"
            r"(?P<arrival_airport>[A-Z]{3})"
            r"\s+"
            r"(?P<departure_time>" + _TIME + r")"
            r"\s*[-–]\s*"
            r"(?P<arrival_time>" + _TIME + r")"
            r".*?"
            r"(?P<flight_number>(?:SK|VS|LH|LX|OS|TP|A3|SN|BA|AF)\s*\d{2,5})"
        ),
        "date_format": "%d %b %Y",
        "time_format": "%H:%M",
        "custom_extractor": "sas",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # Norwegian Air Shuttle (DY)
    # =========================================================================
    {
        "airline_name": "Norwegian Air Shuttle",
        "airline_code": "DY",
        "sender_pattern": r"(norwegian\.com|@norwegian\.no|noreply@norwegian)",
        "subject_pattern": (
            r"(booking\s*confirm|itinerary|e-?ticket|receipt|"
            r"reservation|bestilling|trip|travel|order)"
        ),
        "body_pattern": (
            r"(?P<departure_airport>[A-Z]{3})"
            r"\s*[-–]\s*"
            r"(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?"
            r"(?P<arrival_airport>[A-Z]{3})"
            r"\s+"
            r"(?P<departure_time>" + _TIME + r")"
            r"\s*[-–]\s*"
            r"(?P<arrival_time>" + _TIME + r")"
            r".*?"
            r"(?P<flight_number>(?:DY|D8)\s*\d{2,5})"
        ),
        "date_format": "%d %b %Y",
        "time_format": "%H:%M",
        "custom_extractor": "norwegian",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # Lufthansa (LH)
    # =========================================================================
    {
        "airline_name": "Lufthansa",
        "airline_code": "LH",
        "sender_pattern": r"(lufthansa\.com|@lh\.com|noreply@lufthansa)",
        "subject_pattern": (
            r"(booking\s*confirm|booking\s*details|booking\b|itinerary|e-?ticket|receipt|"
            r"buchungsbest[äa]tigung|flugbest[äa]tigung|reservation|"
            r"Reise|trip|travel)"
        ),
        "body_pattern": (
            r"(?:"
            r"(?P<departure_date>" + _DATE + r")"
            r"\s+"
            r"(?P<departure_time>" + _TIME + r")"
            r".*?"
            r"\((?P<departure_airport>[A-Z]{3})\)"
            r".*?"
            r"(?P<flight_number>LH\s*\d{3,5})"
            r".*?"
            r"(?P<arrival_date>" + _DATE + r")"
            r"\s+"
            r"(?P<arrival_time>" + _TIME + r")"
            r".*?"
            r"\((?P<arrival_airport>[A-Z]{3})\)"
            r")"
        ),
        "date_format": "%d %b %Y",
        "time_format": "%H:%M",
        "custom_extractor": "lufthansa",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # Kiwi.com (multi-carrier OTA — flight data lives in the PDF attachment)
    # =========================================================================
    {
        "airline_name": "Kiwi.com",
        "airline_code": "",
        "sender_pattern": r"(kiwi\.com|tickets@kiwi)",
        "subject_pattern": r"(Reserva|Booking|itinerary|reservation|viagem|trip)",
        "body_pattern": r"",  # unused — custom_extractor handles everything
        "date_format": "%d %b %Y",
        "time_format": "%H:%M",
        "custom_extractor": "kiwi",
        "is_active": True,
        "is_builtin": True,
        "priority": 5,  # lower than direct airline emails
    },
    # =========================================================================
    # British Airways (BA) — also handles Iberia legs in BA itineraries
    # =========================================================================
    {
        "airline_name": "British Airways",
        "airline_code": "BA",
        "sender_pattern": r"(@email\.ba\.com|@britishairways\.com|british.?airways)",
        "subject_pattern": r"(e-?ticket|receipt|itinerary|booking|confirm)",
        "body_pattern": r"",  # custom_extractor handles everything
        "date_format": "%d %b %Y",
        "time_format": "%H:%M",
        "custom_extractor": "british_airways",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # ITA Airways (AZ) — boarding-pass and check-in confirmation emails
    # =========================================================================
    {
        "airline_name": "ITA Airways",
        "airline_code": "AZ",
        "sender_pattern": r"(ita-airways\.com|@enews\.ita-airways)",
        "subject_pattern": r"(boarding\s*pass|check.?in|ticket|confirm|AZ\d)",
        "body_pattern": r"",  # custom_extractor handles everything
        "date_format": "%d %b %Y",
        "time_format": "%H:%M",
        "custom_extractor": "ita_airways",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # Ryanair (FR) — travel itinerary emails
    # =========================================================================
    {
        "airline_name": "Ryanair",
        "airline_code": "FR",
        "sender_pattern": r"(ryanair\.com|@ryanair\.)",
        "subject_pattern": r"(itinerary|travel|booking|confirm|reservat)",
        "body_pattern": r"",  # custom_extractor handles everything
        "date_format": "%d %b %y",
        "time_format": "%H:%M",
        "custom_extractor": "ryanair",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # Austrian Airlines (OS) — boarding pass, travel confirmation, check-in
    # =========================================================================
    {
        "airline_name": "Austrian Airlines",
        "airline_code": "OS",
        "sender_pattern": r"(@austrian\.com|@notifications\.austrian|@information\.austrian)",
        "subject_pattern": r"(boarding|travel|confirm|check.?in|flight)",
        "body_pattern": r"",
        "date_format": "%d %b %y",
        "time_format": "%H:%M",
        "custom_extractor": "austrian",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # TAP Air Portugal (TP) — check-in open and boarding pass emails
    # =========================================================================
    {
        "airline_name": "TAP Air Portugal",
        "airline_code": "TP",
        "sender_pattern": r"(@flytap\.com|@info\.flytap)",
        "subject_pattern": r"(boarding|check.?in|confirm|reservat|itinerar)",
        "body_pattern": r"",
        "date_format": "%d/%m/%Y",
        "time_format": "%H:%M",
        "custom_extractor": "tap",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # Finnair (AY) — e-ticket receipt via Amadeus GDS or direct
    # =========================================================================
    {
        "airline_name": "Finnair",
        "airline_code": "AY",
        "sender_pattern": r"(@finnair\.com|@amadeus\.com)",
        "subject_pattern": r"(eticket|e-?ticket|boarding|confirm|finnair|AY\d)",
        "body_pattern": r"",
        "date_format": "%d%b%Y",
        "time_format": "%H:%M",
        "custom_extractor": "finnair",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
    # =========================================================================
    # Azul Brazilian Airlines (AD)
    # =========================================================================
    {
        "airline_name": "Azul Brazilian Airlines",
        "airline_code": "AD",
        "sender_pattern": r"(voeazul[\w-]*\.com\.br|azullinhasaereas\.com|@azul\.com)",
        "subject_pattern": (
            r"(itinerar|confirm|reserv|booking|e-?ticket|"
            r"compr|viage|voo|passagem|bilhete|trip|travel)"
        ),
        "body_pattern": (
            r"\n\s*(?P<departure_airport>[A-Z]{3})\s*\n"
            r".*?"
            r"(?P<departure_date>\d{2}/\d{2})"
            r"\s*[•·]\s*"
            r"(?P<departure_time>" + _TIME + r")"
            r".*?"
            r"(?:Voo|Flight)\s+(?P<flight_number>\d{3,5})"
            r".*?"
            r"\n\s*(?P<arrival_airport>[A-Z]{3})\s*\n"
            r".*?"
            r"(?P<arrival_date>\d{2}/\d{2})"
            r"\s*[•·]\s*"
            r"(?P<arrival_time>" + _TIME + r")"
        ),
        "date_format": "%d/%m",
        "time_format": "%H:%M",
        "custom_extractor": "azul",
        "is_active": True,
        "is_builtin": True,
        "priority": 10,
    },
]


@dataclass
class BuiltinAirlineRule:
    """
    Lightweight, in-memory representation of an airline parsing rule.

    ``extractor`` is set by ``get_builtin_rules()`` to the unified
    ``extract(email_msg, rule) -> list[dict]`` callable for this airline.
    The engine calls it directly instead of using a string dispatch table.
    """

    airline_name: str
    airline_code: str
    sender_pattern: str
    body_pattern: str
    date_format: str
    time_format: str
    is_active: bool
    is_builtin: bool
    priority: int
    subject_pattern: str = ""
    custom_extractor: str = ""
    extractor: object = field(default=None, repr=False)


def _resolve_extractor(name: str):
    """Return the unified extract() callable for a given custom_extractor name."""
    if name == "latam":
        from .airlines.latam import extract

        return extract
    if name in ("sas", "norwegian"):
        from .airlines.sas import extract

        return extract
    if name == "lufthansa":
        from .airlines.lufthansa import extract

        return extract
    if name == "azul":
        from .airlines.azul import extract

        return extract
    if name == "kiwi":
        from .airlines.kiwi import extract

        return extract
    if name == "british_airways":
        from .airlines.british_airways import extract

        return extract
    if name == "ita_airways":
        from .airlines.ita_airways import extract

        return extract
    if name == "ryanair":
        from .airlines.ryanair import extract

        return extract
    if name == "austrian":
        from .airlines.austrian import extract

        return extract
    if name == "tap":
        from .airlines.tap import extract

        return extract
    if name == "finnair":
        from .airlines.finnair import extract

        return extract
    return None


def get_builtin_rules() -> list[BuiltinAirlineRule]:
    """Return all active built-in airline rules as in-memory objects (no DB query)."""
    rules = []
    for rule_dict in BUILTIN_AIRLINE_RULES:
        if not rule_dict.get("is_active", True):
            continue
        rule = BuiltinAirlineRule(**rule_dict)  # type: ignore[arg-type]
        rule.extractor = _resolve_extractor(rule.custom_extractor)
        rules.append(rule)
    return rules
