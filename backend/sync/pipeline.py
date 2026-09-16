"""
Email sync pipeline — fetches airline confirmation emails from Gmail,
parses them with the engine, and stores flights in SQLite.
Runs every 10 minutes via APScheduler.
"""

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from ..airports.timezone import apply_airport_timezones
from ..database import get_global_setting
from ..flights.repository import FlightRepository
from ..parsers.bcbp import find_bcbp_in_text, parse_bcbp
from ..parsers.boarding_pass_extractor import extract_boarding_pass_images, is_checkin_email
from ..parsers.builtin_rules import get_builtin_rules
from ..parsers.email_connector import ImapFetchResult, fetch_emails_imap
from ..parsers.engine import (
    extract_flights_from_email,
    match_rule_to_email,
    merge_flights,
)
from ..parsers.gds_eticket import extract_gds_eticket
from ..parsers.validation import validate_flights
from ..settings.repository import SettingsRepository
from ..utils import calc_duration_minutes, calc_flight_status, dt_to_iso, now_iso
from .car_rentals_import import import_car_rentals_from_email
from .grouping import auto_group_flights
from .repository import SyncRepository
from .stays_import import import_lodging_from_email

logger = logging.getLogger(__name__)

_flight_repository = FlightRepository()
_settings_repository = SettingsRepository()
_sync_repository = SyncRepository()

# Hardcoded sender domains that never contain flight bookings (admin can add more
# via Settings — see SettingsRepository.list_non_flight_domains).
# Subdomains are also matched (e.g. "property.booking.com" matches "booking.com").
_NON_FLIGHT_DOMAINS: frozenset[str] = frozenset(
    [
        # Accommodation
        "airbnb.com",
        "booking.com",
        "property.booking.com",
        "reservation.accor-mail.com",
        # Car rental
        "emails.hertz.com",
        "europcar.com",
        "sixt.com",
        # Restaurants & events
        "bookatable.com",
        "caspeco.net",
        "boxoffice.axs.nu",
        "ticketmaster.se",
        "bookatable.co.uk",
        # Business / consulting
        "alphasights.com",
        # Tech / SaaS
        "pipdecks.com",
        "aws-experience.com",
        # Government / public services
        "migrationsverket.se",
        "ventus.com",
        # Retail
        "medlem.kjell.com",
        # Travel aggregators that send non-booking emails
        "tripit.com",
        # Schools
        "folkuniversitetet.se",
    ]
)


def _sender_domain(sender: str) -> str:
    m = re.search(r"@([\w.-]+)", sender or "")
    return m.group(1).lower() if m else ""


def _domain_matches(domain: str, blocked: str) -> bool:
    return domain == blocked or domain.endswith("." + blocked)


def is_non_flight_domain(sender: str) -> bool:
    """Return True if the sender domain is known to never send flight bookings."""
    domain = _sender_domain(sender)
    if not domain:
        return False

    if any(_domain_matches(domain, d) for d in _NON_FLIGHT_DOMAINS):
        return True

    try:
        rows = _settings_repository.list_non_flight_domains()
        return any(_domain_matches(domain, row["domain"]) for row in rows)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sync state helpers
# ---------------------------------------------------------------------------


def _set_sync_status(user_id: int, status: str, error: str = ""):
    _sync_repository.upsert_state(user_id, status=status, last_error=error)


def _set_sync_complete(user_id: int, last_synced_at: str):
    _sync_repository.upsert_state(
        user_id,
        last_synced_at=last_synced_at,
        status="idle",
        last_error="",
    )


# ---------------------------------------------------------------------------
# Flight persistence helpers
# ---------------------------------------------------------------------------


def _synced_flight_fields(flight_data: dict, email_msg) -> dict:
    """Build the field set shared by create_synced/update_synced from a parsed
    flight leg and the source email."""
    dep_dt = flight_data.get("departure_datetime")
    arr_dt = flight_data.get("arrival_datetime")
    return {
        "airline_name": flight_data.get("airline_name", ""),
        "airline_code": flight_data.get("airline_code", ""),
        "flight_number": flight_data["flight_number"],
        "booking_reference": flight_data.get("booking_reference", ""),
        "departure_airport": flight_data["departure_airport"],
        "departure_datetime": dt_to_iso(dep_dt),
        "departure_terminal": flight_data.get("departure_terminal", ""),
        "departure_gate": flight_data.get("departure_gate", ""),
        "arrival_airport": flight_data["arrival_airport"],
        "arrival_datetime": dt_to_iso(arr_dt),
        "arrival_terminal": flight_data.get("arrival_terminal", ""),
        "arrival_gate": flight_data.get("arrival_gate", ""),
        "passenger_name": flight_data.get("passenger_name", ""),
        "seat": flight_data.get("seat", ""),
        "cabin_class": flight_data.get("cabin_class", ""),
        "duration_minutes": calc_duration_minutes(dep_dt, arr_dt),
        "status": calc_flight_status(arr_dt),
        "departure_timezone": flight_data.get("departure_timezone"),
        "arrival_timezone": flight_data.get("arrival_timezone"),
        "email_message_id": f"{email_msg.message_id}:{flight_data['flight_number']}",
        "email_subject": (email_msg.subject or "")[:512],
        "email_date": dt_to_iso(email_msg.date),
        "email_body": email_msg.html_body,
    }


