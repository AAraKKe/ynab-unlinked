"""What the Months and Movers tabs of Net worth show, worked out without NiceGUI.

The months a range pill covers, the rules that sort every line (`core.finance.Rules`) from the
counted accounts and Settings › Categories, the period read from the store, and the words of
the period drawer. Everything is plain Python, tested directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.finance import AccountMove, Flows, Period, Rules, annualised, month_start
from ynab_unlinked.core.finance import period as read_period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store
from ynab_unlinked.web.views.networth.data import Snapshot, signed

TABS = {"overview": "Overview", "months": "Months", "movers": "Movers"}

RANGE_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}
"""How many calendar months each range pill shows, the current one included. YTD starts in
January and All at the first transaction."""

TOP_ACCOUNTS = 5
TOP_CATEGORIES = 5


def months_range(key: str, today: dt.date, earliest: dt.date) -> tuple[dt.date, dt.date]:
    """The first day of the first month a range pill covers, and today.

    Whole months, so the bars of the Months tab add up to its totals. Never before the month
    of the first transaction.
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


def rules(snapshot: Snapshot, config: LatestConfig) -> Rules:
    """The counted accounts (on the budget or tracking) and the "not spending" categories."""
    return Rules(
        on_budget={
            account.id: snapshot.stored[account.id].on_budget
            if account.id in snapshot.stored
            else True
            for account in snapshot.tracked
        },
        not_spending=frozenset(config.finances.not_spending),
    )


def load_period(
    store: Store, config: LatestConfig, snapshot: Snapshot, start: dt.date, end: dt.date
) -> Period:
    """Read one period from the store. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    names = {category.id: category.name for category in store.categories(budget_id)}
    return read_period(store, budget_id, rules(snapshot, config), start, end, names)


def period_title(start: dt.date, end: dt.date) -> str:
    """`April 2026` for a whole month (or this month so far), `Jan 2026 – Nov 2026` otherwise."""
    if (start.year, start.month) == (end.year, end.month):
        return start.strftime("%B %Y")
    return f"{start.strftime('%b %Y')} – {end.strftime('%b %Y')}"


@dataclass(frozen=True)
class Step:
    """One bar of the drawer's bridge: what took net worth from the start to the end."""

    label: str
    amount: int
    kind: str
    """`income`, `spending`, `valuation`, `other` or `net`: the bar's colour."""


def bridge(flows: Flows) -> list[Step]:
    """Income, spending, valuation and the rest, then the net change. Empty steps are left out.

    Transfers between counted accounts add up to zero, so they are not a step.
    """
    steps = [
        Step("Income", flows.income, "income"),
        Step("Spending", flows.spending, "spending"),
        Step("Valuation", flows.valuation, "valuation"),
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
    if not flows.valuation:
        return f"{first}."
    joint = "and" if (saved >= 0) == (flows.valuation >= 0) else "but"
    what = "added" if flows.valuation > 0 else "took"
    return f"{first}, {joint} valuation {what} {money(abs(flows.valuation))}."


def why(move: AccountMove, formatter: Formatter) -> str:
    """What moved one account: `income +4,850 · spending −3,650 · transfers −1,520`."""
    flows = move.flows
    parts = [
        ("income", flows.income),
        ("spending", flows.spending),
        ("set aside", flows.set_aside),
        ("transfers", flows.transfers),
        ("valuation", flows.valuation),
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
