"""Find an imported stay on the map — or leave it off rather than guess.

A booking mail carries an address, not coordinates, and the geocoder answers
fuzzily: asked for "No. 1 Xiaotong Lane, Qingyang District, Chengdu" (a Trip.com
confirmation's English rendering), Photon's best answers were a hotel 5 km away
in the same city and a hotel in Taiwan. The importer used to take the first
answer whatever it was, so a stay could be pinned in another country; it was
only ever left off the map because komoot's public instance happened to refuse
the request. A wrong pin is worse than none: it moves distances, the plan map
and the stay's timezone.

So a hit is taken only when the booking backs it up:

* **where** — the hit's city is named in the booking (address, city line or
  property name), or the booking's own country code matches the hit's. A hit
  whose country contradicts the booking's is refused outright;
* **what** — the hit carries the first distinctive word of the line that was
  searched (the street's own name, or the property's), so "Calle de Fernando
  Poo" matches "Calle Fernando Poo 16", "RENJU EAST LAKE ISLAND" does not match
  "Xiaotong Lane", and "Nostalgia S Hotel (Kuanzhai Alley)" is not the
  "IntercityHotel Chengdu Kuanzhai Alley" down the same lane. A hit labelled in
  another script is matched by containment instead.

The queries, in order: the address as printed; the **street** of the
local-script address Trip.com prints under it for China properties ("小通巷",
taken from "成都市青羊区小通巷1号": OSM names Chinese streets in Chinese, and
Photon finds the bare street name where the full address with its district
prefixes finds nothing); the property's name with its city. The street gives a
street-level pin — a hotel on a short lane, which is what the distances and the
map need.
"""

import logging
import re

from ..integrations.photon import client as photon
from ..utils.text import fold_text

logger = logging.getLogger(__name__)

_HITS_PER_QUERY = 5

# Words that say what a line is, not which one it is.
_GENERIC = frozenset(
    """
    no nr number unit building floor room street st road rd lane ln avenue ave
    alley boulevard blvd way district county province city town village area
    zone block calle rua avenida via strada strasse platz de del la el los las
    do da dos das di le the and of hotel hostel inn apartment apartments
    residence house branch store shop north south east west
    """.split()
)
_WORD_RE = re.compile(r"[a-z0-9]+")
_PARENS_RE = re.compile(r"\s*[(（][^)）]*[)）]?")
# CJK, kana and hangul: a label in one of these is compared by containment.
_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
# "成都市青羊区小通巷1号" → "小通巷": drop the administrative prefix and the
# house number. The prefix runs to the district (区/县) when there is one, else
# to the first city (市) — not to the last 市, which can be part of the street
# itself (西羊市, a lane in Xi'an).
_CJK_DISTRICT_RE = re.compile(r"^.*[区區县縣]")
_CJK_CITY_RE = re.compile(r"^.*?[省市]")
_CJK_NUMBER_RE = re.compile(r"[\d０-９]+[号號].*$")


def _words(text: str | None) -> set[str]:
    return {
        w
        for w in _WORD_RE.findall(fold_text(text or ""))
        if len(w) >= 3 and w not in _GENERIC and not w.isdigit()
    }


def _first_word(text: str) -> str | None:
    for w in _WORD_RE.findall(fold_text(text)):
        if len(w) >= 3 and w not in _GENERIC and not w.isdigit():
            return w
    return None


def _named_in(name: str, text: str) -> bool:
    """``name`` appears in ``text`` as whole words (both folded)."""
    folded = fold_text(name).strip()
    if not folded:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(folded)}(?![a-z0-9])", text) is not None


def local_street(local_address: str | None) -> str | None:
    """The street out of a CJK address, or None when it is not one."""
    if not local_address or not _CJK_RE.search(local_address):
        return None
    text = local_address.strip()
    rest = (
        _CJK_DISTRICT_RE.sub("", text)
        if _CJK_DISTRICT_RE.search(text)
        else _CJK_CITY_RE.sub("", text)
    )
    street = _CJK_NUMBER_RE.sub("", rest).strip()
    return street if len(street) >= 2 and _CJK_RE.search(street) else None


def _where_fits(hit: dict, stay: dict, booking_text: str) -> bool:
    code = (stay.get("country_code") or "").upper()
    hit_code = (hit.get("countrycode") or "").upper()
    if code and hit_code and code != hit_code:
        return False
    if hit.get("city") and _named_in(hit["city"], booking_text):
        return True
    return bool(code and hit_code == code)


def _what_fits(hit: dict, searched: str, rank: int) -> bool:
    label = f"{hit.get('name') or ''} {hit.get('address') or ''}"
    if _CJK_RE.search(searched):
        # The street name inside the map's label — or the map labelled it in
        # Latin (Qianjing for 前井胡同), which only its best answer is trusted for.
        return searched in label or (rank == 0 and not _CJK_RE.search(label))
    # The line's first distinctive word — the street's own name, the hotel's
    # own name — must be there: "Kuanzhai Alley" is shared by every hotel in
    # that alley, "Nostalgia" and "IntercityHotel" are not.
    first = _first_word(searched)
    return first is not None and first in _words(label)


def geocode_stay(stay: dict) -> tuple[float | None, float | None, str | None]:
    """(lat, lon, country code) for a booking, or Nones when nothing fits."""
    address = stay.get("address")
    first_line = (address or "").split(",")[0]
    queries: list[tuple[str, str]] = []
    if address:
        queries.append((address, first_line))
    street = local_street(stay.get("local_address"))
    if street:
        queries.append((street, street))
    # The name without its branch note: "Nanfeng Hotel (Xi'an Zhonggulou Huimin
    # Street Branch)" finds nothing, "Nanfeng Hotel, Xi'an" finds the hotel.
    name = _PARENS_RE.sub(" ", stay["name"]).strip() or stay["name"]
    if stay.get("city"):
        queries.append((f"{name}, {stay['city']}", name))
    elif not address:
        queries.append((name, name))

    booking_text = fold_text(
        " ".join(str(stay.get(k) or "") for k in ("address", "local_address", "city", "name"))
    )
    for query, searched in queries:
        try:
            hits = photon.search_places(query, kind="stay", limit=_HITS_PER_QUERY)
        except Exception as exc:  # noqa: BLE001 - a geocoder outage must not lose the booking
            logger.warning("Lodging import: geocoding failed for %r: %s", query[:60], exc)
            return None, None, None
        for rank, hit in enumerate(hits):
            if _where_fits(hit, stay, booking_text) and _what_fits(hit, searched, rank):
                code = (hit.get("countrycode") or "").upper() or None
                return hit.get("lat"), hit.get("lon"), code
    logger.info("Lodging import: %r not placed on the map", str(stay.get("name"))[:60])
    return None, None, None
