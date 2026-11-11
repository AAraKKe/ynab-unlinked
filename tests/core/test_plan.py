import datetime as dt
from pathlib import Path

import pytest

from tests.factories import StoredAccountFactory, StoredTransactionFactory
from tests.helpers.store import upsert
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.core.finance import AccountMove, Flows, Period, Rules
from ynab_unlinked.core.plan import (
    Assumptions,
    BucketMonth,
    Goal,
    Position,
    Return,
    Seen,
    date_after,
    fit,
    goal_pace,
    project,
    see,
    yearly_return,
)
from ynab_unlinked.store import Store

BUDGET = "budget"
CHECKING, SAVINGS, FUND, SHARES, CARD = "checking", "savings", "fund", "shares", "card"
BUCKETS = {
    CHECKING: Bucket.CASH,
    SAVINGS: Bucket.SAVINGS,
    FUND: Bucket.ASSETS,
    SHARES: Bucket.ASSETS,
    CARD: Bucket.DEBT,
}
YEAR = [dt.date(2025, month, 1) for month in range(1, 13)]
THREE_YEARS = [dt.date(2023 + index // 12, index % 12 + 1, 1) for index in range(36)]


def year(*moves: AccountMove, months: list[dt.date] = YEAR) -> Period:
    """The whole of 2025 with these accounts (or `months`, for a longer fit); the period's
    flows are theirs added up."""
    flows = Flows()
    for move in moves:
        flows += move.flows
    return Period(
        start=dt.date(2025, 1, 1),
        end=dt.date(2025, 12, 31),
        flows=flows,
        start_worth=sum(move.start_balance for move in moves),
        end_worth=sum(move.end_balance for move in moves),
        months=tuple((month, Flows()) for month in months),
        accounts=moves,
    )


def move(account: str, start: int, **flows: int) -> AccountMove:
    return AccountMove(account, start, start + Flows(**flows).change, Flows(**flows), None)


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (dt.date(2026, 1, 31), 1, dt.date(2026, 2, 28)),
        (dt.date(2026, 11, 11), 14, dt.date(2028, 1, 11)),
        (dt.date(2026, 3, 1), -3, dt.date(2025, 12, 1)),
    ],
    ids=["a shorter month ends earlier", "over two new years", "backwards"],
)
def test_a_day_some_months_away(day: dt.date, months: int, expected: dt.date):
    assert date_after(day, months) == expected


@pytest.mark.parametrize(
    ("balances", "expected"),
    [
        ({dt.date(2024, 12, 1): 10_000, dt.date(2025, 12, 1): 22_000}, 1_000),
        # Nothing for the month before: from the first month it has a balance for
        ({dt.date(2025, 6, 1): 16_000, dt.date(2025, 12, 1): 22_000}, 1_000),
        ({dt.date(2024, 12, 1): 22_000, dt.date(2025, 12, 1): 10_000}, -1_000),
        ({dt.date(2024, 12, 1): 10_000}, None),
        ({dt.date(2025, 12, 1): 22_000}, None),
        ({}, None),
    ],
    ids=[
        "from the month before",
        "from the first month held",
        "it shrank",
        "no last month",
        "only the last month",
        "nothing held",
    ],
)
def test_the_goals_pace_is_what_it_grew_by_a_month(
    balances: dict[dt.date, int], expected: float | None
):
    assert goal_pace(balances, YEAR) == expected


# ---- returns ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("months", "rate", "years"),
    [
        ([BucketMonth(1_000, 0, 10)] * 12, 1.01**12 - 1, 1),
        ([BucketMonth(1_000, 0, 10)] * 30, 1.01**12 - 1, 2.5),
        # 15 on the 1,000 it had and half of the 1,000 put in: the same 1% a month
        ([BucketMonth(1_000, 1_000, 15)] * 12, 1.01**12 - 1, 1),
        ([BucketMonth(1_000, 0, 0)] * 5 + [BucketMonth(1_000, 0, -100)], 0.9**2 - 1, 0.5),
    ],
    ids=[
        "a year at 1% a month",
        "longer, the same a year",
        "money put in does not raise it",
        "one bad month in six",
    ],
)
def test_a_return_compounds_its_months_into_a_year(
    months: list[BucketMonth], rate: float, years: float
):
    found = yearly_return(months)

    assert found is not None
    assert (found.rate, found.years) == (pytest.approx(rate), years)


