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


def _guest(owner_id: int, name: str) -> int:
    with db_write() as conn:
        cur = conn.execute(
            "INSERT INTO guests (owner_id, name, created_at) VALUES (?, ?, ?)",
            (owner_id, name, "2026-01-01T00:00:00"),
        )
        return cur.lastrowid


class TestASharedBudget:
    """Two people travelling on one purse. Spend is their *combined* share, so
    it makes no difference which of them held the card — which is the whole
    reason the member list exists."""

    def test_both_halves_of_a_split_count_against_a_shared_budget(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.create_expense(
            "t1",
            user_id,
            "Hotel",
            300.0,
            "EUR",
            participants=[("user", user_id), ("user", partner)],
        )
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )

        assert service.get_budget("t1", user_id).spent == 300.0

    def test_a_third_person_on_the_bill_still_only_costs_the_pair_their_share(self, setup):
        """A three-way split costs a two-person budget two thirds, not all of it."""
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        friend = _collaborator("t1", user_id, "friend")
        service.create_expense(
            "t1",
            user_id,
            "Dinner",
            90.0,
            "EUR",
            participants=[("user", user_id), ("user", partner), ("user", friend)],
        )
        service.set_budget(
            "t1", user_id, 500.0, "EUR", members=[("user", user_id), ("user", partner)]
        )

        assert service.get_budget("t1", user_id).spent == 60.0

    def test_an_expense_neither_member_is_in_counts_nothing(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        friend = _collaborator("t1", user_id, "friend")
        service.create_expense(
            "t1", user_id, "Their taxi", 40.0, "EUR", participants=[("user", friend)]
        )
        service.set_budget(
            "t1", user_id, 500.0, "EUR", members=[("user", user_id), ("user", partner)]
        )

        assert service.get_budget("t1", user_id).spent == 0.0

    def test_the_member_sees_the_same_budget_and_the_same_bar(self, setup):
        """The point of sharing: the partner opens the trip and reads the same
        figures, without having set anything up themselves."""
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.create_expense(
            "t1",
            user_id,
            "Hotel",
            300.0,
            "EUR",
            participants=[("user", user_id), ("user", partner)],
        )
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )

        theirs = service.get_budget("t1", partner)
        assert theirs.budget is not None
        assert theirs.budget.amount == 1000.0
        assert theirs.spent == 300.0
        assert theirs.budget.owner_user_id == user_id
        assert theirs.budget.owner_username == "budgeter"

    def test_a_companion_without_an_account_can_be_a_member(self, setup):
        """The common case is a spouse with no Partiu login — that is what
        guests are for, so a guest has to be shareable with."""
        service, user_id = setup
        wife = _guest(user_id, "Barbara")
        service.create_expense(
            "t1",
            user_id,
            "Hotel",
            200.0,
            "EUR",
            participants=[("user", user_id), ("guest", wife)],
        )
        service.set_budget(
            "t1", user_id, 800.0, "EUR", members=[("user", user_id), ("guest", wife)]
        )

        assert service.get_budget("t1", user_id).spent == 200.0

    def test_a_budget_you_already_had_wins_over_one_shared_with_you(self, setup):
        """Setting a budget is a deliberate act; being added to someone else's
        is not, so it must not silently replace what you chose.

        Note the ordering: once you *are* in a shared budget, saving edits that
        one — there is no second gesture meaning "and also start a private one".
        Unchecking yourself from its member list is how you leave, and the save
        after that is your own again.
        """
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget("t1", partner, 250.0, "EUR")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )

        assert service.get_budget("t1", partner).budget.amount == 250.0
        assert service.get_budget("t1", user_id).budget.amount == 1000.0

    def test_leaving_a_shared_budget_frees_you_to_set_your_own(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )
        service.set_budget("t1", partner, 1000.0, "EUR", members=[("user", user_id)])
        service.set_budget("t1", partner, 250.0, "EUR")

        assert service.get_budget("t1", partner).budget.amount == 250.0
        assert service.get_budget("t1", partner).budget.owner_user_id == partner
        assert service.get_budget("t1", user_id).budget.amount == 1000.0

    def test_a_member_editing_edits_the_shared_budget_not_a_private_copy(self, setup):
        """Otherwise "we share a budget" becomes two budgets the moment the
        other person adjusts the amount."""
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )
        service.set_budget("t1", partner, 1200.0, "EUR")

        owner_view = service.get_budget("t1", user_id)
        assert owner_view.budget.amount == 1200.0
        assert owner_view.budget.owner_user_id == user_id

    def test_the_owner_is_always_a_member(self, setup):
        """A budget belongs to at least the person who made it, whatever the
        member list leaves out."""
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget("t1", user_id, 500.0, "EUR", members=[("user", partner)])

        members = service.get_budget("t1", user_id).budget.members
        assert ("user", user_id) in [(m.type, m.id) for m in members]

    def test_members_default_to_you_alone(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.create_expense(
            "t1",
            user_id,
            "Hotel",
            300.0,
            "EUR",
            participants=[("user", user_id), ("user", partner)],
        )
        service.set_budget("t1", user_id, 1000.0, "EUR")

        status = service.get_budget("t1", user_id)
        assert [(m.type, m.id) for m in status.budget.members] == [("user", user_id)]
        assert status.spent == 150.0

    def test_saving_without_a_member_list_keeps_the_one_it_has(self, setup):
        """A client that predates sharing must not silently un-share a budget by
        saving a new amount."""
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )
        service.set_budget("t1", user_id, 1100.0, "EUR")

        members = service.get_budget("t1", user_id).budget.members
        assert ("user", partner) in [(m.type, m.id) for m in members]

    def test_someone_not_on_the_trip_cannot_be_a_member(self, setup):
        service, user_id = setup
        stranger = _user("stranger")
        with pytest.raises(ValueError):
            service.set_budget("t1", user_id, 500.0, "EUR", members=[("user", stranger)])

    def test_clearing_a_shared_budget_clears_it_for_everyone(self, setup):
        """It is one object — leaving half of it behind would be stranger than
        removing it, and the UI names whose budget it is first."""
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )
        service.clear_budget("t1", partner)

        assert service.get_budget("t1", user_id).budget is None
        assert service.get_budget("t1", partner).budget is None

    def test_a_member_who_left_the_trip_is_not_printed_as_a_bare_id(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )
        with db_write() as conn:
            conn.execute("DELETE FROM trip_shares WHERE trip_id = 't1' AND user_id = ?", (partner,))

        members = service.get_budget("t1", user_id).budget.members
        assert [(m.type, m.id) for m in members] == [("user", user_id)]


