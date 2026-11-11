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
    DAYS_IN_YEAR,
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
    """Income, spending, growth and the rest, then the net change. Empty steps are left out.

    Transfers between counted accounts add up to zero, so they are not a step.
    """
    steps = [
        Step("Income", flows.income, "income"),
        Step("Spending", flows.spending, "spending"),
        Step("Growth", flows.assets, "assets"),
        Step("Other", flows.other + flows.transfers, "other"),
    ]
    return [step for step in steps if step.amount] + [Step("Net", flows.change, "net")]


def why(move: AccountMove, formatter: Formatter) -> str:
    """What moved one account: `income +4,850 · spending −3,650 · transfers −1,520`."""
    flows = move.flows
    parts = [
        ("income", flows.income),
        ("spending", flows.spending),
        ("set aside", flows.set_aside),
        ("transfers", flows.transfers),
        ("growth", flows.assets),
        ("from outside", flows.outside),
    ]
    text = " · ".join(f"{label} {signed(formatter, amount)}" for label, amount in parts if amount)
    return text or "no change"


def moved(period: Period, limit: int = TOP_ACCOUNTS) -> list[AccountMove]:
    """The accounts that moved most, either way; the ones that did not move are left out."""
    return [move for move in period.accounts if move.change or move.flows.transfers][:limit]


PART_MARK = "*"
PART_NOTE = (
    "* Measured only over the days the account held money. It was empty, or not open yet, "
    "for the rest of the range."
)


def rate_text(move: AccountMove, days: int) -> str:
    """The account's return, per year when it is measured over more than one: `6.1%`,
    `−8.9%/yr`, with `PART_MARK` when it is measured over fewer days than the range's."""
    if move.rate is None:
        return "—"
    rate = annualised(move.rate, move.rate_days)
    suffix = "/yr" if move.rate_days > DAYS_IN_YEAR else ""
    mark = PART_MARK if partial(move, days) else ""
    return f"{rate * 100:+.1f}%{suffix}{mark}".replace("-", "−")


def partial(move: AccountMove, days: int) -> bool:
    """Whether the return leaves out days of the range: the account held nothing on them."""
    return move.rate is not None and move.rate_days < days


def rate_title(move: AccountMove, days: int) -> str | None:
    """The hover of a partial return: `Held money on 205 of the 315 days of the range`."""
    if not partial(move, days):
        return None
    yearly = ", per year over those days" if move.rate_days > DAYS_IN_YEAR else ""
    return f"Held money on {move.rate_days} of the {days} days of the range{yearly}"


RETURN_TITLE = "How Return is measured"
RETURN_LEDE = (
    "Return is how the account itself did: what was in it grew or shrank by that much, "
    "whatever you put in or took out. Growth is what that made you, in money. The two can "
    "point different ways."
)
RETURN_END = (
    "So Return says how the account did, and selling or emptying it does not make it look "
    "worse; Growth says what it made you. Finance calls Return the time weighted return, and "
    "what your money made the money weighted one."
)


@dataclass(frozen=True)
class StoryStep:
    """One step of the made-up account behind the "i" of Return."""

    label: str
    """Under its bar."""
    text: str
    held: int
    """What the account holds after it, milliunits."""
    put_in: int
    """What you put in so far."""
    rate: float
    """Return so far."""

    @property
    def growth(self) -> int:
        return self.held - self.put_in


def return_story(formatter: Formatter) -> list[StoryStep]:
    """1,000 that grows 50%, 8,500 more put in, and a 20% fall: Return ends up, Growth down."""
    money = formatter.format_amount_milli
    return [
        StoryStep("Start", f"You put {money(1_000_000)} into an account.", 1_000_000, 1_000_000, 0),
        StoryStep(
            "+50%",
            f"It grows 50%: it holds {money(1_500_000)}. Return is +50.0%, Growth "
            f"+{money(500_000)}.",
            1_500_000,
            1_000_000,
            0.5,
        ),
        StoryStep(
            "Put in",
            f"You put {money(8_500_000)} more in. That is your money, not a gain: Return and "
            "Growth stay where they were.",
            10_000_000,
            9_500_000,
            0.5,
        ),
        StoryStep(
            "−20%",
            f"It falls 20%: {money(10_000_000)} becomes {money(8_000_000)}. Up 50% and then "
            "down 20% is up 20%, so Return is +20.0%. But the fall hit ten times the money the "
            f"rise did: Growth is {money(-1_500_000)}.",
            8_000_000,
            9_500_000,
            0.2,
        ),
    ]


def percent_text(rate: float) -> str:
    return f"{rate * 100:+.1f}%".replace("-", "−")


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
