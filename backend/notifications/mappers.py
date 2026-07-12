"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import Notification, NotificationPreferences, PushSubscription
from .dto import NotificationDTO, PreferencesDTO


def row_to_notification(row: sqlite3.Row) -> Notification:
    return Notification(
        id=row["id"],
        user_id=row["user_id"],
        type=row["type"],
        title=row["title"],
        body=row["body"],
        url=row["url"],
        read=bool(row["read"]),
        created_at=row["created_at"],
    )


def row_to_push_subscription(row: sqlite3.Row) -> PushSubscription:
    return PushSubscription(endpoint=row["endpoint"], p256dh=row["p256dh"], auth=row["auth"])


def notification_to_dto(notification: Notification) -> NotificationDTO:
    return NotificationDTO(
        id=notification.id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        url=notification.url,
        read=notification.read,
        created_at=notification.created_at,
    )


def user_to_preferences(user: dict) -> NotificationPreferences:
    """Build preferences straight from an already-loaded user row/dict.

    Avoids a redundant DB query — callers (e.g. the auth dependency) already loaded
    the user's notif_* columns.
    """
    return NotificationPreferences(
        flight_reminder=bool(user.get("notif_flight_reminder", 1)),
        checkin_reminder=bool(user.get("notif_checkin_reminder", 1)),
        trip_reminder=bool(user.get("notif_trip_reminder", 1)),
        delay_alert=bool(user.get("notif_delay_alert", 1)),
        boarding_pass=bool(user.get("notif_boarding_pass", 1)),
        new_flight=bool(user.get("notif_new_flight", 1)),
    )


def preferences_to_dto(preferences: NotificationPreferences) -> PreferencesDTO:
    return PreferencesDTO(
        flight_reminder=preferences.flight_reminder,
        checkin_reminder=preferences.checkin_reminder,
        trip_reminder=preferences.trip_reminder,
        delay_alert=preferences.delay_alert,
        boarding_pass=preferences.boarding_pass,
        new_flight=preferences.new_flight,
    )
