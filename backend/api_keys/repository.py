"""Repository for the `api_keys` table. Stores hashes only — never a key's value."""

from ..database import db_conn, db_write
from .domain import ApiKey
from .mappers import row_to_key

_COLUMNS = "id, user_id, name, prefix, scope, created_at, last_used_at, expires_at"


class ApiKeyRepository:
    def list_for_user(self, user_id: int) -> list[ApiKey]:
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM api_keys WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        return [row_to_key(r) for r in rows]

    def count_for_user(self, user_id: int) -> int:
        with db_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM api_keys WHERE user_id = ?", (user_id,)
            ).fetchone()[0]

    def find_by_hash(self, key_hash: str) -> ApiKey | None:
        with db_conn() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM api_keys WHERE key_hash = ?", (key_hash,)
            ).fetchone()
        return row_to_key(row) if row else None

    def create(
        self,
        user_id: int,
        name: str,
        prefix: str,
        key_hash: str,
        scope: str,
        created_at: str,
        expires_at: str | None,
    ) -> ApiKey:
        with db_write() as conn:
            cursor = conn.execute(
                """INSERT INTO api_keys (user_id, name, prefix, key_hash, scope, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, name, prefix, key_hash, scope, created_at, expires_at),
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM api_keys WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return row_to_key(row)

    def delete(self, key_id: int, user_id: int) -> bool:
        with db_write() as conn:
            cursor = conn.execute(
                "DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id)
            )
        return cursor.rowcount > 0

    def touch(self, key_id: int, used_at: str) -> None:
        with db_write() as conn:
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (used_at, key_id))
