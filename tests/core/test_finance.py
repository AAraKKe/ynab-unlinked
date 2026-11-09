import datetime as dt
from pathlib import Path

import pytest

from tests.factories import StoredAccountFactory, StoredTransactionFactory
from tests.helpers.store import upsert
from ynab_unlinked.core.finance import (
    Flows,
    Rules,
    annualised,
    income_by_payee,
    months_between,
    period,
    period_return,
    spending_by_category,
)
from ynab_unlinked.store import Line, Store

BUDGET = "budget"
CHECKING, CARD, FUND, OUTSIDE = "checking", "card", "fund", "not-counted"
RULES = Rules(
    on_budget={CHECKING: True, CARD: True, FUND: False},
    not_spending=frozenset({"broker"}),
    returns=frozenset({FUND}),
)


def line(
    amount: int,
    *,
    account: str = CHECKING,
    day: int = 10,
    category: str | None = "groceries",
    transfer: str | None = None,
    payee: str = "Shop",
) -> Line:
    return Line(
        transaction_id=f"t{amount}{account}{day}",
        account_id=account,
        date=dt.date(2025, 4, day),
        amount=amount,
        payee_name=payee,
        category_id=category,
        category_name=category,
        transfer_account_id=transfer,
    )


@pytest.mark.parametrize(
    ("given", "kind"),
    [
        (line(3_000_000, category="ready-to-assign"), "income"),
        (line(40_000, category="groceries"), "income"),
        (line(-50_000), "spending"),
        (line(-50_000, account=CARD), "spending"),
        (line(12_000, account=CARD), "income"),
        (line(-500_000, category="broker"), "set_aside"),
        (line(500_000, category="broker"), "income"),
        (line(-1_640_000, account=FUND, category=None), "assets"),
        (line(1_000_000, account=FUND, category=None, transfer=CHECKING), "transfers"),
        (line(-1_000_000, transfer=FUND), "transfers"),
        (line(-300_000, transfer=OUTSIDE), "outside"),
        (line(5_000_000, payee="Starting Balance", category="ready-to-assign"), "outside"),
        (line(80_000_000, account=FUND, payee="Starting Balance", category=None), "outside"),
        (line(-50_000, account=OUTSIDE), None),
    ],
    ids=[
        "salary is income",
        "a refund is income too",
        "a purchase is spending",
        "a card purchase is spending",
        "a card refund is income",
        "a not spending category sets money aside",
        "money in to a not spending category is income",
        "a tracking account moving on its own is valuation",
        "money put into a tracking account is a transfer",
        "a transfer between counted accounts",
        "a transfer to an account not counted leaves net worth",
        "a starting balance is not income",
        "a tracking account's starting balance is not valuation",
        "an account not counted is left out",
    ],
)
def test_each_line_has_one_kind(given: Line, kind: str | None):
    assert RULES.kind(given) == kind


def test_spending_by_category_ignores_refunds_and_names_categories_as_they_are_now():
    lines = [
        line(-50_000, category="groceries"),
        line(-20_000, category="groceries"),
        line(30_000, category="groceries"),
        line(-90_000, category="rent"),
        line(-10_000, category=None),
    ]

    spent = spending_by_category(lines, RULES, {"rent": "🏠 Rent"})

    assert [(s.name, s.amount) for s in spent] == [
        ("🏠 Rent", -90_000),
        ("groceries", -70_000),
        ("Uncategorized", -10_000),
    ]


def test_months_between_covers_every_month_the_period_touches():
    assert months_between(dt.date(2024, 11, 20), dt.date(2025, 2, 3)) == [
        dt.date(2024, 11, 1),
        dt.date(2024, 12, 1),
        dt.date(2025, 1, 1),
        dt.date(2025, 2, 1),
    ]


@pytest.mark.parametrize(
    ("start_balance", "flows", "gain", "expected"),
    [
        (100_000, [], 10_000, 0.10),
        # Money put in halfway through counts for half of it
        (100_000, [(dt.date(2025, 1, 16), 100_000)], 15_000, 0.10),
        (0, [], 5_000, None),
    ],
    ids=["no flows", "a contribution mid period", "nothing invested"],
)
def test_period_return_weighs_money_by_how_long_it_was_invested(
    start_balance, flows, gain, expected
):
    rate = period_return(start_balance, flows, gain, dt.date(2025, 1, 1), dt.date(2025, 1, 30))

    assert rate == (None if expected is None else pytest.approx(expected, abs=1e-3))


def test_annualised_leaves_a_year_or_less_alone_and_compounds_longer_periods():
    assert annualised(0.05, 200) == 0.05
    assert annualised(0.21, 730) == pytest.approx(0.1, abs=1e-3)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


