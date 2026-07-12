"""Repository for the `aircraft_types` reference-data table, plus the static
seed list of known aircraft type codes."""

from ...database import db_conn, db_write

# (iata_code, name, manufacturer)
_AIRCRAFT_TYPES: list[tuple[str, str, str]] = [
    # Airbus narrow-body
    ("A318", "Airbus A318", "Airbus"),
    ("A319", "Airbus A319", "Airbus"),
    ("A320", "Airbus A320", "Airbus"),
    ("A321", "Airbus A321", "Airbus"),
    ("A19N", "Airbus A319neo", "Airbus"),
    ("A20N", "Airbus A320neo", "Airbus"),
    ("A21N", "Airbus A321neo", "Airbus"),
    ("A21X", "Airbus A321XLR", "Airbus"),
    # Airbus wide-body
    ("A225", "Airbus A220-100", "Airbus"),
    ("A223", "Airbus A220-300", "Airbus"),
    ("BCS1", "Airbus A220-100", "Airbus"),
    ("BCS3", "Airbus A220-300", "Airbus"),
    ("A332", "Airbus A330-200", "Airbus"),
    ("A333", "Airbus A330-300", "Airbus"),
    ("A338", "Airbus A330-800neo", "Airbus"),
    ("A339", "Airbus A330-900neo", "Airbus"),
    ("A342", "Airbus A340-200", "Airbus"),
    ("A343", "Airbus A340-300", "Airbus"),
    ("A345", "Airbus A340-500", "Airbus"),
    ("A346", "Airbus A340-600", "Airbus"),
    ("A359", "Airbus A350-900", "Airbus"),
    ("A35K", "Airbus A350-1000", "Airbus"),
    ("A380", "Airbus A380-800", "Airbus"),
    ("A388", "Airbus A380-800", "Airbus"),
    # Boeing narrow-body
    ("B712", "Boeing 717-200", "Boeing"),
    ("B721", "Boeing 727-100", "Boeing"),
    ("B722", "Boeing 727-200", "Boeing"),
    ("B732", "Boeing 737-200", "Boeing"),
    ("B733", "Boeing 737-300", "Boeing"),
    ("B734", "Boeing 737-400", "Boeing"),
    ("B735", "Boeing 737-500", "Boeing"),
    ("B736", "Boeing 737-600", "Boeing"),
    ("B737", "Boeing 737-700", "Boeing"),
    ("B738", "Boeing 737-800", "Boeing"),
    ("B739", "Boeing 737-900", "Boeing"),
    ("B37M", "Boeing 737 MAX 7", "Boeing"),
    ("B38M", "Boeing 737 MAX 8", "Boeing"),
    ("B39M", "Boeing 737 MAX 9", "Boeing"),
    ("B3XM", "Boeing 737 MAX 10", "Boeing"),
    # Boeing wide-body
    ("B741", "Boeing 747-100", "Boeing"),
    ("B742", "Boeing 747-200", "Boeing"),
    ("B743", "Boeing 747-300", "Boeing"),
    ("B744", "Boeing 747-400", "Boeing"),
    ("B748", "Boeing 747-8", "Boeing"),
    ("B74S", "Boeing 747SP", "Boeing"),
    ("B752", "Boeing 757-200", "Boeing"),
    ("B753", "Boeing 757-300", "Boeing"),
    ("B762", "Boeing 767-200", "Boeing"),
    ("B763", "Boeing 767-300", "Boeing"),
    ("B764", "Boeing 767-400", "Boeing"),
    ("B772", "Boeing 777-200", "Boeing"),
    ("B77L", "Boeing 777-200LR", "Boeing"),
    ("B773", "Boeing 777-300", "Boeing"),
    ("B77W", "Boeing 777-300ER", "Boeing"),
    ("B778", "Boeing 777X-8", "Boeing"),
    ("B779", "Boeing 777X-9", "Boeing"),
    ("B788", "Boeing 787-8 Dreamliner", "Boeing"),
    ("B789", "Boeing 787-9 Dreamliner", "Boeing"),
    ("B78X", "Boeing 787-10 Dreamliner", "Boeing"),
    # Embraer
    ("E135", "Embraer ERJ-135", "Embraer"),
    ("E140", "Embraer ERJ-140", "Embraer"),
    ("E145", "Embraer ERJ-145", "Embraer"),
    ("E170", "Embraer E170", "Embraer"),
    ("E175", "Embraer E175", "Embraer"),
    ("E190", "Embraer E190", "Embraer"),
    ("E195", "Embraer E195", "Embraer"),
    ("E75L", "Embraer E175-E2", "Embraer"),
    ("E75S", "Embraer E175-E2", "Embraer"),
    ("E290", "Embraer E190-E2", "Embraer"),
    ("E295", "Embraer E195-E2", "Embraer"),
    # ATR
    ("AT43", "ATR 42-300", "ATR"),
    ("AT45", "ATR 42-500", "ATR"),
    ("AT46", "ATR 42-600", "ATR"),
    ("AT72", "ATR 72-200", "ATR"),
    ("AT73", "ATR 72-300", "ATR"),
    ("AT75", "ATR 72-500", "ATR"),
    ("AT76", "ATR 72-600", "ATR"),
    # Bombardier / CRJ
    ("CRJ1", "Bombardier CRJ-100", "Bombardier"),
    ("CRJ2", "Bombardier CRJ-200", "Bombardier"),
    ("CRJ7", "Bombardier CRJ-700", "Bombardier"),
    ("CRJ9", "Bombardier CRJ-900", "Bombardier"),
    ("CRJX", "Bombardier CRJ-1000", "Bombardier"),
    ("DH8A", "Bombardier Dash 8-100", "Bombardier"),
    ("DH8B", "Bombardier Dash 8-200", "Bombardier"),
    ("DH8C", "Bombardier Dash 8-300", "Bombardier"),
    ("DH8D", "Bombardier Dash 8-400", "Bombardier"),
    # McDonnell Douglas / MD
    ("MD11", "McDonnell Douglas MD-11", "McDonnell Douglas"),
    ("MD81", "McDonnell Douglas MD-81", "McDonnell Douglas"),
    ("MD82", "McDonnell Douglas MD-82", "McDonnell Douglas"),
    ("MD83", "McDonnell Douglas MD-83", "McDonnell Douglas"),
    ("MD87", "McDonnell Douglas MD-87", "McDonnell Douglas"),
    ("MD88", "McDonnell Douglas MD-88", "McDonnell Douglas"),
    ("MD90", "McDonnell Douglas MD-90", "McDonnell Douglas"),
    ("DC10", "Douglas DC-10", "McDonnell Douglas"),
    # Fokker
    ("F100", "Fokker 100", "Fokker"),
    ("F70", "Fokker 70", "Fokker"),
    ("F50", "Fokker 50", "Fokker"),
    ("F27", "Fokker 27 Friendship", "Fokker"),
    # Sukhoi / Irkut
    ("SU95", "Sukhoi Superjet 100", "Sukhoi"),
    ("SU9S", "Sukhoi Superjet 100", "Sukhoi"),
    # Comac
    ("C919", "Comac C919", "Comac"),
    ("ARJ1", "Comac ARJ21", "Comac"),
    # Saab
    ("SB20", "Saab 2000", "Saab"),
    ("SF34", "Saab 340", "Saab"),
    # Cessna / Beechcraft
    ("C208", "Cessna 208 Caravan", "Cessna"),
    ("B190", "Beechcraft 1900", "Beechcraft"),
    # De Havilland Canada
    ("DHC6", "De Havilland Canada Twin Otter", "De Havilland Canada"),
    ("DH6", "De Havilland Canada Twin Otter", "De Havilland Canada"),
]


