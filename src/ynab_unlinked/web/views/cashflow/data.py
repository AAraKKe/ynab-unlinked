"""What the Cash flow view shows, worked out without NiceGUI: the range, the tiles' words and
the comparison with the range before."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.cashflow import CashFlow
from ynab_unlinked.core.finance import month_start
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store
from ynab_unlinked.web import finances

DEFAULT_RANGE = "1Y"
TOP_PAYEES = 6


@dataclass(frozen=True)
class CashFlowPage:
    flow: CashFlow
    before: CashFlow | None
    """The same number of months right before, when the budget goes back that far."""
    liquid: int
    """Cash and savings now, after the debts netted into them."""


def load(store: Store, config: LatestConfig, range_key: str, today: dt.date) -> CashFlowPage:
    """Read the range and the one before it. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    first = finances.earliest(store, budget_id, today)
    start, end = finances.months_range(range_key, today, first)
    flow = finances.load_cash_flow(store, config, start, end)
    before = None
    if range_key != "All":
        previous_start, previous_end = finances.previous_range(start, end)
        if previous_start >= month_start(first):
            before = finances.load_cash_flow(store, config, previous_start, previous_end)
    return CashFlowPage(flow, before, finances.liquid(config, store.accounts(budget_id)))


def percent(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}%"


def rate_change(page: CashFlowPage) -> str | None:
    """`▲ 4.2 pts vs the 12 months before`, None without a range before to compare with."""
    now = page.flow.savings_rate
    before = None if page.before is None else page.before.savings_rate
    if now is None or before is None:
        return None
    points = (now - before) * 100
    months = len(page.flow.complete)
    if abs(points) < 0.05:
        return f"same as the {months} months before"
    arrow = "▲" if points > 0 else "▼"
    return f"{arrow} {abs(points):.1f} pts vs the {months} months before"


def runway(page: CashFlowPage) -> float | None:
    """How many months of core spending cash and savings cover."""
    return finances.runway_months(page.flow, page.liquid)


def runway_text(page: CashFlowPage) -> str:
    months = runway(page)
    return "—" if months is None else f"{months:.1f} months"


def spending_hint(page: CashFlowPage, formatter: Formatter) -> str:
    """`core 2,700.00€ · one-offs 575.00€`: steady and variable categories against the rest."""
    flow = page.flow
    core = flow.core_spending()
    if not core:
        return "per complete month"
    one_offs = max(flow.mean_spending - core, 0)
    money = formatter.format_amount_milli
    return f"core {money(round(core))} · one-offs {money(round(one_offs))}"


def complete_note(flow: CashFlow) -> str:
    """What the averages are over: `12 complete months, not this one`."""
    months = len(flow.complete)
    word = "month" if months == 1 else "months"
    running = len(flow.months) > months
    return f"{months} complete {word}" + (", not this one" if running else "")
