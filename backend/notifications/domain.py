"""Domain objects for the notifications feature.

These are what repositories return and services operate on — independent of both the SQL
row shape (see mappers.py) and the HTTP request/response shape (see dto.py).
"""

from dataclasses import dataclass


@dataclass
class Notification:
    id: int
    user_id: int
    type: str
    title: str
    body: str
    url: str
    read: bool
    created_at: str


@dataclass
class PushSubscription:
    endpoint: str
    p256dh: str
    auth: str


@dataclass
class VapidKeys:
    private_key: str
    public_key: str
    subject: str
    source: str  # "env" | "database" | "none"


@dataclass
class NotificationPreferences:
    flight_reminder: bool
    checkin_reminder: bool
    trip_reminder: bool
    delay_alert: bool
    boarding_pass: bool
    new_flight: bool
