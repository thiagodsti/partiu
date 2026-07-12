"""
Trip sharing and trusted users API routes.

  POST   /api/trips/{trip_id}/share              — invite a user to a trip
  GET    /api/trips/invitations                  — list pending invitations for current user
  POST   /api/trips/invitations/{share_id}/accept
  POST   /api/trips/invitations/{share_id}/reject
  DELETE /api/trips/{trip_id}/shares/{shared_user_id}
  GET    /api/trips/{trip_id}/shares             — list accepted shares for a trip
  GET    /api/settings/trusted-users
  POST   /api/settings/trusted-users
  DELETE /api/settings/trusted-users/{trusted_user_id}
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from . import share_service
from .sharing_dto import (
    InvitationDTO,
    OkDTO,
    ShareInviteDTO,
    TripShareDTO,
    TrustedUserDTO,
    TrustedUserRequestDTO,
)
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
from .sharing_mappers import invitation_to_dto, trip_share_to_dto, trusted_user_to_dto

# Use no prefix — routes are declared with full paths to avoid conflicts
# with the trips router's prefix (/api/trips).
router = APIRouter(tags=["shares"])


# ---------------------------------------------------------------------------
# Invite a user to a trip
# ---------------------------------------------------------------------------


@router.post("/api/trips/{trip_id}/share", status_code=201)
def share_trip(trip_id: str, body: ShareInviteDTO, user: dict = Depends(get_current_user)):
    try:
        return share_service.share_trip(trip_id, user["id"], user["username"], body.username)
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except SelfShareError:
        raise HTTPException(status_code=400, detail="Cannot share a trip with yourself")
    except AlreadySharedError:
        raise HTTPException(status_code=400, detail="User already has access")


# ---------------------------------------------------------------------------
# List pending invitations for current user
# IMPORTANT: this literal route must be declared BEFORE /{trip_id}/... routes
# ---------------------------------------------------------------------------


@router.get("/api/trips/invitations", response_model=list[InvitationDTO])
def list_invitations(user: dict = Depends(get_current_user)):
    return [invitation_to_dto(i) for i in share_service.list_invitations(user["id"])]


@router.post("/api/trips/invitations/{share_id}/accept", response_model=OkDTO)
def accept_invitation(share_id: int, user: dict = Depends(get_current_user)):
    try:
        share_service.accept_invitation(share_id, user["id"])
    except InvitationNotFoundError:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return OkDTO(ok=True)


@router.post("/api/trips/invitations/{share_id}/reject", response_model=OkDTO)
def reject_invitation(share_id: int, user: dict = Depends(get_current_user)):
    try:
        share_service.reject_invitation(share_id, user["id"])
    except InvitationNotFoundError:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return OkDTO(ok=True)


# ---------------------------------------------------------------------------
# List / revoke shares on a trip (owner only)
# ---------------------------------------------------------------------------


@router.get("/api/trips/{trip_id}/shares", response_model=list[TripShareDTO])
def list_trip_shares(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        shares = share_service.list_trip_shares(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [trip_share_to_dto(s) for s in shares]


@router.delete("/api/trips/{trip_id}/shares/{shared_user_id}", status_code=204)
def revoke_trip_share(trip_id: str, shared_user_id: int, user: dict = Depends(get_current_user)):
    try:
        share_service.revoke_trip_share(trip_id, shared_user_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return None


# ---------------------------------------------------------------------------
# Leave a shared trip (collaborator removes themselves)
# ---------------------------------------------------------------------------


@router.delete("/api/trips/{trip_id}/leave", status_code=204)
def leave_trip(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        share_service.leave_trip(trip_id, user["id"])
    except SharedTripNotFoundError:
        raise HTTPException(status_code=404, detail="Shared trip not found")
    return None


# ---------------------------------------------------------------------------
# Trusted users
# ---------------------------------------------------------------------------


@router.get("/api/settings/trusted-users", response_model=list[TrustedUserDTO])
def list_trusted_users(user: dict = Depends(get_current_user)):
    return [trusted_user_to_dto(t) for t in share_service.list_trusted_users(user["id"])]


@router.post("/api/settings/trusted-users", status_code=201, response_model=OkDTO)
def add_trusted_user(body: TrustedUserRequestDTO, user: dict = Depends(get_current_user)):
    try:
        share_service.add_trusted_user(user["id"], body.username)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except SelfTrustError:
        raise HTTPException(status_code=400, detail="Cannot trust yourself")
    except TrustedUserError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OkDTO(ok=True)


@router.delete("/api/settings/trusted-users/{trusted_user_id}", status_code=204)
def remove_trusted_user(trusted_user_id: int, user: dict = Depends(get_current_user)):
    share_service.remove_trusted_user(user["id"], trusted_user_id)
    return None
