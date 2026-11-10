"""The month so far, for Home: what came in and went out against a usual month.

Read from the budget copy without NiceGUI. "Usual" is the average of the complete months of
the last year, the same months Cash flow and Spending average over.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.finance import month_start, spending_by_category
from ynab_unlinked.store import Store
from ynab_unlinked.web import finances

TOP_CATEGORIES = 5
USUAL_RANGE = "1Y"


@dataclass(frozen=True)
class CategoryPulse:
    category_id: str | None
    name: str
    spent: int
    """This month so far, positive milliunits."""
    usual: float
    """Its average over the complete months, 0 for a category with no history."""


@dataclass(frozen=True)
class MonthPulse:
    month: dt.date
    """The first day of the running month."""
    day: int
    days: int
    income: int
    spending: int
    """Positive milliunits."""
    usual_income: float
    usual_spending: float
    months: int
    """How many complete months "usual" averages; 0 in a budget's first month."""
    savings_rate: float | None
    runway: float | None
    """Months of core spending that cash and savings cover."""
    top: list[CategoryPulse]
    """The categories that spent most this month, most first."""

    @property
    def saved(self) -> int:
        return self.income - self.spending

    @property
    def elapsed(self) -> float:
        """How much of the month is gone, 0..1."""
        return self.day / self.days

    @property
    def spent_share(self) -> float | None:
        """This month's spending over a usual month's, None without one to compare with."""
        return self.spending / self.usual_spending if self.usual_spending > 0 else None


def load_pulse(store: Store, config: LatestConfig, today: dt.date) -> MonthPulse:
    """Read the running month and the year behind it. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    stored = store.accounts(budget_id)
    first = finances.earliest(store, budget_id, today)
    start, end = finances.months_range(USUAL_RANGE, today, first)
    flow = finances.load_cash_flow(store, config, start, end)
    running = next((month for month in flow.months if not month.complete), None)

    usual = {trend.category_id: trend.mean for trend in flow.categories}
    this_month = month_start(today)
    spent = spending_by_category(
        store.lines(budget_id, since=this_month, until=today),
        finances.rules(config, stored),
        finances.category_names(store, budget_id),
    )
    top = [
        CategoryPulse(item.category_id, item.name, -item.amount, usual.get(item.category_id, 0))
        for item in spent
        if item.amount < 0
    ][:TOP_CATEGORIES]

    return MonthPulse(
        month=this_month,
        day=today.day,
        days=calendar.monthrange(today.year, today.month)[1],
        income=running.income if running else 0,
        spending=running.spending if running else 0,
        usual_income=flow.mean_income,
        usual_spending=flow.mean_spending,
        months=len(flow.complete),
        savings_rate=flow.savings_rate,
        runway=finances.runway_months(flow, finances.liquid(config, stored)),
        top=top,
    )


def percent(share: float) -> str:
    return f"{share * 100:.0f}%"


def pace_line(pulse: MonthPulse) -> str:
    """How this month's spending compares with a usual one, in one line.

    `52% of a usual month's spending, 33% of the month gone`.
    """
    share = pulse.spent_share
    if share is None:
        return "No complete month yet to compare with."
    return (
        f"{percent(share)} of a usual month's spending, {percent(pulse.elapsed)} of the month gone"
    )


def rate_text(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}%"


def runway_text(months: float | None) -> str:
    return "—" if months is None else f"{months:.1f} months"