@pytest.mark.parametrize(
    "months", [[BucketMonth(1_000, 0, 0)] * 12, []], ids=["nothing moved on its own", "no history"]
)
def test_a_bucket_that_did_nothing_on_its_own_has_no_return(months: list[BucketMonth]):
    assert yearly_return(months) is None


def test_a_month_that_is_not_a_return_is_left_out():
    months = [
        BucketMonth(0, 0, 0),
        # A balance set by hand on an account that held next to nothing: money brought in
        BucketMonth(100, 0, 50_000),
        *[BucketMonth(50_000, 0, 500)] * 12,
    ]

    found = yearly_return(months)

    assert found is not None
    assert (found.rate, found.years) == (pytest.approx(1.01**12 - 1), 1)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


def test_the_lines_say_what_went_in_and_out_of_assets_and_each_months_gain(store: Store):
    rows = [
        (FUND, "2025-01-10", 10_000, "Starting Balance", None),
        # Before the months of the fit: only in what the fund held when they began
        (FUND, "2025-02-05", 500, "Transfer", CHECKING),
        (FUND, "2025-02-20", 210, "Market", None),
        (FUND, "2025-03-05", 500, "Transfer", CHECKING),
        (FUND, "2025-03-12", -300, "Transfer", SAVINGS),
        # Between two assets: neither put in nor taken out
        (FUND, "2025-03-15", -2_000, "Transfer", SHARES),
        (SHARES, "2025-03-15", 2_000, "Transfer", FUND),
        (SHARES, "2025-04-02", 700, "Transfer", CHECKING),
        (FUND, "2025-04-28", -90, "Market", None),
        (SAVINGS, "2025-03-12", 300, "Transfer", FUND),
    ]
    upsert(
        store,
        BUDGET,
        accounts=[
            StoredAccountFactory(id=CHECKING),
            StoredAccountFactory(id=SAVINGS, type="savings", balance=300),
            StoredAccountFactory(id=FUND, type="otherAsset", on_budget=False, balance=8_820),
            StoredAccountFactory(id=SHARES, type="otherAsset", on_budget=False, balance=2_700),
        ],
        transactions=[
            StoredTransactionFactory(
                id=f"t{n}",
                account_id=account,
                date=dt.date.fromisoformat(day),
                amount=amount,
                payee_name=payee,
                transfer_account_id=transfer,
            )
            for n, (account, day, amount, payee, transfer) in enumerate(rows)
        ],
    )
    rules = Rules(on_budget={CHECKING: True, SAVINGS: True, FUND: False, SHARES: False})

    seen = see(
        store,
        BUDGET,
        rules,
        BUCKETS,
        dt.date(2025, 3, 1),
        dt.date(2025, 4, 30),
    )

    assert (seen.put_in, seen.taken_out) == (1_200, 300)
    assert seen.assets == (BucketMonth(10_710, 200, 0), BucketMonth(10_910, 700, -90))
    assert seen.savings[0] == BucketMonth(0, 300, 0)


