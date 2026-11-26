"""EmailReviewService: booking emails nothing could read, and what to do with them.

A mail lands here when the sync produced nothing from it (no flight, stay,
rental, update to a stored flight, KDE leg or booking) but it passes
``booking_signal.looks_like_flight_booking``, does not name a flight already
stored, and its sender is not on the user's ignore list. One booking code is
offered once.

From the review page the traveller can:

* **import** it — the legs they confirm are created as flights through the
  normal path (times as local time at each airport) and grouped into a trip;
* ask the **LLM for a draft** of those legs, on demand, when Ollama is set up.
  Nothing is saved from a draft until the traveller confirms it;
* **dismiss** it, or **ignore its sender** (dismisses that sender's pending
  mail and keeps future mail from it off the list).

Importing or dismissing clears the stored email text: it is kept only while
there is a decision to make.
"""

import logging
import re
import uuid
from datetime import datetime

from ..parsers.booking_signal import looks_like_flight_booking
from . import detect
from .repository import EmailReviewRepository

logger = logging.getLogger(__name__)

# An import left 'importing' this long was cut off (a crash, a restart): no
# import of a handful of legs takes minutes.
STALE_IMPORT_MINUTES = 15

# Enough for the excerpt and the LLM (which reads at most ~8k tokens anyway).
_MAX_BODY = 20_000


class CandidateNotFoundError(Exception):
    pass


class CandidateClosedError(Exception):
    """The email was already imported or dismissed, or another import of it is
    running."""


def _domain(sender: str | None) -> str:
    m = re.search(r"@([\w.-]+)", sender or "")
    return m.group(1).lower() if m else ""