def test_a_period_explains_the_whole_change_of_net_worth(store: Store):
    rows = [
        # Before the period: starting balances
        (CHECKING, "2025-03-01", 2_000_000, "Starting Balance", None, None),
        (FUND, "2025-03-01", 10_000_000, "Starting Balance", None, None),
        # April
        (CHECKING, "2025-04-01", 3_000_000, "Employer", "ready-to-assign", None),
        (CHECKING, "2025-04-03", -900_000, "Landlord", "rent", None),
        (CARD, "2025-04-05", -100_000, "Shop", "groceries", None),
        (CHECKING, "2025-04-10", -1_000_000, "Transfer : Fund", None, FUND),
        (FUND, "2025-04-10", 1_000_000, "Transfer : Checking", None, CHECKING),
        (FUND, "2025-04-30", -400_000, "Reconciliation Balance Adjustment", None, None),
        (CHECKING, "2025-04-20", -200_000, "Transfer : Old account", None, OUTSIDE),
        # May, outside the period
        (CHECKING, "2025-05-02", -50_000, "Shop", "groceries", None),
    ]
    upsert(
        store,
        BUDGET,
        accounts=[
            StoredAccountFactory(id=CHECKING, balance=2_850_000),
            StoredAccountFactory(id=CARD, type="creditCard", balance=-100_000),
            StoredAccountFactory(id=FUND, type="otherAsset", on_budget=False, balance=10_600_000),
        ],
        transactions=[
            StoredTransactionFactory(
                id=f"t{n}",
                account_id=account,
                date=dt.date.fromisoformat(day),
                amount=amount,
                payee_name=payee,
                category_id=category,
                transfer_account_id=transfer,
            )
            for n, (account, day, amount, payee, category, transfer) in enumerate(rows)
        ],
    )

    april = period(store, BUDGET, RULES, dt.date(2025, 4, 1), dt.date(2025, 4, 30))

    assert april.flows == Flows(
        income=3_000_000, spending=-1_000_000, assets=-400_000, outside=-200_000
    )
    assert (april.start_worth, april.end_worth) == (12_000_000, 13_400_000)
    assert april.end_worth - april.start_worth == april.flows.change
    assert april.months == ((dt.date(2025, 4, 1), april.flows),)

    moves = {move.account_id: move for move in april.accounts}
    assert [move.account_id for move in april.accounts] == [CHECKING, FUND, CARD]
    assert (moves[FUND].change, moves[FUND].own_money, moves[FUND].flows.assets) == (
        600_000,
        1_000_000,
        -400_000,
    )
    assert moves[FUND].rate == pytest.approx(-400_000 / (10_000_000 + 1_000_000 * 21 / 30))
    assert moves[CHECKING].rate is None
    assert [spend.category_id for spend in april.spending] == ["rent", "groceries"]


SAVINGS = "savings"
FOLLOWED = Rules(
    on_budget={CHECKING: True, SAVINGS: True, FUND: False},
    returns=frozenset({SAVINGS, FUND}),
    adjustment_payees=frozenset({"Reconciliation Balance Adjustment", "Balance Adjustment"}),
)


@pytest.mark.parametrize(
    ("given", "kind"),
    [
        (line(40_000, account=SAVINGS, payee="Reconciliation Balance Adjustment"), "assets"),
        (line(7_982_000, account=SAVINGS, payee="Balance Adjustment"), "assets"),
        (line(500_000, account=SAVINGS, payee="Employer"), "income"),
        (line(-80_000, account=SAVINGS, payee="Amtrak"), "spending"),
        (line(40_000, payee="Balance Adjustment"), "income"),
    ],
    ids=[
        "interest of a followed savings account",
        "a sale recorded as an adjustment in it",
        "a payment into it is still income",
        "spending from it is still spending",
        "an adjustment of an account not followed is income",
    ],
)
def test_adjustments_of_a_followed_budget_account_are_asset_changes(given: Line, kind: str):
    assert FOLLOWED.kind(given) == kind


def test_income_is_listed_by_payee_most_first():
    lines = [
        line(3_000_000, payee="Employer", category="ready-to-assign"),
        line(1_000_000, payee="Employer", category="ready-to-assign"),
        line(40_000, payee="Shop", category="groceries"),
        line(-50_000, payee="Shop"),
        line(1_000_000, transfer=CARD, payee="Transfer : Card"),
    ]

    assert [(i.name, i.amount) for i in income_by_payee(lines, RULES)] == [
        ("Employer", 4_000_000),
        ("Shop", 40_000),
    ]


def test_a_return_is_only_given_for_followed_accounts(store: Store):
    upsert(
        store,
        BUDGET,
        accounts=[
            StoredAccountFactory(id=FUND, type="otherAsset", on_budget=False, balance=9_600_000)
        ],
        transactions=[
            StoredTransactionFactory(
                id="t1",
                account_id=FUND,
                date=dt.date(2025, 3, 1),
                amount=10_000_000,
                payee_name="Starting Balance",
            ),
            StoredTransactionFactory(
                id="t2",
                account_id=FUND,
                date=dt.date(2025, 4, 30),
                amount=-400_000,
                payee_name="Reconciliation Balance Adjustment",
            ),
        ],
    )
    april = (dt.date(2025, 4, 1), dt.date(2025, 4, 30))

    followed = period(
        store, BUDGET, Rules(on_budget={FUND: False}, returns=frozenset({FUND})), *april
    )
    not_followed = period(store, BUDGET, Rules(on_budget={FUND: False}), *april)

    assert followed.accounts[0].rate == pytest.approx(-0.04)
    assert not_followed.accounts[0].rate is None
    assert not_followed.flows.assets == -400_000