def _insert_synced_flight(flight_data: dict, email_msg, user_id: int) -> str | None:
    """Insert a new flight parsed from a synced email (dedup by email_message_id).
    Returns the new flight id, or None if it was a duplicate."""
    flight_id = str(uuid.uuid4())
    fields = _synced_flight_fields(flight_data, email_msg)
    rowcount = _flight_repository.create_synced(flight_id, fields, user_id, now_iso())
    return flight_id if rowcount else None


# ---------------------------------------------------------------------------
# Boarding pass helpers
# ---------------------------------------------------------------------------


def _update_flight_from_bcbp(existing_id: str, user_id: int, bcbp_leg: dict):
    """Patch an existing flight with data from a boarding pass (seat, cabin, pax name, pnr)."""
    updates = {}
    if bcbp_leg.get("seat"):
        updates["seat"] = bcbp_leg["seat"]
    if bcbp_leg.get("cabin_class"):
        updates["cabin_class"] = bcbp_leg["cabin_class"]
    if bcbp_leg.get("passenger_name"):
        updates["passenger_name"] = bcbp_leg["passenger_name"]
    if bcbp_leg.get("booking_reference"):
        updates["booking_reference"] = bcbp_leg["booking_reference"]
    if not updates:
        return
    updates["updated_at"] = now_iso()
    _flight_repository.update(existing_id, user_id, updates)


def _apply_boarding_pass_details(rule, email_msg, user_id: int) -> int:
    """Patch stored flights with seat/gate/terminal from a boarding-pass email.

    A boarding pass names a leg the traveller already has — it carries no
    arrival time, so it cannot describe a flight on its own (the same reason
    `_process_bcbp_email` only ever updates). An airline opts in by exporting
    `extract_boarding_pass_details`; everyone else has no attribute and is
    skipped.

    Only empty fields are filled. The booking confirmation is the authority on
    where and when the flight goes, and a boarding pass reprinted after a gate
    change should not be able to overwrite a seat the traveller has since
    edited by hand.
    """
    extractor = getattr(rule, "boarding_pass_extractor", None)
    if extractor is None:
        return 0

    try:
        records = extractor(email_msg) or []
    except Exception as e:  # noqa: BLE001 - enrichment must never fail a sync
        logger.warning("User %d: boarding-pass detail extraction failed: %s", user_id, e)
        return 0

    updated = 0
    for record in records:
        fn = record.get("flight_number")
        dep_date = record.get("departure_date")
        if not fn or not dep_date:
            continue
        existing = _flight_repository.find_by_number_and_date(fn, dep_date, user_id)
        if not existing:
            logger.debug(
                "User %d: boarding pass for %s on %s matches no stored flight",
                user_id,
                fn,
                dep_date,
            )
            continue
        updates = {
            key: record[key]
            for key in (
                "seat",
                "cabin_class",
                "passenger_name",
                "booking_reference",
                "departure_terminal",
                "departure_gate",
            )
            if record.get(key) and not getattr(existing, key, None)
        }
        if record.get("gate") and not getattr(existing, "departure_gate", None):
            updates["departure_gate"] = record["gate"]
        if not updates:
            continue
        updates["updated_at"] = now_iso()
        _flight_repository.update(existing.id, user_id, updates)
        updated += 1
        logger.info(
            "User %d: enriched flight %s on %s from boarding pass (%s)",
            user_id,
            fn,
            dep_date,
            ", ".join(sorted(k for k in updates if k != "updated_at")),
        )
    return updated


def _apply_cancellations(rule, email_msg, user_id: int) -> int:
    """Mark stored flights cancelled when an airline says a booking or leg is off.

    The counterpart to `_apply_boarding_pass_details`, and built the same way:
    an airline opts in by exporting `extract_cancellations`, everyone else has
    no attribute and is skipped. Both describe flights the traveller *already*
    has rather than producing new ones, which is why they run whether or not the
    email yielded an itinerary — a cancellation mail never does.

    **A cancellation marks, it never deletes.** See `parsers/cancellations.py`
    for why; the short version is that `status = 'cancelled'` is reversible,
    visible and honest, and a delete is none of those.

    **A cancellation older than the flight it names is ignored.** A booking
    reference outlives a cancellation — an airline that cancels and rebooks
    often reissues under the same PNR — so a stored leg whose source email is
    *newer* than this one describes the rebooking, and cancelling it would undo
    a fact the traveller received later. This is the same "newer email wins"
    rule `_process_emails` already applies when a restated itinerary updates a
    stored flight, and a flight with no source email at all (typed by hand)
    fails the comparison and is cancelled, which is correct: nothing about it
    postdates the airline's notice.
    """
    extractor = getattr(rule, "cancellation_extractor", None)
    if extractor is None:
        return 0

    try:
        records = extractor(email_msg) or []
    except Exception as e:  # noqa: BLE001 - a bad cancellation must not fail a sync
        logger.warning("User %d: cancellation extraction failed: %s", user_id, e)
        return 0
    if not records:
        return 0

    email_date = dt_to_iso(email_msg.date) if email_msg.date else None
    cancelled = 0
    for record in records:
        if ref := record.get("booking_reference"):
            matches = _flight_repository.find_cancellable_by_booking_reference(ref, user_id)
            described = f"booking {ref}"
        else:
            matches = _flight_repository.find_cancellable_by_number_and_date(
                record["flight_number"], record["departure_date"], user_id
            )
            described = f"{record['flight_number']} on {record['departure_date']}"

        if not matches:
            logger.debug(
                "User %d: cancellation for %s matches no stored flight", user_id, described
            )
            continue

        for flight in matches:
            if email_date and flight.email_date and flight.email_date > email_date:
                logger.info(
                    "User %d: ignoring cancellation of %s — stored flight %s comes from a "
                    "later email (%s > %s), so it was rebooked after this notice",
                    user_id,
                    described,
                    flight.flight_number,
                    flight.email_date,
                    email_date,
                )
                continue
            _flight_repository.update(
                flight.id, user_id, {"status": "cancelled", "updated_at": now_iso()}
            )
            cancelled += 1
            logger.info(
                "User %d: cancelled flight %s %s→%s (%s)",
                user_id,
                flight.flight_number,
                flight.departure_airport,
                flight.arrival_airport,
                described,
            )
            _send_cancellation_notification(flight, user_id)

    return cancelled


