"""
Email sync job — fetches airline confirmation emails from Gmail,
parses them with the engine, and stores flights in SQLite.
Runs every 10 minutes via APScheduler.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from .config import settings
from .database import db_conn, db_write
from .parsers.builtin_rules import RULES_VERSION, get_builtin_rules
from .parsers.email_connector import fetch_emails_imap
from .parsers.engine import match_rule_to_email, extract_flights_from_email
from .grouping import auto_group_flights
from .timezone_utils import apply_airport_timezones
from .email_cache import save_emails, load_emails, cache_exists
from .parsers.bcbp import find_bcbp_in_text, parse_bcbp

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_to_iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _get_sync_state() -> dict:
    with db_conn() as conn:
        row = conn.execute('SELECT * FROM email_sync_state WHERE id = 1').fetchone()
        if row:
            return dict(row)
        return {}


def _set_sync_status(status: str, error: str = ''):
    with db_write() as conn:
        conn.execute(
            '''INSERT INTO email_sync_state (id, status, last_error)
               VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status = excluded.status, last_error = excluded.last_error''',
            (status, error),
        )


def _set_sync_complete(last_synced_at: str):
    with db_write() as conn:
        conn.execute(
            '''INSERT INTO email_sync_state (id, last_synced_at, last_rules_version, status, last_error)
               VALUES (1, ?, ?, 'idle', '')
               ON CONFLICT(id) DO UPDATE SET
                   last_synced_at = excluded.last_synced_at,
                   last_rules_version = excluded.last_rules_version,
                   status = 'idle',
                   last_error = ''
            ''',
            (last_synced_at, RULES_VERSION),
        )


def _flight_exists_by_message_id(msg_id_for_dedup: str) -> bool:
    with db_conn() as conn:
        row = conn.execute(
            'SELECT id FROM flights WHERE email_message_id = ?', (msg_id_for_dedup,)
        ).fetchone()
        return row is not None


def _find_existing_flight(flight_number: str, departure_date: str) -> dict | None:
    """Find an existing non-manual flight by flight_number and departure date."""
    with db_conn() as conn:
        row = conn.execute(
            '''SELECT * FROM flights
               WHERE flight_number = ?
               AND substr(departure_datetime, 1, 10) = ?
               AND is_manually_added = 0
               LIMIT 1''',
            (flight_number, departure_date),
        ).fetchone()
        return dict(row) if row else None


def _insert_flight(flight_data: dict, email_msg) -> str:
    """Insert a new flight row. Returns the new flight id."""
    now = _now_iso()
    flight_id = str(uuid.uuid4())

    dep_dt = flight_data.get('departure_datetime')
    arr_dt = flight_data.get('arrival_datetime')
    dep_iso = _dt_to_iso(dep_dt)
    arr_iso = _dt_to_iso(arr_dt)

    duration_minutes = None
    if dep_dt and arr_dt:
        delta = arr_dt - dep_dt
        minutes = int(delta.total_seconds() / 60)
        if minutes > 0:
            duration_minutes = minutes

    now_dt = datetime.now(timezone.utc)
    arr_dt_aware = arr_dt
    if arr_dt_aware and arr_dt_aware.tzinfo is None:
        arr_dt_aware = arr_dt_aware.replace(tzinfo=timezone.utc)
    status = 'completed' if (arr_dt_aware and arr_dt_aware < now_dt) else 'upcoming'

    msg_id_for_dedup = f"{email_msg.message_id}:{flight_data['flight_number']}"

    with db_write() as conn:
        conn.execute(
            '''INSERT INTO flights (
                id, trip_id, airline_name, airline_code, flight_number,
                booking_reference, departure_airport, departure_datetime,
                departure_terminal, departure_gate, arrival_airport, arrival_datetime,
                arrival_terminal, arrival_gate, passenger_name, seat, cabin_class,
                duration_minutes, status, departure_timezone, arrival_timezone,
                email_message_id, email_subject, email_date, email_body,
                is_manually_added, notes, created_at, updated_at
            ) VALUES (
                ?, NULL, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                0, NULL, ?, ?
            )''',
            (
                flight_id,
                flight_data.get('airline_name', ''),
                flight_data.get('airline_code', ''),
                flight_data['flight_number'],
                flight_data.get('booking_reference', ''),
                flight_data['departure_airport'],
                dep_iso,
                flight_data.get('departure_terminal', ''),
                flight_data.get('departure_gate', ''),
                flight_data['arrival_airport'],
                arr_iso,
                flight_data.get('arrival_terminal', ''),
                flight_data.get('arrival_gate', ''),
                flight_data.get('passenger_name', ''),
                flight_data.get('seat', ''),
                flight_data.get('cabin_class', ''),
                duration_minutes,
                status,
                flight_data.get('departure_timezone'),
                flight_data.get('arrival_timezone'),
                msg_id_for_dedup,
                (email_msg.subject or '')[:512],
                _dt_to_iso(email_msg.date),
                email_msg.html_body,
                now,
                now,
            ),
        )
    return flight_id


def _update_flight(existing_id: str, flight_data: dict, email_msg):
    """Update an existing flight with newer email data."""
    now = _now_iso()
    dep_dt = flight_data.get('departure_datetime')
    arr_dt = flight_data.get('arrival_datetime')
    dep_iso = _dt_to_iso(dep_dt)
    arr_iso = _dt_to_iso(arr_dt)

    duration_minutes = None
    if dep_dt and arr_dt:
        delta = arr_dt - dep_dt
        minutes = int(delta.total_seconds() / 60)
        if minutes > 0:
            duration_minutes = minutes

    now_dt = datetime.now(timezone.utc)
    arr_dt_aware = arr_dt
    if arr_dt_aware and arr_dt_aware.tzinfo is None:
        arr_dt_aware = arr_dt_aware.replace(tzinfo=timezone.utc)
    status = 'completed' if (arr_dt_aware and arr_dt_aware < now_dt) else 'upcoming'

    msg_id_for_dedup = f"{email_msg.message_id}:{flight_data['flight_number']}"

    with db_write() as conn:
        conn.execute(
            '''UPDATE flights SET
                departure_datetime = ?, arrival_datetime = ?,
                departure_terminal = ?, arrival_terminal = ?,
                departure_gate = ?, arrival_gate = ?,
                seat = ?, cabin_class = ?,
                booking_reference = ?, passenger_name = ?,
                duration_minutes = ?, status = ?,
                departure_timezone = ?, arrival_timezone = ?,
                email_message_id = ?, email_subject = ?, email_date = ?, email_body = ?,
                updated_at = ?
               WHERE id = ?''',
            (
                dep_iso, arr_iso,
                flight_data.get('departure_terminal', ''),
                flight_data.get('arrival_terminal', ''),
                flight_data.get('departure_gate', ''),
                flight_data.get('arrival_gate', ''),
                flight_data.get('seat', ''),
                flight_data.get('cabin_class', ''),
                flight_data.get('booking_reference', ''),
                flight_data.get('passenger_name', ''),
                duration_minutes, status,
                flight_data.get('departure_timezone'),
                flight_data.get('arrival_timezone'),
                msg_id_for_dedup,
                (email_msg.subject or '')[:512],
                _dt_to_iso(email_msg.date),
                email_msg.html_body,
                now,
                existing_id,
            ),
        )


def _update_flight_from_bcbp(existing_id: str, bcbp_leg: dict):
    """Patch an existing flight with data from a boarding pass (seat, cabin, pax name, pnr)."""
    updates = {}
    if bcbp_leg.get('seat'):
        updates['seat'] = bcbp_leg['seat']
    if bcbp_leg.get('cabin_class'):
        updates['cabin_class'] = bcbp_leg['cabin_class']
    if bcbp_leg.get('passenger_name'):
        updates['passenger_name'] = bcbp_leg['passenger_name']
    if bcbp_leg.get('booking_reference'):
        updates['booking_reference'] = bcbp_leg['booking_reference']
    if not updates:
        return
    updates['updated_at'] = _now_iso()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [existing_id]
    with db_write() as conn:
        conn.execute(f'UPDATE flights SET {set_clause} WHERE id = ?', values)


def _process_bcbp_email(email_msg) -> tuple[int, int]:
    """
    Scan email plain-text body for BCBP boarding pass strings.
    For each leg found:
      - If a matching flight exists (by flight_number + date): update seat/cabin/pax/pnr.
      - Otherwise: skip (we don't have enough info to create a complete flight from BCBP alone).

    Returns (bcbp_legs_found, flights_updated).
    """
    text = email_msg.body or ''
    if not text:
        return 0, 0

    candidates = find_bcbp_in_text(text)
    if not candidates:
        return 0, 0

    legs_found = 0
    updated = 0

    for candidate in candidates:
        legs = parse_bcbp(candidate)
        for leg in legs:
            legs_found += 1
            dep_date = leg.get('departure_date')
            if not dep_date:
                continue
            dep_date_str = dep_date.isoformat()
            existing = _find_existing_flight(leg['flight_number'], dep_date_str)
            if existing:
                _update_flight_from_bcbp(existing['id'], leg)
                updated += 1
                logger.info(
                    "BCBP update: %s on %s — seat=%s cabin=%s pax=%s",
                    leg['flight_number'], dep_date_str,
                    leg.get('seat'), leg.get('cabin_class'), leg.get('passenger_name'),
                )

    return legs_found, updated


def run_email_sync() -> dict:
    """
    Main sync function. Called by APScheduler every 10 minutes.
    Also callable directly via the /api/sync/now endpoint.
    """
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        logger.warning("Gmail credentials not configured — skipping sync")
        return {'status': 'skipped', 'reason': 'No credentials configured'}

    _set_sync_status('running')
    sync_state = _get_sync_state()

    try:
        # Determine fetch window
        last_synced_at = sync_state.get('last_synced_at')
        last_rules_version = sync_state.get('last_rules_version', '')

        # Force full rescan if rules version changed
        force_full = (last_rules_version != RULES_VERSION)

        since_date = None
        if last_synced_at and not force_full:
            try:
                since_date = datetime.fromisoformat(last_synced_at)
                # Go back 1 extra day to catch any edge cases
                since_date = since_date - timedelta(days=1)
            except ValueError:
                since_date = None

        if since_date is None:
            since_date = datetime.now(timezone.utc) - timedelta(days=settings.FIRST_SYNC_DAYS)

        if force_full:
            logger.info("Rules version changed — performing full rescan since %s", since_date)

        # Get sender patterns for pre-filtering
        rules = get_builtin_rules()
        sender_patterns = [r.sender_pattern for r in rules if r.sender_pattern]

        logger.info("Fetching emails since %s from %s", since_date, settings.GMAIL_ADDRESS)

        emails = fetch_emails_imap(
            host=settings.IMAP_HOST,
            port=settings.IMAP_PORT,
            username=settings.GMAIL_ADDRESS,
            password=settings.GMAIL_APP_PASSWORD,
            use_ssl=True,
            sender_patterns=sender_patterns,
            since_date=since_date,
            max_results=settings.MAX_EMAILS_PER_SYNC,
        )

        logger.info("Fetched %d matching emails", len(emails))
        if emails:
            save_emails(emails)

        emails_processed = 0
        flights_created = 0
        flights_updated = 0
        new_flight_ids: list[str] = []
        errors = []

        sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))

        for email_msg in emails:
            try:
                # --- BCBP boarding pass scan (primary source) ---
                bcbp_legs, bcbp_updated = _process_bcbp_email(email_msg)
                if bcbp_legs:
                    flights_updated += bcbp_updated
                    emails_processed += 1
                    # Still fall through to HTML parsing — boarding pass emails
                    # usually don't contain full itinerary data (no arrival time etc.),
                    # so we don't skip; we let the HTML parser create/update the flight
                    # record and the BCBP data was already merged above.

                # --- HTML / rule-based parsing (fallback / primary for booking emails) ---
                rule = match_rule_to_email(email_msg, sorted_rules)
                if not rule:
                    if bcbp_legs:
                        pass  # BCBP already handled
                    continue

                flights_data = extract_flights_from_email(email_msg, rule)
                if not flights_data:
                    continue

                # Fix local times → UTC using airport timezones
                flights_data = [apply_airport_timezones(f) for f in flights_data]

                if not bcbp_legs:
                    # Only count as "email processed" once
                    emails_processed += 1

                for flight_data in flights_data:
                    fn = flight_data.get('flight_number', '')
                    if not fn:
                        continue

                    msg_id_for_dedup = f"{email_msg.message_id}:{fn}"

                    # Skip if already processed this exact email+flight
                    if _flight_exists_by_message_id(msg_id_for_dedup):
                        logger.debug("Skipping duplicate: %s", msg_id_for_dedup)
                        continue

                    dep_dt = flight_data.get('departure_datetime')
                    dep_date = _dt_to_iso(dep_dt)[:10] if dep_dt else None

                    if dep_date:
                        existing = _find_existing_flight(fn, dep_date)
                        if existing:
                            existing_email_date = existing.get('email_date')
                            new_email_date = _dt_to_iso(email_msg.date) if email_msg.date else None

                            if (new_email_date and existing_email_date
                                    and new_email_date > existing_email_date):
                                _update_flight(existing['id'], flight_data, email_msg)
                                flights_updated += 1
                                logger.info("Updated flight %s with newer email", fn)
                            else:
                                logger.debug("Skipping older email for existing flight %s", fn)
                            continue

                    new_id = _insert_flight(flight_data, email_msg)
                    flights_created += 1
                    new_flight_ids.append(new_id)
                    logger.info("Created flight: %s %s→%s", fn,
                                flight_data.get('departure_airport'),
                                flight_data.get('arrival_airport'))

            except Exception as e:
                err = f"Error processing email {email_msg.message_id}: {e}"
                logger.error(err, exc_info=True)
                errors.append(err)

        # Run grouping
        grouping_result = {}
        try:
            grouping_result = auto_group_flights()
        except Exception as e:
            logger.error("Error during grouping: %s", e, exc_info=True)

        # Immediately try aircraft lookup for newly added flights
        if new_flight_ids:
            try:
                from .aircraft_sync import fetch_aircraft_for_new_flights
                fetch_aircraft_for_new_flights(new_flight_ids)
            except Exception as e:
                logger.warning("Aircraft sync for new flights failed: %s", e)

        # Update sync state
        _set_sync_complete(_now_iso())

        summary = {
            'status': 'success',
            'emails_fetched': len(emails),
            'emails_processed': emails_processed,
            'flights_created': flights_created,
            'flights_updated': flights_updated,
            'grouping': grouping_result,
            'errors': errors,
        }
        logger.info("Sync complete: %s", summary)
        return summary

    except Exception as e:
        err_msg = str(e)
        logger.error("Sync failed: %s", err_msg, exc_info=True)
        _set_sync_status('error', err_msg)
        return {'status': 'error', 'error': err_msg}


def _process_emails(emails: list) -> dict:
    """Shared logic: parse a list of EmailMessage objects and store flights."""
    emails_processed = 0
    flights_created = 0
    flights_updated = 0
    errors = []

    rules = get_builtin_rules()
    sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))

    for email_msg in emails:
        try:
            # --- BCBP boarding pass scan (primary source) ---
            bcbp_legs, bcbp_updated = _process_bcbp_email(email_msg)
            if bcbp_legs:
                flights_updated += bcbp_updated
                emails_processed += 1

            # --- HTML / rule-based parsing ---
            rule = match_rule_to_email(email_msg, sorted_rules)
            if not rule:
                continue

            flights_data = extract_flights_from_email(email_msg, rule)
            if not flights_data:
                continue

            flights_data = [apply_airport_timezones(f) for f in flights_data]
            if not bcbp_legs:
                emails_processed += 1

            for flight_data in flights_data:
                fn = flight_data.get('flight_number', '')
                if not fn:
                    continue

                msg_id_for_dedup = f"{email_msg.message_id}:{fn}"
                if _flight_exists_by_message_id(msg_id_for_dedup):
                    continue

                dep_dt = flight_data.get('departure_datetime')
                dep_date = _dt_to_iso(dep_dt)[:10] if dep_dt else None

                if dep_date:
                    existing = _find_existing_flight(fn, dep_date)
                    if existing:
                        new_email_date = _dt_to_iso(email_msg.date) if email_msg.date else None
                        existing_email_date = existing.get('email_date')
                        if new_email_date and existing_email_date and new_email_date > existing_email_date:
                            _update_flight(existing['id'], flight_data, email_msg)
                            flights_updated += 1
                        continue

                _insert_flight(flight_data, email_msg)
                flights_created += 1
                logger.info("Created flight: %s %s→%s", fn,
                            flight_data.get('departure_airport'),
                            flight_data.get('arrival_airport'))

        except Exception as e:
            err = f"Error processing email {email_msg.message_id}: {e}"
            logger.error(err, exc_info=True)
            errors.append(err)

    grouping_result = {}
    try:
        grouping_result = auto_group_flights()
    except Exception as e:
        logger.error("Grouping error: %s", e, exc_info=True)

    return {
        'emails_processed': emails_processed,
        'flights_created': flights_created,
        'flights_updated': flights_updated,
        'grouping': grouping_result,
        'errors': errors,
    }


def reset_auto_flights() -> dict:
    """Delete all auto-synced flights and auto-generated trips."""
    with db_write() as conn:
        deleted_flights = conn.execute(
            'DELETE FROM flights WHERE is_manually_added = 0'
        ).rowcount
        deleted_trips = conn.execute(
            'DELETE FROM trips WHERE is_auto_generated = 1'
        ).rowcount
    logger.info("Reset: deleted %d flights and %d trips", deleted_flights, deleted_trips)
    return {'deleted_flights': deleted_flights, 'deleted_trips': deleted_trips}


def process_inbound_email(email_msg) -> dict:
    """
    Process a single inbound email (e.g. from the SMTP server).
    Runs through BCBP + HTML parsing, groups flights, triggers aircraft sync.
    Returns a summary dict.
    """
    logger.info('SMTP inbound: processing email from %s — %s', email_msg.sender, email_msg.subject)
    result = _process_emails([email_msg])

    new_flight_ids = []
    if result.get('flights_created', 0) > 0:
        # Re-query the latest inserted flights to trigger aircraft sync
        with db_conn() as conn:
            rows = conn.execute(
                'SELECT id FROM flights WHERE aircraft_fetched_at IS NULL ORDER BY created_at DESC LIMIT 20'
            ).fetchall()
            new_flight_ids = [r['id'] for r in rows]

    if new_flight_ids:
        try:
            from .aircraft_sync import fetch_aircraft_for_new_flights
            fetch_aircraft_for_new_flights(new_flight_ids)
        except Exception as e:
            logger.warning('Aircraft sync for inbound email failed: %s', e)

    logger.info('SMTP inbound result: %s', result)
    return result


def run_cached_sync() -> dict:
    """
    Re-process emails from the local cache — no Gmail connection needed.
    Useful during development to test parsing changes quickly.
    """
    if not cache_exists():
        return {'status': 'error', 'error': 'No email cache found. Run a full sync first.'}

    _set_sync_status('running')
    try:
        emails = load_emails()
        result = _process_emails(emails)
        _set_sync_complete(_now_iso())
        summary = {'status': 'success', 'source': 'cache', 'emails_fetched': len(emails), **result}
        logger.info("Cached sync complete: %s", summary)
        return summary
    except Exception as e:
        err_msg = str(e)
        logger.error("Cached sync failed: %s", err_msg, exc_info=True)
        _set_sync_status('error', err_msg)
        return {'status': 'error', 'error': err_msg}
