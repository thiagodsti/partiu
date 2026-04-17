"""
Built-in airline parsing rules (code-only, not stored in the database).

Adapted from AdventureLog — Django dependencies removed.
Added Norwegian Air Shuttle (DY).
"""

import importlib
from dataclasses import dataclass, field

# Increment this version whenever rules, extractors, or PDF logic are added or modified.
# When a sync detects a version mismatch, it performs a full rescan
# instead of an incremental one (deduplication prevents duplicate flights).
PARSER_VERSION = "25"  # feat: Wizz Air (W6/W9) itinerary confirmation parser

# ---------------------------------------------------------------------------
# Shared subject filter — applied to every airline rule.
# Covers flight-confirmation keywords across EN / PT / ES / DE / FR / NO / SV / DK.
# The sender_pattern already pins the airline; this prevents matching marketing
# or service emails that happen to come from the same domain.
# Add new keywords here when a new language or format is discovered — all
# airlines benefit automatically.
# ---------------------------------------------------------------------------
SUBJECT_PATTERN = (
    r"(?:confirm|reserv|booking|itinerar|e-?ticket|eticket|receipt|"
    r"boarding|check.?in|travel|trip|flight|order|"
    r"voo|passagem|bilhete|viagem|compr|embarque|cart[aã]o|"
    r"vuelo|viaje|"
    r"buchung|reise|"
    r"billet|resa|rejse|bestilling|flygning|bokning|"
    r"\d{2}[A-Z]{3})"  # e.g. "01FEB" date token in TAP e-ticket subjects
)

BUILTIN_AIRLINE_RULES = [
    # =========================================================================
    # LATAM Airlines (LA / JJ / 4C / 4M)
    # =========================================================================
    {
        "airline_name": "LATAM Airlines",
        "airline_code": "LA",
        "sender_pattern": r"(latam\.com|latamairlines\.com|info\.latam\.|@latam\.)",
        "custom_extractor": "latam",
        "priority": 10,
    },
    # =========================================================================
    # SAS Scandinavian Airlines (SK)
    # =========================================================================
    {
        "airline_name": "SAS Scandinavian Airlines",
        "airline_code": "SK",
        "sender_pattern": r"(flysas\.com|sas\.se|sas\.dk|sas\.no|@sas\.)",
        "custom_extractor": "sas",
        "priority": 10,
    },
    # =========================================================================
    # Norwegian Air Shuttle (DY)
    # =========================================================================
    {
        "airline_name": "Norwegian Air Shuttle",
        "airline_code": "DY",
        "sender_pattern": r"(norwegian\.com|@norwegian\.no|noreply@norwegian)",
        "custom_extractor": "norwegian",
        "priority": 10,
    },
    # =========================================================================
    # Lufthansa (LH)
    # =========================================================================
    {
        "airline_name": "Lufthansa",
        "airline_code": "LH",
        "sender_pattern": r"(lufthansa\.com|lufthansa-group\.com|@lh\.com|noreply@lufthansa)",
        "custom_extractor": "lufthansa",
        "priority": 10,
    },
    # =========================================================================
    # Kiwi.com (multi-carrier OTA — flight data lives in the PDF attachment)
    # =========================================================================
    {
        "airline_name": "Kiwi.com",
        "airline_code": "",
        "sender_pattern": r"(kiwi\.com|tickets@kiwi)",
        "custom_extractor": "kiwi",
        "priority": 5,  # lower than direct airline emails
    },
    # =========================================================================
    # British Airways (BA) — also handles Iberia legs in BA itineraries
    # =========================================================================
    {
        "airline_name": "British Airways",
        "airline_code": "BA",
        "sender_pattern": r"(@email\.ba\.com|@britishairways\.com|british.?airways)",
        "custom_extractor": "british_airways",
        "priority": 10,
    },
    # =========================================================================
    # ITA Airways (AZ) — boarding-pass and check-in confirmation emails
    # =========================================================================
    {
        "airline_name": "ITA Airways",
        "airline_code": "AZ",
        "sender_pattern": r"(ita-airways\.com|@enews\.ita-airways)",
        "custom_extractor": "ita_airways",
        "priority": 10,
    },
    # =========================================================================
    # Ryanair (FR) — travel itinerary emails
    # =========================================================================
    {
        "airline_name": "Ryanair",
        "airline_code": "FR",
        "sender_pattern": r"(ryanair\.com|@ryanair\.)",
        "custom_extractor": "ryanair",
        "priority": 10,
    },
    # =========================================================================
    # Austrian Airlines (OS) — boarding pass, travel confirmation, check-in
    # =========================================================================
    {
        "airline_name": "Austrian Airlines",
        "airline_code": "OS",
        "sender_pattern": r"(@austrian\.com|@notifications\.austrian|@information\.austrian)",
        "custom_extractor": "austrian",
        "priority": 10,
    },
    # =========================================================================
    # TAP Air Portugal (TP) — check-in, boarding pass, booking confirmation, e-ticket receipt
    # =========================================================================
    {
        "airline_name": "TAP Air Portugal",
        "airline_code": "TP",
        "sender_pattern": r"(@flytap\.com|@info\.flytap)",
        "custom_extractor": "tap",
        "priority": 10,
    },
    # =========================================================================
    # Qatar Airways (QR) — booking confirmation
    # =========================================================================
    {
        "airline_name": "Qatar Airways",
        "airline_code": "QR",
        "sender_pattern": r"(qatarairways\.com)",
        "custom_extractor": "qatar",
        "priority": 10,
    },
    # =========================================================================
    # Finnair (AY) — e-ticket receipt via Amadeus GDS or direct
    # =========================================================================
    {
        "airline_name": "Finnair",
        "airline_code": "AY",
        "sender_pattern": r"(@finnair\.com|@amadeus\.com)",
        "custom_extractor": "finnair",
        "priority": 10,
    },
    # =========================================================================
    # Wizz Air (W6 / W9) — travel itinerary confirmation emails
    # =========================================================================
    {
        "airline_name": "Wizz Air",
        "airline_code": "W6",
        "sender_pattern": r"(wizzair\.com|@wizz\.)",
        "custom_extractor": "wizz_air",
        "priority": 10,
    },
    # =========================================================================
    # Azul Brazilian Airlines (AD)
    # =========================================================================
    {
        "airline_name": "Azul Brazilian Airlines",
        "airline_code": "AD",
        "sender_pattern": r"(voeazul[\w-]*\.com\.br|azullinhasaereas\.com|@azul\.com)",
        "custom_extractor": "azul",
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
    priority: int
    custom_extractor: str = ""
    extractor: object = field(default=None, repr=False)


def _resolve_extractor(name: str):
    """Return the unified ``extract()`` callable for a custom_extractor name.

    Dynamically imports ``backend.parsers.airlines.<name>`` and returns its
    ``extract`` function.  Adding a new airline only requires creating the
    module — no changes needed here.
    """
    if not name:
        return None
    try:
        module = importlib.import_module(f".airlines.{name}", package="backend.parsers")
        return getattr(module, "extract", None)
    except ImportError:
        return None


def get_builtin_rules() -> list[BuiltinAirlineRule]:
    """Return all built-in airline rules as in-memory objects (no DB query)."""
    rules = []
    for rule_dict in BUILTIN_AIRLINE_RULES:
        rule = BuiltinAirlineRule(**rule_dict)  # type: ignore[arg-type]
        rule.extractor = _resolve_extractor(rule.custom_extractor)
        rules.append(rule)
    return rules