def _send_cancellation_notification(flight, user_id: int) -> None:
    """Tell the traveller a flight they had is off.

    Rides on the `delay_alert` preference rather than a new one: that is the
    preference `integrations/aircraft/status_sync.py` already sends its own
    `delay_alert_cancelled` under, and a reader who turned delay alerts off has
    said what they think of schedule-disruption notices. `already_sent` keys on
    the same event name, so a full rescan re-reading the cancellation mail does
    not notify twice.
    """
    try:
        from ..notifications import push_service

        if not push_service.is_preference_enabled(user_id, "delay_alert"):
            return
        if push_service.already_sent(user_id, flight.id, "delay_alert_cancelled"):
            return
        route = f"{flight.departure_airport} → {flight.arrival_airport}"
        sent = push_service.send_push(
            user_id,
            {
                "title": f"Flight {flight.flight_number} cancelled",
                "body": route,
                "url": f"/#/flights/{flight.id}",
            },
        )
        if sent:
            push_service.log_sent(user_id, flight.id, "delay_alert_cancelled")
    except Exception as e:  # noqa: BLE001 - notification failure must not fail a sync
        logger.warning("User %d: failed to send cancellation notification: %s", user_id, e)


def _local_clock(iso: str | None, tz_name: str | None) -> str:
    """ "10 Nov 19:30" in the airport's own zone, for a notification body."""
    if not iso:
        return "?"
    try:
        from zoneinfo import ZoneInfo

        dt = datetime.fromisoformat(iso)
        if tz_name:
            dt = dt.astimezone(ZoneInfo(tz_name))
        return dt.strftime("%d %b %H:%M")
    except Exception:  # noqa: BLE001 - a bad zone name must not lose the notification
        return iso[:16].replace("T", " ")


def _record_reschedule(existing, flight_data: dict, email_msg, user_id: int) -> bool:
    """After a newer itinerary has overwritten a stored leg, keep what it moved from.

    `update_synced` has always applied the new times silently — right data, no
    trace. This runs beside it: when either instant changed, the previous pair
    goes into `rescheduled_from_*` (previous, not original — a notification
    reports the move that just happened), the row is stamped, and any pending
    schedule-change notice on it is cleared, because an itinerary newer than the
    notice *is* the itinerary the notice pointed at. Returns whether times moved.
    """
    new_dep = dt_to_iso(flight_data.get("departure_datetime"))
    new_arr = dt_to_iso(flight_data.get("arrival_datetime"))
    if new_dep == existing.departure_datetime and new_arr == existing.arrival_datetime:
        return False
    _flight_repository.update(
        existing.id,
        user_id,
        {
            "rescheduled_from_departure": existing.departure_datetime,
            "rescheduled_from_arrival": existing.arrival_datetime,
            "rescheduled_at": dt_to_iso(email_msg.date) or now_iso(),
            "schedule_change_notice_at": None,
        },
    )
    logger.info(
        "User %d: flight %s rescheduled %s -> %s by newer email",
        user_id,
        existing.flight_number,
        existing.departure_datetime,
        new_dep,
    )
    _send_reschedule_notification(existing, new_dep, flight_data.get("departure_timezone"), user_id)
    return True


def _send_reschedule_notification(
    flight, new_dep_iso: str | None, tz_name: str | None, user_id: int
) -> None:
    """In-app plus push, under the delay-alert preference like cancellations.

    `already_sent` keys on the new departure, so re-reading the same change mail
    on a full rescan cannot notify twice, while a second, later move can.
    """
    try:
        from ..notifications import notification_service, push_service
        from ..utils.i18n import t

        if not push_service.is_preference_enabled(user_id, "delay_alert"):
            return
        event = f"rescheduled:{(new_dep_iso or '')[:16]}"
        if push_service.already_sent(user_id, flight.id, event):
            return
        locale = push_service.get_locale(user_id)
        zone = tz_name or flight.departure_timezone
        title = t("notif.rescheduled_title", locale, flight=flight.flight_number)
        body = t(
            "notif.rescheduled_body",
            locale,
            **{"from": flight.departure_airport, "to": flight.arrival_airport},
            new=_local_clock(new_dep_iso, zone),
            old=_local_clock(flight.departure_datetime, zone),
        )
        url = f"/#/flights/{flight.id}"
        notification_service.create_notification(user_id, "rescheduled", title, body, url)
        if push_service.send_push(user_id, {"title": title, "body": body, "url": url}):
            push_service.log_sent(user_id, flight.id, event)
    except Exception as e:  # noqa: BLE001 - notification failure must not fail a sync
        logger.warning("User %d: failed to send reschedule notification: %s", user_id, e)


