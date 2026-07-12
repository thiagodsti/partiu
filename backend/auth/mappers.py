"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import UserSummary
from .dto import MeResponseDTO, UserResponseDTO


def row_to_user_summary(row: sqlite3.Row) -> UserSummary:
    return UserSummary(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        smtp_recipient_address=row["smtp_recipient_address"],
        totp_enabled=bool(row["totp_enabled"]),
        locale=row["locale"] or "en",
    )


def user_summary_to_dto(user: UserSummary) -> UserResponseDTO:
    return UserResponseDTO(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        smtp_recipient_address=user.smtp_recipient_address,
        totp_enabled=user.totp_enabled,
        locale=user.locale,
    )


def user_summary_to_me_dto(user: UserSummary, announcement: str) -> MeResponseDTO:
    return MeResponseDTO(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        smtp_recipient_address=user.smtp_recipient_address,
        totp_enabled=user.totp_enabled,
        locale=user.locale,
        announcement=announcement,
    )
