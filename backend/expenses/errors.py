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
