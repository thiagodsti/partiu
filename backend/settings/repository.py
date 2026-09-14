"""Repository for global settings, per-user setting columns, airport counts, and the
admin-managed non-flight sender domain blocklist."""

from ..database import db_conn, db_write, get_global_setting, set_global_setting


class SettingsRepository:
    def get_global_setting(self, key: str, default: str = "") -> str:
        return get_global_setting(key, default)

    def set_global_setting(self, key: str, value: str) -> None:
        set_global_setting(key, value)

    def has_smtp_conflict(self, recipient: str, exclude_user_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE lower(smtp_recipient_address) = lower(?) AND id != ?",
                (recipient, exclude_user_id),
            ).fetchone()
        return row is not None

    def update_user_settings(self, user_id: int, updates: dict) -> None:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id = ?", (*updates.values(), user_id)
            )

    def get_airport_count(self) -> int:
        from ..airports.repository import AirportRepository

        return AirportRepository().count()

    def get_ranked_airport_count(self) -> int:
        from ..airports.repository import AirportRepository

        return AirportRepository().count_ranked()

    def reload_airports(self) -> int:
        from ..airports.repository import AirportRepository

        with db_write() as conn:
            conn.execute("DELETE FROM airports")
        repo = AirportRepository()
        repo.load_from_csv_if_empty()
        return repo.count()

    def list_non_flight_domains(self) -> list[dict]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT domain, note, created_at FROM non_flight_domains ORDER BY domain"
            ).fetchall()
        return [dict(r) for r in rows]

    def add_non_flight_domain(self, domain: str, note: str = "") -> None:
        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO non_flight_domains (domain, note) VALUES (?, ?)",
                (domain, note),
            )

    def remove_non_flight_domain(self, domain: str) -> None:
        with db_write() as conn:
            conn.execute("DELETE FROM non_flight_domains WHERE domain = ?", (domain,))
