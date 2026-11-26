"""EmailReviewRepository: the `email_candidates` and ignored-sender tables."""

import json
import re
import uuid

from ..database import db_conn, db_write
from ..utils import now_iso


def _domain(sender: str | None) -> str:
    m = re.search(r"@([\w.-]+)", sender or "")
    return m.group(1).lower() if m else ""


def _within(domain: str, ignored: str) -> bool:
    """The domain is the ignored one or a subdomain of it — never a mere suffix
    match: ignoring example.com covers mail.example.com, not example.com.au."""
    return domain == ignored or domain.endswith("." + ignored)


# Closing drops the email's text and the lines quoted from it in the hints:
# the contents are kept only while there is a decision to make.
_CLEAR_TEXT = "body_text = NULL, hints = json_remove(hints, '$.excerpt')"


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

    def pending_restatement(
        self, user_id: int, flight_numbers: list[str], reference: str | None, dates: list[str]
    ) -> bool:
        """Whether a pending email already offers this same booking.

        The same flight numbers alone are not enough — LH803 flies every day.
        Two booking codes that differ mean two bookings; with a code missing on
        either side, the dates the two mails print must overlap.
        """
        wanted = sorted(flight_numbers)
        for item in self.list_pending(user_id):
            hints = item["hints"]
            if sorted(hints.get("flight_numbers") or []) != wanted:
                continue
            theirs = item.get("booking_reference")
            if reference and theirs:
                if reference == theirs:
                    return True
                continue
            if set(dates) & set(hints.get("dates") or []):
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
                f"""UPDATE email_candidates
                       SET status = ?, {_CLEAR_TEXT}, updated_at = ?
                     WHERE id = ? AND user_id = ?""",
                (status, now_iso(), candidate_id, user_id),
            )

    def claim_for_import(self, user_id: int, candidate_id: str) -> bool:
        """Move a pending candidate to 'importing', atomically. False when it is
        not pending — already imported, dismissed, or claimed by a concurrent
        request — so flights are created at most once per email."""
        with db_write() as conn:
            cur = conn.execute(
                """UPDATE email_candidates SET status = 'importing', updated_at = ?
                    WHERE id = ? AND user_id = ? AND status = 'pending'""",
                (now_iso(), candidate_id, user_id),
            )
            return cur.rowcount == 1

    def release(self, user_id: int, candidate_id: str) -> None:
        """Give a claimed candidate back (the import failed)."""
        with db_write() as conn:
            conn.execute(
                """UPDATE email_candidates SET status = 'pending', updated_at = ?
                    WHERE id = ? AND user_id = ? AND status = 'importing'""",
                (now_iso(), candidate_id, user_id),
            )

    def close_pending_message(self, user_id: int, message_id: str) -> None:
        """A sync imported this email after all: take it off the list."""
        with db_write() as conn:
            conn.execute(
                f"""UPDATE email_candidates
                       SET status = 'imported', {_CLEAR_TEXT}, updated_at = ?
                     WHERE user_id = ? AND message_id = ? AND status = 'pending'""",
                (now_iso(), user_id, message_id),
            )

    def _ids_from_domain(self, conn, user_id: int, status: str, domain: str) -> list[str]:
        rows = conn.execute(
            "SELECT id, sender FROM email_candidates WHERE user_id = ? AND status = ?",
            (user_id, status),
        ).fetchall()
        return [r["id"] for r in rows if _within(_domain(r["sender"]), domain)]

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
            ids = self._ids_from_domain(conn, user_id, "pending", domain)
            conn.executemany(
                f"""UPDATE email_candidates
                       SET status = 'dismissed', {_CLEAR_TEXT}, updated_at = ?
                     WHERE id = ?""",
                [(now, i) for i in ids],
            )
            return len(ids)

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
            ids = self._ids_from_domain(conn, user_id, "dismissed", domain)
            conn.executemany("DELETE FROM email_candidates WHERE id = ?", [(i,) for i in ids])
            return cur.rowcount > 0

    def is_ignored(self, user_id: int, domain: str) -> bool:
        if not domain:
            return False
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT domain FROM email_review_ignored_senders WHERE user_id = ?", (user_id,)
            ).fetchall()
        return any(_within(domain, r["domain"]) for r in rows)

    def known_flight_numbers(self, user_id: int) -> set[str]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT flight_number FROM flights WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {(r["flight_number"] or "").replace(" ", "").upper() for r in rows}
