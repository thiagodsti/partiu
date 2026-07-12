"""Tests for backend.expenses.service (trip-access checks + validation rules)."""

from datetime import UTC, datetime

import pytest

from backend.tests.expenses.conftest import _seed_guest, _seed_trip, _seed_user


def _seed_accepted_share(db_path: str, trip_id: str, owner_id: int, collaborator_id: int) -> None:
    import sqlite3

    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trip_shares (trip_id, user_id, invited_by, status, created_at, updated_at)
           VALUES (?, ?, ?, 'accepted', ?, ?)""",
        (trip_id, collaborator_id, owner_id, now, now),
    )
    conn.commit()
    conn.close()


class TestListExpenses:
    def test_raises_when_no_access(self, test_db):
        from backend.expenses.service import ExpenseService, TripAccessError

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_expenses(trip_id, other_id)


class TestCreateExpense:
    def test_rejects_blank_description(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "   ", 10.0, "EUR")

    def test_rejects_zero_amount(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "Hotel", 0.0, "EUR")

    def test_rejects_negative_amount(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "Refund", -50.0, "EUR")

    def test_rejects_unsupported_currency(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "Item", 10.0, "XYZ")

    def test_uppercases_currency(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        service.create_expense(trip_id, user_id, "Taxi", 20.0, "usd")
        [expense] = service.list_expenses(trip_id, user_id)
        assert expense.currency == "USD"

    def test_strips_description(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        service.create_expense(trip_id, user_id, "  Hotel  ", 10.0, "EUR")
        [expense] = service.list_expenses(trip_id, user_id)
        assert expense.description == "Hotel"

    def test_validation_runs_before_access_check(self, test_db):
        """Bad input on someone else's trip should 400 (ValueError), not 404 (TripAccessError) —
        matches the original route's ordering."""
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, other_id, "", 10.0, "EUR")

    def test_raises_access_error_when_input_valid(self, test_db):
        from backend.expenses.service import ExpenseService, TripAccessError

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.create_expense(trip_id, other_id, "Item", 10.0, "EUR")


