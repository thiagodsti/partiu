"""Repository for the `trip_shares` and `trusted_users` tables.

Trip-ownership authorization (see ..auth.access) is handled by the service
layer — this repository only knows how to read/write rows. User and trip
lookups are NOT duplicated here — SharingService calls UserRepository/
TripRepository directly for those.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .sharing_domain import Invitation, ShareRecord, TripShare, TrustedUser
from .sharing_mappers import row_to_invitation, row_to_trip_share, row_to_trusted_user


class ShareRepository:
    # -- Sharing / invitations -----------------------------------------------

    def get_share(self, trip_id: str, user_id: int) -> ShareRecord | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, status FROM trip_shares WHERE trip_id = ? AND user_id = ?",
                (trip_id, user_id),
            ).fetchone()
        return ShareRecord(id=row["id"], status=row["status"]) if row else None

    def invitee_trusts_inviter(self, invitee_id: int, inviter_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM trusted_users WHERE owner_id = ? AND trusted_user_id = ?",
                (invitee_id, inviter_id),
            ).fetchone()
        return row is not None

    def create_share(self, trip_id: str, invitee_id: int, inviter_id: int, status: str) -> None:
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_shares (trip_id, user_id, invited_by, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (trip_id, invitee_id, inviter_id, status, now_iso(), now_iso()),
            )

    def reinvite(self, share_id: int, inviter_id: int) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE trip_shares SET status = 'pending', invited_by = ?, updated_at = ? WHERE id = ?",
                (inviter_id, now_iso(), share_id),
            )

    def list_invitations_for_user(self, user_id: int) -> list[Invitation]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT ts.id, ts.trip_id, t.name AS trip_name,
                          u.username AS invited_by_username, ts.created_at
                   FROM trip_shares ts
                   JOIN trips t ON t.id = ts.trip_id
                   JOIN users u ON u.id = ts.invited_by
                   WHERE ts.user_id = ? AND ts.status = 'pending'
                   ORDER BY ts.created_at DESC""",
                (user_id,),
            ).fetchall()
        return [row_to_invitation(r) for r in rows]

    def find_pending_invitation(self, share_id: int, user_id: int) -> int | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id FROM trip_shares WHERE id = ? AND user_id = ? AND status = 'pending'",
                (share_id, user_id),
            ).fetchone()
        return row["id"] if row else None

    def update_invitation_status(self, share_id: int, status: str) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE trip_shares SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), share_id),
            )

    def list_shares_for_trip(self, trip_id: str) -> list[TripShare]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT ts.id, ts.user_id, u.username, ts.status, ts.created_at
                   FROM trip_shares ts
                   JOIN users u ON u.id = ts.user_id
                   WHERE ts.trip_id = ? AND ts.status IN ('pending', 'accepted')
                   ORDER BY ts.created_at ASC""",
                (trip_id,),
            ).fetchall()
        return [row_to_trip_share(r) for r in rows]

    def delete_share(self, trip_id: str, user_id: int) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_shares WHERE trip_id = ? AND user_id = ?",
                (trip_id, user_id),
            )

    def find_active_share(self, trip_id: str, user_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id FROM trip_shares WHERE trip_id = ? AND user_id = ? AND status IN ('pending', 'accepted')",
                (trip_id, user_id),
            ).fetchone()
        return row is not None

    # -- Trusted users --------------------------------------------------------

    def list_trusted_users(self, owner_id: int) -> list[TrustedUser]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT u.id AS user_id, u.username, tu.created_at
                   FROM trusted_users tu
                   JOIN users u ON u.id = tu.trusted_user_id
                   WHERE tu.owner_id = ?
                   ORDER BY tu.created_at ASC""",
                (owner_id,),
            ).fetchall()
        return [row_to_trusted_user(r) for r in rows]

    def add_trusted_user(self, owner_id: int, trusted_user_id: int) -> None:
        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO trusted_users (owner_id, trusted_user_id, created_at) VALUES (?, ?, ?)",
                (owner_id, trusted_user_id, now_iso()),
            )

    def remove_trusted_user(self, owner_id: int, trusted_user_id: int) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trusted_users WHERE owner_id = ? AND trusted_user_id = ?",
                (owner_id, trusted_user_id),
            )
