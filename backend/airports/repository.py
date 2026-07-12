"""Repository for the `airports` reference-data table, plus the CSV bulk loader
that seeds it on first run."""

import logging

from ..database import db_conn, db_write, get_db_path

logger = logging.getLogger(__name__)


def _float_or_none(val):
    try:
        return float(val) if val else None
    except (ValueError, TypeError):
        return None


class AirportRepository:
    def get_by_iata(self, iata_code: str) -> dict | None:
        """Return full airport info (including coordinates) for an IATA code."""
        with db_conn() as conn:
            row = conn.execute(
                "SELECT iata_code, name, city_name, country_code, latitude, longitude "
                "FROM airports WHERE iata_code = ?",
                (iata_code.upper(),),
            ).fetchone()
        return dict(row) if row else None

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search airports by IATA code prefix, name, or city — exact IATA matches
        first, then prefix matches, then substring matches elsewhere."""
        pattern = f"%{query}%"
        prefix = f"{query}%"
        with db_conn() as conn:
            rows = conn.execute(
                """
                SELECT iata_code, name, city_name, country_code
                FROM airports
                WHERE iata_code LIKE ? OR name LIKE ? OR city_name LIKE ?
                ORDER BY
                    CASE WHEN upper(iata_code) = upper(?) THEN 0
                         WHEN upper(iata_code) LIKE upper(?) THEN 1
                         ELSE 2 END,
                    iata_code
                LIMIT ?
                """,
                (prefix, pattern, pattern, query, prefix, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with db_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM airports").fetchone()[0]

    def load_from_csv_if_empty(self) -> None:
        """
        Load airports from data/airports.csv if the airports table is empty.
        The CSV should be downloaded from https://ourairports.com/data/airports.csv
        and placed in the data/ directory.
        """
        import csv
        from pathlib import Path

        existing = self.count()
        if existing > 0:
            logger.debug("Airports table already populated (%d rows)", existing)
            return

        csv_path = Path(get_db_path()).parent / "airports.csv"
        if not csv_path.exists():
            logger.info("airports.csv not found — downloading from ourairports.com ...")
            try:
                import urllib.request

                url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
                urllib.request.urlretrieve(url, csv_path)
                logger.info("Downloaded airports.csv to %s", csv_path)
            except Exception as e:
                logger.warning(
                    "Could not download airports.csv: %s — airport lookups unavailable", e
                )
                return

        logger.info("Loading airports from %s ...", csv_path)
        rows = []
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for record in reader:
                    iata = (record.get("iata_code") or "").strip().upper()
                    if not iata or len(iata) != 3:
                        continue
                    rows.append(
                        (
                            iata,
                            (record.get("icao_code") or "").strip().upper() or None,
                            (record.get("name") or "").strip(),
                            (record.get("municipality") or "").strip() or None,
                            (record.get("iso_country") or "").strip() or None,
                            _float_or_none(record.get("latitude_deg")),
                            _float_or_none(record.get("longitude_deg")),
                        )
                    )
        except Exception as e:
            logger.error("Failed to read airports.csv: %s", e)
            return

        with db_write() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO airports "
                "(iata_code, icao_code, name, city_name, country_code, latitude, longitude) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        logger.info("Loaded %d airports", len(rows))
