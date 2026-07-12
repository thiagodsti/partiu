"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import CreatedUser, User
from .dto import CreateUserResponseDTO, UserDTO


def row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        smtp_recipient_address=row["smtp_recipient_address"],
        totp_enabled=bool(row["totp_enabled"]),
        created_at=row["created_at"],
    )


def user_to_dto(user: User) -> UserDTO:
    return UserDTO(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        smtp_recipient_address=user.smtp_recipient_address,
        totp_enabled=user.totp_enabled,
        created_at=user.created_at,
    )


def created_user_to_dto(user: CreatedUser) -> CreateUserResponseDTO:
    return CreateUserResponseDTO(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        smtp_recipient_address=user.smtp_recipient_address,
    )