# ---- the fit ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seen", "to_assets", "from_assets", "stays"),
    [
        # 6,000 of the year ended up in the fund: 500 of the 3,000 that come in a month
        (Seen(put_in=9_000, taken_out=3_000), 1 / 6, 0, 500),
        # Shares that vest and are sold pass through: nothing ends up there
        (Seen(put_in=9_000, taken_out=9_000), 0, 0, 1_000),
        (Seen(put_in=3_000, taken_out=9_000), 0, 500, 1_500),
    ],
    ids=["assets took money", "all that went in came out", "assets gave money back"],
)
def test_a_fit_reads_a_month_and_what_ended_up_in_assets(
    seen: Seen, to_assets: float, from_assets: float, stays: float
):
    found = fit(
        year(
            # 36,000 in, 24,000 spent, 6,000 moved on: 6,000 stayed, half of it in savings
            move(CHECKING, 5_000, income=36_000, spending=-24_000, transfers=-9_000),
            move(SAVINGS, 10_000, transfers=3_000),
            move(FUND, 40_000, transfers=0),
        ),
        BUCKETS,
        seen=seen,
    )

    assumptions = found.assumptions
    assert (assumptions.income, assumptions.spending) == (3_000, 2_000)
    assert (assumptions.to_assets, assumptions.from_assets) == (to_assets, from_assets)
    # What went in and what came out are kept as they were, to say what happened
    assert (found.put_in, found.taken_out) == (seen.put_in / 12, seen.taken_out / 12)
    assert assumptions.to_savings == 0.5
    assert assumptions.stays == pytest.approx(stays)


@pytest.mark.parametrize(
    ("income", "put_in", "expected"),
    [(36_000, 9_000, 0.25), (20_000, 6_000, 0.3), (36_000, 0, 0), (36_000, 50_000, 1)],
    ids=["a quarter of the pay", "a year that lost money", "nothing put in", "more than came in"],
)
def test_what_goes_into_assets_is_a_share_of_what_comes_in(
    income: int, put_in: int, expected: float
):
    found = fit(
        year(move(CHECKING, 5_000, income=income, spending=-24_000)),
        BUCKETS,
        seen=Seen(put_in=put_in),
    )

    assert found.assumptions.to_assets == expected


def test_savings_that_were_drawn_from_take_none_of_what_stays():
    found = fit(
        year(
            move(CHECKING, 5_000, income=36_000, spending=-24_000, transfers=8_000),
            move(SAVINGS, 10_000, transfers=-8_000),
        ),
        BUCKETS,
    )

    assert found.assumptions.to_savings == 0


def test_what_a_card_owes_is_cash_that_did_not_stay():
    found = fit(
        year(
            move(CHECKING, 5_000, income=36_000, transfers=-6_000),
            move(SAVINGS, 0, transfers=6_000),
            move(CARD, 0, spending=-12_000),
        ),
        BUCKETS,
    )

    # 30,000 in checking less the 12,000 on the card, against 6,000 in savings
    assert found.assumptions.to_savings == 0.25


@pytest.mark.parametrize(
    ("months", "expected"),
    [(THREE_YEARS, 1.01**12 - 1), (YEAR, 0.05)],
    ids=["three years measured", "a year is too short to go by"],
)
def test_the_plan_starts_from_what_assets_returned_only_over_enough_months(
    months: list[dt.date], expected: float
):
    seen = Seen(
        assets=(BucketMonth(1_000, 0, 10),) * len(months),
        savings=(BucketMonth(1_000, 0, 2),) * len(months),
    )

    found = fit(year(move(CHECKING, 0, income=12_000), months=months), BUCKETS, seen=seen)

    # What they returned is kept either way, to say so
    assert found.assets_return == Return(pytest.approx(1.01**12 - 1), len(months) / 12)
    assert found.assumptions.assets_return == pytest.approx(expected)
    assert found.trusts_return is (months is THREE_YEARS)
    # Interest is what it was, however short the months
    assert found.savings_return is not None
    assert found.assumptions.savings_return == found.savings_return.rate


def test_assets_that_never_moved_on_their_own_grow_at_the_default():
    found = fit(year(move(CHECKING, 0, income=12_000), months=THREE_YEARS), BUCKETS)

    assert (found.assets_return, found.assumptions.assets_return) == (None, 0.05)
    assert not found.trusts_return


