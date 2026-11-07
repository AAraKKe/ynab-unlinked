"""What the Net worth view shows, worked out without NiceGUI.

The range pills, the snapshot of the store the view draws from, the order of the accounts
table, the age pill of a balance set by hand, and the one write: the adjustment that takes an
account to the balance the user typed. Everything here is plain Python over the store, the
config and the YNAB client, so it is tested directly.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ynab import TransactionClearedStatus

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.balances import (
    AccountBalance,
    Adjustment,
    DebtNetting,
    NetWorth,
    build_adjustments,
    create_adjustments,
    net_worth,
    parse_amount_to_milliunits,
)
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store, StoredAccount
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web.accounts import STALE_AFTER_DAYS
from ynab_unlinked.web.buckets import NET_WORTH_ORDER
from ynab_unlinked.ynab_api import Client

RANGES = ("1M", "3M", "6M", "YTD", "1Y", "All")
DEFAULT_RANGE = "6M"
GROUPINGS = {"total": "Total", "type": "By type", "account": "By account"}
MAX_PICKED = 6
DEFAULT_PICKED = 4
"""How many accounts "by account" shows before the user picks: the largest after netting."""
DRAWER_TRANSACTIONS = 20

ByHandKind = Literal["warn", "acc"]
"""The pill kinds of `by_hand_pill`: stale or not."""


# ---- ranges and wording ----------------------------------------------------------------------


def _months_back(day: dt.date, months: int) -> dt.date:
    month_index = day.year * 12 + day.month - 1 - months
    year, month = divmod(month_index, 12)
    month += 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def range_start(key: str, today: dt.date, earliest: dt.date) -> dt.date:
    """First day of a range pill. Never before the first transaction, never after today."""
    match key:
        case "1M":
            start = _months_back(today, 1)
        case "3M":
            start = _months_back(today, 3)
        case "6M":
            start = _months_back(today, 6)
        case "YTD":
            start = dt.date(today.year, 1, 1)
        case "1Y":
            start = _months_back(today, 12)
        case _:
            start = earliest
    return min(max(start, earliest), today)


def age_text(days: int) -> str:
    if days <= 0:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


def by_hand_pill(last: dt.date | None, today: dt.date) -> tuple[str, ByHandKind]:
    """ "by hand · 9 days ago", or "stale · 41 days ago" once older than 30 days."""
    if last is None:
        return "stale · never set", "warn"
    days = (today - last).days
    if days > STALE_AFTER_DAYS:
        return f"stale · {age_text(days)}", "warn"
    return f"by hand · {age_text(days)}", "acc"


def assign_slots(previous: dict[str, int], picked: Sequence[str]) -> dict[str, int]:
    """Colour slot of each picked account: kept while it stays picked, else the first free."""
    slots = {account_id: slot for account_id, slot in previous.items() if account_id in picked}
    for account_id in picked:
        if account_id not in slots:
            slots[account_id] = min(set(range(MAX_PICKED)) - set(slots.values()))
    return slots


def signed(formatter: Formatter, milliunits: int) -> str:
    text = formatter.format_amount_milli(milliunits)
    return f"+{text}" if milliunits > 0 else text


# ---- the snapshot ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """What the view shows, read from the store in one go."""

    tracked: tuple[TrackedAccount, ...]
    stored: dict[str, StoredAccount]
    nettings: tuple[DebtNetting, ...]
    worth: NetWorth
    earliest: dt.date
    last_set: dict[str, dt.date | None]
    """By hand accounts only."""

    def raw(self, account_id: str) -> int:
        stored = self.stored.get(account_id)
        return 0 if stored is None else stored.balance

    def name(self, account: TrackedAccount) -> str:
        stored = self.stored.get(account.id)
        return account.name if stored is None else stored.name

    def netted(self, account_id: str) -> int:
        return next(a.balance for a in self.worth.accounts if a.id == account_id)

    def mapped(self, debt_account_id: str) -> tuple[str, ...]:
        tracked = {a.id for a in self.tracked if a.bucket is not Bucket.DEBT}
        targets = next(
            (n.mapped_to for n in self.nettings if n.debt_account_id == debt_account_id), ()
        )
        return tuple(target for target in targets if target in tracked)


def load_snapshot(store: Store, config: LatestConfig, today: dt.date) -> Snapshot:
    """Read everything the view shows from the store. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    stored = {account.id: account for account in store.accounts(budget_id)}
    tracked = tuple(tracking.effective_accounts(config, stored.values()))
    nettings = tracking.effective_nettings(config)
    worth = net_worth(
        [
            AccountBalance(
                id=a.id,
                name=a.name,
                bucket=a.bucket,
                balance=stored[a.id].balance if a.id in stored else 0,
            )
            for a in tracked
        ],
        nettings,
    )
    amounts = store.daily_amounts(budget_id, [a.id for a in tracked]) if tracked else {}
    earliest = min((a.days[0][0] for a in amounts.values() if a.days), default=today)
    logged = tracking.logged_adjustments(store, budget_id)
    by_hand = {
        a.id: tracking.last_set_by_hand(
            store.transactions(budget_id, account_id=a.id), config.adjustments, logged.get(a.id)
        )
        for a in tracked
        if a.track_balance
    }
    return Snapshot(
        tracked=tracked,
        stored=stored,
        nettings=nettings,
        worth=worth,
        earliest=min(earliest, today),
        last_set=by_hand,
    )


def table_order(snapshot: Snapshot) -> list[TrackedAccount]:
    """The counted accounts as the Accounts table lists them: by bucket, largest first."""
    ordered: list[TrackedAccount] = []
    for bucket in NET_WORTH_ORDER:
        accounts = [a for a in snapshot.tracked if a.bucket is bucket]
        if bucket is Bucket.DEBT:
            accounts.sort(key=lambda a: snapshot.raw(a.id))
        else:
            accounts.sort(key=lambda a: snapshot.netted(a.id), reverse=True)
        ordered += accounts
    return ordered


def default_picked(snapshot: Snapshot) -> list[str]:
    """The accounts "by account" starts with: the largest after netting, debt left out."""
    positive = [a for a in snapshot.worth.accounts if a.bucket is not Bucket.DEBT]
    positive.sort(key=lambda a: a.balance, reverse=True)
    return [a.id for a in positive[:DEFAULT_PICKED]]


# ---- the balance write -----------------------------------------------------------------------


def parse_balance(text: str, currency_format: CurrencyFormat) -> int | None:
    """The typed balance in milliunits, with the budget's separators first, then plain."""
    try:
        return parse_amount_to_milliunits(
            text,
            decimal_separator=currency_format.decimal_separator,
            group_separator=currency_format.group_separator,
        )
    except ValueError:
        return parse_amount_to_milliunits(text)


def set_balance(
    client: Client, config: LatestConfig, account_id: str, wanted: int, today: dt.date
) -> list[Adjustment]:
    """Create the adjustment that takes the account to `wanted`. Blocking: YNAB calls.

    The budget copy may lag behind YNAB (the phone app, `yul load`), so the adjustment starts
    from the balance YNAB has right now. Empty when YNAB already has that balance.
    """
    budget_id = config.budget.id
    settings = config.adjustments
    live = client.account(budget_id, account_id).balance
    adjustments = build_adjustments({account_id: live}, {account_id: wanted})
    if adjustments:
        create_adjustments(
            client,
            budget_id,
            adjustments,
            settings.memo,
            settings.payee,
            TransactionClearedStatus(settings.cleared.value),
            today,
        )
    return adjustments
