"""Domain objects for trip sharing / invitations / trusted users."""

from dataclasses import dataclass


@dataclass
class ShareRecord:
    id: int
    status: str


@dataclass
class Invitation:
    id: int
    trip_id: str
    trip_name: str
    invited_by_username: str
    created_at: str


@dataclass
class TripShare:
    id: int
    user_id: int
    username: str
    status: str
    created_at: str


@dataclass
class TrustedUser:
    user_id: int
    username: str
    created_at: str
