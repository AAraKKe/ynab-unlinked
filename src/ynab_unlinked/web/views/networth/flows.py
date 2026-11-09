"""What the Months and Movers tabs of Net worth show, worked out without NiceGUI.

The months a range pill covers, the rules that sort every line (`core.finance.Rules`) from the
counted accounts (closed ones too) and Settings, the period read from the store, and the words
of the period panel. Everything is plain Python, tested directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.finance import (
    AccountMove,
    Flows,
    Period,
    Rules,
    annualised,
)
from ynab_unlinked.core.finance import period as read_period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store
from ynab_unlinked.web import finances
from ynab_unlinked.web.finances import RANGE_MONTHS, months_range, period_title
from ynab_unlinked.web.views.networth.data import Snapshot, signed

TABS = {"overview": "Overview", "months": "Months", "movers": "Movers"}

__all__ = ["RANGE_MONTHS", "months_range", "period_title"]

TOP_ACCOUNTS = 5
TOP_CATEGORIES = 5


def rules(snapshot: Snapshot, config: LatestConfig) -> Rules:
    """`web.finances.rules` for the accounts of the snapshot."""
    return finances.rules(config, snapshot.stored.values())


def account_names(snapshot: Snapshot) -> dict[str, str]:
    """The name of every account the period counts, closed ones included."""
    return {account.id: snapshot.name(account) for account in snapshot.history}


def load_period(
    store: Store, config: LatestConfig, snapshot: Snapshot, start: dt.date, end: dt.date
) -> Period:
    """Read one period from the store. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    names = finances.category_names(store, budget_id)
    return read_period(store, budget_id, rules(snapshot, config), start, end, names)


@dataclass(frozen=True)
class Step:
    """One bar of the drawer's bridge: what took net worth from the start to the end."""

    label: str
    amount: int
    kind: str
    """`income`, `spending`, `assets`, `other` or `net`: the bar's colour."""


def bridge(flows: Flows) -> list[Step]:
    """Income, spending, assets and the rest, then the net change. Empty steps are left out.

    Transfers between counted accounts add up to zero, so they are not a step.
    """
    steps = [
        Step("Income", flows.income, "income"),
        Step("Spending", flows.spending, "spending"),
        Step("Assets", flows.assets, "assets"),
        Step("Other", flows.other + flows.transfers, "other"),
    ]
    return [step for step in steps if step.amount] + [Step("Net", flows.change, "net")]


def headline(flows: Flows, formatter: Formatter) -> str:
    """One sentence on where the change came from."""
    saved = flows.saved
    money = formatter.format_amount_milli
    first = (
        f"You saved {money(saved)}"
        if saved >= 0
        else f"You spent {money(-saved)} more than came in"
    )
    if not flows.assets:
        return f"{first}."
    joint = "and" if (saved >= 0) == (flows.assets >= 0) else "but"
    what = "gained" if flows.assets > 0 else "lost"
    return f"{first}, {joint} your assets {what} {money(abs(flows.assets))}."


def why(move: AccountMove, formatter: Formatter) -> str:
    """What moved one account: `income +4,850 · spending −3,650 · transfers −1,520`."""
    flows = move.flows
    parts = [
        ("income", flows.income),
        ("spending", flows.spending),
        ("set aside", flows.set_aside),
        ("transfers", flows.transfers),
        ("assets", flows.assets),
        ("from outside", flows.outside),
    ]
    text = " · ".join(f"{label} {signed(formatter, amount)}" for label, amount in parts if amount)
    return text or "no change"


def moved(period: Period, limit: int = TOP_ACCOUNTS) -> list[AccountMove]:
    """The accounts that moved most, either way; the ones that did not move are left out."""
    return [move for move in period.accounts if move.change or move.flows.transfers][:limit]


def rate_text(move: AccountMove, days: int) -> str:
    """The account's return, per year when the period is longer than one: `6.1%`, `−8.9%/yr`."""
    if move.rate is None:
        return "—"
    rate = annualised(move.rate, days)
    suffix = "/yr" if days > 365 else ""
    return f"{rate * 100:+.1f}%{suffix}".replace("-", "−")


def next_selection(current: int | None, clicked: int | None) -> int | None:
    """The month selected after a click: another month, or none when it was the one selected
    (or the click was outside the bars)."""
    return None if clicked is None or clicked == current else clicked


OTHER_NOTE = (
    "Other is money set aside in a category marked not spending, starting balances, and "
    "transfers with accounts left out of net worth."
)


def months_up(period: Period) -> tuple[int, int]:
    """How many months net worth went up, of how many."""
    return sum(1 for _, flows in period.months if flows.change > 0), len(period.months)


def best_month(period: Period) -> tuple[dt.date, Flows] | None:
    return max(period.months, key=lambda month: month[1].change, default=None)


def month_bounds(month: dt.date, today: dt.date) -> tuple[dt.date, dt.date]:
    """A month's first and last day, or today for the current month."""
    following = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return month, min(following - dt.timedelta(days=1), today)


def share_of_change(part: int, flows: Flows) -> str | None:
    """`80% of the change` when the part goes the same way as the change and is not larger."""
    change = flows.change
    if not change or (part > 0) != (change > 0) or abs(part) > abs(change):
        return None
    return f"{part / change * 100:.0f}% of the change"


def spread(moves: Sequence[AccountMove]) -> int:
    """The largest change of `moves`, either way: the full width of their bars."""
    return max((abs(move.change) for move in moves), default=0)
