"""
Email sync job — fetches airline confirmation emails from Gmail,
parses them with the engine, and stores flights in SQLite.
Runs every 10 minutes via APScheduler.
"""

import logging
from datetime import UTC, datetime, timedelta

from .boarding_pass_extractor import extract_boarding_pass_images, is_checkin_email
from .database import db_conn, db_write, get_global_setting
from .email_cache import save_emails
from .failed_email_queue import email_has_flight_keywords, retry_failed_emails, save_failed_email
from .flight_store import find_existing_flight, insert_flight, update_flight
from .grouping import auto_group_flights
from .parsers.bcbp import find_bcbp_in_text, parse_bcbp
from .parsers.builtin_rules import PARSER_VERSION, get_builtin_rules
from .parsers.email_connector import ImapFetchResult, fetch_emails_imap
from .parsers.engine import (
    extract_flights_from_email,
    match_rule_to_email,
    try_generic_pdf_extraction,
)
from .timezone_utils import apply_airport_timezones
from .utils import dt_to_iso, now_iso

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync state helpers
# ---------------------------------------------------------------------------


def _get_sync_state(user_id: int) -> dict:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM email_sync_state WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        if row:
            return dict(row)
        return {}


_SYNC_STATE_COLUMNS = frozenset({"status", "last_error", "last_synced_at", "last_rules_version"})


def _upsert_sync_state(user_id: int, **fields):
    """Insert or update the email_sync_state row for a user."""
    unknown = set(fields) - _SYNC_STATE_COLUMNS
    if unknown:
        raise ValueError(f"Unknown email_sync_state columns: {unknown}")

    with db_write() as conn:
        existing = conn.execute(
            "SELECT id FROM email_sync_state WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE email_sync_state SET {set_clause} WHERE user_id = ?",
                list(fields.values()) + [user_id],
            )
        else:
            cols = "user_id, " + ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in range(len(fields) + 1))
            conn.execute(
                f"INSERT INTO email_sync_state ({cols}) VALUES ({placeholders})",
                [user_id] + list(fields.values()),
            )


def _set_sync_status(user_id: int, status: str, error: str = ""):
    _upsert_sync_state(user_id, status=status, last_error=error)


def _set_sync_complete(user_id: int, last_synced_at: str):
    _upsert_sync_state(
        user_id,
        last_synced_at=last_synced_at,
        last_rules_version=PARSER_VERSION,
        status="idle",
        last_error="",
    )


# ---------------------------------------------------------------------------
# Boarding pass helpers
# ---------------------------------------------------------------------------