@pytest.mark.parametrize(
    ("balances", "seen", "share", "pace"),
    [
        ({dt.date(2024, 12, 1): 0, dt.date(2025, 12, 1): 6_000}, Seen(), 0.5, 500),
        # Half of the saving goes to assets and 3,000 came back: 750 a month stay
        (
            {dt.date(2024, 12, 1): 0, dt.date(2025, 12, 1): 4_500},
            Seen(put_in=6_000, taken_out=3_000),
            0.5,
            375,
        ),
        # It grew faster than what stayed: from money moved between categories
        ({dt.date(2024, 12, 1): 0, dt.date(2025, 12, 1): 60_000}, Seen(), 1, 5_000),
        ({dt.date(2024, 12, 1): 9_000, dt.date(2025, 12, 1): 6_000}, Seen(), 0, -250),
        ({}, Seen(), 0, None),
    ],
    ids=[
        "half of the saving",
        "half of what assets leave",
        "more than stayed",
        "it was spent from",
        "no past months",
    ],
)
def test_the_goal_takes_the_share_of_what_stays_in_the_budget_it_grew_by(
    balances: dict[dt.date, int], seen: Seen, share: float, pace: float | None
):
    found = fit(year(move(CHECKING, 0, income=36_000, spending=-24_000)), BUCKETS, balances, seen)

    assert found.assumptions.to_goal == share
    assert found.goal_pace == pace


# ---- the plan --------------------------------------------------------------------------------


def test_a_plan_puts_each_months_saving_where_it_goes():
    plan = project(
        Position(cash=1_000, savings=2_000, assets=3_000),
        # 300 of the 3,000 go to assets; of the 700 that stay, 30% to savings
        Assumptions(income=3_000, spending=2_000, to_assets=0.1, to_savings=0.3, inflation=0),
        months=10,
    )

    end = plan.end
    assert (end.cash, end.savings, end.assets) == pytest.approx((5_900, 4_100, 6_000))
    assert len(plan.steps) == 11
    assert plan.steps[0].total == 6_000


def test_what_is_taken_out_of_assets_comes_back_to_the_budget_and_feeds_the_goal():
    plan = project(
        Position(assets=2_500),
        Assumptions(income=2_000, spending=2_000, from_assets=1_000, to_goal=0.5, inflation=0),
        months=4,
        goal=Goal("🏠 Down Payment", balance=0, target=10_000),
    )

    # Nothing comes out of assets that are not there: 1,000, 1,000, the last 500, nothing
    assert [(step.assets, step.cash, step.goal) for step in plan.steps[1:]] == [
        (1_500, 1_000, 500),
        (500, 2_000, 1_000),
        (0, 2_500, 1_250),
        (0, 2_500, 1_250),
    ]
    assert plan.end.total == 2_500


def test_more_put_into_assets_than_is_saved_is_made_up_from_cash():
    plan = project(
        Position(cash=1_000),
        # Shares that vest are pay: 500 go to assets of a month that saves 100
        Assumptions(income=2_000, spending=1_900, to_assets=0.25, inflation=0),
        months=2,
    )

    assert [(step.cash, step.assets, step.total) for step in plan.steps] == [
        (1_000, 0, 1_000),
        (600, 500, 1_100),
        (200, 1_000, 1_200),
    ]


def test_assets_and_savings_grow_at_their_yearly_return():
    plan = project(
        Position(cash=1_000, savings=1_000, assets=1_000),
        Assumptions(assets_return=0.10, savings_return=0.02, inflation=0),
        months=24,
    )

    end = plan.end
    assert (end.cash, end.savings, end.assets) == pytest.approx((1_000, 1_040.4, 1_210))


def test_prices_raise_income_and_spending_and_say_what_money_is_worth():
    plan = project(
        Position(),
        Assumptions(income=3_000, spending=2_000, inflation=0.10),
        months=12,
    )

    assert plan.end.prices == pytest.approx(1.10)
    # The twelfth month saves 1,000 at that month's prices
    assert plan.end.cash - plan.steps[11].cash == pytest.approx(1_100)


def test_a_month_that_spends_more_takes_from_cash_then_savings_then_assets():
    plan = project(
        Position(cash=1_500, savings=1_000, assets=1_000),
        Assumptions(income=1_000, spending=2_000, inflation=0),
        months=5,
    )

    assert [(step.cash, step.savings, step.assets) for step in plan.steps[1:]] == [
        (500, 1_000, 1_000),
        (0, 500, 1_000),
        (0, 0, 500),
        # Nothing is left to take: the rest is owed
        (-500, 0, 0),
        (-1_500, 0, 0),
    ]


