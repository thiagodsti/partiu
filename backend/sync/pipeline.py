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
    try_generic_html_extraction,
    try_generic_pdf_extraction,
)
from ..parsers.gds_eticket import extract_gds_eticket
from ..parsers.validation import validate_flights
from ..settings.repository import SettingsRepository
from ..utils import calc_duration_minutes, calc_flight_status, dt_to_iso, now_iso
from .grouping import auto_group_flights
from .repository import SyncRepository

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
    new_flight_ids: list[str] = []
    errors = []

    rules = get_builtin_rules()
    sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))

    for email_msg in emails:
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

            # 3. Generic line-based scanners: last resort before the LLM.
            if not flights_data:
                flights_data = try_generic_html_extraction(
                    email_msg, rule
                ) or try_generic_pdf_extraction(email_msg)

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
