"""
User management routes (admin only).
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import refuse_on_demo, require_admin
from . import user_service
from .dto import (
    CreateUserRequestDTO,
    CreateUserResponseDTO,
    OkDTO,
    UpdateUserRequestDTO,
    UserDTO,
)
from .errors import SelfDeleteError, UserNotFoundError, ValidationError
from .mappers import created_user_to_dto, user_to_dto

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserDTO])
def list_users(admin: dict = Depends(require_admin)):
    return [user_to_dto(u) for u in user_service.list_users()]


@router.post("", response_model=CreateUserResponseDTO)
def create_user(body: CreateUserRequestDTO, admin: dict = Depends(require_admin)):
    refuse_on_demo("Creating users")
    try:
        created = user_service.create_user(
            admin["id"], body.username, body.password, body.is_admin, body.smtp_recipient_address
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return created_user_to_dto(created)


@router.patch("/{user_id}", response_model=OkDTO)
def update_user(user_id: int, body: UpdateUserRequestDTO, admin: dict = Depends(require_admin)):
    # Editing an account is the same one-way door as creating or deleting one:
    # this route can reset a password and grant or revoke admin.
    refuse_on_demo("Editing users")
    try:
        user_service.update_user(
            admin["id"], user_id, body.is_admin, body.smtp_recipient_address, body.new_password
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OkDTO(ok=True)


@router.delete("/{user_id}", response_model=OkDTO)
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    refuse_on_demo("Deleting users")
    try:
        user_service.delete_user(admin["id"], user_id)
    except SelfDeleteError:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    return OkDTO(ok=True)
