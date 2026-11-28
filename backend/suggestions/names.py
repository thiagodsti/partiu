"""Is this the place that was named? Shared by the map lookup and the
Wikipedia lookup, which answer the same question about different sources."""

import math
import re
import unicodedata

from ..utils.text import fold_text

_STOPWORDS = frozenset(
    "the and of de da do das dos e la le les el los del di du der die das und "
    "restaurant restaurante cafe bar museu museum museo park parque".split()
)


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(h))


def latin(text: str) -> bool:
    """No letters from outside the Latin script (accents are fine)."""
    return all(not c.isalpha() or unicodedata.name(c, "LATIN").startswith("LATIN") for c in text)


def words(name: str) -> set[str]:
    folded = "".join(c if c.isalnum() else " " for c in fold_text(name))
    return {w for w in folded.split() if len(w) >= 3 and w not in _STOPWORDS}


def same_name(suggested: str, found: str) -> bool:
    """Whether a map hit is the place the model named.

    True when one name contains the other once folded, or when they share a
    distinctive word ("Torre de Belém" / "Belém Tower"); words every second
    place carries ("restaurante", "museu", "de") do not count.
    """
    a, b = fold_text(suggested), fold_text(found)
    if a and b and (a in b or b in a):
        return True
    return bool(words(suggested) & words(found))


def article_is_about(name: str, title: str) -> bool:
    """Whether a Wikipedia article title is about the named place — stricter
    than :func:`same_name`, because an article's photo is shown as the place's.

    The place's whole name inside the title counts ("Time Out Market" /
    "Time Out Market Lisboa"), and so do shared words when the title adds one
    of its own ("Torre de Belém" / "Belém Tower"). A title whose words are all
    inside the name does not: "Chiado" in "Café Chiado" is the district the
    café is named after, and its photo is of the district.
    """
    a, b = fold_text(name).strip(), fold_text(title).strip()
    if not a or not b:
        return False
    # The whole name as whole words of the title: "Time Out Market" in
    # "Time Out Market Lisboa", never "Bar" inside "Barcelona".
    if a == b or re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", b):
        return True
    name_words, title_words = words(name), words(title)
    return bool(name_words & title_words) and not title_words <= name_words
