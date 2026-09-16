"""Use cases for the trash: delete-to-trash, list, restore, purge.

Two rules are load-bearing.

**Deleting still deletes the live rows.** The snapshot goes into `trash`, then
the same deletion as before runs. Every read path in the app stays correct
without learning a "deleted" filter, and — the reason a traveller deletes a
trip in this app at all — the source mail's unique key on `flights` is free
again and its entry in the processed-mail ledger is dropped, so a mis-parsed
booking can be deleted and re-imported with a better parser and come back as
fresh rows. The cover image is kept until the trash entry is purged.

**Restore never clobbers.** Rows are put back with INSERT OR IGNORE, parents
first, so anything re-created in the meantime (a re-imported flight, a trip the
grouping rebuilt under the same id) is left as it is and reported as skipped.
A restored flight whose trip no longer exists is re-inserted ungrouped, where
the next sync's grouping picks it up.
"""

import logging

from ..activity.service import activity_service
from ..flights.repository import FlightRepository
from ..integrations.wikipedia.client import trip_image_path
from ..sync.repository import SyncRepository
from ..trip_documents.repository import TripDocumentRepository
from ..trips.repository import TripRepository
from .domain import RestoreResult, TrashItem
from .errors import TrashError
from .repository import TrashRepository

logger = logging.getLogger(__name__)


def _message_ids(flight_rows: list[dict]) -> list[str]:
    """Bare mail ids behind synced flights: `<msgid>:<flight number>` → `<msgid>`."""
    ids = []
    for row in flight_rows:
        emid = row.get("email_message_id")
        if emid and ":" in emid:
            ids.append(emid.rsplit(":", 1)[0])
    return ids


class TrashService:
    def __init__(
        self,
        repository: TrashRepository | None = None,
        trips: TripRepository | None = None,
        flights: FlightRepository | None = None,
        sync: SyncRepository | None = None,
    ):
        self._repository = repository or TrashRepository()
        self._trips = trips or TripRepository()
        self._flights = flights or FlightRepository()
        self._sync = sync or SyncRepository()

    # -- Delete-to-trash -------------------------------------------------------

    def trash_trip(self, trip_id: str, user_id: int) -> int:
        """Snapshot a trip and everything on it, then delete it. Owner-checked by the caller."""
        graph = self._repository.snapshot_trip(trip_id)
        trip_rows = graph.get("trips") or []
        if not trip_rows:
            raise TrashError("Trip not found", 404)
        trip = trip_rows[0]
        flights = graph.get("flights") or []
        summary = {
            "start_date": trip.get("start_date"),
            "end_date": trip.get("end_date"),
            "flight_count": len(flights),
            "stay_count": len(graph.get("trip_stays") or []),
            "segment_count": len(graph.get("trip_segments") or []),
            "expense_count": len(graph.get("trip_expenses") or []),
            "rating": trip.get("rating"),
            "has_notes": bool(trip.get("note")),
        }
        trash_id = self._repository.add(
            user_id, "trip", trip_id, trip.get("name") or trip_id, summary, graph
        )
        self._trips.delete_owned(trip_id, user_id)
        self._forget_mails(user_id, flights)
        activity_service.record(
            user_id,
            "trip.trashed",
            entity_type="trip",
            entity_id=trip_id,
            label=trip.get("name"),
            details={"trash_id": trash_id, **summary},
        )
        return trash_id

    def trash_flight(self, flight_id: str, user_id: int) -> int:
        graph = self._repository.snapshot_flight(flight_id)
        rows = graph.get("flights") or []
        if not rows:
            raise TrashError("Flight not found", 404)
        flight = rows[0]
        label = (
            f"{flight.get('flight_number')} {flight.get('departure_airport')} → "
            f"{flight.get('arrival_airport')}"
        )
        summary = {
            "departure_datetime": flight.get("departure_datetime"),
            "trip_id": flight.get("trip_id"),
            "booking_reference": flight.get("booking_reference"),
        }
        trash_id = self._repository.add(user_id, "flight", flight_id, label, summary, graph)
        self._flights.delete_owned(flight_id, user_id)
        self._forget_mails(user_id, rows)
        activity_service.record(
            user_id,
            "flight.trashed",
            entity_type="flight",
            entity_id=flight_id,
            label=label,
            details={"trash_id": trash_id, **summary},
        )
        return trash_id

    def _forget_mails(self, user_id: int, flight_rows: list[dict]) -> None:
        ids = _message_ids(flight_rows)
        if ids:
            self._sync.forget_emails(user_id, ids)

    # -- Read ------------------------------------------------------------------

    def list_items(self, user_id: int) -> list[TrashItem]:
        return self._repository.list_for_user(user_id)

    # -- Restore ---------------------------------------------------------------

    def restore(self, trash_id: int, user_id: int) -> RestoreResult:
        item = self._repository.get_owned(trash_id, user_id)
        graph = self._repository.payload(trash_id, user_id)
        if item is None or graph is None:
            raise TrashError("Nothing in the trash with that id", 404)

        if item.kind == "flight":
            # The trip may have gone since; an orphaned leg is still a leg and
            # the next grouping run will find it a trip.
            for row in graph.get("flights") or []:
                if row.get("trip_id") and self._trips.get_by_id(row["trip_id"]) is None:
                    row["trip_id"] = None

        outcome = self._repository.restore_and_remove(trash_id, graph)
        restored = {t: c["restored"] for t, c in outcome.items() if c["restored"]}
        skipped = {t: c["skipped"] for t, c in outcome.items() if c["skipped"]}

        if item.kind == "trip" and outcome.get("trips", {}).get("restored"):
            try:
                from ..utils import now_iso

                self._trips.recompute_span(item.entity_id, now_iso())
            except Exception as e:  # noqa: BLE001 - a span is derived; never fail a restore over it
                logger.warning(
                    "Could not recompute span for restored trip %s: %s", item.entity_id, e
                )

        activity_service.record(
            user_id,
            f"{item.kind}.restored",
            entity_type=item.kind,
            entity_id=item.entity_id,
            label=item.label,
            details={"restored": restored, "skipped": skipped},
        )
        return RestoreResult(
            kind=item.kind,
            entity_id=item.entity_id,
            label=item.label,
            restored=restored,
            skipped=skipped,
        )

    # -- Purge -----------------------------------------------------------------

    def purge(self, trash_id: int, user_id: int) -> None:
        item = self._repository.get_owned(trash_id, user_id)
        graph = self._repository.payload(trash_id, user_id)
        if item is None or graph is None:
            raise TrashError("Nothing in the trash with that id", 404)
        # Files the snapshot still pointed at: the cover image and any documents.
        if item.kind == "trip":
            webp = trip_image_path(item.entity_id)
            webp.unlink(missing_ok=True)
            webp.with_suffix(".jpg").unlink(missing_ok=True)
            docs = TripDocumentRepository()
            for row in graph.get("trip_documents") or []:
                if row.get("file_path"):
                    try:
                        docs.delete_file(row["file_path"])
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Could not delete document file %s: %s", row["file_path"], e)
        self._repository.remove(trash_id, user_id)
        activity_service.record(
            user_id,
            f"{item.kind}.purged",
            entity_type=item.kind,
            entity_id=item.entity_id,
            label=item.label,
        )


trash_service = TrashService()
