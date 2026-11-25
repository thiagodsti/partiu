"""Does an email name this airport? The check for airport codes a reader derived.

Partiu's structural readers take an airport only when the email states its
IATA code. Two readers can hand over a code the email never printed: the LLM
fallback maps city names to codes, and KDE Itinerary's extractor fills a
missing code from the airport's name when that name matches one airport. Both
are mostly right and sometimes not — LATAM's "Florianópolis" came back from
the model as FLY, Finley in Australia — so both keep an airport only when the
email names it here: by its code printed as a word of its own, or by a locating
word of its name, city or aliases.

Moved here from ``integrations/llm/parser.py`` when the KItinerary tier needed
the same check; that module re-exports it under the old names.
"""

import logging
import re

logger = logging.getLogger(__name__)


def airport_index() -> tuple[frozenset[str], dict[str, set[str]], dict[str, set[str]]]:
    """Airport codes, and what in a mail can name each airport.

    Returns (codes, words, phrases): ``words`` maps every locating word of an
    airport's name, city or aliases (``_significant_tokens``, the filter
    ``resolve_iata`` uses, so "airport" or "international" name nothing) to
    codes; ``phrases`` maps whole folded city names and aliases ("sao paulo",
    "milan bergamo") to codes. Only airports with scheduled service, which an
    airline itinerary always uses — unless the table has none flagged, as on
    an install that never ran the ranking backfill.

    Read on every call (tens of ms): one call per mail, next to a model that
    takes a minute, and no cache to go stale when the airports change.
    """
    from ..database import db_conn
    from .shared import _significant_tokens

    codes: set[str] = set()
    words: dict[str, set[str]] = {}
    phrases: dict[str, set[str]] = {}
    try:
        with db_conn() as conn:
            scheduled = conn.execute(
                "SELECT 1 FROM airports WHERE scheduled_service = 1 LIMIT 1"
            ).fetchone()
            where = "WHERE scheduled_service = 1" if scheduled else ""
            rows = conn.execute(
                f"SELECT iata_code, name_folded, city_folded FROM airports {where}"
            ).fetchall()
            aliases = conn.execute("SELECT alias, iata_code FROM airport_aliases").fetchall()
    except Exception as e:  # noqa: BLE001 - no airport data: no candidates
        logger.debug("airport candidates unavailable (%s)", e)
        return frozenset(), {}, {}
    for code, name, city in rows:
        codes.add(code)
        for value in (name, city):
            for token in _significant_tokens(value or ""):
                words.setdefault(token, set()).add(code)
        if city:
            phrases.setdefault(city, set()).add(code)
    for alias, code in aliases:
        if code not in codes:
            continue
        phrases.setdefault(alias, set()).add(code)
        for token in _significant_tokens(alias or ""):
            words.setdefault(token, set()).add(code)
    return frozenset(codes), words, phrases


_MAX_AIRPORTS_PER_WORD = 5


def airport_candidates(text: str) -> list[str]:
    """Every airport the mail names: printed codes, and words of airport names.

    A code counts when printed as a word of its own; a name when a locating
    word of an airport's name, city or aliases is in the mail, or one to three
    consecutive words are a whole city name or alias ("sao paulo" → GRU and
    CGH). Noise comes along — PIX (the payment method) is Pico Island, the
    Portuguese word "nome" is Nome, Alaska — which only adds a choice the
    model has no reason to take. On the 192 corpus legs the right airport was
    in the list every time (median 23 candidates per mail).

    Only used to check an answer (``airport_in_text``). Offering the list to
    the model as the schema's choices was measured and dropped: no gain over
    the check alone (40-41 of 53 legs either way), and the fuller the list the
    more wrong choices it offers — a passenger named Barbara is Santa Barbara
    (SBA), "Brasil" is an airport name in Boa Vista.
    """
    from ..utils import fold_text
    from .shared import _significant_tokens

    codes, words, phrases = airport_index()
    found = {t for t in re.findall(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])", text) if t in codes}
    folded = fold_text(text)
    for token in set(_significant_tokens(folded)):
        airports = words.get(token, set())
        # A word shared by many airports ("santa" names 29) locates nothing and
        # would only bury the right airport in noise. Five keeps every corpus
        # airport (Stockholm alone names ARN, BMA, NYO and VST) at a median of
        # 23 candidates per mail; three already loses Arlanda.
        if len(airports) <= _MAX_AIRPORTS_PER_WORD:
            found |= airports
    plain = re.findall(r"[a-z0-9]+", folded)
    for n in (2, 3):
        for i in range(len(plain) - n + 1):
            found |= phrases.get(" ".join(plain[i : i + n]), set())
    return sorted(found)


def airport_in_text(code: str, text: str) -> bool:
    """True when the mail names this airport, by the same rule as the answer schema.

    The model maps city names to codes, mostly right ("Sicily-Catania" → CTA)
    but not always: LATAM's "Florianópolis" came back as FLY, Finley in
    Australia, and asking it to map cities made it invent city codes (STO,
    CAT). An airport is kept exactly when it is one of the mail's
    ``airport_candidates``. With no airport data at all, nothing can be checked.
    """
    codes, _, _ = airport_index()
    if not codes:
        return True
    return (code or "").upper() in airport_candidates(text)


def airport_stated_in_text(code: str, text: str) -> bool:
    """True when the mail pins this airport down, not merely mentions its city.

    Stricter than ``airport_in_text``, for codes a reader filled in itself
    (KDE Itinerary's name lookup). The airport counts only when the mail
    prints its IATA code as a word of its own, or contains a word or a whole
    phrase of its name, city or aliases that names **this airport alone** —
    "Malpensa", "Gatwick", "Lisbon". A shared city name does not: "Milan" names
    LIN, MXP and BGY, so it says nothing about which one, and neither does
    "London" or "Stockholm". With no airport data nothing can be checked, and
    the answer is no: this check exists to refuse what cannot be confirmed.
    """
    from ..utils import fold_text
    from .shared import _significant_tokens

    code = (code or "").upper()
    codes, words, phrases = airport_index()
    if not codes or code not in codes:
        return False
    if re.search(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])", text or ""):
        return True
    folded = fold_text(text or "")
    if any(words.get(token) == {code} for token in set(_significant_tokens(folded))):
        return True
    plain = re.findall(r"[a-z0-9]+", folded)
    return any(
        phrases.get(" ".join(plain[i : i + n])) == {code}
        for n in (2, 3)
        for i in range(len(plain) - n + 1)
    )