class TestSharedBudgetsInBulk:
    """The trips list reads budgets in bulk; the two paths must agree, sharing
    and all."""

    def test_bulk_matches_the_single_trip_answer_for_a_shared_budget(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.create_expense(
            "t1",
            user_id,
            "Hotel",
            300.0,
            "EUR",
            participants=[("user", user_id), ("user", partner)],
        )
        service.create_expense(
            "t1", user_id, "Their taxi", 40.0, "EUR", participants=[("user", partner)]
        )
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )

        single = service.get_budget("t1", user_id)
        bulk = service.budgets_for_trips(user_id, ["t1"])["t1"]
        assert bulk.spent == single.spent == 340.0

    def test_a_guest_members_share_counts_in_bulk_too(self, setup):
        service, user_id = setup
        wife = _guest(user_id, "Barbara")
        service.create_expense(
            "t1",
            user_id,
            "Hotel",
            200.0,
            "EUR",
            participants=[("user", user_id), ("guest", wife)],
        )
        service.set_budget(
            "t1", user_id, 800.0, "EUR", members=[("user", user_id), ("guest", wife)]
        )

        assert service.budgets_for_trips(user_id, ["t1"])["t1"].spent == 200.0

    def test_the_card_shows_a_budget_shared_with_you(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )

        theirs = service.budgets_for_trips(partner, ["t1"])
        assert theirs["t1"].budget.amount == 1000.0
        assert theirs["t1"].budget.owner_user_id == user_id

    def test_your_own_budget_wins_in_bulk_as_well(self, setup):
        service, user_id = setup
        partner = _collaborator("t1", user_id, "partner")
        service.set_budget(
            "t1", user_id, 1000.0, "EUR", members=[("user", user_id), ("user", partner)]
        )
        service.set_budget("t1", partner, 250.0, "EUR")

        assert service.budgets_for_trips(partner, ["t1"])["t1"].budget.amount == 250.0


class TestABudgetWithNoMemberRows:
    """Migration 0031 backfills an owner row for every budget that predates it,
    and `set_budget` has written one ever since — so this state should not
    exist. It is covered anyway because the single-trip and bulk paths reach the
    member list differently, and a divergence there would value a trip's budget
    at zero on the list while the trip page showed the real figure."""

    def _memberless_budget(self, trip_id: str, user_id: int, amount: float) -> None:
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_budgets (trip_id, user_id, amount, currency, created_at, updated_at)
                   VALUES (?, ?, ?, 'EUR', ?, ?)""",
                (trip_id, user_id, amount, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )

    def test_it_still_resolves_and_counts_the_owners_share(self, setup):
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
        self._memberless_budget("t1", user_id, 500.0)

        assert service.get_budget("t1", user_id).spent == 50.0

    def test_the_bulk_path_gives_the_same_answer(self, setup):
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
        self._memberless_budget("t1", user_id, 500.0)

        bulk = service.budgets_for_trips(user_id, ["t1"])
        assert bulk["t1"].budget.amount == 500.0
        assert bulk["t1"].spent == service.get_budget("t1", user_id).spent
