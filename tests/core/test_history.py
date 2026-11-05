import datetime as dt
import itertools
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest
from ynab import (
    AccountsResponse,
    AccountsResponseData,
    TransactionsResponse,
    TransactionsResponseData,
)

from tests.factories import AccountFactory, TransactionDetailFactory
from tests.helpers.ynab_api import YnabClientStub
from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config.models.v4 import TrackedAccount
from ynab_unlinked.core.balances import DebtNetting
from ynab_unlinked.core.history import Point, balance_series, net_worth_series, sample_dates
from ynab_unlinked.store import Store
from ynab_unlinked.ynab_api import Client

from .conftest import BUDGET_ID

CHECKING = uuid.UUID(int=1)
SAVINGS = uuid.UUID(int=2)
CARD = uuid.UUID(int=3)

# (account, date, amount in milliunits, deleted)
Row = tuple[uuid.UUID, dt.date, int, bool]


def day(n: int) -> dt.date:
    """Day `n` of May 2025. May 1st 2025 is a Thursday."""
    return dt.date(2025, 5, n)


def values(points: Sequence[Point]) -> list[int]:
    return [point.value for point in points]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store.sqlite")


@pytest.fixture
def populate(store: Store, client: Client, ynab_api: YnabClientStub):
    """Fill the store through a full sync with the given transactions and account balances.

    Each account's balance is the sum of its non deleted transactions, as YNAB reports it,
    unless `balances` overrides it.
    """

    def fill(rows: Sequence[Row], balances: dict[uuid.UUID, int] | None = None) -> None:
        ids = (f"t{n}" for n in itertools.count())
        transactions = [
            TransactionDetailFactory(
                id=next(ids), account_id=account, var_date=date, amount=amount, deleted=deleted
            )
            for account, date, amount, deleted in rows
        ]
        sums = {account: 0 for account, *_ in rows}
        for account, _, amount, deleted in rows:
            sums[account] += 0 if deleted else amount
        sums.update(balances or {})

        ynab_api.api("transactions").get_transactions.return_value = TransactionsResponse(
            data=TransactionsResponseData(transactions=transactions, server_knowledge=1)
        )
        ynab_api.api("accounts").get_accounts.return_value = AccountsResponse(
            data=AccountsResponseData(
                accounts=[
                    AccountFactory(id=account, name=str(account), balance=balance)
                    for account, balance in sums.items()
                ],
                server_knowledge=1,
            )
        )
        store.sync(client, BUDGET_ID)

    return fill


def stored_balance(store: Store, account: uuid.UUID) -> int:
    return next(a.balance for a in store.accounts(BUDGET_ID) if a.id == str(account))


@pytest.fixture
def checking_history(populate):
    populate(
        [
            (CHECKING, day(2), 1_000_000, False),  # starting balance
            (CHECKING, day(3), -20_000, False),
            (CHECKING, day(3), -5_000, False),
            (CHECKING, day(4), -999_999, True),
            (CHECKING, day(6), 300_000, False),
            (SAVINGS, day(3), 50_000, False),
        ]
    )


def test_balance_series_is_the_running_sum_of_the_transactions(store: Store, checking_history):
    points = balance_series(store, BUDGET_ID, str(CHECKING), day(1), day(7))

    assert [point.date for point in points] == [day(n) for n in range(1, 8)]
    assert values(points) == [
        0,
        1_000_000,
        975_000,
        975_000,
        975_000,
        1_275_000,
        1_275_000,
    ]
    # The starting balance is a transaction: the history ends on the live balance
    assert points[-1].value == stored_balance(store, CHECKING)


def test_balance_series_stops_at_the_end_of_the_range(store: Store, checking_history):
    points = balance_series(store, BUDGET_ID, str(CHECKING), day(3), day(4))

    assert values(points) == [975_000, 975_000]


def test_balance_series_is_anchored_on_the_live_balance_when_history_is_missing(
    store: Store, populate
):
    # YNAB reports a balance the stored transactions do not add up to, so the series is
    # shifted rather than ending on a value the user never saw in YNAB
    populate([(CHECKING, day(2), 100_000, False)], balances={CHECKING: 600_000})

    points = balance_series(store, BUDGET_ID, str(CHECKING), day(1), day(3))

    assert values(points) == [500_000, 600_000, 600_000]