class EmailReviewService:
    def __init__(self, repository: EmailReviewRepository | None = None) -> None:
        self._repository = repository or EmailReviewRepository()

    # --- During sync ---------------------------------------------------------

    def consider(self, email_msg, user_id: int) -> bool:
        """Put the email on the review list if it qualifies. Returns whether it
        was added."""
        message_id = getattr(email_msg, "message_id", None)
        subject = getattr(email_msg, "subject", "") or ""
        body = getattr(email_msg, "body", "") or ""
        if not message_id or not looks_like_flight_booking(subject, body):
            return False
        if self._repository.exists(user_id, message_id):
            return False
        sender = getattr(email_msg, "sender", "") or ""
        if self._repository.is_ignored(user_id, _domain(sender)):
            return False
        found = detect.hints(subject, body)
        # A flight number and a real airport code, or there is nothing to
        # import: a reminder about a tax-office visit has a reference that
        # looks like a flight number and no airport anywhere.
        if not found["flight_numbers"] or not found["airports"]:
            return False
        known = {
            detect.normalise_flight_number(fn)
            for fn in self._repository.known_flight_numbers(user_id)
        }
        every = detect.all_flight_numbers(detect.clean(f"{subject}\n{body}"))
        if any(detect.normalise_flight_number(fn) in known for fn in every):
            # About a flight already stored: a reminder, an upgrade offer, a
            # receipt for a bag — not a missing booking.
            return False
        reference = found.get("booking_reference")
        if reference and self._repository.pending_with_reference(user_id, reference):
            return False
        if self._repository.pending_restatement(
            user_id, found["flight_numbers"], reference, found["dates"]
        ):
            # The same booking restated (a confirmation and its receipt).
            return False
        date = getattr(email_msg, "date", None)
        self._repository.create(
            user_id,
            {
                "message_id": message_id,
                "sender": sender,
                "subject": subject,
                "email_date": date.isoformat() if date else None,
                "body_text": body[:_MAX_BODY],
                "hints": found,
                "booking_reference": reference,
            },
        )
        logger.info("User %d: offered %r for review", user_id, subject[:60])
        return True

    # --- The review page -----------------------------------------------------

    def _recover(self, user_id: int) -> None:
        """Undo imports cut off part-way (a crash, a restart): left 'importing'
        for longer than any import takes, their recorded flights are deleted
        and the emails are offered again."""
        from datetime import UTC, timedelta

        cutoff = (datetime.now(UTC) - timedelta(minutes=STALE_IMPORT_MINUTES)).isoformat()
        if n := self._repository.recover_stale_imports(user_id, cutoff):
            logger.warning("User %d: recovered %d interrupted email import(s)", user_id, n)

    def list_pending(self, user_id: int) -> list[dict]:
        self._recover(user_id)
        return self._repository.list_pending(user_id)

    def count_pending(self, user_id: int) -> int:
        self._recover(user_id)
        return self._repository.count_pending(user_id)

    def _get(self, user_id: int, candidate_id: str) -> dict:
        candidate = self._repository.get(user_id, candidate_id)
        if candidate is None:
            raise CandidateNotFoundError(candidate_id)
        return candidate

    def dismiss(self, user_id: int, candidate_id: str) -> None:
        self._get(user_id, candidate_id)
        self._repository.close(user_id, candidate_id, "dismissed")

    def ignore_sender(self, user_id: int, candidate_id: str) -> int:
        candidate = self._get(user_id, candidate_id)
        domain = _domain(candidate.get("sender"))
        if not domain:
            self._repository.close(user_id, candidate_id, "dismissed")
            return 1
        return self._repository.ignore_domain(user_id, domain)

    def list_ignored_senders(self, user_id: int) -> list[dict]:
        return self._repository.list_ignored(user_id)

    def stop_ignoring(self, user_id: int, domain: str) -> None:
        """Undo "Ignore this sender". Raises CandidateNotFoundError when the
        domain was not ignored."""
        if not self._repository.unignore_domain(user_id, domain.strip().lower()):
            raise CandidateNotFoundError(domain)

    def draft(self, user_id: int, candidate_id: str) -> list[dict]:
        """The LLM's reading of the email's legs, for the traveller to confirm.

        Every leg the model read is returned; a field the email does not
        support (flight number not printed, airport not named, time not
        printed) is left empty with the guess under ``doubts``. Times are wall
        clock at each airport ("2026-03-10T07:05"), the form's format. Raises
        LookupError when no LLM is configured.
        """
        from datetime import datetime

        from ..integrations.llm.parser import llm_available, llm_draft_flights
        from ..parsers.email_connector import EmailMessage

        candidate = self._get(user_id, candidate_id)
        if not llm_available():
            raise LookupError("No LLM is configured")
        sent = candidate.get("email_date")
        email_msg = EmailMessage(
            message_id=candidate["message_id"],
            sender=candidate.get("sender") or "",
            subject=candidate.get("subject") or "",
            body=candidate.get("body_text") or "",
            # The model resolves a year-less date ("16 NOV") against this.
            date=datetime.fromisoformat(sent) if sent else None,
        )
        # Fields the email does not support come back empty, with the model's
        # guess under "doubts" for the page to show beside the field.
        return llm_draft_flights(email_msg)

    def import_legs(self, user_id: int, candidate_id: str, legs: list[dict]) -> dict:
        """Create the confirmed legs as flights, group them, close the candidate.

        Returns the new flight ids and the trips they landed in.
        """
        from ..database import db_conn
        from ..flights.service import flight_service
        from ..sync.grouping import auto_group_flights
        from ..utils.dates import validate_flight_number

        self._get(user_id, candidate_id)
        if not legs:
            raise ValueError("Add at least one flight")
        # Every leg is checked before any is created, so a typo in the second
        # leg cannot leave the first one saved on its own.
        for i, leg in enumerate(legs, 1):
            number = (leg.get("flight_number") or "").replace(" ", "").upper()
            if not validate_flight_number(number):
                raise ValueError(f"Flight {i}: '{leg.get('flight_number')}' is not a flight number")
            for field in ("departure_airport", "arrival_airport"):
                if not re.fullmatch(r"[A-Za-z]{3}", leg.get(field) or ""):
                    raise ValueError(f"Flight {i}: an airport needs its three-letter code")
            for field in ("departure_datetime", "arrival_datetime"):
                value = leg.get(field) or ""
                # A real date and time, not just the shape: "2026-13-10T07:05"
                # would otherwise be stored as text with no zone or duration.
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", value):
                    raise ValueError(f"Flight {i}: both times are needed")
                try:
                    datetime.fromisoformat(value)
                except ValueError:
                    raise ValueError(f"Flight {i}: both times are needed") from None
        # Claimed before any flight is created, so a retry after a lost
        # response, a second tab or a double click cannot import it twice.
        if not self._repository.claim_for_import(user_id, candidate_id):
            raise CandidateClosedError(candidate_id)
        flight_ids: list[str] = []
        try:
            for leg in legs:
                number = leg["flight_number"].replace(" ", "").upper()
                # The id is chosen and recorded on the candidate *before* the
                # flight is written: whenever the process stops, recovery knows
                # every flight this import may have created (deleting one that
                # never got written is a no-op).
                flight_id = str(uuid.uuid4())
                self._repository.record_imported_flight(user_id, candidate_id, flight_id)
                flight_service.create_flight(
                    user_id,
                    {
                        "flight_number": number,
                        "airline_name": leg.get("airline_name") or number[:2],
                        "airline_code": number[:2],
                        "departure_airport": leg["departure_airport"].upper(),
                        "departure_datetime": leg["departure_datetime"],
                        "arrival_airport": leg["arrival_airport"].upper(),
                        "arrival_datetime": leg["arrival_datetime"],
                        "booking_reference": leg.get("booking_reference") or "",
                        "passenger_name": "",
                        "seat": "",
                        "cabin_class": "",
                        "departure_terminal": "",
                        "departure_gate": "",
                        "arrival_terminal": "",
                        "arrival_gate": "",
                        "notes": "",
                        "trip_id": None,
                    },
                    flight_id=flight_id,
                )
                flight_ids.append(flight_id)
            auto_group_flights(user_id=user_id)
        except Exception:
            if len(flight_ids) == len(legs):
                # Every leg was saved and only grouping failed: close it, or a
                # retry would create them a second time. Grouping runs again on
                # the next sync.
                self._repository.close(user_id, candidate_id, "imported")
            else:
                # A leg failed part-way: undo this attempt's flights (nothing
                # refers to them yet — grouping has not run) and hand the email
                # back, so a retry imports every leg once rather than half.
                self._repository.delete_flights(user_id, flight_ids)
                self._repository.release(user_id, candidate_id)
            raise
        self._repository.close(user_id, candidate_id, "imported")
        with db_conn() as conn:
            placeholders = ",".join("?" * len(flight_ids))
            rows = conn.execute(
                f"SELECT DISTINCT trip_id FROM flights WHERE id IN ({placeholders})",
                flight_ids,
            ).fetchall()
        return {
            "flight_ids": flight_ids,
            "trip_ids": [r["trip_id"] for r in rows if r["trip_id"]],
        }

    def close_if_imported(self, email_msg, user_id: int) -> None:
        """The sync read this email after all (a later sync, the LLM): if it was
        on the review list, take it off."""
        message_id = getattr(email_msg, "message_id", None)
        if message_id:
            self._repository.close_pending_message(user_id, message_id)


email_review_service = EmailReviewService()


def consider_for_review(email_msg, user_id: int) -> bool:
    """The pipeline's entry point (see ``sync/pipeline._process_emails``)."""
    return email_review_service.consider(email_msg, user_id)


def close_review_if_imported(email_msg, user_id: int) -> None:
    """The pipeline's call for an email that produced something."""
    email_review_service.close_if_imported(email_msg, user_id)