def _apply_schedule_change_notices(rule, email_msg, user_id: int) -> int:
    """Flag the stored legs of a booking an airline says it has moved.

    For the mail that announces a change and prints *no* itinerary (SAS). There
    is nothing to update from it, so the legs are stamped with the notice date
    and the traveller is pointed at the airline. Two guards: a leg whose own
    email is newer than the notice was already re-read from the itinerary the
    notice refers to, and a leg already stamped with this notice is left alone,
    which is what makes a full rescan a no-op — a notice creates no flight, so
    it is never marked processed.
    """
    extractor = getattr(rule, "schedule_change_extractor", None)
    if extractor is None:
        return 0
    try:
        records = extractor(email_msg) or []
    except Exception as e:  # noqa: BLE001 - a bad notice must not fail a sync
        logger.warning("User %d: schedule-change extraction failed: %s", user_id, e)
        return 0
    notice_at = dt_to_iso(email_msg.date) or now_iso()
    flagged = 0
    for record in records:
        ref = record.get("booking_reference")
        if not ref:
            continue
        for flight in _flight_repository.find_cancellable_by_booking_reference(ref, user_id):
            if flight.email_date and flight.email_date > notice_at:
                continue
            if flight.schedule_change_notice_at and flight.schedule_change_notice_at >= notice_at:
                continue
            _flight_repository.update(flight.id, user_id, {"schedule_change_notice_at": notice_at})
            _send_schedule_change_notice_notification(
                flight, ref, rule.airline_name, notice_at, user_id
            )
            flagged += 1
    return flagged


def _send_schedule_change_notice_notification(
    flight, ref: str, airline: str, notice_at: str, user_id: int
) -> None:
    try:
        from ..notifications import notification_service, push_service
        from ..utils.i18n import t

        if not push_service.is_preference_enabled(user_id, "delay_alert"):
            return
        event = f"schedule_change_notice:{notice_at[:16]}"
        if push_service.already_sent(user_id, flight.id, event):
            return
        locale = push_service.get_locale(user_id)
        title = t("notif.schedule_change_notice_title", locale, ref=ref)
        body = t("notif.schedule_change_notice_body", locale, airline=airline)
        url = f"/#/flights/{flight.id}"
        notification_service.create_notification(user_id, "schedule_change", title, body, url)
        if push_service.send_push(user_id, {"title": title, "body": body, "url": url}):
            push_service.log_sent(user_id, flight.id, event)
    except Exception as e:  # noqa: BLE001
        logger.warning("User %d: failed to send schedule-change notification: %s", user_id, e)


def _process_bcbp_email(email_msg, user_id: int) -> tuple[int, int]:
    """
    Scan email plain-text body for BCBP boarding pass strings.
    For each leg found:
      - If a matching flight exists (by flight_number + date): update seat/cabin/pax/pnr.
      - Otherwise: skip (we don't have enough info to create a complete flight from BCBP alone).

    Returns (legs_found, flights_updated).
    """
    text = email_msg.body or ""
    if not text:
        return 0, 0

    candidates = find_bcbp_in_text(text)
    if not candidates:
        return 0, 0

    legs_found = 0
    flights_updated = 0
    for candidate in candidates:
        legs = parse_bcbp(candidate)
        for leg in legs:
            legs_found += 1
            dep_date = leg.get("departure_date")
            if not dep_date:
                continue
            existing = _flight_repository.find_by_number_and_date(
                leg["flight_number"], dep_date.isoformat(), user_id
            )
            if existing:
                _update_flight_from_bcbp(existing.id, user_id, leg)
                flights_updated += 1
                logger.debug(
                    "User %d: Updated flight %s from BCBP",
                    user_id,
                    leg["flight_number"],
                )

    return legs_found, flights_updated


