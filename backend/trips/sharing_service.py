"""Use cases for trip sharing, invitations, and trusted users."""

import logging

from ..users.repository import UserRepository
from .repository import TripRepository
from .sharing_domain import Invitation, TripShare, TrustedUser
from .sharing_errors import (
    AlreadySharedError,
    InvitationNotFoundError,
    SelfShareError,
    SelfTrustError,
    SharedTripNotFoundError,
    TripAccessError,
    TrustedUserError,
    UserNotFoundError,
)
from .sharing_repository import ShareRepository

logger = logging.getLogger(__name__)


class ShareService:
    def __init__(
        self,
        repository: ShareRepository | None = None,
        user_repository: UserRepository | None = None,
        trip_repository: TripRepository | None = None,
    ):
        self._repository = repository or ShareRepository()
        self._user_repository = user_repository or UserRepository()
        self._trip_repository = trip_repository or TripRepository()

    # -- Sharing / invitations -----------------------------------------------

    def share_trip(
        self, trip_id: str, inviter_id: int, inviter_username: str, invitee_username: str
    ) -> dict:
        self._check_trip_owner(trip_id, inviter_id)

        invitee = self._user_repository.find_by_username(invitee_username)
        if invitee is None:
            raise UserNotFoundError(invitee_username)
        if invitee.id == inviter_id:
            raise SelfShareError()

        existing = self._repository.get_share(trip_id, invitee.id)
        if existing is not None:
            if existing.status == "accepted":
                raise AlreadySharedError()
            # Re-invite: reset to pending
            self._repository.reinvite(existing.id, inviter_id)
            return {"ok": True}

        trusted = self._repository.invitee_trusts_inviter(invitee.id, inviter_id)
        initial_status = "accepted" if trusted else "pending"

        self._repository.create_share(trip_id, invitee.id, inviter_id, initial_status)
        trip = self._trip_repository.get_by_id(trip_id)
        trip_label = (trip.name if trip else None) or trip_id

        if initial_status == "pending":
            self._notify_invitee(invitee.id, inviter_username, trip_label)

        return {"ok": True, "status": initial_status}

    def list_invitations(self, user_id: int) -> list[Invitation]:
        return self._repository.list_invitations_for_user(user_id)

    def accept_invitation(self, share_id: int, user_id: int) -> None:
        if self._repository.find_pending_invitation(share_id, user_id) is None:
            raise InvitationNotFoundError(share_id)
        self._repository.update_invitation_status(share_id, "accepted")

    def reject_invitation(self, share_id: int, user_id: int) -> None:
        if self._repository.find_pending_invitation(share_id, user_id) is None:
            raise InvitationNotFoundError(share_id)
        self._repository.update_invitation_status(share_id, "rejected")

    # -- List / revoke shares on a trip (owner only) --------------------------

    def list_trip_shares(self, trip_id: str, user_id: int) -> list[TripShare]:
        self._check_trip_owner(trip_id, user_id)
        return self._repository.list_shares_for_trip(trip_id)

    def revoke_trip_share(self, trip_id: str, shared_user_id: int, user_id: int) -> None:
        self._check_trip_owner(trip_id, user_id)
        self._repository.delete_share(trip_id, shared_user_id)

    # -- Leave a shared trip (collaborator removes themselves) ----------------

    def leave_trip(self, trip_id: str, user_id: int) -> None:
        if not self._repository.find_active_share(trip_id, user_id):
            raise SharedTripNotFoundError(trip_id)
        self._repository.delete_share(trip_id, user_id)

    # -- Trusted users ---------------------------------------------------------

    def list_trusted_users(self, owner_id: int) -> list[TrustedUser]:
        return self._repository.list_trusted_users(owner_id)

    def add_trusted_user(self, owner_id: int, username: str) -> None:
        target = self._user_repository.find_by_username(username)
        if target is None:
            raise UserNotFoundError(username)
        if target.id == owner_id:
            raise SelfTrustError()

        try:
            self._repository.add_trusted_user(owner_id, target.id)
        except Exception as e:
            raise TrustedUserError(str(e)) from e

    def remove_trusted_user(self, owner_id: int, trusted_user_id: int) -> None:
        self._repository.remove_trusted_user(owner_id, trusted_user_id)

    # -- Helpers ---------------------------------------------------------------

    def _notify_invitee(self, invitee_id: int, inviter_username: str, trip_label: str) -> None:
        try:
            from ..notifications import notification_service

            notification_service.create_notification(
                invitee_id,
                "invitation",
                f"{inviter_username} invited you to a trip",
                trip_label,
                "/#/notifications",
            )
        except Exception:
            logger.exception("Failed to create invitation notification")

    def _check_trip_owner(self, trip_id: str, user_id: int) -> None:
        from ..auth import is_trip_owner
        from ..database import db_conn

        with db_conn() as conn:
            allowed = is_trip_owner(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


share_service = ShareService()
