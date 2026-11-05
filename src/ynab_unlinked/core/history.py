"""Balance and net worth over time, rebuilt from the transactions in the local store."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.core.balances import AccountBalance, DebtNetting, net_worth

if TYPE_CHECKING:
    from ynab_unlinked.config.models.v4 import TrackedAccount
    from ynab_unlinked.store import DailyAmounts, Store

WEEKLY_AFTER_DAYS = 366
"""Ranges longer than this get one point per week instead of one per day."""

TOTAL = "total"


@dataclass(frozen=True)
class Point:
    date: dt.date
    value: int  # milliunits


def balance_series(
    store: Store, budget_id: str, account_id: str, start: dt.date, end: dt.date
) -> list[Point]:
    """The account balance at the end of each day from `start` to `end`, both included.

    Weekly (every Monday and `end`) when the range is longer than `WEEKLY_AFTER_DAYS`. Empty
    when `end` is before `start`.
    """
    dates = sample_dates(start, end)
    amounts = store.daily_amounts(budget_id, [account_id]).get(account_id)
    return [
        Point(day, value)
        for day, value in zip(dates, _running_balance(amounts, dates), strict=True)
    ]


def net_worth_series(
    store: Store,
    budget_id: str,
    accounts: Sequence[TrackedAccount],
    nettings: Sequence[DebtNetting],
    start: dt.date,
    end: dt.date,
) -> dict[str, list[Point]]:
    """Net worth over time, with debts netted on every day as `core.balances.net_worth` does.

    Keys: `"total"`, every `Bucket` value and every account id. Account series hold the
    balance after netting; debt accounts keep their raw balance and add to the total only
    through the accounts they are mapped to.
    """
    dates = sample_dates(start, end)
    amounts = store.daily_amounts(budget_id, [account.id for account in accounts])
    balances = {
        account.id: _running_balance(amounts.get(account.id), dates) for account in accounts
    }

    series: dict[str, list[Point]] = {TOTAL: []}
    series.update({bucket.value: [] for bucket in Bucket})
    series.update({account.id: [] for account in accounts})

    for position, day in enumerate(dates):
        worth = net_worth(
            [
                AccountBalance(
                    account.id, account.name, account.bucket, balances[account.id][position]
                )
                for account in accounts
            ],
            nettings,
        )
        series[TOTAL].append(Point(day, worth.total))
        for bucket, value in worth.by_bucket().items():
            series[bucket.value].append(Point(day, value))
        for account in worth.accounts:
            series[account.id].append(Point(day, account.balance))

    return series


def sample_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every day of the range, or every Monday plus `end` when it is longer than a year."""
    if end < start:
        return []

    if (end - start).days <= WEEKLY_AFTER_DAYS:
        return [start + dt.timedelta(days=offset) for offset in range((end - start).days + 1)]

    monday = start + dt.timedelta(days=-start.weekday() % 7)
    dates = [monday + dt.timedelta(weeks=week) for week in range((end - monday).days // 7 + 1)]
    if dates[-1] != end:
        dates.append(end)
    return dates


def _running_balance(amounts: DailyAmounts | None, dates: Sequence[dt.date]) -> list[int]:
    """The balance at the end of each of `dates`, which must be sorted."""
    if amounts is None:
        return [0] * len(dates)

    days = amounts.days
    # The starting balance is a transaction, so the sum of every day is the balance. When
    # they differ (history YNAB did not send), anchor the series on the live balance.
    balance = 0
    if amounts.balance is not None:
        balance = amounts.balance - sum(amount for _, amount in days)

    values: list[int] = []
    next_day = 0
    for date in dates:
        while next_day < len(days) and days[next_day][0] <= date:
            balance += days[next_day][1]
            next_day += 1
        values.append(balance)
    return values
