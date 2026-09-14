"""A trip budget, and what counts against it.

The interesting decision is what "spent" means when expenses are split. It is
the caller's **own share** — an expense split four ways counts a quarter of it,
whoever paid. What you paid out is a cash-flow question, and the balances view
already answers that one; a budget is about what the trip costs you.
"""

import pytest

from backend.database import db_write
from backend.expenses.service import ExpenseService


def _user(username: str) -> int:
    with db_write() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
            (username, "x", 0, "2026-01-01T00:00:00"),
        )
        return cur.lastrowid


def _trip(trip_id: str, user_id: int) -> None:
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, is_auto_generated, user_id, created_at, updated_at)
               VALUES (?, 'Trip', '[]', 0, ?, ?, ?)""",
            (trip_id, user_id, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )


def _collaborator(trip_id: str, owner_id: int, username: str) -> int:
    """Only people on the trip can be tagged on its expenses, so a second user
    has to be an accepted collaborator before they can share a bill."""
    user_id = _user(username)
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trip_shares (trip_id, user_id, invited_by, status, created_at, updated_at)
               VALUES (?, ?, ?, 'accepted', ?, ?)""",
            (trip_id, user_id, owner_id, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
    return user_id


@pytest.fixture
def setup(test_db):
    user_id = _user("budgeter")
    _trip("t1", user_id)
    return ExpenseService(), user_id


class TestSpendIsYourOwnShare:
    def test_a_split_expense_counts_only_your_part(self, setup):
        service, user_id = setup
        other = _collaborator("t1", user_id, "companion")
        service.create_expense(
            "t1",
            user_id,
            "Lunch",
            100.0,
            "EUR",
            participants=[("user", user_id), ("user", other)],
        )
        service.set_budget("t1", user_id, 500.0, "EUR")

        assert service.get_budget("t1", user_id).spent == 50.0

    def test_paying_for_others_does_not_spend_your_budget(self, setup):
        """You are settling up for other people, not spending on yourself."""
        service, user_id = setup
        other = _collaborator("t1", user_id, "friend")
        service.create_expense(
            "t1",
            user_id,
            "Their taxi",
            60.0,
            "EUR",
            paid_by=("user", user_id),
            participants=[("user", other)],
        )
        service.set_budget("t1", user_id, 500.0, "EUR")

        assert service.get_budget("t1", user_id).spent == 0.0

    def test_an_expense_someone_else_paid_still_counts_your_share(self, setup):
        """The cost is yours even when the card was not."""
        service, user_id = setup
        other = _collaborator("t1", user_id, "payer")
        service.create_expense(
            "t1",
            user_id,
            "Hotel",
            400.0,
            "EUR",
            paid_by=("user", other),
            participants=[("user", user_id), ("user", other)],
        )
        service.set_budget("t1", user_id, 500.0, "EUR")

        assert service.get_budget("t1", user_id).spent == 200.0

    def test_shares_accumulate_across_expenses(self, setup):
        service, user_id = setup
        other = _collaborator("t1", user_id, "ana")
        service.create_expense(
            "t1",
            user_id,
            "Lunch",
            100.0,
            "EUR",
            participants=[("user", user_id), ("user", other)],
        )
        service.create_expense("t1", user_id, "Taxi", 30.0, "EUR", participants=[("user", user_id)])
        service.set_budget("t1", user_id, 500.0, "EUR")

        assert service.get_budget("t1", user_id).spent == 80.0


class TestCurrencies:
    def test_other_currencies_are_reported_not_converted(self, setup):
        """There are no exchange rates here; a converted figure would be a guess
        wearing the clothes of a fact."""
        service, user_id = setup
        service.create_expense(
            "t1", user_id, "Hotel", 420.0, "EUR", participants=[("user", user_id)]
        )
        service.create_expense(
            "t1", user_id, "Train", 900.0, "SEK", participants=[("user", user_id)]
        )
        service.set_budget("t1", user_id, 800.0, "EUR")

        status = service.get_budget("t1", user_id)
        assert status.spent == 420.0
        assert status.uncounted == {"SEK": 900.0}

    def test_without_a_budget_every_currency_is_uncounted(self, setup):
        service, user_id = setup
        service.create_expense(
            "t1", user_id, "Hotel", 420.0, "EUR", participants=[("user", user_id)]
        )

        status = service.get_budget("t1", user_id)
        assert status.budget is None
        assert status.spent == 0.0
        assert status.uncounted == {"EUR": 420.0}


class TestBudgetIsPersonal:
    def test_two_people_on_one_trip_keep_separate_budgets(self, setup):
        service, user_id = setup
        other = _collaborator("t1", user_id, "collaborator")

        service.set_budget("t1", user_id, 500.0, "EUR")
        service.set_budget("t1", other, 900.0, "SEK")

        mine = service.get_budget("t1", user_id).budget
        theirs = service.get_budget("t1", other).budget
        assert (mine.amount, mine.currency) == (500.0, "EUR")
        assert (theirs.amount, theirs.currency) == (900.0, "SEK")


class TestValidation:
    def test_a_budget_must_be_positive(self, setup):
        service, user_id = setup
        with pytest.raises(ValueError):
            service.set_budget("t1", user_id, 0.0, "EUR")

    def test_currency_must_be_one_we_support(self, setup):
        service, user_id = setup
        with pytest.raises(ValueError):
            service.set_budget("t1", user_id, 100.0, "XYZ")

    def test_clearing_leaves_the_spend_visible(self, setup):
        service, user_id = setup
        service.create_expense(
            "t1", user_id, "Hotel", 420.0, "EUR", participants=[("user", user_id)]
        )
        service.set_budget("t1", user_id, 800.0, "EUR")
        service.clear_budget("t1", user_id)

        status = service.get_budget("t1", user_id)
        assert status.budget is None
        assert status.uncounted == {"EUR": 420.0}


class TestBulkBudgetsForTheTripsList:
    """The trips list renders a card per trip, so it reads every budget at once.

    `budgets_for_trips` is the bulk twin of `get_budget`, and the two must agree:
    the SQL divides each expense by its participant count exactly as the Python
    does, and an expense the caller is not tagged in never joins.
    """

    def test_matches_the_single_trip_answer(self, setup):
        service, user_id = setup
        other = _collaborator("t1", user_id, "bulk-mate")
        service.create_expense(
            "t1",
            user_id,
            "Lunch",
            100.0,
            "EUR",
            participants=[("user", user_id), ("user", other)],
        )
        service.create_expense("t1", user_id, "Taxi", 30.0, "EUR", participants=[("user", user_id)])
        service.set_budget("t1", user_id, 500.0, "EUR")

        one = service.get_budget("t1", user_id)
        bulk = service.budgets_for_trips(user_id, ["t1"])["t1"]
        assert bulk.spent == one.spent == 80.0
        assert bulk.budget.amount == 500.0

    def test_paying_for_others_does_not_count_in_bulk_either(self, setup):
        service, user_id = setup
        other = _collaborator("t1", user_id, "bulk-friend")
        service.create_expense(
            "t1",
            user_id,
            "Their taxi",
            60.0,
            "EUR",
            paid_by=("user", user_id),
            participants=[("user", other)],
        )
        service.set_budget("t1", user_id, 500.0, "EUR")

        assert service.budgets_for_trips(user_id, ["t1"])["t1"].spent == 0.0

    def test_only_trips_with_a_budget_come_back(self, setup):
        """A card with no budget has nothing to show, so it is not in the map."""
        service, user_id = setup
        _trip("t2", user_id)
        service.set_budget("t1", user_id, 500.0, "EUR")

        result = service.budgets_for_trips(user_id, ["t1", "t2"])
        assert set(result) == {"t1"}

    def test_other_currencies_stay_uncounted_in_bulk(self, setup):
        service, user_id = setup
        service.create_expense(
            "t1", user_id, "Train", 900.0, "SEK", participants=[("user", user_id)]
        )
        service.create_expense(
            "t1", user_id, "Hotel", 420.0, "EUR", participants=[("user", user_id)]
        )
        service.set_budget("t1", user_id, 800.0, "EUR")

        status = service.budgets_for_trips(user_id, ["t1"])["t1"]
        assert status.spent == 420.0
        assert status.uncounted == {"SEK": 900.0}

    def test_no_trips_reads_nothing(self, setup):
        service, user_id = setup
        assert service.budgets_for_trips(user_id, []) == {}

    def test_another_user_sees_their_own_budget_only(self, setup):
        service, user_id = setup
        other = _collaborator("t1", user_id, "bulk-other")
        service.set_budget("t1", user_id, 500.0, "EUR")

        assert service.budgets_for_trips(other, ["t1"]) == {}
