"""Tests for backend.expenses.guests_service (ownership checks + trip-scoped picker)."""

import uuid
from datetime import UTC, datetime

import pytest

from backend.tests.expenses.conftest import _seed_trip, _seed_user


class TestCreate:
    def test_rejects_blank_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)

        with pytest.raises(ValueError):
            service.create(owner_id, "   ")

    def test_strips_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)

        service.create(owner_id, "  Grandma  ")
        [guest] = service.list_mine(owner_id)
        assert guest.name == "Grandma"


class TestListForTrip:
    def test_raises_when_no_access(self, test_db):
        from backend.expenses.errors import TripAccessError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_for_trip(trip_id, other_id)

    def test_only_returns_guests_on_this_trip_not_the_whole_address_book(self, test_db):
        """The scoping that makes a per-trip roster worth having: your address
        book does not leak into a trip nobody was added to."""
        from backend.expenses.guests_repository import GuestRepository
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        service.create(owner_id, "Own unused guest")
        on_trip = service.create(owner_id, "Jimmy")[0].id
        GuestRepository().add_to_trip(trip_id, on_trip)

        assert {g.id for g in service.list_for_trip(trip_id, owner_id)} == {on_trip}


class TestTripRoster:
    """Adding and removing the guests on one trip. This is the feature the old
    derived membership made impossible: a guest created in Settings was in no
    picker because no expense named them, and no expense could name them because
    they were in no picker."""

    def test_a_guest_created_in_settings_can_be_put_on_a_trip(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = service.create(owner_id, "Jimmy")[0].id

        assert service.list_for_trip(trip_id, owner_id) == []
        service.add_to_trip(trip_id, guest_id, owner_id)
        assert [g.name for g in service.list_for_trip(trip_id, owner_id)] == ["Jimmy"]

    def test_adding_someone_elses_guest_is_refused(self, test_db):
        from backend.expenses.errors import GuestNotFoundError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        stranger = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        theirs = service.create(stranger, "Not yours")[0].id

        with pytest.raises(GuestNotFoundError):
            service.add_to_trip(trip_id, theirs, owner_id)

    def test_adding_to_a_trip_you_cannot_see_is_refused(self, test_db):
        from backend.expenses.errors import TripAccessError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        stranger = _seed_user(test_db)
        trip_id = _seed_trip(test_db, stranger)
        guest_id = service.create(owner_id, "Jimmy")[0].id

        with pytest.raises(TripAccessError):
            service.add_to_trip(trip_id, guest_id, owner_id)

    def test_removing_is_refused_while_an_expense_names_them(self, test_db):
        from backend.expenses.errors import GuestOnTripError
        from backend.expenses.guests_service import GuestService
        from backend.expenses.service import ExpenseService

        guests = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = guests.create(owner_id, "Jimmy")[0].id
        guests.add_to_trip(trip_id, guest_id, owner_id)

        ExpenseService().create_expense(
            trip_id, owner_id, "Cab", 30.0, "EUR", paid_by=("guest", guest_id)
        )

        with pytest.raises(GuestOnTripError):
            guests.remove_from_trip(trip_id, guest_id, owner_id)

    def test_removing_an_unused_guest_leaves_the_address_book_alone(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = service.create(owner_id, "Jimmy")[0].id
        service.add_to_trip(trip_id, guest_id, owner_id)

        service.remove_from_trip(trip_id, guest_id, owner_id)

        assert service.list_for_trip(trip_id, owner_id) == []
        assert [g.id for g in service.list_mine(owner_id)] == [guest_id]

    def test_naming_a_guest_on_an_expense_puts_them_on_the_trip(self, test_db):
        """`_acceptable_choices` accepts a guest the caller owns but has not yet
        added, so a quick-add in the expense form works. The roster has to keep
        up, or the expense would name somebody the trip says is not on it."""
        from backend.expenses.guests_service import GuestService
        from backend.expenses.service import ExpenseService

        guests = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = guests.create(owner_id, "Quick-added")[0].id

        ExpenseService().create_expense(
            trip_id, owner_id, "Lunch", 20.0, "EUR", participants=[("guest", guest_id)]
        )

        assert [g.id for g in guests.list_for_trip(trip_id, owner_id)] == [guest_id]


class TestRename:
    def test_rejects_blank_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")[0].id

        with pytest.raises(ValueError):
            service.rename(guest_id, owner_id, "   ")

    def test_raises_when_not_owner(self, test_db):
        from backend.expenses.errors import GuestNotFoundError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")[0].id

        with pytest.raises(GuestNotFoundError):
            service.rename(guest_id, other_id, "Grandpa")

    def test_renames_and_strips_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")[0].id

        updated = service.rename(guest_id, owner_id, "  Grandpa  ")
        assert updated.name == "Grandpa"
        [guest] = service.list_mine(owner_id)
        assert guest.name == "Grandpa"


class TestDelete:
    def test_raises_when_not_owner(self, test_db):
        from backend.expenses.errors import GuestNotFoundError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")[0].id

        with pytest.raises(GuestNotFoundError):
            service.delete(guest_id, other_id)

    def test_raises_when_in_use(self, test_db):
        import sqlite3

        from backend.expenses.errors import GuestInUseError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = service.create(owner_id, "Grandma")[0].id

        now = datetime.now(UTC).isoformat()
        conn = sqlite3.connect(test_db)
        conn.execute(
            """INSERT INTO trip_expenses
                   (id, trip_id, description, amount, currency, created_by,
                    paid_by_guest_id, created_at, updated_at)
               VALUES (?, ?, 'Cab', 30.0, 'EUR', ?, ?, ?, ?)""",
            (str(uuid.uuid4()), trip_id, owner_id, guest_id, now, now),
        )
        conn.commit()
        conn.close()

        with pytest.raises(GuestInUseError) as exc_info:
            service.delete(guest_id, owner_id)
        assert exc_info.value.guest_name == "Grandma"
        assert exc_info.value.expense_count == 1
        assert str(exc_info.value) == "Guest Grandma is used in 1 existing expense(s)"

    def test_deletes_when_unused_and_owned(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")[0].id

        service.delete(guest_id, owner_id)
        assert service.list_mine(owner_id) == []


class TestNamesAreOnePerson:
    """A person is not a row. Typing a name you have already used means the
    person it already names — the bug this fixes put two identical names in
    every payer select with nothing to tell them apart."""

    def test_the_same_name_reuses_the_existing_guest(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)

        first, created_first = service.create(owner_id, "Jimmy")
        second, created_second = service.create(owner_id, "Jimmy")

        assert created_first is True
        assert created_second is False
        assert second.id == first.id
        assert len(service.list_mine(owner_id)) == 1

    def test_case_and_accents_do_not_make_a_second_person(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)

        first, _ = service.create(owner_id, "João")
        again, created = service.create(owner_id, "  joao ")

        assert created is False
        assert again.id == first.id
        # The stored spelling is the one already on file, not what was typed:
        # the rest of the app calls this person "João".
        assert again.name == "João"

    def test_another_owners_guest_is_not_a_collision(self, test_db):
        """The address book is per-user, so two accounts can each know a Jimmy."""
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        mine = _seed_user(test_db)
        theirs = _seed_user(test_db)

        a, _ = service.create(mine, "Jimmy")
        b, created = service.create(theirs, "Jimmy")

        assert created is True
        assert a.id != b.id

    def test_renaming_onto_another_guest_is_refused(self, test_db):
        """Refused rather than merged: merging would have to move every expense
        naming one of them onto the other, which nobody asked for."""
        from backend.expenses.errors import GuestNameTakenError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        service.create(owner_id, "Jimmy")
        lucas, _ = service.create(owner_id, "Lucas")

        with pytest.raises(GuestNameTakenError) as exc:
            service.rename(lucas.id, owner_id, "jimmy")
        assert exc.value.guest_name == "Jimmy"

    def test_recasing_your_own_name_is_allowed(self, test_db):
        """A guest cannot collide with itself — fixing a capital is a rename."""
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest, _ = service.create(owner_id, "jimmy")

        updated = service.rename(guest.id, owner_id, "Jimmy")
        assert updated.name == "Jimmy"


class TestDeletingAGuestWhoIsOnATrip:
    """Deleting the address-book entry cascades `trip_guests` away, so it takes
    the guest off trips the caller is not looking at. Allowed, but never
    silently."""

    def test_is_refused_until_confirmed_and_names_the_trips(self, test_db):
        from backend.expenses.errors import GuestOnTripsError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id, name="Lisbon")
        guest, _ = service.create(owner_id, "Jimmy")
        service.add_to_trip(trip_id, guest.id, owner_id)

        with pytest.raises(GuestOnTripsError) as exc:
            service.delete(guest.id, owner_id)
        assert exc.value.trip_names == ["Lisbon"]
        assert service.list_mine(owner_id) != []

    def test_force_goes_through_and_takes_them_off_the_trip(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest, _ = service.create(owner_id, "Jimmy")
        service.add_to_trip(trip_id, guest.id, owner_id)

        service.delete(guest.id, owner_id, force=True)

        assert service.list_mine(owner_id) == []
        assert service.list_for_trip(trip_id, owner_id) == []

    def test_an_expense_reference_is_reported_before_the_trip_warning(self, test_db):
        """The in-use refusal is unconditional, so reporting the confirmable
        warning first would ask a question whose every answer is still a no."""
        from backend.expenses.errors import GuestInUseError
        from backend.expenses.guests_service import GuestService
        from backend.expenses.service import ExpenseService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest, _ = service.create(owner_id, "Jimmy")
        service.add_to_trip(trip_id, guest.id, owner_id)
        ExpenseService().create_expense(
            trip_id, owner_id, "Cab", 30.0, "EUR", paid_by=("guest", guest.id)
        )

        with pytest.raises(GuestInUseError):
            service.delete(guest.id, owner_id)
        # …and force does not override it either.
        with pytest.raises(GuestInUseError):
            service.delete(guest.id, owner_id, force=True)

    def test_a_guest_on_no_trip_deletes_without_a_question(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest, _ = service.create(owner_id, "Jimmy")

        service.delete(guest.id, owner_id)
        assert service.list_mine(owner_id) == []
