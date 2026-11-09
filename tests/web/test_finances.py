import datetime as dt

import pytest

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.store import StoredAccount
from ynab_unlinked.web.finances import liquid, previous_range, rules

pytestmark = pytest.mark.version("V4")


def account(id: str, type: str, balance: int, *, closed: bool = False, on_budget: bool = True):
    return StoredAccount(
        id=id,
        name=id,
        type=type,
        closed=closed,
        on_budget=on_budget,
        balance=balance,
        cleared_balance=balance,
        uncleared_balance=0,
    )


ACCOUNTS = [
    account("checking", "checking", 2_000_000),
    account("savings", "savings", 10_000_000),
    account("card", "creditCard", -500_000),
    account("fund", "otherAsset", 50_000_000, on_budget=False),
    account("old", "savings", 0, closed=True),
]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (dt.date(2026, 1, 1), dt.date(2026, 11, 9), (dt.date(2025, 2, 1), dt.date(2025, 12, 31))),
        (dt.date(2026, 11, 1), dt.date(2026, 11, 9), (dt.date(2026, 10, 1), dt.date(2026, 10, 31))),
    ],
    ids=["year to date", "this month"],
)
def test_the_range_before_has_as_many_months(start, end, expected):
    assert previous_range(start, end) == expected


def test_runway_counts_cash_and_savings_after_debt(config_v4: LatestConfig):
    # The card is not netted into an account, so it comes off neither bucket
    assert liquid(config_v4, ACCOUNTS) == 12_000_000


def test_the_rules_count_closed_accounts_and_follow_tracking_ones(config_v4: LatestConfig):
    found = rules(config_v4, ACCOUNTS)

    assert set(found.on_budget) == {"checking", "savings", "card", "fund", "old"}
    assert found.on_budget["fund"] is False
    assert found.returns == {"fund"}