def test_the_goal_grows_with_its_share_of_what_stays_and_stops_at_its_target():
    goal = Goal("🏠 Down Payment", balance=1_000, target=2_500)
    plan = project(
        Position(),
        Assumptions(income=3_000, spending=2_000, to_goal=0.5, inflation=0),
        months=6,
        goal=goal,
    )

    assert plan.goal_month == 3
    assert [step.goal for step in plan.steps] == [1_000, 1_500, 2_000, 2_500, 2_500, 2_500, 2_500]


def test_a_goal_that_is_spent_leaves_net_worth_the_month_after_it_is_reached():
    plan = project(
        Position(cash=500, savings=2_000),
        Assumptions(income=3_000, spending=2_000, to_goal=0.5, inflation=0, goal_spent=True),
        months=5,
        goal=Goal("🏠 Down Payment", balance=1_500, target=2_500),
    )

    assert plan.goal_month == 2
    # Out of savings first, then cash; once spent the goal holds nothing to show
    assert [(step.cash, step.savings, step.goal) for step in plan.steps] == [
        (500, 2_000, 1_500),
        (1_500, 2_000, 2_000),
        (2_500, 2_000, 2_500),
        (3_000, 0, None),
        (4_000, 0, None),
        (5_000, 0, None),
    ]
    assert [step.total for step in plan.steps] == [2_500, 3_500, 4_500, 3_000, 4_000, 5_000]


def test_a_goal_already_reached_is_spent_in_the_first_month():
    plan = project(
        Position(savings=3_000),
        Assumptions(goal_spent=True, inflation=0),
        months=2,
        goal=Goal("Trip", balance=2_800, target=2_500),
    )

    assert plan.goal_month == 0
    # Today is as it is; what the goal holds, more than its target, goes the month after
    assert [(step.savings, step.goal) for step in plan.steps] == [
        (3_000, 2_800),
        (200, None),
        (200, None),
    ]


def test_once_reached_the_goals_share_can_go_to_assets():
    plan = project(
        Position(),
        Assumptions(income=3_000, spending=2_000, to_goal=0.5, inflation=0, goal_to_assets=True),
        months=4,
        goal=Goal("Trip", balance=1_500, target=2_500),
    )

    # Until it is reached its share stays in the budget; after, half of the 1,000 is invested
    assert [(step.cash, step.assets, step.goal) for step in plan.steps] == [
        (0, 0, 1_500),
        (1_000, 0, 2_000),
        (2_000, 0, 2_500),
        (2_500, 500, 2_500),
        (3_000, 1_000, 2_500),
    ]


@pytest.mark.parametrize(
    ("balance", "saving", "expected"),
    [(5_000, 1_000, 0), (1_000, -500, None), (1_000, 10, None)],
    ids=["it already holds its target", "nothing is saved", "too slow for the plan"],
)
def test_when_the_goal_is_reached(balance: int, saving: int, expected: int | None):
    plan = project(
        Position(cash=100_000),
        Assumptions(income=2_000 + saving, spending=2_000, to_goal=1, inflation=0),
        months=12,
        goal=Goal("Trip", balance=balance, target=5_000),
    )

    assert plan.goal_month == expected
    # A month that loses money never takes from the goal
    assert plan.end.goal is not None and plan.end.goal >= balance


def test_work_is_optional_once_four_percent_of_net_worth_pays_a_year_of_spending():
    # A year costs 12,000: 300,000 pays for it at 4%
    assumptions = Assumptions(income=2_000, spending=1_000, inflation=0)

    assert project(Position(cash=290_000), assumptions, months=24).free_month == 10
    assert project(Position(cash=300_000), assumptions, months=24).free_month == 0
    assert project(Position(cash=100_000), assumptions, months=24).free_month is None
    assert project(Position(cash=10**9), Assumptions(income=1_000), months=1).free_month is None
