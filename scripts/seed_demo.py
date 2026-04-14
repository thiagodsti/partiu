#!/usr/bin/env python3
"""
Demo seed script for Partiu.

Creates a demo admin user and pre-loads two trips with flights
at dates relative to today, so the demo always looks current:

  - "Rio Weekend"        — 3 weeks in the past   (Brazilian-centric, LATAM + Azul)
  - "European Tour"      — 8 weeks in the past    (International, LATAM / BA / SAS / Finnair)
  - "Rio de Janeiro"     — departing in ~10 days  (Brazilian-centric, Azul + LATAM)
  - "Lisbon & Oslo"      — departing in ~5 weeks  (International, TAP / Norwegian / LATAM)

Usage:
    python scripts/seed_demo.py                        # defaults to http://localhost:8000
    python scripts/seed_demo.py http://my-app.fly.dev
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.cookiejar import CookieJar

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo123"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_jar = CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _req(method: str, path: str, body: dict | None = None) -> dict:
    url = BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with _opener.open(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        # 409 on setup/duplicate is expected — not an error
        if e.code == 409:
            return {"_status": 409, "_body": text}
        print(f"  HTTP {e.code} {method} {path}: {text}")
        raise


def get(path: str) -> dict:
    return _req("GET", path)


def post(path: str, body: dict | None = None) -> dict:
    return _req("POST", path, body)


# ---------------------------------------------------------------------------
# Date helpers — all times in UTC, realistic local flight hours
# ---------------------------------------------------------------------------


def dt(base: datetime, *, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """Return an ISO-8601 string offset from base."""
    return (base + timedelta(days=days, hours=hours, minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def build_trips(now: datetime) -> list[dict]:
    """
    Build trip + flight definitions relative to `now`.
    Each trip dict has: name, note, flights[]
    Each flight dict matches FlightCreate fields.
    """

    # Anchor dates
    past_short = now - timedelta(weeks=3)  # Rio Weekend start
    past_long = now - timedelta(weeks=8)  # European Tour start
    future_short = now + timedelta(days=10)  # Upcoming Rio
    future_long = now + timedelta(weeks=5)  # Upcoming Lisbon & Oslo

    return [
        # ------------------------------------------------------------------ #
        # 1. Rio Weekend — 3 weeks ago, Brazilian-centric                     #
        # ------------------------------------------------------------------ #
        {
            "name": "Rio Weekend",
            "note": "Quick escape to Rio — samba, sun, and caipirinhas.",
            "flights": [
                {
                    "flight_number": "LA3456",
                    "airline_name": "LATAM Airlines",
                    "airline_code": "LA",
                    "departure_airport": "GRU",
                    "arrival_airport": "GIG",
                    "departure_datetime": dt(past_short, hours=7),
                    "arrival_datetime": dt(past_short, hours=8, minutes=10),
                    "booking_reference": "LTRW21",
                    "seat": "12A",
                    "cabin_class": "Economy",
                    "departure_terminal": "3",
                    "arrival_terminal": "2",
                },
                {
                    "flight_number": "AD4788",
                    "airline_name": "Azul Brazilian Airlines",
                    "airline_code": "AD",
                    "departure_airport": "GIG",
                    "arrival_airport": "GRU",
                    "departure_datetime": dt(past_short, days=3, hours=18),
                    "arrival_datetime": dt(past_short, days=3, hours=19, minutes=15),
                    "booking_reference": "AZRW21",
                    "seat": "22F",
                    "cabin_class": "Economy",
                },
            ],
        },
        # ------------------------------------------------------------------ #
        # 2. European Tour — 8 weeks ago, international                       #
        # ------------------------------------------------------------------ #
        {
            "name": "European Tour",
            "note": "São Paulo → London → Paris → Stockholm → Helsinki → home.",
            "flights": [
                {
                    "flight_number": "LA8084",
                    "airline_name": "LATAM Airlines",
                    "airline_code": "LA",
                    "departure_airport": "GRU",
                    "arrival_airport": "LHR",
                    "departure_datetime": dt(past_long, hours=22, minutes=30),
                    "arrival_datetime": dt(past_long, days=1, hours=14),
                    "booking_reference": "LTEU84",
                    "seat": "34C",
                    "cabin_class": "Economy",
                    "departure_terminal": "3",
                    "arrival_terminal": "2",
                },
                {
                    "flight_number": "BA304",
                    "airline_name": "British Airways",
                    "airline_code": "BA",
                    "departure_airport": "LHR",
                    "arrival_airport": "CDG",
                    "departure_datetime": dt(past_long, days=4, hours=10, minutes=15),
                    "arrival_datetime": dt(past_long, days=4, hours=12, minutes=35),
                    "booking_reference": "BAEU04",
                    "seat": "15D",
                    "cabin_class": "Economy",
                    "departure_terminal": "5",
                    "arrival_terminal": "2E",
                },
                {
                    "flight_number": "SK2617",
                    "airline_name": "SAS Scandinavian Airlines",
                    "airline_code": "SK",
                    "departure_airport": "CDG",
                    "arrival_airport": "ARN",
                    "departure_datetime": dt(past_long, days=7, hours=8),
                    "arrival_datetime": dt(past_long, days=7, hours=10, minutes=35),
                    "booking_reference": "SKEU17",
                    "seat": "8A",
                    "cabin_class": "Economy",
                },
                {
                    "flight_number": "AY1395",
                    "airline_name": "Finnair",
                    "airline_code": "AY",
                    "departure_airport": "ARN",
                    "arrival_airport": "HEL",
                    "departure_datetime": dt(past_long, days=10, hours=16, minutes=45),
                    "arrival_datetime": dt(past_long, days=10, hours=18),
                    "booking_reference": "AYEU95",
                    "seat": "11B",
                    "cabin_class": "Economy",
                },
                {
                    "flight_number": "AY53",
                    "airline_name": "Finnair",
                    "airline_code": "AY",
                    "departure_airport": "HEL",
                    "arrival_airport": "GRU",
                    "departure_datetime": dt(past_long, days=12, hours=15, minutes=30),
                    "arrival_datetime": dt(past_long, days=13, hours=5),
                    "booking_reference": "AYEU53",
                    "seat": "42K",
                    "cabin_class": "Economy",
                    "departure_terminal": "2",
                },
            ],
        },
        # ------------------------------------------------------------------ #
        # 3. Rio de Janeiro — upcoming in ~10 days, Brazilian-centric         #
        # ------------------------------------------------------------------ #
        {
            "name": "Rio de Janeiro",
            "note": "Long weekend in Rio — beach, sunset at Arpoador.",
            "flights": [
                {
                    "flight_number": "AD2231",
                    "airline_name": "Azul Brazilian Airlines",
                    "airline_code": "AD",
                    "departure_airport": "GRU",
                    "arrival_airport": "GIG",
                    "departure_datetime": dt(future_short, hours=6, minutes=45),
                    "arrival_datetime": dt(future_short, hours=7, minutes=55),
                    "booking_reference": "AZRJ31",
                    "seat": "5F",
                    "cabin_class": "Economy",
                    "departure_terminal": "3",
                },
                {
                    "flight_number": "LA3501",
                    "airline_name": "LATAM Airlines",
                    "airline_code": "LA",
                    "departure_airport": "GIG",
                    "arrival_airport": "GRU",
                    "departure_datetime": dt(future_short, days=4, hours=20),
                    "arrival_datetime": dt(future_short, days=4, hours=21, minutes=15),
                    "booking_reference": "LTRJ01",
                    "seat": "18C",
                    "cabin_class": "Economy",
                },
            ],
        },
        # ------------------------------------------------------------------ #
        # 4. Lisbon & Oslo — upcoming in ~5 weeks, international              #
        # ------------------------------------------------------------------ #
        {
            "name": "Lisbon & Oslo",
            "note": "TAP to Lisbon, then up to Oslo — fjords and bacalhau.",
            "flights": [
                {
                    "flight_number": "TP042",
                    "airline_name": "TAP Air Portugal",
                    "airline_code": "TP",
                    "departure_airport": "GRU",
                    "arrival_airport": "LIS",
                    "departure_datetime": dt(future_long, hours=21, minutes=55),
                    "arrival_datetime": dt(future_long, days=1, hours=11, minutes=30),
                    "booking_reference": "TPLO42",
                    "seat": "24A",
                    "cabin_class": "Economy",
                    "departure_terminal": "3",
                    "arrival_terminal": "1",
                },
                {
                    "flight_number": "TP954",
                    "airline_name": "TAP Air Portugal",
                    "airline_code": "TP",
                    "departure_airport": "LIS",
                    "arrival_airport": "OSL",
                    "departure_datetime": dt(future_long, days=4, hours=9, minutes=20),
                    "arrival_datetime": dt(future_long, days=4, hours=13, minutes=15),
                    "booking_reference": "TPLO54",
                    "seat": "31D",
                    "cabin_class": "Economy",
                    "departure_terminal": "1",
                },
                {
                    "flight_number": "DY651",
                    "airline_name": "Norwegian Air Shuttle",
                    "airline_code": "DY",
                    "departure_airport": "OSL",
                    "arrival_airport": "LGW",
                    "departure_datetime": dt(future_long, days=9, hours=7, minutes=10),
                    "arrival_datetime": dt(future_long, days=9, hours=9, minutes=20),
                    "booking_reference": "DYLO51",
                    "seat": "4B",
                    "cabin_class": "Economy",
                },
                {
                    "flight_number": "LA8083",
                    "airline_name": "LATAM Airlines",
                    "airline_code": "LA",
                    "departure_airport": "LHR",
                    "arrival_airport": "GRU",
                    "departure_datetime": dt(future_long, days=10, hours=12, minutes=45),
                    "arrival_datetime": dt(future_long, days=11, hours=3, minutes=30),
                    "booking_reference": "LTLO83",
                    "seat": "29F",
                    "cabin_class": "Economy",
                    "departure_terminal": "2",
                    "arrival_terminal": "3",
                },
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"Seeding demo data against {BASE_URL} (reference date: {now.date()})")

    # 1. Create admin/demo user
    print("\n[1/3] Setting up demo user...")
    result = post("/api/auth/setup", {"username": DEMO_USERNAME, "password": DEMO_PASSWORD})
    if result.get("_status") == 409:
        print("  User already exists — logging in")
        post("/api/auth/login", {"username": DEMO_USERNAME, "password": DEMO_PASSWORD})
    else:
        print(f"  Created user: {result.get('username')}")

    # 2. Check existing trips (idempotency — skip if already seeded)
    print("\n[2/3] Checking existing trips...")
    trips_resp = get("/api/trips")
    existing_names = {t["name"] for t in (trips_resp.get("trips") or [])}
    print(f"  Found {len(existing_names)} existing trip(s): {existing_names or '(none)'}")

    # 3. Create trips and flights
    print("\n[3/3] Creating trips and flights...")
    trips = build_trips(now)
    created = 0

    for trip_def in trips:
        name = trip_def["name"]
        if name in existing_names:
            print(f"  Skipping '{name}' (already exists)")
            continue

        trip = post("/api/trips", {"name": name})
        trip_id = trip["id"]
        print(f"  Created trip '{name}' (id={trip_id})")

        for flight_def in trip_def["flights"]:
            flight_def = {**flight_def, "trip_id": trip_id}
            flight = post("/api/flights", flight_def)
            print(
                f"    + {flight_def['flight_number']}  "
                f"{flight_def['departure_airport']} → {flight_def['arrival_airport']}  "
                f"{flight_def['departure_datetime'][:10]}"
            )
            _ = flight  # flight id available if needed

        # Add note if present
        if trip_def.get("note"):
            post(f"/api/trips/{trip_id}/note", {"note": trip_def["note"]})

        created += 1

    print(f"\nDone. Created {created} new trip(s).")


if __name__ == "__main__":
    main()
