"""
API keys routes. Reachable only with a signed-in session — see
``service._is_session_only`` for why a key can never manage keys.

  GET    /api/api-keys          — the caller's keys (never their values)
  POST   /api/api-keys          — mint one; the response is the only time its value is shown
  DELETE /api/api-keys/{key_id} — revoke one
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user, refuse_on_demo
from ..auth.audit_log import audit
from .dto import ApiKeyDTO, CreateApiKeyDTO, CreatedApiKeyDTO
from .mappers import created_key_to_dto, key_to_dto
from .service import MAX_KEYS_PER_USER, ApiKeyLimitError, ApiKeyNotFoundError, api_key_service

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyDTO])
def list_keys(user: dict = Depends(get_current_user)):
    return [key_to_dto(k) for k in api_key_service.list_keys(user["id"])]


@router.post("", status_code=201, response_model=CreatedApiKeyDTO)
def create_key(body: CreateApiKeyDTO, user: dict = Depends(get_current_user)):
    # Everyone signed in to a demo is the same account; a key minted there would
    # outlive the visitor who made it and hand the next one a working credential.
    refuse_on_demo("Creating API keys")
    try:
        key, secret = api_key_service.create_key(
            user["id"], body.name, body.scope, body.expires_in_days
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ApiKeyLimitError:
        raise HTTPException(
            status_code=409, detail=f"You can hold at most {MAX_KEYS_PER_USER} API keys"
        )
    audit("api_key_created", user["id"], key_id=key.id, name=key.name, scope=key.scope)
    return created_key_to_dto(key, secret)


@router.delete("/{key_id}", status_code=204)
def revoke_key(key_id: int, user: dict = Depends(get_current_user)):
    try:
        api_key_service.revoke_key(key_id, user["id"])
    except ApiKeyNotFoundError:
        raise HTTPException(status_code=404, detail="API key not found")
    audit("api_key_revoked", user["id"], key_id=key_id)
    return None
