"""Add non_flight_domains table and seed known non-flight senders.

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Domains that never send flight bookings — pre-seeded from NON_FLIGHT_DOMAINS.
_SEED_DOMAINS = [
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


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS non_flight_domains (
            domain      TEXT PRIMARY KEY,
            note        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    # Seed known non-flight domains
    for domain in _SEED_DOMAINS:
        op.execute(f"INSERT OR IGNORE INTO non_flight_domains (domain) VALUES ('{domain}')")

    # Remove any existing failed_emails from these domains
    domains_sql = ", ".join(f"'{d}'" for d in _SEED_DOMAINS)
    op.execute(f"DELETE FROM failed_emails WHERE airline_hint IN ({domains_sql})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS non_flight_domains")