class TestUpdateExpense:
    def test_raises_when_expense_missing(self, test_db):
        from backend.expenses.service import ExpenseNotFoundError, ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ExpenseNotFoundError):
            service.update_expense(trip_id, "nonexistent-id", user_id, amount=100.0)

    def test_rejects_blank_description(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = service.create_expense(trip_id, user_id, "Hotel", 10.0, "EUR")

        with pytest.raises(ValueError):
            service.update_expense(trip_id, expense_id, user_id, description="   ")

    def test_updates_amount(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = service.create_expense(trip_id, user_id, "Hotel", 100.0, "EUR")

        service.update_expense(trip_id, expense_id, user_id, amount=250.0)
        [expense] = service.list_expenses(trip_id, user_id)
        assert expense.amount == 250.0


class TestDeleteExpense:
    def test_raises_when_expense_missing(self, test_db):
        from backend.expenses.service import ExpenseNotFoundError, ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ExpenseNotFoundError):
            service.delete_expense(trip_id, "nonexistent-id", user_id)

    def test_deletes_existing_expense(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = service.create_expense(trip_id, user_id, "Hotel", 10.0, "EUR")

        service.delete_expense(trip_id, expense_id, user_id)
        assert service.list_expenses(trip_id, user_id) == []


class TestListParticipantsForTrip:
    def test_includes_owner_only_by_default(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        participants = service.list_participants_for_trip(trip_id, owner_id)
        assert [(p.type, p.id) for p in participants] == [("user", owner_id)]

    def test_includes_accepted_collaborators_only(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        collaborator_id = _seed_user(test_db)
        pending_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_accepted_share(test_db, trip_id, owner_id, collaborator_id)

        participants = service.list_participants_for_trip(trip_id, owner_id)
        ids = {(p.type, p.id) for p in participants}
        assert ("user", collaborator_id) in ids
        assert ("user", pending_id) not in ids

    def test_excludes_guests_not_yet_used_on_this_trip(self, test_db):
        """Guests are scoped per trip — an unused guest from the caller's address
        book must not show up as a suggested participant on a trip it's never
        been tagged on."""
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = _seed_guest(test_db, owner_id, "Grandma")

        participants = service.list_participants_for_trip(trip_id, owner_id)
        assert ("guest", guest_id) not in {(p.type, p.id) for p in participants}

    def test_includes_guests_already_used_on_this_trip(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = _seed_guest(test_db, owner_id, "Grandma")
        service.create_expense(trip_id, owner_id, "Cab", 30.0, "EUR", paid_by=("guest", guest_id))

        participants = service.list_participants_for_trip(trip_id, owner_id)
        assert ("guest", guest_id) in {(p.type, p.id) for p in participants}

    def test_guest_used_on_one_trip_does_not_leak_into_another(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        trip_a = _seed_trip(test_db, owner_id)
        trip_b = _seed_trip(test_db, owner_id)
        guest_id = _seed_guest(test_db, owner_id, "Grandma")
        service.create_expense(trip_a, owner_id, "Cab", 30.0, "EUR", paid_by=("guest", guest_id))

        participants_b = service.list_participants_for_trip(trip_b, owner_id)
        assert ("guest", guest_id) not in {(p.type, p.id) for p in participants_b}


class TestCreateExpenseWithSplits:
    def test_defaults_paid_by_to_creator_and_participants_to_everyone(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        collaborator_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_accepted_share(test_db, trip_id, owner_id, collaborator_id)

        service.create_expense(trip_id, owner_id, "Lunch", 100.0, "EUR")
        [expense] = service.list_expenses(trip_id, owner_id)

        assert (expense.paid_by.type, expense.paid_by.id) == ("user", owner_id)
        keys = {(p.type, p.id) for p in expense.participants}
        assert keys == {("user", owner_id), ("user", collaborator_id)}

    def test_explicit_empty_participants_is_not_defaulted(self, test_db):
        """An explicit `participants: []` means "don't split this with anyone" —
        it must not silently fall back to the default (everyone on the trip)."""
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        collaborator_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_accepted_share(test_db, trip_id, owner_id, collaborator_id)

        service.create_expense(trip_id, owner_id, "Personal item", 20.0, "EUR", participants=[])
        [expense] = service.list_expenses(trip_id, owner_id)

        assert expense.participants == []

    def test_explicit_paid_by_and_participants(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        collaborator_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_accepted_share(test_db, trip_id, owner_id, collaborator_id)
        guest_id = _seed_guest(test_db, owner_id, "Grandma")

        service.create_expense(
            trip_id,
            owner_id,
            "Lunch",
            100.0,
            "EUR",
            paid_by=("user", owner_id),
            participants=[("user", owner_id), ("guest", guest_id)],
        )
        [expense] = service.list_expenses(trip_id, owner_id)
        keys = {(p.type, p.id) for p in expense.participants}
        assert keys == {("user", owner_id), ("guest", guest_id)}

    def test_rejects_paid_by_not_on_trip(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        stranger_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(ValueError):
            service.create_expense(
                trip_id, owner_id, "Lunch", 100.0, "EUR", paid_by=("user", stranger_id)
            )

    def test_rejects_participant_not_on_trip(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        stranger_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(ValueError):
            service.create_expense(
                trip_id,
                owner_id,
                "Lunch",
                100.0,
                "EUR",
                participants=[("user", owner_id), ("user", stranger_id)],
            )


class TestUpdateExpenseSplits:
    def test_update_paid_by(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        collaborator_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_accepted_share(test_db, trip_id, owner_id, collaborator_id)
        expense_id = service.create_expense(trip_id, owner_id, "Lunch", 100.0, "EUR")

        service.update_expense(trip_id, expense_id, owner_id, paid_by=("user", collaborator_id))

        [expense] = service.list_expenses(trip_id, owner_id)
        assert (expense.paid_by.type, expense.paid_by.id) == ("user", collaborator_id)

    def test_update_participants(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        collaborator_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_accepted_share(test_db, trip_id, owner_id, collaborator_id)
        expense_id = service.create_expense(trip_id, owner_id, "Lunch", 100.0, "EUR")

        service.update_expense(trip_id, expense_id, owner_id, participants=[("user", owner_id)])

        [expense] = service.list_expenses(trip_id, owner_id)
        assert [(p.type, p.id) for p in expense.participants] == [("user", owner_id)]


class TestGetBalances:
    def test_equal_split_balances(self, test_db):
        """The scenario from the design discussion: a 100 EUR lunch paid by the
        owner, split 4 ways between owner, their collaborator (spouse) and two
        guests — owner nets +75, everyone else nets -25."""
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        spouse_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_accepted_share(test_db, trip_id, owner_id, spouse_id)
        friend1 = _seed_guest(test_db, owner_id, "Friend1")
        friend2 = _seed_guest(test_db, owner_id, "Friend2")

        service.create_expense(
            trip_id,
            owner_id,
            "Lunch",
            100.0,
            "EUR",
            paid_by=("user", owner_id),
            participants=[
                ("user", owner_id),
                ("user", spouse_id),
                ("guest", friend1),
                ("guest", friend2),
            ],
        )

        balances = service.get_balances(trip_id, owner_id)
        by_key = {(b.type, b.id): b.net for b in balances["EUR"]}
        assert by_key[("user", owner_id)] == pytest.approx(75.0)
        assert by_key[("user", spouse_id)] == pytest.approx(-25.0)
        assert by_key[("guest", friend1)] == pytest.approx(-25.0)
        assert by_key[("guest", friend2)] == pytest.approx(-25.0)

    def test_balances_grouped_per_currency(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        service.create_expense(trip_id, owner_id, "Hotel", 200.0, "EUR")
        service.create_expense(trip_id, owner_id, "Train", 500.0, "SEK")

        balances = service.get_balances(trip_id, owner_id)
        assert set(balances.keys()) == {"EUR", "SEK"}
        assert balances["EUR"][0].net == pytest.approx(0.0)  # sole participant = payer
        assert balances["SEK"][0].net == pytest.approx(0.0)

    def test_raises_when_no_access(self, test_db):
        from backend.expenses.service import ExpenseService, TripAccessError

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.get_balances(trip_id, other_id)
