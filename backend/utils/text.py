"""Text normalisation helpers shared by airport resolution and its data loader."""

import unicodedata


def fold_text(s: str | None) -> str:
    """Lowercase and strip diacritics: 'Düsseldorf' → 'dusseldorf'.

    Airport data is full of accented place names ('Florianópolis', 'Hercílio',
    'Düsseldorf') while emails and user input usually are not, and SQLite's LIKE
    is accent-sensitive. Both sides are folded so they can be compared directly.
    """
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
