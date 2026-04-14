"""
Non-flight sender domains — domains that never contain flight bookings.
Used during sync to skip emails that will never parse into flights.
"""

import re

from .database import db_conn, db_write

# Hardcoded domains that never contain flight bookings.
# Subdomains are also matched (e.g. "property.booking.com" matches "booking.com").
NON_FLIGHT_DOMAINS: frozenset[str] = frozenset(
    [
        # Accommodation
        "airbnb.com",
        "booking.com",
        "property.booking.com",
        "reservation.accor-mail.com",
        # Car rental
        "emails.hertz.com",
        "europcar.com",
        "sixt.com",
        # Restaurants & events
        "bookatable.com",
        "caspeco.net",
        "boxoffice.axs.nu",
        "ticketmaster.se",
        "bookatable.co.uk",
        # Business / consulting
        "alphasights.com",
        # Tech / SaaS
        "pipdecks.com",
        "aws-experience.com",
        # Government / public services
        "migrationsverket.se",
        "ventus.com",
        # Retail
        "medlem.kjell.com",
        # Travel aggregators that send non-booking emails
        "tripit.com",
        # Schools
        "folkuniversitetet.se",
    ]
)


def _sender_domain(sender: str) -> str:
    m = re.search(r"@([\w.-]+)", sender or "")
    return m.group(1).lower() if m else ""


def _matches(domain: str, blocked: str) -> bool:
    return domain == blocked or domain.endswith("." + blocked)


def is_non_flight_domain(sender: str) -> bool:
    """Return True if the sender domain is known to never send flight bookings."""
    domain = _sender_domain(sender)
    if not domain:
        return False

    if any(_matches(domain, d) for d in NON_FLIGHT_DOMAINS):
        return True

    try:
        with db_conn() as conn:
            rows = conn.execute("SELECT domain FROM non_flight_domains").fetchall()
        return any(_matches(domain, row["domain"]) for row in rows)
    except Exception:
        return False


def list_non_flight_domains() -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT domain, note, created_at FROM non_flight_domains ORDER BY domain"
        ).fetchall()
    return [dict(r) for r in rows]


def add_non_flight_domain(domain: str, note: str = "") -> None:
    domain = domain.strip().lower()
    if not domain:
        return
    with db_write() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO non_flight_domains (domain, note) VALUES (?, ?)",
            (domain, note),
        )


def remove_non_flight_domain(domain: str) -> None:
    with db_write() as conn:
        conn.execute("DELETE FROM non_flight_domains WHERE domain = ?", (domain,))