def _process_boarding_pass_email(email_msg, user_id: int) -> int:
    """
    If this looks like a check-in / boarding pass email, extract QR/barcode images
    and save them against the matching flight.

    Returns number of boarding pass images saved.
    """
    if not is_checkin_email(email_msg):
        return 0

    images = extract_boarding_pass_images(email_msg)
    if not images:
        return 0

    text = (email_msg.body or "") + " " + (email_msg.html_body or "")
    bcbp_matches: list[dict] = []
    if text:
        candidates = find_bcbp_in_text(text)
        for candidate in candidates:
            legs = parse_bcbp(candidate)
            for leg in legs:
                dep_date = leg.get("departure_date")
                if not dep_date:
                    continue
                existing = _flight_repository.find_by_number_and_date(
                    leg["flight_number"], dep_date.isoformat(), user_id
                )
                if existing:
                    bcbp_matches.append(
                        {
                            "flight_id": existing.id,
                            "passenger_name": leg.get("passenger_name"),
                            "seat": leg.get("seat"),
                        }
                    )

    saved = 0
    from ..boarding_passes import boarding_pass_service

    if bcbp_matches:
        # Pair images with BCBP legs (best-effort: page N → leg N)
        for i, img_info in enumerate(images):
            match = bcbp_matches[i] if i < len(bcbp_matches) else bcbp_matches[-1]
            try:
                boarding_pass_service.save_from_sync(
                    flight_id=match["flight_id"],
                    image_bytes=img_info["image_bytes"],
                    passenger_name=match.get("passenger_name"),
                    seat=match.get("seat"),
                    source_email_id=email_msg.message_id,
                    source_page=img_info["source_page"],
                )
                saved += 1
                _send_boarding_pass_notification(match["flight_id"], user_id)
            except Exception as e:
                logger.warning("Failed to save boarding pass image: %s", e)
    else:
        # No BCBP — try to find flight by scanning email subject/body for flight numbers
        flight_id = _find_flight_from_email_text(email_msg, user_id)
        if flight_id:
            for img_info in images:
                try:
                    boarding_pass_service.save_from_sync(
                        flight_id=flight_id,
                        image_bytes=img_info["image_bytes"],
                        passenger_name=None,
                        seat=None,
                        source_email_id=email_msg.message_id,
                        source_page=img_info["source_page"],
                    )
                    saved += 1
                    _send_boarding_pass_notification(flight_id, user_id)
                except Exception as e:
                    logger.warning("Failed to save boarding pass image: %s", e)

    if saved:
        logger.info(
            "User %d: Saved %d boarding pass image(s) from email %s",
            user_id,
            saved,
            email_msg.message_id,
        )
    return saved


def _find_flight_from_email_text(email_msg, user_id: int) -> str | None:
    """Try to find a matching flight by scanning the email text for flight number patterns."""
    text = (email_msg.subject or "") + " " + (email_msg.body or "")
    # Common flight number patterns: 2-letter IATA code + 1-4 digits
    matches = re.findall(r"\b([A-Z]{2})\s*(\d{1,4})\b", text)
    for airline, num in matches:
        flight_number = f"{airline}{int(num)}"
        flight = _flight_repository.find_latest_by_number(flight_number, user_id)
        if flight:
            return flight.id
    return None


def _send_boarding_pass_notification(flight_id: str, user_id: int) -> None:
    """Send a push notification about a new boarding pass, if the user has this preference enabled."""
    try:
        from ..notifications import push_service

        if not push_service.is_preference_enabled(user_id, "boarding_pass"):
            return

        flight = _flight_repository.get_by_id(flight_id)
        if not flight:
            return

        if push_service.already_sent(user_id, flight_id, "boarding_pass"):
            return

        route = f"{flight.departure_airport} → {flight.arrival_airport}"
        sent = push_service.send_push(
            user_id,
            {
                "title": "Boarding pass ready ✈",
                "body": f"{flight.flight_number} · {route}",
                "url": f"/#/flights/{flight_id}",
            },
        )
        if sent:
            push_service.log_sent(user_id, flight_id, "boarding_pass")
    except Exception as e:
        logger.warning("Failed to send boarding pass notification: %s", e)


# ---------------------------------------------------------------------------
# Email processing pipeline
# ---------------------------------------------------------------------------


