"""Use cases for boarding passes: trip/flight-access checks + upload validation rules."""

from pathlib import Path

from .domain import BoardingPass, TripBoardingPass
from .errors import (
    BoardingPassNotFoundError,
    FileTooLargeError,
    FileTooSmallError,
    FlightAccessError,
    ImageNotFoundError,
    TripAccessError,
    UnsupportedFileTypeError,
)
from .repository import BoardingPassRepository

_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class BoardingPassService:
    def __init__(self, repository: BoardingPassRepository | None = None):
        self._repository = repository or BoardingPassRepository()

    def list_for_trip(self, trip_id: str, user_id: int) -> list[TripBoardingPass]:
        self._check_trip_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def list_for_flight(self, flight_id: str, user_id: int) -> list[BoardingPass]:
        if not self._repository.can_read_flight(flight_id, user_id):
            raise FlightAccessError(flight_id)
        return self._repository.list_for_flight(flight_id)

    def check_upload_allowed(self, flight_id: str, user_id: int, content_type: str | None) -> None:
        """Cheap pre-checks that don't require the (possibly large) file body.

        Callers should run this before reading the upload into memory.
        """
        if not self._repository.flight_owned_by(flight_id, user_id):
            raise FlightAccessError(flight_id)
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise UnsupportedFileTypeError(content_type)

    def save_upload(self, flight_id: str, image_bytes: bytes) -> str:
        if len(image_bytes) > _MAX_UPLOAD_BYTES:
            raise FileTooLargeError()
        if len(image_bytes) < 10:
            raise FileTooSmallError()

        return self._repository.save(
            flight_id=flight_id,
            image_bytes=image_bytes,
            passenger_name=None,
            seat=None,
            source_email_id=None,
            source_page=0,
        )

    def save_from_sync(
        self,
        *,
        flight_id: str,
        image_bytes: bytes,
        passenger_name: str | None,
        seat: str | None,
        source_email_id: str | None,
        source_page: int,
    ) -> str:
        """Persist a boarding pass extracted during email sync.

        No access checks: the caller (sync/pipeline.py) already scoped the flight lookup to
        this user, so ownership is implied.
        """
        return self._repository.save(
            flight_id=flight_id,
            image_bytes=image_bytes,
            passenger_name=passenger_name,
            seat=seat,
            source_email_id=source_email_id,
            source_page=source_page,
        )

    def get_image_path(self, bp_id: str, user_id: int) -> Path:
        bp = self._repository.get_with_read_access(bp_id, user_id)
        if bp is None:
            raise BoardingPassNotFoundError(bp_id)
        if not bp.image_path:
            raise ImageNotFoundError(bp_id)

        image_path = self._repository.safe_file_path(bp.image_path)
        if not image_path.exists():
            raise ImageNotFoundError(bp_id)
        return image_path

    def delete(self, bp_id: str, user_id: int) -> None:
        bp = self._repository.get_owned(bp_id, user_id)
        if bp is None:
            raise BoardingPassNotFoundError(bp_id)

        self._repository.delete(bp_id)
        if bp.image_path:
            self._repository.delete_image_file(bp.image_path)

    def _check_trip_access(self, trip_id: str, user_id: int) -> None:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            allowed = can_access_trip(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


boarding_pass_service = BoardingPassService()
