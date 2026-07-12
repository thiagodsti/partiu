"""Conversions between SQL rows, domain objects and DTOs for trip sharing."""

import sqlite3

from .sharing_domain import Invitation, TripShare, TrustedUser
from .sharing_dto import InvitationDTO, TripShareDTO, TrustedUserDTO


def row_to_invitation(row: sqlite3.Row) -> Invitation:
    return Invitation(
        id=row["id"],
        trip_id=row["trip_id"],
        trip_name=row["trip_name"],
        invited_by_username=row["invited_by_username"],
        created_at=row["created_at"],
    )


def row_to_trip_share(row: sqlite3.Row) -> TripShare:
    return TripShare(
        id=row["id"],
        user_id=row["user_id"],
        username=row["username"],
        status=row["status"],
        created_at=row["created_at"],
    )


def row_to_trusted_user(row: sqlite3.Row) -> TrustedUser:
    return TrustedUser(
        user_id=row["user_id"],
        username=row["username"],
        created_at=row["created_at"],
    )


def invitation_to_dto(invitation: Invitation) -> InvitationDTO:
    return InvitationDTO(
        id=invitation.id,
        trip_id=invitation.trip_id,
        trip_name=invitation.trip_name,
        invited_by_username=invitation.invited_by_username,
        created_at=invitation.created_at,
    )


def trip_share_to_dto(share: TripShare) -> TripShareDTO:
    return TripShareDTO(
        id=share.id,
        user_id=share.user_id,
        username=share.username,
        status=share.status,
        created_at=share.created_at,
    )


def trusted_user_to_dto(trusted: TrustedUser) -> TrustedUserDTO:
    return TrustedUserDTO(
        user_id=trusted.user_id,
        username=trusted.username,
        created_at=trusted.created_at,
    )
