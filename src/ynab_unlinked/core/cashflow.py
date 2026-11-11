"""Income, spending and savings month by month, and how each category spends, from the store.

Lines are sorted by `core.finance.Rules`: income is any money in to a budget account (refunds
too), spending any money out of one that is not a transfer or set aside. Averages, savings
rates and volatility only use complete months: the month that is still running would pull
every average down.

A category's volatility is how much its monthly spending moves around its average (the
coefficient of variation: standard deviation over mean, empty months counted as zero),
between the first and the last month it spent in:

- **steady** under `STEADY_BELOW` (rent, a gym);
- **variable** under `VARIABLE_BELOW` (groceries, eating out);
- above it the money sits in a few months, and how often it spends says which kind it is
  (`presence`):
  - **lumpy** with an expense in less than `LUMPY_BELOW` of its months: nothing most
    months, then an expense, whatever its size (a yearly subscription, an insurance, a
    repair, a holiday);
  - **spiky** with one more often than that: it keeps coming, and some months are far
    bigger than the rest (gifts, clothes).

What a category is does not depend on the range on screen: it is told from its history, the
complete months of the last `HISTORY_MONTHS` (or the range, when that is longer). A yearly
charge is lumpy while the page shows one month, because the history holds three of them.
A history of fewer than `MIN_MONTHS` complete months, or a category that spent in one month
only, gets no label: there is not enough to tell.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ynab_unlinked.core.finance import (
    PayeeIncome,
    Rules,
    income_by_payee,
    month_end,
    month_start,
    months_between,
)
from ynab_unlinked.store import Line, Store

STEADY_BELOW = 0.25
VARIABLE_BELOW = 0.75
LUMPY_BELOW = 0.4
"""A category that moves over `VARIABLE_BELOW` is lumpy with an expense in less than this
share of its months, spiky from it. Over a third, so that a charge every three months is
lumpy: counted from its first charge to its last, five of them show in 5 months of 13."""
EXPENSE_FROM = 0.25
"""The share of the average month from which a month counts as one with an expense."""
ALIKE_BELOW = 0.25
"""Charges are about the same when they vary less than this (their own variation)."""
MIN_MONTHS = 6
HISTORY_MONTHS = 36
"""How far back a category's label looks: long enough for three yearly charges, short enough
that how it spent years ago (another flat, another job) does not blur what it is now."""
MIN_LIFETIME = 3
"""The fewest months from a category's first spending to its last for a label."""
UNUSUAL_ABOVE = 1.25
"""A month is labelled when its income or spending is this many times its median."""
LABEL_LENGTH = 28

Label = str
"""`steady`, `variable`, `spiky` or `lumpy`."""


@dataclass(frozen=True)
class Volatility:
    mean: float
    """Average monthly spending over the months measured, positive milliunits."""
    cv: float | None
    """Standard deviation over mean; None when nothing was spent."""
    label: Label | None
    active: int
    """Months it spent in."""


def presence(spent: Sequence[int]) -> float:
    """The share of `spent`'s months with an expense.

    A month counts in full from `EXPENSE_FROM` of the average month and in proportion below
    it: a fee of a few euros next to a yearly charge does not make it an expense of every
    month.
    """
    mean = statistics.fmean(spent) if spent else 0
    if mean <= 0:
        return 0
    return statistics.fmean(min(1.0, value / (EXPENSE_FROM * mean)) for value in spent)


def volatility(spent: Sequence[int], months: int | None = None) -> Volatility:
    """How `spent` (one positive amount per month, zero when nothing) moves around its mean.

    `months`: how many months the history holds, when `spent` is only part of it (a
    category's life); it must reach `MIN_MONTHS` for a label, and `spent` three months.
    """
    if not spent:
        return Volatility(0, None, None, 0)
    mean = statistics.fmean(spent)
    active = [value for value in spent if value > 0]
    if mean <= 0:
        return Volatility(0, None, None, 0)
    cv = statistics.pstdev(spent) / mean
    label: Label | None = None
    enough = (len(spent) if months is None else months) >= MIN_MONTHS
    if enough and len(spent) >= MIN_LIFETIME and len(active) >= 2:
        if cv < STEADY_BELOW:
            label = "steady"
        elif cv < VARIABLE_BELOW:
            label = "variable"
        else:
            label = "lumpy" if presence(spent) < LUMPY_BELOW else "spiky"
    return Volatility(mean, cv, label, len(active))


@dataclass(frozen=True)
class Rhythm:
    """How a category that spends every so often does it: what a charge costs and how far
    apart charges are."""

    charge: float
    """The average of the months it spent in, positive milliunits."""
    charges: int
    every: float | None
    """Months from one charge to the next, on average; None with fewer than two."""
    alike: bool = False
    """Its charges are about the same amount: "a charge" says what the next one costs."""

    @property
    def set_aside(self) -> float | None:
        """What to put away each month to have the next charge ready."""
        return self.charge / self.every if self.every else None