def test_balance_series_of_an_account_the_store_does_not_know_is_flat(
    store: Store, checking_history
):
    points = balance_series(store, BUDGET_ID, "unknown", day(1), day(3))

    assert values(points) == [0, 0, 0]


def test_balance_series_of_an_inverted_range_is_empty(store: Store, checking_history):
    assert balance_series(store, BUDGET_ID, str(CHECKING), day(5), day(4)) == []


def test_a_range_of_366_days_is_sampled_daily():
    dates = sample_dates(dt.date(2025, 1, 1), dt.date(2026, 1, 2))

    assert dates == [dt.date(2025, 1, 1) + dt.timedelta(days=n) for n in range(367)]


@pytest.mark.parametrize(
    ("start", "end", "expected_count", "expected_first", "expected_last_two"),
    [
        pytest.param(
            # Thursday to Saturday: the first Monday, then Mondays, then the last day
            dt.date(2025, 1, 2),
            dt.date(2026, 1, 10),
            54,
            dt.date(2025, 1, 6),
            (dt.date(2026, 1, 5), dt.date(2026, 1, 10)),
            id="longer ranges are weekly plus the last day",
        ),
        pytest.param(
            dt.date(2025, 1, 6),
            dt.date(2026, 1, 12),
            54,
            dt.date(2025, 1, 6),
            (dt.date(2026, 1, 5), dt.date(2026, 1, 12)),
            id="a last day on a Monday is not repeated",
        ),
    ],
)
def test_a_longer_range_is_sampled_every_monday_and_on_its_last_day(
    start: dt.date,
    end: dt.date,
    expected_count: int,
    expected_first: dt.date,
    expected_last_two: tuple[dt.date, dt.date],
):
    dates = sample_dates(start, end)

    assert len(dates) == expected_count
    assert dates[0] == expected_first
    assert tuple(dates[-2:]) == expected_last_two
    assert all(date.weekday() == 0 for date in dates[:-1])


def tracked(account: uuid.UUID, bucket: Bucket) -> TrackedAccount:
    return TrackedAccount(id=str(account), name=bucket.value, type="checking", bucket=bucket)


def test_net_worth_series_nets_the_debt_every_day(store: Store, populate):
    populate(
        [
            (CHECKING, day(1), 1_000_000, False),
            (SAVINGS, day(1), 500_000, False),
            (CARD, day(2), -100_000, False),
            (CARD, day(3), 100_000, False),  # the card is paid off
            (CHECKING, day(3), -100_000, False),
        ]
    )
    accounts = [
        tracked(CHECKING, Bucket.CASH),
        tracked(SAVINGS, Bucket.SAVINGS),
        tracked(CARD, Bucket.DEBT),
    ]
    nettings = [DebtNetting(str(CARD), (str(CHECKING),))]

    series = net_worth_series(store, BUDGET_ID, accounts, nettings, day(1), day(3))

    assert set(series) == {"total", *Bucket, str(CHECKING), str(SAVINGS), str(CARD)}
    assert values(series["total"]) == [1_500_000, 1_400_000, 1_400_000]
    assert values(series[str(CHECKING)]) == [1_000_000, 900_000, 900_000]
    assert values(series[str(CARD)]) == [0, -100_000, 0]
    assert values(series[Bucket.CASH]) == [1_000_000, 900_000, 900_000]
    assert values(series[Bucket.SAVINGS]) == [500_000, 500_000, 500_000]
    assert values(series[Bucket.ASSETS]) == [0, 0, 0]
    assert values(series[Bucket.DEBT]) == [0, -100_000, 0]


def test_net_worth_series_ignores_accounts_that_are_not_given(store: Store, populate):
    populate([(CHECKING, day(1), 1_000_000, False), (SAVINGS, day(1), 500_000, False)])

    series = net_worth_series(
        store, BUDGET_ID, [tracked(CHECKING, Bucket.CASH)], [], day(1), day(2)
    )

    assert values(series["total"]) == [1_000_000, 1_000_000]
    assert str(SAVINGS) not in series
