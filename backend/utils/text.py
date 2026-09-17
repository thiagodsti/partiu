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


def normalize_username(s: str | None) -> str:
    """The canonical form of a username: stripped and lowercased.

    Usernames are case-insensitive — "Thiago" and "thiago" are one account, and
    someone typing their own name with a capital at 7am should not be told their
    password is wrong. Every write path stores this form, and every lookup
    compares against it, so the two cannot drift.

    Deliberately *not* accent-folded, unlike `fold_text`: a username is an
    identifier the account holder chose and types back exactly, and folding
    would make "joão" and "joao" the same login while the stored name can only
    be one of them. Case is the part people get wrong by accident.
    """
    return (s or "").strip().lower()
