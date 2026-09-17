"""Shared exceptions for the expenses feature (expenses + guests sub-features)."""


class TripAccessError(Exception):
    """Raised when the user cannot access the given trip."""


class ExpenseNotFoundError(Exception):
    """Raised when the expense does not exist for the given trip."""


class GuestNotFoundError(Exception):
    """Raised when the guest does not exist or is not owned by the current user."""


class GuestInUseError(Exception):
    """Raised when attempting to delete a guest referenced by an existing expense."""

    def __init__(self, guest_name: str, expense_count: int):
        self.guest_name = guest_name
        self.expense_count = expense_count
        super().__init__(f"Guest {guest_name} is used in {expense_count} existing expense(s)")


class GuestOnTripError(Exception):
    """Raised when taking a guest off a trip that still has an expense naming them.

    Same rule as deleting a guest outright: a reference must never be left
    pointing at somebody the trip says is not on it.
    """

    def __init__(self, guest_name: str):
        self.guest_name = guest_name
        super().__init__(f"Guest {guest_name} is named by an expense on this trip")


class GuestNameTakenError(Exception):
    """Raised when a name would collide with another guest of the same owner.

    Folded, so "Jimmy" and "jimmy" are the same person — see
    `GuestRepository.find_by_name`.
    """

    def __init__(self, guest_name: str):
        self.guest_name = guest_name
        super().__init__(f"You already have a guest named {guest_name}")


class GuestOnTripsError(Exception):
    """Raised when deleting a guest who is still on one or more trips.

    Deleting the address-book entry cascades their roster rows away, so the
    guest disappears from trips the caller was not looking at. That is a
    legitimate thing to want and a terrible thing to do silently, so the trips
    are named and the caller has to ask again with `force=True`.
    """

    def __init__(self, guest_name: str, trip_names: list[str]):
        self.guest_name = guest_name
        self.trip_names = trip_names
        joined = ", ".join(trip_names)
        super().__init__(f"Guest {guest_name} is on {len(trip_names)} trip(s): {joined}")