def _update_flight_from_bcbp(existing_id: str, bcbp_leg: dict):
    """Patch an existing flight with data from a boarding pass (seat, cabin, pax name, pnr)."""
    from .flight_store import update_flight_from_bcbp
    update_flight_from_bcbp(existing_id, bcbp_leg)


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
            existing = find_existing_flight(leg["flight_number"], dep_date.isoformat(), user_id)
            if existing:
                _update_flight_from_bcbp(existing["id"], leg)
                flights_updated += 1
                logger.debug(
                    "User %d: Updated flight %s from BCBP",
                    user_id, leg["flight_number"],
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
                existing = find_existing_flight(leg["flight_number"], dep_date.isoformat(), user_id)
                if existing:
                    bcbp_matches.append({
                        "flight_id": existing["id"],
                        "passenger_name": leg.get("passenger_name"),
                        "seat": leg.get("seat"),
                    })

    saved = 0
    from .routes.boarding_passes import _save_boarding_pass

    if bcbp_matches:
        # Pair images with BCBP legs (best-effort: page N → leg N)
        for i, img_info in enumerate(images):
            match = bcbp_matches[i] if i < len(bcbp_matches) else bcbp_matches[-1]
            try:
                _save_boarding_pass(
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
                    _save_boarding_pass(
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
            user_id, saved, email_msg.message_id,
        )
    return saved


def _find_flight_from_email_text(email_msg, user_id: int) -> str | None:
    """Try to find a matching flight by scanning the email text for flight number patterns."""
    import re

    text = (email_msg.subject or "") + " " + (email_msg.body or "")
    # Common flight number patterns: 2-letter IATA code + 1-4 digits
    matches = re.findall(r'\b([A-Z]{2})\s*(\d{1,4})\b', text)
    for airline, num in matches:
        flight_number = f"{airline}{int(num)}"
        with db_conn() as conn:
            row = conn.execute(
                """SELECT id FROM flights
                   WHERE flight_number = ? AND user_id = ?
                   ORDER BY departure_datetime DESC LIMIT 1""",
                (flight_number, user_id),
            ).fetchone()
        if row:
            return row["id"]
    return None


def _send_boarding_pass_notification(flight_id: str, user_id: int) -> None:
    """Send a push notification about a new boarding pass, if the user has this preference enabled."""
    try:
        with db_conn() as conn:
            user = conn.execute(
                "SELECT notif_boarding_pass FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not user or not user["notif_boarding_pass"]:
                return

            flight = conn.execute(
                "SELECT flight_number, departure_airport, arrival_airport FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchone()
            if not flight:
                return

        from .push import already_sent, log_sent, send_push

        if already_sent(user_id, flight_id, "boarding_pass"):
            return

        route = f"{flight['departure_airport']} → {flight['arrival_airport']}"
        sent = send_push(
            user_id,
            {
                "title": "Boarding pass ready ✈",
                "body": f"{flight['flight_number']} · {route}",
                "url": f"/#/flights/{flight_id}",
            },
        )
        if sent:
            log_sent(user_id, flight_id, "boarding_pass")
    except Exception as e:
        logger.warning("Failed to send boarding pass notification: %s", e)


# ---------------------------------------------------------------------------
# Email processing pipeline
# ---------------------------------------------------------------------------


def _process_emails(emails: list, user_id: int) -> dict:
    """Parse a list of EmailMessage objects and persist flights to the DB.

    Returns a summary dict including ``new_flight_ids`` so callers can
    trigger aircraft lookups for freshly inserted flights.
    """
    emails_processed = 0
    flights_created = 0
    flights_updated = 0
    new_flight_ids: list[str] = []
    errors = []

    rules = get_builtin_rules()
    sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))

    for email_msg in emails:
        try:
            # --- BCBP boarding pass scan (always attempted first) ---
            bcbp_legs, bcbp_updated = _process_bcbp_email(email_msg, user_id)
            if bcbp_legs:
                flights_updated += bcbp_updated
                emails_processed += 1

            # --- HTML / rule-based or PDF parsing ---
            rule = match_rule_to_email(email_msg, sorted_rules)
            flights_data = (
                extract_flights_from_email(email_msg, rule)
                if rule
                else try_generic_pdf_extraction(email_msg)
            )

            if not flights_data:
                # If the email had flight-like keywords but we couldn't parse it,
                # save it to the failed queue for later reprocessing
                if email_has_flight_keywords(email_msg) and not bcbp_legs:
                    if rule:
                        reason = "rule matched but extraction empty"
                    elif email_msg.pdf_attachments or email_msg.html_body:
                        reason = "generic extractor failed"
                    else:
                        reason = "no rule matched"
                    save_failed_email(user_id, email_msg, reason)
                continue

            flights_data = [apply_airport_timezones(f) for f in flights_data]
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
                    existing = find_existing_flight(fn, dep_date, user_id)
                    if existing:
                        new_email_date = dt_to_iso(email_msg.date) if email_msg.date else None
                        existing_email_date = existing.get("email_date")
                        if new_email_date and existing_email_date and new_email_date > existing_email_date:
                            update_flight(existing["id"], flight_data, email_msg)
                            flights_updated += 1
                            logger.info("User %d: Updated flight %s with newer email", user_id, fn)
                        else:
                            logger.debug("User %d: Skipping older email for flight %s", user_id, fn)
                        continue

                # INSERT OR IGNORE deduplicates by email_message_id atomically
                new_id = insert_flight(flight_data, email_msg, user_id)
                if new_id:
                    flights_created += 1
                    new_flight_ids.append(new_id)
                    logger.info(
                        "User %d: Created flight: %s %s→%s",
                        user_id,
                        fn,
                        flight_data.get("departure_airport"),
                        flight_data.get("arrival_airport"),
                    )
                else:
                    logger.debug("User %d: Duplicate skipped: %s:%s", user_id, email_msg.message_id, fn)

            # --- Boarding pass extraction (check-in emails) ---
            try:
                _process_boarding_pass_email(email_msg, user_id)
            except Exception as e:
                logger.warning("User %d: Boarding pass extraction error: %s", user_id, e)

        except Exception as e:
            err = f"User {user_id}: Error processing email {email_msg.message_id}: {e}"
            logger.error(err, exc_info=True)
            errors.append(err)

    grouping_result = {}
    try:
        grouping_result = auto_group_flights(user_id=user_id)
    except Exception as e:
        logger.error("User %d: Grouping error: %s", user_id, e, exc_info=True)

    return {
        "emails_processed": emails_processed,
        "flights_created": flights_created,
        "flights_updated": flights_updated,
        "new_flight_ids": new_flight_ids,
        "grouping": grouping_result,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Public sync entry points
# ---------------------------------------------------------------------------


def run_email_sync_for_user(user: dict) -> dict:
    """
    Sync email for a single user. Called by run_email_sync() for each user,
    and also directly from the /api/sync/now endpoint.
    """
    from .auth import get_user_imap_settings

    user_id = user["id"]
    imap = get_user_imap_settings(user)

    if not imap["gmail_address"] or not imap["gmail_app_password"]:
        logger.warning("User %d: Gmail credentials not configured — skipping sync", user_id)
        return {"status": "skipped", "reason": "No credentials configured"}

    _set_sync_status(user_id, "running")
    sync_state = _get_sync_state(user_id)

    try:
        last_synced_at = sync_state.get("last_synced_at")
        last_rules_version = sync_state.get("last_rules_version", "")
        force_full = last_rules_version != PARSER_VERSION

        since_date = None
        if last_synced_at and not force_full:
            try:
                since_date = datetime.fromisoformat(last_synced_at)
                since_date = since_date - timedelta(days=1)
            except ValueError:
                since_date = None

        if since_date is None:
            first_sync_days = int(get_global_setting("first_sync_days", "90"))
            since_date = datetime.now(UTC) - timedelta(days=first_sync_days)

        if force_full:
            logger.info(
                "User %d: PARSER_VERSION changed — performing full rescan since %s",
                user_id,
                since_date,
            )
            try:
                retry_result = retry_failed_emails(user_id)
                logger.info("User %d: Retry result: %s", user_id, retry_result)
            except Exception as e:
                logger.warning("User %d: Failed email retry error: %s", user_id, e)

        rules = get_builtin_rules()
        sender_patterns = [r.sender_pattern for r in rules if r.sender_pattern]

        logger.info(
            "User %d: Fetching emails since %s from %s", user_id, since_date, imap["gmail_address"]
        )

        imap_result: ImapFetchResult = fetch_emails_imap(
            host=imap["imap_host"],
            port=imap["imap_port"],
            username=imap["gmail_address"],
            password=imap["gmail_app_password"],
            use_ssl=True,
            sender_patterns=sender_patterns,
            since_date=since_date,
            max_results=int(get_global_setting("max_emails_per_sync", "200")),
        )

        if not imap_result.success:
            err_msg = imap_result.error or "IMAP fetch failed"
            logger.error("User %d: IMAP fetch failed: %s", user_id, err_msg)
            _set_sync_status(user_id, "error", err_msg)
            return {"status": "error", "error": err_msg}

        emails = imap_result.emails
        logger.info("User %d: Fetched %d matching emails", user_id, len(emails))
        if emails:
            save_emails(emails)

        result = _process_emails(emails, user_id)

        if result["new_flight_ids"]:
            try:
                from .aircraft_sync import fetch_aircraft_for_new_flights

                fetch_aircraft_for_new_flights(result["new_flight_ids"])
            except Exception as e:
                logger.warning("User %d: Aircraft sync for new flights failed: %s", user_id, e)

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
            state = _get_sync_state(user_id)
            if state.get("status") == "running":
                _set_sync_status(user_id, "idle")
        except Exception:
            pass


def run_email_sync() -> dict:
    """
    Main sync function. Called by APScheduler every N minutes.
    Iterates all users and syncs each one.
    """
    with db_conn() as conn:
        users = conn.execute(
            "SELECT id, gmail_address, gmail_app_password, imap_host, imap_port FROM users"
        ).fetchall()

    if not users:
        logger.warning("No users found — skipping sync")
        return {"status": "skipped", "reason": "No users configured"}

    from .crypto import decrypt

    results = {}
    for user_row in users:
        user = dict(user_row)
        if user.get("gmail_app_password"):
            user["gmail_app_password"] = decrypt(user["gmail_app_password"])
        try:
            result = run_email_sync_for_user(user)
            results[user["id"]] = result
        except Exception as e:
            logger.error("Sync failed for user %d: %s", user["id"], e, exc_info=True)
            results[user["id"]] = {"status": "error", "error": str(e)}

    return {"status": "success", "users": results}


def reset_auto_flights(user_id: int | None = None) -> dict:
    """Delete all auto-synced flights and auto-generated trips for a user."""
    with db_write() as conn:
        if user_id is not None:
            deleted_flights = conn.execute(
                "DELETE FROM flights WHERE is_manually_added = 0 AND user_id = ?", (user_id,)
            ).rowcount
            deleted_trips = conn.execute(
                "DELETE FROM trips WHERE is_auto_generated = 1 AND user_id = ?", (user_id,)
            ).rowcount
        else:
            deleted_flights = conn.execute(
                "DELETE FROM flights WHERE is_manually_added = 0"
            ).rowcount
            deleted_trips = conn.execute("DELETE FROM trips WHERE is_auto_generated = 1").rowcount
    logger.info("Reset: deleted %d flights and %d trips", deleted_flights, deleted_trips)
    return {"deleted_flights": deleted_flights, "deleted_trips": deleted_trips}


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

    result = _process_emails([email_msg], user_id)

    new_flight_ids = []
    if result.get("flights_created", 0) > 0:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM flights WHERE aircraft_fetched_at IS NULL AND user_id = ? ORDER BY created_at DESC LIMIT 20",
                (user_id,),
            ).fetchall()
            new_flight_ids = [r["id"] for r in rows]

    if new_flight_ids:
        try:
            from .aircraft_sync import fetch_aircraft_for_new_flights

            fetch_aircraft_for_new_flights(new_flight_ids)
        except Exception as e:
            logger.warning("Aircraft sync for inbound email failed: %s", e)

    logger.info("SMTP inbound result: %s", result)
    return result
