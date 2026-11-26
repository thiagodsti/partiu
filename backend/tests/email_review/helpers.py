"""Shared set-up for the email review tests."""

import itertools
import sqlite3
import uuid
from datetime import UTC, datetime

_n = itertools.count(1)

AIRPORTS = [
    ("GRU", "Guarulhos International Airport", "Sao Paulo", -23.43, -46.47, "BR"),
    ("FLN", "Hercilio Luz International Airport", "Florianopolis", -27.67, -48.55, "BR"),
    ("CGH", "Congonhas Airport", "Sao Paulo", -23.63, -46.66, "BR"),
    ("LIS", "Lisbon Portela Airport", "Lisbon", 38.77, -9.13, "PT"),
    ("ARN", "Stockholm Arlanda Airport", "Stockholm", 59.65, 17.92, "SE"),
]

# A booking nothing in Partiu reads: an airline without a rule (Avianca
# Brasil, O6), a booking-like subject, a flight number, a reference label.
BODY = """Sua passagem foi emitida com sucesso
Código da reserva: PVNQDY
Número do voo: O66175
Florianópolis (FLN) 16 NOV 15:40 → São Paulo (GRU) 17:00
"""
SUBJECT = "Sua passagem foi emitida com sucesso - e-ticket PVNQDY"


def seed_airports(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    for code, name, city, lat, lon, country in AIRPORTS:
        conn.execute(
            """INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code,
                   latitude, longitude, type, scheduled_service, name_folded, city_folded)
               VALUES (?, ?, ?, ?, ?, ?, 'large_airport', 1, ?, ?)""",
            (code, name, city, country, lat, lon, name.lower(), city.lower()),
        )
    conn.commit()
    conn.close()


def make_user(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, 'h', 0)",
        (f"review{next(_n)}",),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def email(subject=SUBJECT, body=BODY, sender="MaxMilhas <contato@maxmilhas.example>"):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id=f"<{uuid.uuid4()}@example.com>",
        sender=sender,
        subject=subject,
        body=body,
        date=datetime(2018, 11, 7, 13, 3, tzinfo=UTC),
    )