def _process_emails(
    emails: list,
    user_id: int,
    use_llm: bool = False,
    progress_callback: object = None,
    skip_dedup: bool = False,
) -> dict:
    """Parse a list of EmailMessage objects and persist flights to the DB.

    Args:
        use_llm: When True and Ollama is configured, try the LLM extractor
                 immediately after rule-based + PDF parsing fail, instead of
                 deferring to the failed-email queue.  Should be False for
                 full re-scans (too many emails).
        progress_callback: Optional callable(n) called after every 10 emails
                           with the current processed count.

    Returns a summary dict including ``new_flight_ids`` so callers can
    trigger aircraft lookups for freshly inserted flights.
    """
    from ..integrations.llm.parser import llm_available, llm_extract_flights

    _use_llm = use_llm and llm_available()

    emails_processed = 0
    flights_created = 0
    flights_updated = 0
    flights_cancelled = 0
    flights_rescheduled = 0
    stays_created = 0
    car_rentals_created = 0
    new_flight_ids: list[str] = []
    errors = []

    rules = get_builtin_rules()
    sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))

    for email_msg in emails:
        # --- Accommodation, from schema.org markup only -------------------
        # Deliberately ahead of the blocked-domain skip. That list exists
        # because *heuristic* parsing of accommodation mail produced junk, and
        # the booking platforms on it (Airbnb, Booking.com) are exactly the
        # senders that ship typed reservation markup. A structural reader
        # cannot invent a booking: it finds a typed LodgingReservation or
        # returns nothing, so the reason for the block does not apply to it.
        # Idempotency lives in the importer rather than the processed-email
        # ledger below, because a lodging email is often the same email a
        # flight was already read from.
        try:
            stay_ids = import_lodging_from_email(email_msg, user_id)
            stays_created += len(stay_ids)
        except Exception as e:  # noqa: BLE001 - never let accommodation stop the sync
            logger.error("User %d: Lodging import error: %s", user_id, e, exc_info=True)

        # --- Car rentals, from the three vendors we can read -----------------
        # Also ahead of the blocked-domain skip, and for exactly the reason the
        # lodging import is: hertz, sixt and europcar are on that list because
        # they never contain *flights*, and `extract_car_rentals` is gated on
        # the sender and on the vendor's own labels rather than guessing — it
        # finds the booking it knows how to read or returns nothing. Idempotency
        # lives in the importer, not the processed-email ledger, because a
        # rental confirmation is often re-read by a full rescan.
        try:
            rental_ids = import_car_rentals_from_email(email_msg, user_id)
            car_rentals_created += len(rental_ids)
        except Exception as e:  # noqa: BLE001 - never let a rental stop the sync
            logger.error("User %d: Car rental import error: %s", user_id, e, exc_info=True)

        if is_non_flight_domain(email_msg.sender or ""):
            logger.debug("Skipping email from blocked domain: %s", email_msg.sender)
            continue
        if (
            not skip_dedup
            and email_msg.message_id
            and _sync_repository.is_email_processed(user_id, email_msg.message_id)
        ):
            logger.debug(
                "User %d: Skipping already-processed email %s", user_id, email_msg.message_id
            )
            continue
        try:
            # --- BCBP boarding pass scan (always attempted first) ---
            bcbp_legs, bcbp_updated = _process_bcbp_email(email_msg, user_id)
            if bcbp_legs:
                flights_updated += bcbp_updated
                emails_processed += 1

            # --- Extraction, most trustworthy strategy first ---------------
            # 1. The airline's own rule. Hand-written against real emails for
            #    that carrier, and the only thing that reads formats the others
            #    cannot (boarding-pass microdata, check-in mails, seat/cabin).
            rule = match_rule_to_email(email_msg, sorted_rules)
            flights_data = extract_flights_from_email(email_msg, rule) if rule else []

            # A boarding pass enriches a leg rather than describing one. Run it
            # whether or not the rule yielded flights: the email it belongs to
            # usually yields none, which is the point.
            if rule is not None:
                flights_updated += _apply_boarding_pass_details(rule, email_msg, user_id)
                # Also a statement about flights already stored, and the only
                # path by which a cancellation ever reaches one. Every parser
                # here refuses to *create* a cancelled leg; nothing until now
                # went back to the leg the booking confirmation created weeks
                # earlier, so a cancelled flight sat in its trip for ever.
                flights_cancelled += _apply_cancellations(rule, email_msg, user_id)
                # And the third kind of statement about stored flights: "we moved
                # this booking, see the new itinerary elsewhere". Nothing to
                # update from, so the legs are flagged and the traveller told.
                flights_rescheduled += _apply_schedule_change_notices(rule, email_msg, user_id)

            # 2. GDS e-ticket receipt. Reads the receipt's own structure — a
            #    table cell's column, or a whole matched line — instead of
            #    guessing from proximity to a flight number, which makes it far
            #    more reliable than the line scanners below. It self-gates on a
            #    receipt marker, returning [] rather than guessing at other
            #    formats, so it is safe to attempt on every email.
            #
            #    Its results are *merged* rather than used only as a fallback:
            #    an airline rule can quietly miss legs on a multi-carrier
            #    itinerary (a three-leg ARN→AMS→LHR→JNB ticket came through as
            #    the final leg alone), and merging recovers those while keeping
            #    any richer per-leg fields the rule found. Legs are matched on
            #    flight number and route, so agreeing parsers do not duplicate.
            gds_flights = extract_gds_eticket(email_msg, rule)
            if gds_flights:
                flights_data = merge_flights(flights_data, gds_flights)

            # There used to be a third tier here: generic line scanners that
            # anchored on any flight-number-shaped token and guessed the rest
            # from nearby lines. Across a 372-email corpus every leg it was the
            # sole source of was wrong or incomplete — a Ryanair round trip with
            # both legs pointing the same way, a TAP receipt reading the "NVA"
            # not-valid-after label as Neiva, e-tickets dated a year off — and
            # each one passed the plausibility gate looking perfectly ordinary.
            # The formats it was covering are now read by the airlines' own rules;
            # anything else is better left to the LLM, which at least knows when
            # it doesn't know.

            # --- LLM fallback (incremental sync only, when Ollama is available) ---
            if not flights_data and _use_llm:
                flights_data = llm_extract_flights(email_msg)
                if flights_data:
                    logger.info(
                        "User %d: LLM extracted %d flight(s) from %s",
                        user_id,
                        len(flights_data),
                        email_msg.subject[:60],
                    )

            if not flights_data:
                continue

            flights_data = [apply_airport_timezones(f) for f in flights_data]
            # Single gate every extraction path passes through: times are real
            # UTC by this point, so impossible legs can actually be spotted.
            flights_data = validate_flights(flights_data, source=email_msg.subject[:60])
            if not flights_data:
                continue
            if not bcbp_legs:
                emails_processed += 1

            for flight_data in flights_data:
                fn = flight_data.get("flight_number", "")
                if not fn:
                    continue

                dep_dt = flight_data.get("departure_datetime")
                dep_iso = dt_to_iso(dep_dt) if dep_dt else None
                dep_date = dep_iso[:10] if dep_iso else None

                if dep_date:
                    existing = _flight_repository.find_by_number_and_date(fn, dep_date, user_id)
                    if not existing:
                        # A schedule change can move the *date*, which is the
                        # key above. Same number, route and booking within a
                        # few days is that leg moved, not a second one.
                        existing = _flight_repository.find_moved_leg(
                            fn,
                            flight_data.get("booking_reference") or "",
                            flight_data.get("departure_airport") or "",
                            flight_data.get("arrival_airport") or "",
                            dep_date,
                            user_id,
                        )
                    if existing:
                        new_email_date = dt_to_iso(email_msg.date) if email_msg.date else None
                        existing_email_date = existing.email_date
                        if (
                            new_email_date
                            and existing_email_date
                            and new_email_date > existing_email_date
                        ):
                            fields = _synced_flight_fields(flight_data, email_msg)
                            _flight_repository.update_synced(existing.id, fields, now_iso())
                            flights_updated += 1
                            logger.info("User %d: Updated flight %s with newer email", user_id, fn)
                            if _record_reschedule(existing, flight_data, email_msg, user_id):
                                flights_rescheduled += 1
                        else:
                            logger.debug("User %d: Skipping older email for flight %s", user_id, fn)
                        continue

                # INSERT OR IGNORE deduplicates by email_message_id atomically
                new_id = _insert_synced_flight(flight_data, email_msg, user_id)
                if new_id:
                    flights_created += 1
                    new_flight_ids.append(new_id)
                    if email_msg.message_id:
                        _sync_repository.mark_email_processed(user_id, email_msg.message_id)
                    logger.info(
                        "User %d: Created flight: %s %s→%s",
                        user_id,
                        fn,
                        flight_data.get("departure_airport"),
                        flight_data.get("arrival_airport"),
                    )
                else:
                    logger.debug(
                        "User %d: Duplicate skipped: %s:%s", user_id, email_msg.message_id, fn
                    )

            # --- Boarding pass extraction (check-in emails) ---
            try:
                _process_boarding_pass_email(email_msg, user_id)
            except Exception as e:
                logger.warning("User %d: Boarding pass extraction error: %s", user_id, e)

        except Exception as e:
            err = f"User {user_id}: Error processing email {email_msg.message_id}: {e}"
            logger.error(err, exc_info=True)
            errors.append(err)
        finally:
            # Report progress every 10 emails to avoid excessive DB writes.
            # Skip total_seen == 0 to avoid resetting the counter to 0 at the
            # start of processing (which would look like a restart to the user).
            total_seen = emails_processed + len(errors)
            if progress_callback and total_seen > 0 and total_seen % 10 == 0:
                try:
                    progress_callback(total_seen)  # type: ignore[operator]
                except Exception:
                    pass

    grouping_result = {}
    try:
        grouping_result = auto_group_flights(user_id=user_id)
    except Exception as e:
        logger.error("User %d: Grouping error: %s", user_id, e, exc_info=True)

    return {
        "emails_processed": emails_processed,
        "flights_created": flights_created,
        "flights_updated": flights_updated,
        "flights_cancelled": flights_cancelled,
        "flights_rescheduled": flights_rescheduled,
        "stays_created": stays_created,
        "car_rentals_created": car_rentals_created,
        "new_flight_ids": new_flight_ids,
        "grouping": grouping_result,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Sync result notifications
# ---------------------------------------------------------------------------


def _send_sync_notifications(user_id: int, flights_created: int) -> None:
    """Create in-app notifications and optionally send push after a sync."""
    try:
        from ..notifications import notification_service, push_service
        from ..utils.i18n import t

        if flights_created > 0 and push_service.is_preference_enabled(user_id, "new_flight"):
            n = flights_created
            locale = push_service.get_locale(user_id)
            title = t("notif.new_flights_title", locale)
            body_key = "notif.new_flights_body_plural" if n > 1 else "notif.new_flights_body"
            body = t(body_key, locale, n=n)
            notification_service.create_notification(user_id, "new_flight", title, body, "/#/trips")
            push_service.send_push(user_id, {"title": title, "body": body, "url": "/#/trips"})
    except Exception as e:
        logger.warning("User %d: Failed to send sync notifications: %s", user_id, e)


# ---------------------------------------------------------------------------
# Public sync entry points
# ---------------------------------------------------------------------------


def run_email_sync_for_user(user: dict) -> dict:
    """
    Sync email for a single user. Called by run_email_sync() for each user,
    and also directly from the /api/sync/now endpoint.
    """
    from ..auth import get_user_imap_settings

    user_id = user["id"]
    imap = get_user_imap_settings(user)

    if not imap["gmail_address"] or not imap["gmail_app_password"]:
        logger.warning("User %d: Gmail credentials not configured — skipping sync", user_id)
        return {"status": "skipped", "reason": "No credentials configured"}

    _set_sync_status(user_id, "running")
    sync_state = _sync_repository.get_latest_state(user_id)

    try:
        last_synced_at = sync_state.last_synced_at if sync_state else None

        since_date = None
        if last_synced_at:
            try:
                since_date = datetime.fromisoformat(last_synced_at)
                since_date = since_date - timedelta(days=1)
            except ValueError:
                since_date = None

        if since_date is None:
            first_sync_days = int(get_global_setting("first_sync_days", "90"))
            since_date = datetime.now(UTC) - timedelta(days=first_sync_days)

        rules = get_builtin_rules()
        sender_patterns = [r.sender_pattern for r in rules if r.sender_pattern]

        logger.info(
            "User %d: Fetching emails since %s from %s", user_id, since_date, imap["gmail_address"]
        )

        def _imap_progress(fetched: int, total: int) -> None:
            _sync_repository.upsert_state(user_id, emails_total=total, emails_processed=fetched)

        imap_result: ImapFetchResult = fetch_emails_imap(
            host=imap["imap_host"],
            port=imap["imap_port"],
            username=imap["gmail_address"],
            password=imap["gmail_app_password"],
            use_ssl=True,
            sender_patterns=sender_patterns,
            since_date=since_date,
            progress_callback=_imap_progress,
        )

        if not imap_result.success:
            err_msg = imap_result.error or "IMAP fetch failed"
            logger.error("User %d: IMAP fetch failed: %s", user_id, err_msg)
            _set_sync_status(user_id, "error", err_msg)
            return {"status": "error", "error": err_msg}

        emails = imap_result.emails
        logger.info("User %d: Fetched %d matching emails", user_id, len(emails))
        # Reset processing counter so the UI shows a clean 0→N progress for
        # the parse phase (separate from the IMAP fetch counter above).
        _sync_repository.upsert_state(user_id, emails_processed=0, emails_total=len(emails))

        result = _process_emails(
            emails,
            user_id,
            use_llm=True,
            progress_callback=lambda n: _sync_repository.upsert_state(user_id, emails_processed=n),
        )

        if result["new_flight_ids"]:
            try:
                from ..integrations.aircraft.sync import fetch_aircraft_for_new_flights

                fetch_aircraft_for_new_flights(result["new_flight_ids"])
            except Exception as e:
                logger.warning("User %d: Aircraft sync for new flights failed: %s", user_id, e)

        _send_sync_notifications(user_id, result["flights_created"])

        _set_sync_complete(user_id, now_iso())

        summary = {
            "status": "success",
            "emails_fetched": len(emails),
            "emails_processed": result["emails_processed"],
            "flights_created": result["flights_created"],
            "flights_updated": result["flights_updated"],
            "grouping": result["grouping"],
            "errors": result["errors"],
        }
        logger.info("User %d: Sync complete: %s", user_id, summary)
        return summary

    except Exception as e:
        err_msg = str(e)
        logger.error("User %d: Sync failed: %s", user_id, err_msg, exc_info=True)
        _set_sync_status(user_id, "error", err_msg)
        return {"status": "error", "error": err_msg}
    finally:
        try:
            state = _sync_repository.get_latest_state(user_id)
            if state and state.status == "running":
                _set_sync_status(user_id, "idle")
        except Exception:
            pass


def run_email_sync() -> dict:
    """
    Main sync function. Called by APScheduler every N minutes.
    Iterates all users and syncs each one.
    """
    users = _sync_repository.list_all_sync_credentials()

    if not users:
        logger.warning("No users found — skipping sync")
        return {"status": "skipped", "reason": "No users configured"}

    from ..crypto import decrypt

    results = {}
    for user_row in users:
        user = {k: user_row[k] for k in user_row.keys()}
        state = _sync_repository.get_latest_state(user["id"])
        if state and state.status == "running":
            logger.info("User %d: Skipping scheduled sync — already running", user["id"])
            results[user["id"]] = {"status": "skipped", "reason": "already running"}
            continue
        if user.get("gmail_app_password"):
            user["gmail_app_password"] = decrypt(user["gmail_app_password"])
        try:
            result = run_email_sync_for_user(user)
            results[user["id"]] = result
        except Exception as e:
            logger.error("Sync failed for user %d: %s", user["id"], e, exc_info=True)
            results[user["id"]] = {"status": "error", "error": str(e)}

    return {"status": "success", "users": results}


def process_inbound_email(email_msg, user_id: int | None = None) -> dict:
    """
    Process a single inbound email (e.g. from the SMTP server).
    Runs through BCBP + HTML parsing, groups flights, triggers aircraft sync.
    Returns a summary dict.
    """
    logger.info("SMTP inbound: processing email from %s — %s", email_msg.sender, email_msg.subject)

    if user_id is None:
        logger.warning("SMTP inbound: email rejected — no user_id, recipient address not matched")
        return {"status": "error", "error": "Recipient not matched to any user"}

    # SMTP inbound: always try LLM — it's a single email, latency is fine.
    result = _process_emails([email_msg], user_id, use_llm=True)

    new_flight_ids = []
    if result.get("flights_created", 0) > 0:
        new_flight_ids = _flight_repository.list_missing_aircraft_data(user_id)

    if new_flight_ids:
        try:
            from ..integrations.aircraft.sync import fetch_aircraft_for_new_flights

            fetch_aircraft_for_new_flights(new_flight_ids)
        except Exception as e:
            logger.warning("Aircraft sync for inbound email failed: %s", e)

    logger.info("SMTP inbound result: %s", result)
    return result