def rhythm(spent: Sequence[int]) -> Rhythm:
    """The charges in `spent` (one amount per month, zero when nothing was spent)."""
    active = [index for index, value in enumerate(spent) if value > 0]
    if not active:
        return Rhythm(0, 0, None)
    gaps = [later - earlier for earlier, later in zip(active, active[1:], strict=False)]
    amounts = [spent[index] for index in active]
    charge = statistics.fmean(amounts)
    return Rhythm(
        charge=charge,
        charges=len(active),
        every=statistics.fmean(gaps) if gaps else None,
        alike=statistics.pstdev(amounts) / charge < ALIKE_BELOW,
    )


@dataclass(frozen=True)
class CategoryTrend:
    category_id: str | None
    name: str
    group: str
    spent: tuple[int, ...]
    """Positive milliunits per month measured (`CashFlow.measured`), oldest first."""
    volatility: Volatility
    past: tuple[int, ...] = ()
    """What it spent in each month of the history its label was told from (`CashFlow.history`),
    oldest first: the range's months and the ones before them."""

    @property
    def total(self) -> int:
        return sum(self.spent)

    @property
    def mean(self) -> float:
        """Average per month measured of the range, quiet months included."""
        return statistics.fmean(self.spent) if self.spent else 0


@dataclass(frozen=True)
class GroupSpend:
    name: str
    mean: float
    """Average per complete month, positive milliunits."""
    share: float


@dataclass(frozen=True)
class FlowMonth:
    month: dt.date
    """The first day."""
    income: int
    spending: int
    """Positive milliunits."""
    complete: bool
    """False for the month still running."""
    label: str | None = None
    """What made it unusual: the user's note in YNAB, else the payee or category that stood out."""

    @property
    def saved(self) -> int:
        return self.income - self.spending

    @property
    def rate(self) -> float | None:
        return self.saved / self.income if self.income > 0 else None


@dataclass(frozen=True)
class CashFlow:
    start: dt.date
    end: dt.date
    months: tuple[FlowMonth, ...]
    categories: tuple[CategoryTrend, ...] = field(default=())
    """Most spent first."""
    history: tuple[dt.date, ...] = field(default=())
    """The complete months the categories' labels were told from, oldest first."""
    income: tuple[PayeeIncome, ...] = field(default=())
    """By payee over the range, most first."""

    @property
    def complete(self) -> tuple[FlowMonth, ...]:
        return tuple(month for month in self.months if month.complete)

    @property
    def measured(self) -> tuple[FlowMonth, ...]:
        """The months spending is averaged over and `categories` cover: the complete ones, or
        the running month when the range holds no other (this month so far)."""
        return self.complete or self.months

    @property
    def running_only(self) -> bool:
        """The range is the month still running: figures are so far, not averages."""
        return bool(self.months) and not self.complete

    @property
    def mean_income(self) -> float:
        return statistics.fmean(m.income for m in self.complete) if self.complete else 0

    @property
    def median_income(self) -> float:
        return statistics.median(m.income for m in self.complete) if self.complete else 0

    @property
    def mean_spending(self) -> float:
        return statistics.fmean(m.spending for m in self.measured) if self.measured else 0

    @property
    def savings_rate(self) -> float | None:
        """Saved over earned across the complete months."""
        income = sum(m.income for m in self.complete)
        return sum(m.saved for m in self.complete) / income if income > 0 else None

    def core_spending(self) -> float:
        """The average monthly spending of the steady and variable categories: the cost of
        living without one-offs."""
        return sum(
            trend.mean
            for trend in self.categories
            if trend.volatility.label in ("steady", "variable")
        )

    def groups(self) -> list[GroupSpend]:
        totals: dict[str, float] = {}
        for trend in self.categories:
            totals[trend.group] = totals.get(trend.group, 0) + trend.mean
        whole = sum(totals.values())
        return sorted(
            (GroupSpend(name, mean, mean / whole if whole else 0) for name, mean in totals.items()),
            key=lambda group: -group.mean,
        )


@dataclass(frozen=True)
class Categories:
    """Each category's current name and group, for the trends."""

    names: Mapping[str, str] = field(default_factory=dict[str, str])
    groups: Mapping[str, str] = field(default_factory=dict[str, str])


def _lifetime(spent: Sequence[int]) -> Sequence[int]:
    """The months from a category's first spending to its last: the months before it existed
    or after it stopped are not quiet months, they would make it look swingy."""
    active = [index for index, value in enumerate(spent) if value > 0]
    return spent[active[0] : active[-1] + 1] if active else spent


def _monthly(
    lines: Iterable[Line], rules: Rules, months: Sequence[dt.date]
) -> tuple[dict[str | None, list[int]], dict[str | None, str]]:
    """What each category spent in each of `months` (positive), and a name for each."""
    index = {month: position for position, month in enumerate(months)}
    spent: dict[str | None, list[int]] = {}
    names: dict[str | None, str] = {}
    for line in lines:
        if (
            rules.kind(line) != "spending"
            or (position := index.get(month_start(line.date))) is None
        ):
            continue
        row = spent.setdefault(line.category_id, [0] * len(months))
        row[position] -= line.amount
        names.setdefault(line.category_id, line.category_name or "Uncategorized")
    return spent, names


