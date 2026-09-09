"""Repository for the `airports` reference-data table, plus the CSV bulk loader
that seeds it on first run."""

import logging

from ..database import (
    db_conn,
    db_write,
    get_db_path,
    get_global_setting,
    set_global_setting,
)
from ..utils import fold_text

logger = logging.getLogger(__name__)

# Marks the one-time ranking/folding backfill as done (see backfill_rank_columns).
_RANK_BACKFILL_FLAG = "airport_rank_backfill_done"


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

    def backfill_rank_columns(self) -> int:
        """Populate `type` / `scheduled_service` / folded search columns on databases
        seeded before those columns existed. No-op once done. Returns rows updated.

        Completion is recorded as a flag rather than inferred from the data: a
        handful of stored airports are absent from the current reference CSV
        (upstream retires codes), so their `type` stays NULL forever and a
        data-driven check would re-read a 12 MB file on every startup. The flag
        is only set when the CSV-based pass actually ran, so an instance that was
        offline at upgrade time still retries on its next start.
        """
        if get_global_setting(_RANK_BACKFILL_FLAG) == "1":
            return 0

        with db_conn() as conn:
            missing = conn.execute(
                "SELECT COUNT(*) FROM airports WHERE type IS NULL OR name_folded IS NULL"
            ).fetchone()[0]
        if not missing:
            set_global_setting(_RANK_BACKFILL_FLAG, "1")
            return 0

        # An upgraded instance usually has a populated table but no CSV, since
        # the data directory is a volume — fetch it rather than silently
        # shipping without the ranking data name resolution depends on.
        records = self._read_csv_records() if self._ensure_csv() else []
        if not records:
            # Offline or the download failed. Folding is derivable from what is
            # already stored, so do that much: accent-insensitive search keeps
            # working and the next startup retries the ranking columns.
            logger.warning(
                "Ranking data unavailable — falling back to folded columns only. "
                "Airport name resolution will not rank by airport size."
            )
            with db_conn() as conn:
                rows = conn.execute("SELECT iata_code, name, city_name FROM airports").fetchall()
            updates = [
                (fold_text(r["name"]), fold_text(r["city_name"]), r["iata_code"]) for r in rows
            ]
            with db_write() as conn:
                conn.executemany(
                    "UPDATE airports SET name_folded = ?, city_folded = ? WHERE iata_code = ?",
                    updates,
                )
            return len(updates)

        updates = [
            (
                r["type"],
                r["scheduled_service"],
                fold_text(r["name"]),
                fold_text(r["city"]),
                r["iata"],
            )
            for r in records
        ]
        with db_write() as conn:
            conn.executemany(
                "UPDATE airports SET type = ?, scheduled_service = ?, "
                "name_folded = ?, city_folded = ? WHERE iata_code = ?",
                updates,
            )
        logger.info("Backfilled ranking data for %d airports", len(updates))
        self.seed_aliases_from_keywords(records)
        set_global_setting(_RANK_BACKFILL_FLAG, "1")
        return len(updates)

    def seed_aliases_from_keywords(self, records: list[dict] | None = None) -> int:
        """Seed `airport_aliases` from the CSV's `keywords` column.

        OurAirports records alternative and English names there ("Göteborg
        Landvetter" carries the keyword "Gothenburg"), which is the only way a
        name search can bridge exonyms. Curated aliases already in the table win:
        keywords are inserted with OR IGNORE, largest scheduled airports first,
        so an ambiguous name lands on the airport a traveller is likeliest to mean.
        """
        if records is None:
            records = self._read_csv_records()
        if not records:
            return 0

        rank = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
        ordered = sorted(
            (r for r in records if r["scheduled_service"] and r["keywords"]),
            key=lambda r: rank.get(r["type"] or "", 3),
        )

        pairs: list[tuple[str, str]] = []
        for record in ordered:
            for keyword in record["keywords"].split(","):
                alias = fold_text(keyword).strip()
                # Skip URLs, codes and anything too short to be a place name
                if len(alias) < 4 or "/" in alias or ":" in alias:
                    continue
                pairs.append((alias, record["iata"]))

        with db_write() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO airport_aliases (alias, iata_code) VALUES (?, ?)",
                pairs,
            )
        logger.info("Seeded %d airport keyword aliases", len(pairs))
        return len(pairs)

    def _ensure_csv(self) -> bool:
        """Make sure data/airports.csv exists, downloading it if not.

        The data directory is a mounted volume rather than part of the image, so
        a deployed instance can easily have a populated `airports` table but no
        CSV alongside it. Both the initial load and the ranking backfill need the
        file, so fetching it is handled in one place.

        Returns True when the file is available.
        """
        from pathlib import Path

        csv_path = Path(get_db_path()).parent / "airports.csv"
        if csv_path.exists():
            return True

        logger.info("airports.csv not found — downloading from ourairports.com ...")
        try:
            import urllib.request

            url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
            urllib.request.urlretrieve(url, csv_path)
            logger.info("Downloaded airports.csv to %s", csv_path)
            return True
        except Exception as e:
            logger.warning("Could not download airports.csv: %s", e)
            return False

    def _read_csv_records(self) -> list[dict]:
        """Read data/airports.csv into normalised dicts. Returns [] when unavailable."""
        import csv
        from pathlib import Path

        csv_path = Path(get_db_path()).parent / "airports.csv"
        if not csv_path.exists():
            logger.warning("airports.csv not found at %s", csv_path)
            return []

        records: list[dict] = []
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                for record in csv.DictReader(f):
                    iata = (record.get("iata_code") or "").strip().upper()
                    if not iata or len(iata) != 3:
                        continue
                    records.append(
                        {
                            "iata": iata,
                            "icao": (record.get("icao_code") or "").strip().upper() or None,
                            "name": (record.get("name") or "").strip(),
                            "city": (record.get("municipality") or "").strip() or None,
                            "country": (record.get("iso_country") or "").strip() or None,
                            "lat": _float_or_none(record.get("latitude_deg")),
                            "lon": _float_or_none(record.get("longitude_deg")),
                            "type": (record.get("type") or "").strip() or None,
                            "scheduled_service": 1
                            if (record.get("scheduled_service") or "").strip() == "yes"
                            else 0,
                            "keywords": (record.get("keywords") or "").strip(),
                        }
                    )
        except Exception as e:
            logger.error("Failed to read airports.csv: %s", e)
            return []
        return records

    def load_from_csv_if_empty(self) -> None:
        """
        Load airports from data/airports.csv if the airports table is empty.
        The CSV should be downloaded from https://ourairports.com/data/airports.csv
        and placed in the data/ directory.
        """
        from pathlib import Path

        existing = self.count()
        if existing > 0:
            logger.debug("Airports table already populated (%d rows)", existing)
            return

        csv_path = Path(get_db_path()).parent / "airports.csv"
        if not self._ensure_csv():
            logger.warning("airports.csv unavailable — airport lookups unavailable")
            return

        logger.info("Loading airports from %s ...", csv_path)
        records = self._read_csv_records()
        if not records:
            return

        rows = [
            (
                r["iata"],
                r["icao"],
                r["name"],
                r["city"],
                r["country"],
                r["lat"],
                r["lon"],
                r["type"],
                r["scheduled_service"],
                fold_text(r["name"]),
                fold_text(r["city"]),
            )
            for r in records
        ]
        with db_write() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO airports "
                "(iata_code, icao_code, name, city_name, country_code, latitude, longitude, "
                "type, scheduled_service, name_folded, city_folded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        logger.info("Loaded %d airports", len(rows))
        self.seed_aliases_from_keywords(records)
