"""What the finance pages (Net worth's Months and Movers, Cash flow, Spending) share.

The range pills in whole months, the title of a period, and the rules that sort every line
of the store (`core.finance.Rules`) from the accounts and Settings. No NiceGUI here: the views'
data modules use it and it is tested directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.balances import AccountBalance, net_worth
from ynab_unlinked.core.cashflow import CashFlow, Categories, cash_flow
from ynab_unlinked.core.finance import RECONCILIATION_PAYEE, Rules, month_start, months_between
from ynab_unlinked.store import Store, StoredAccount
from ynab_unlinked.web import accounts as tracking

RANGES = ("1M", "3M", "6M", "YTD", "1Y", "All")
RANGE_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}
"""How many calendar months each range pill shows, the current one included. YTD starts in
January and All at the first transaction."""


def months_range(key: str, today: dt.date, earliest: dt.date) -> tuple[dt.date, dt.date]:
    """The first day of the first month a range pill covers, and today.

    Whole months, so monthly bars add up to the totals. Never before the month of the first
    transaction.
    """
    first = month_start(earliest)
    if key == "YTD":
        start = dt.date(today.year, 1, 1)
    elif (months := RANGE_MONTHS.get(key)) is not None:
        index = today.year * 12 + today.month - months
        start = dt.date(index // 12, index % 12 + 1, 1)
    else:
        start = first
    return max(start, first), today


def period_title(start: dt.date, end: dt.date) -> str:
    """`April 2026` for a whole month (or this month so far), `Jan 2026 – Nov 2026` otherwise."""
    if (start.year, start.month) == (end.year, end.month):
        return start.strftime("%B %Y")
    return f"{start.strftime('%b %Y')} – {end.strftime('%b %Y')}"


def rules(config: LatestConfig, stored: Iterable[StoredAccount]) -> Rules:
    """The counted accounts, closed ones too (on the budget or tracking), the "not spending"
    categories, the accounts whose return is followed and the payees of balance adjustments."""
    stored = list(stored)
    by_id = {account.id: account for account in stored}
    accounts = tracking.history_accounts(config, stored)
    on_budget = {
        account.id: by_id[account.id].on_budget if account.id in by_id else True
        for account in accounts
    }
    return Rules(
        on_budget=on_budget,
        not_spending=frozenset(config.finances.not_spending),
        returns=frozenset(
            account.id
            for account in accounts
            if tracking.follows_return(config, account, on_budget[account.id])
        ),
        adjustment_payees=frozenset({RECONCILIATION_PAYEE, config.adjustments.payee}),
    )


def category_names(store: Store, budget_id: str) -> dict[str, str]:
    """Every category's name as it is now. Blocking."""
    return {category.id: category.name for category in store.categories(budget_id)}


def earliest(store: Store, budget_id: str, today: dt.date) -> dt.date:
    """The date of the budget's first transaction, today when there is none. Blocking."""
    lines = store.lines(budget_id, until=today)
    return lines[0].date if lines else today


def load_cash_flow(store: Store, config: LatestConfig, start: dt.date, end: dt.date) -> CashFlow:
    """Cash flow and category trends of `start`..`end`, labelled with the notes written in
    YNAB. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    stored = store.accounts(budget_id)
    categories = store.categories(budget_id)
    return cash_flow(
        store,
        budget_id,
        rules(config, stored),
        start,
        end,
        categories=Categories(
            names={c.id: c.name for c in categories},
            groups={c.id: c.group_name for c in categories},
        ),
        notes=store.month_notes(budget_id),
    )


def liquid(config: LatestConfig, stored: Iterable[StoredAccount]) -> int:
    """Cash and savings now, after the debts netted into them: what runway is counted from."""
    stored = list(stored)
    balances = {account.id: account.balance for account in stored}
    worth = net_worth(
        [
            AccountBalance(a.id, a.name, a.bucket, balances.get(a.id, 0))
            for a in tracking.effective_accounts(config, stored)
        ],
        tracking.effective_nettings(config),
    )
    by_bucket = worth.by_bucket()
    return by_bucket[Bucket.CASH] + by_bucket[Bucket.SAVINGS]


def previous_range(start: dt.date, end: dt.date) -> tuple[dt.date, dt.date]:
    """The same number of whole months right before `start`, for a comparison."""
    months = len(months_between(start, end))
    index = start.year * 12 + start.month - 1 - months
    first = dt.date(index // 12, index % 12 + 1, 1)
    return first, start - dt.timedelta(days=1)
