"""Request/response DTOs for the notifications HTTP API (routes/notifications.py).

Routes only ever see these shapes — never raw dict bodies or domain objects.
"""

from pydantic import BaseModel, field_validator


class PushSubscriptionKeysDTO(BaseModel):
    p256dh: str = ""
    auth: str = ""


class PushSubscriptionDTO(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeysDTO = PushSubscriptionKeysDTO()

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_not_be_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("endpoint must not be blank")
        return v


class SubscribeRequestDTO(BaseModel):
    subscription: PushSubscriptionDTO


class UnsubscribeRequestDTO(BaseModel):
    endpoint: str

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_not_be_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("endpoint must not be blank")
        return v


class NotificationDTO(BaseModel):
    id: int
    type: str
    title: str
    body: str
    url: str
    read: bool
    created_at: str


class PreferencesDTO(BaseModel):
    flight_reminder: bool
    checkin_reminder: bool
    trip_reminder: bool
    delay_alert: bool
    boarding_pass: bool
    new_flight: bool


class PreferencesUpdateDTO(BaseModel):
    flight_reminder: bool | None = None
    checkin_reminder: bool | None = None
    trip_reminder: bool | None = None
    delay_alert: bool | None = None
    boarding_pass: bool | None = None
    new_flight: bool | None = None


class VapidStatusDTO(BaseModel):
    configured: bool
    source: str
    public_key: str | None


class VapidPublicKeyDTO(BaseModel):
    public_key: str


class VapidGenerateDTO(BaseModel):
    ok: bool
    public_key: str
    source: str


class OkDTO(BaseModel):
    ok: bool


class UnreadCountDTO(BaseModel):
    unread: int


class MarkedCountDTO(BaseModel):
    ok: bool
    marked: int


class TestPushResultDTO(BaseModel):
    ok: bool
    sent: int
