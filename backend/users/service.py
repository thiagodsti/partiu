"""Use cases for admin user management: validation + audit logging."""

from .domain import CreatedUser, User
from .errors import SelfDeleteError, UserNotFoundError, ValidationError
from .repository import UserRepository


class UserService:
    def __init__(self, repository: UserRepository | None = None):
        self._repository = repository or UserRepository()

    def list_users(self) -> list[User]:
        return self._repository.list_users()

    def create_user(
        self,
        admin_id: int,
        username: str,
        password: str,
        is_admin: bool,
        smtp_recipient_address: str | None,
    ) -> CreatedUser:
        from ..auth import hash_password
        from ..auth.audit_log import audit

        normalized = username.strip().lower()
        if len(normalized) < 4:
            raise ValidationError("Username must be at least 4 characters")
        if len(password) < 8:
            raise ValidationError("Password must be at least 8 characters")

        try:
            user_id = self._repository.create_user(
                normalized, hash_password(password), is_admin, smtp_recipient_address
            )
        except Exception as e:
            raise ValidationError("Could not create user") from e

        audit(
            "user_created",
            user_id=admin_id,
            target_user_id=user_id,
            username=normalized,
            is_admin=is_admin,
        )
        return CreatedUser(
            id=user_id,
            username=normalized,
            is_admin=is_admin,
            smtp_recipient_address=smtp_recipient_address,
        )

    def update_user(
        self,
        admin_id: int,
        user_id: int,
        is_admin: bool | None,
        smtp_recipient_address: str | None,
        new_password: str | None,
    ) -> None:
        from ..auth import hash_password
        from ..auth.audit_log import audit

        if not self._repository.exists(user_id):
            raise UserNotFoundError(user_id)

        updates: dict = {}
        if is_admin is not None:
            updates["is_admin"] = 1 if is_admin else 0
        if smtp_recipient_address is not None:
            updates["smtp_recipient_address"] = smtp_recipient_address
        if new_password is not None:
            if len(new_password) < 8:
                raise ValidationError("Password must be at least 8 characters")
            updates["password_hash"] = hash_password(new_password)

        if updates:
            self._repository.update_user(user_id, updates)

        audit("user_updated", user_id=admin_id, target_user_id=user_id, fields=list(updates.keys()))

    def delete_user(self, admin_id: int, user_id: int) -> None:
        from ..auth.audit_log import audit

        if user_id == admin_id:
            raise SelfDeleteError()

        self._repository.delete_user(user_id)
        audit("user_deleted", user_id=admin_id, target_user_id=user_id)


user_service = UserService()