class AircraftTypeRepository:
    def get_name(self, iata_code: str) -> str | None:
        """Look up a human-readable aircraft name by IATA type code."""
        with db_conn() as conn:
            row = conn.execute(
                "SELECT name FROM aircraft_types WHERE iata_code = ?",
                (iata_code.upper(),),
            ).fetchone()
        return row["name"] if row else None

    def cache(self, iata_code: str, name: str, manufacturer: str) -> None:
        """Cache a type name resolved from a third-party lookup (e.g. hexdb.io)."""
        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO aircraft_types (iata_code, name, manufacturer) VALUES (?, ?, ?)",
                (iata_code, name, manufacturer),
            )

    def count(self) -> int:
        with db_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM aircraft_types").fetchone()[0]

    def seed_if_empty(self) -> None:
        """Pre-populate the aircraft_types table on first run."""
        if self.count() > 0:
            return
        with db_write() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO aircraft_types (iata_code, name, manufacturer) VALUES (?, ?, ?)",
                _AIRCRAFT_TYPES,
            )

    def normalize_existing_flight_types(self) -> None:
        """Data-consistency sweep: resolve raw IATA codes stored in flights.aircraft_type
        (from before names were cached) to their human-readable name."""
        with db_write() as conn:
            rows = conn.execute(
                "SELECT id, aircraft_type FROM flights "
                "WHERE aircraft_type IS NOT NULL AND aircraft_type != '' "
                "AND aircraft_type NOT LIKE '% %'"
            ).fetchall()
            for row in rows:
                resolved = conn.execute(
                    "SELECT name FROM aircraft_types WHERE iata_code = ?",
                    (row["aircraft_type"].upper(),),
                ).fetchone()
                if resolved:
                    conn.execute(
                        "UPDATE flights SET aircraft_type = ? WHERE id = ?",
                        (resolved["name"], row["id"]),
                    )