def _spent_by_category(
    lines: Sequence[Line],
    rules: Rules,
    months: Sequence[dt.date],
    history: Sequence[dt.date],
    categories: Categories,
) -> list[CategoryTrend]:
    """The categories that spent in `months` (the range), each told what it is from `history`
    (the months its label looks at, the range's among them)."""
    spent, names = _monthly(lines, rules, months)
    past, _ = _monthly(lines, rules, history)
    trends = [
        CategoryTrend(
            category_id=category_id,
            name=categories.names.get(category_id or "", names[category_id]),
            group=categories.groups.get(category_id or "", "Other"),
            spent=tuple(values),
            volatility=volatility(_lifetime(past.get(category_id, values)), months=len(history)),
            past=tuple(past.get(category_id, ())),
        )
        for category_id, values in spent.items()
    ]
    return sorted(trends, key=lambda trend: (-trend.total, trend.name))


def _months_before(month: dt.date, count: int) -> dt.date:
    """The first day of the month `count` months before `month`."""
    index = month.year * 12 + month.month - 1 - count
    return dt.date(index // 12, index % 12 + 1, 1)


def _short(text: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first if len(first) <= LABEL_LENGTH else first[: LABEL_LENGTH - 1].rstrip() + "…"


def _labels(
    months: Sequence[FlowMonth],
    by_month: Mapping[dt.date, list[Line]],
    rules: Rules,
    trends: Sequence[CategoryTrend],
    notes: Mapping[dt.date, str],
) -> list[str | None]:
    """A month's note in YNAB, else what stood out in a month far above the usual."""
    complete = [m for m in months if m.complete]
    usual_income = statistics.median(m.income for m in complete) if complete else 0
    usual_spending = statistics.median(m.spending for m in complete) if complete else 0
    # What a category usually spends over the whole range, its quiet months included
    means = {trend.category_id: trend.mean for trend in trends}
    names = {trend.category_id: trend.name for trend in trends}
    earned = {
        month.month: {
            i.name: i.amount for i in income_by_payee(by_month.get(month.month, []), rules)
        }
        for month in months
    }
    payees = {name for month in complete for name in earned[month.month]}
    usual_payee = {
        name: statistics.median(earned[month.month].get(name, 0) for month in complete)
        for name in payees
    }
    labels: list[str | None] = []
    for month in months:
        if (note := notes.get(month.month)) and _short(note):
            labels.append(_short(note))
            continue
        label = None
        lines = by_month.get(month.month, [])
        if month.complete and usual_income > 0 and month.income > usual_income * UNUSUAL_ABOVE:
            this = earned[month.month]
            if this:
                label = max(this, key=lambda name: this[name] - usual_payee.get(name, 0))
        elif (
            month.complete
            and usual_spending > 0
            and month.spending > usual_spending * UNUSUAL_ABOVE
        ):
            spent: dict[str | None, int] = {}
            for line in lines:
                if rules.kind(line) == "spending":
                    spent[line.category_id] = spent.get(line.category_id, 0) - line.amount
            if spent:
                over = max(spent, key=lambda key: spent[key] - means.get(key, 0))
                label = names.get(over)
        labels.append(_short(label) if label else None)
    return labels


def cash_flow(
    store: Store,
    budget_id: str,
    rules: Rules,
    start: dt.date,
    end: dt.date,
    *,
    categories: Categories | None = None,
    notes: Mapping[dt.date, str] | None = None,
) -> CashFlow:
    """Every month from `start`'s to `end`'s; the last one is incomplete when `end` is before
    its last day. Blocking: it reads the store."""
    categories = categories or Categories()
    first = month_start(start)
    # Further back than the range when it is short: what a category is takes its history
    since = min(first, _months_before(month_start(end), HISTORY_MONTHS))
    known = [
        line
        for line in store.lines(budget_id, since=since, until=end)
        if line.account_id in rules.on_budget
    ]
    lines = [line for line in known if line.date >= first]
    by_month: dict[dt.date, list[Line]] = {month: [] for month in months_between(start, end)}
    for line in lines:
        by_month[month_start(line.date)].append(line)

    months: list[FlowMonth] = []
    for month, month_lines in by_month.items():
        income = spending = 0
        for line in month_lines:
            kind = rules.kind(line)
            if kind == "income":
                income += line.amount
            elif kind == "spending":
                spending -= line.amount
        months.append(FlowMonth(month, income, spending, complete=month_end(month) <= end))

    # A range that is only the running month shows it so far, rather than nothing
    complete = [month.month for month in months if month.complete] or [m.month for m in months]
    # The history starts with the budget: the months before its first line are not quiet ones
    began = month_start(known[0].date) if known else first
    history = [month for month in months_between(max(since, began), end) if month_end(month) <= end]
    trends = _spent_by_category(known, rules, complete, history, categories)
    labels = _labels(months, by_month, rules, trends, notes or {})
    months = [
        FlowMonth(m.month, m.income, m.spending, m.complete, label)
        for m, label in zip(months, labels, strict=True)
    ]
    return CashFlow(
        start=month_start(start),
        end=end,
        months=tuple(months),
        categories=tuple(trends),
        income=tuple(income_by_payee(lines, rules)),
        history=tuple(history),
    )
