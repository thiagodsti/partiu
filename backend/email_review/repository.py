"""EmailReviewRepository: the `email_candidates` and ignored-sender tables."""

import json
import uuid

from ..database import db_conn, db_write
from ..utils import now_iso


def _row_to_dict(row) -> dict:
    item = dict(row)
    item["hints"] = json.loads(item.get("hints") or "{}")
    return item


class EmailReviewRepository:
    def exists(self, user_id: int, message_id: str) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM email_candidates WHERE user_id = ? AND message_id = ?",
                (user_id, message_id),
            ).fetchone()
        return row is not None

    def pending_with_reference(self, user_id: int, reference: str) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM email_candidates
                   WHERE user_id = ? AND booking_reference = ? AND status = 'pending'""",
                (user_id, reference),
            ).fetchone()
        return row is not None

    def pending_with_flights(self, user_id: int, flight_numbers: list[str]) -> bool:
        """Whether a pending email already offers exactly these flight numbers."""
        wanted = sorted(flight_numbers)
        for item in self.list_pending(user_id):
            if sorted(item["hints"].get("flight_numbers") or []) == wanted:
                return True
        return False

    def create(self, user_id: int, values: dict) -> str:
        candidate_id = str(uuid.uuid4())
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO email_candidates
                   (id, user_id, message_id, sender, subject, email_date, body_text,
                    hints, booking_reference, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    candidate_id,
                    user_id,
                    values["message_id"],
                    values.get("sender"),
                    values.get("subject"),
                    values.get("email_date"),
                    values.get("body_text"),
                    json.dumps(values.get("hints") or {}),
                    values.get("booking_reference"),
                    now,
                    now,
                ),
            )
        return candidate_id

    def list_pending(self, user_id: int) -> list[dict]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT id, sender, subject, email_date, hints, booking_reference, created_at
                     FROM email_candidates
                    WHERE user_id = ? AND status = 'pending'
                    ORDER BY COALESCE(email_date, created_at) DESC""",
                (user_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count_pending(self, user_id: int) -> int:
        with db_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM email_candidates WHERE user_id = ? AND status = 'pending'",
                (user_id,),
            ).fetchone()[0]

    def get(self, user_id: int, candidate_id: str) -> dict | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM email_candidates WHERE id = ? AND user_id = ?",
                (candidate_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def close(self, user_id: int, candidate_id: str, status: str) -> None:
        """Mark it imported or dismissed, and drop the email's text with it."""
        with db_write() as conn:
            conn.execute(
                """UPDATE email_candidates
                      SET status = ?, body_text = NULL, updated_at = ?
                    WHERE id = ? AND user_id = ?""",
                (status, now_iso(), candidate_id, user_id),
            )

    def ignore_domain(self, user_id: int, domain: str) -> int:
        """Remember the sender's domain and dismiss its pending mail. Returns how
        many were dismissed."""
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO email_review_ignored_senders (user_id, domain, created_at)
                   VALUES (?, ?, ?)""",
                (user_id, domain, now),
            )
            cur = conn.execute(
                """UPDATE email_candidates
                      SET status = 'dismissed', body_text = NULL, updated_at = ?
                    WHERE user_id = ? AND status = 'pending'
                      AND LOWER(sender) LIKE ?""",
                (now, user_id, f"%@{domain}%"),
            )
            return cur.rowcount

    def list_ignored(self, user_id: int) -> list[dict]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT domain, created_at FROM email_review_ignored_senders
                   WHERE user_id = ? ORDER BY domain""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def unignore_domain(self, user_id: int, domain: str) -> bool:
        """Forget an ignored sender. Its dismissed mail is forgotten too, so a
        full sync — which re-reads the mailbox — can offer it again; the text
        was cleared on dismissal, so there is nothing to restore in place."""
        with db_write() as conn:
            cur = conn.execute(
                "DELETE FROM email_review_ignored_senders WHERE user_id = ? AND domain = ?",
                (user_id, domain),
            )
            conn.execute(
                """DELETE FROM email_candidates
                   WHERE user_id = ? AND status = 'dismissed' AND LOWER(sender) LIKE ?""",
                (user_id, f"%@{domain}%"),
            )
            return cur.rowcount > 0

    def is_ignored(self, user_id: int, domain: str) -> bool:
        if not domain:
            return False
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT domain FROM email_review_ignored_senders WHERE user_id = ?", (user_id,)
            ).fetchall()
        return any(domain == r["domain"] or domain.endswith("." + r["domain"]) for r in rows)

    def known_flight_numbers(self, user_id: int) -> set[str]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT flight_number FROM flights WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {(r["flight_number"] or "").replace(" ", "").upper() for r in rows}
