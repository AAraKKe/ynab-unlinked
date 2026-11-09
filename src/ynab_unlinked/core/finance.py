"""Where the money of a period came from and where it went, from the lines in the store.

Every line of a counted account (a transaction, or one line of a split) is one of:

- **income**: money in, other than a transfer, to an account on the budget, whatever its
  category. Refunds and reimbursements are income too: they raise income and spending alike.
- **spending**: money out, other than a transfer, of an account on the budget.
- **set aside**: money out of an account on the budget in a category marked "not spending"
  (money put away or moved to assets YNAB does not track).
- **valuation**: any line of a tracking account that is not a transfer: what its value did.
- **transfers**: transfers with another counted account. They add up to zero over all of them.
- **outside**: starting balances, and transfers with accounts that are not counted.

So the change of net worth over a period is exactly the sum of the six, and each account's
change splits the same way.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields

from ynab_unlinked.core.history import balances_at
from ynab_unlinked.store import STARTING_BALANCE_PAYEE, Line, Store

DAYS_IN_YEAR = 365


@dataclass(frozen=True)
class Flows:
    """Milliunits, signed as they change net worth: spending and set aside are never positive."""

    income: int = 0
    spending: int = 0
    set_aside: int = 0
    valuation: int = 0
    transfers: int = 0
    outside: int = 0

    @property
    def saved(self) -> int:
        """Income minus spending."""
        return self.income + self.spending

    @property
    def other(self) -> int:
        """What moved net worth besides saving and valuation: set aside and outside."""
        return self.set_aside + self.outside

    @property
    def change(self) -> int:
        return self.saved + self.other + self.valuation + self.transfers

    def __add__(self, other: Flows) -> Flows:
        return Flows(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)}
        )


@dataclass(frozen=True)
class Rules:
    """What a line is depends on its account and category."""

    on_budget: Mapping[str, bool]
    """Every counted account, and whether it is on the budget (False: a tracking account)."""
    not_spending: frozenset[str] = frozenset()
    """Category ids whose outflows are set aside, not spent."""

    def kind(self, line: Line) -> str | None:
        """The `Flows` field the line adds to, None when its account is not counted."""
        on_budget = self.on_budget.get(line.account_id)
        if on_budget is None:
            return None
        if line.transfer_account_id is not None:
            return "transfers" if line.transfer_account_id in self.on_budget else "outside"
        if line.payee_name == STARTING_BALANCE_PAYEE:
            return "outside"
        if not on_budget:
            return "valuation"
        if line.amount >= 0:
            return "income"
        return "set_aside" if line.category_id in self.not_spending else "spending"


@dataclass(frozen=True)
class CategorySpend:
    category_id: str | None
    name: str
    amount: int
    """Spent in the period: negative, or positive when refunds outweigh it."""


@dataclass(frozen=True)
class AccountMove:
    """How one counted account moved over the period."""

    account_id: str
    start_balance: int
    """At the end of the day before the period."""
    end_balance: int
    flows: Flows
    rate: float | None
    """Its return over the period (money weighted), when valuation moved it; not annualised."""

    @property
    def change(self) -> int:
        return self.end_balance - self.start_balance

    @property
    def own_money(self) -> int:
        """What moved it besides valuation: what you put in or took out."""
        return self.change - self.flows.valuation


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date
    flows: Flows
    """Every counted account together. `flows.change` is the change of net worth."""
    start_worth: int
    end_worth: int
    months: tuple[tuple[dt.date, Flows], ...]
    """Every calendar month the period touches, by its first day, oldest first."""
    accounts: tuple[AccountMove, ...] = field(default=())
    """Largest change first, either way."""
    spending: tuple[CategorySpend, ...] = field(default=())
    """By category, most spent first."""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def month_end(day: dt.date) -> dt.date:
    following = (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return following - dt.timedelta(days=1)


def months_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """The first day of every month from `start`'s to `end`'s, both included."""
    months: list[dt.date] = []
    month = month_start(start)
    while month <= end:
        months.append(month)
        month = month_end(month) + dt.timedelta(days=1)
    return months


def flows_by_account(lines: Iterable[Line], rules: Rules) -> dict[str, Flows]:
    """The flows of each counted account that has lines."""
    totals: dict[str, dict[str, int]] = {}
    for line in lines:
        if (kind := rules.kind(line)) is None:
            continue
        account = totals.setdefault(line.account_id, {})
        account[kind] = account.get(kind, 0) + line.amount
    return {account_id: Flows(**values) for account_id, values in totals.items()}


def total(flows: Iterable[Flows]) -> Flows:
    result = Flows()
    for item in flows:
        result += item
    return result


def spending_by_category(
    lines: Iterable[Line], rules: Rules, names: Mapping[str, str] | None = None
) -> list[CategorySpend]:
    """What each category spent, most first. `names` (id to name) wins over a line's name.

    Only spending lines count: income in a category (a refund) does not lower it, since
    refunds are income.
    """
    names = names or {}
    amounts: dict[str | None, int] = {}
    seen: dict[str | None, str] = {}
    for line in lines:
        if rules.kind(line) != "spending":
            continue
        amounts[line.category_id] = amounts.get(line.category_id, 0) + line.amount
        seen.setdefault(line.category_id, line.category_name or "Uncategorized")
    return sorted(
        (
            CategorySpend(category_id, names.get(category_id or "", seen[category_id]), amount)
            for category_id, amount in amounts.items()
        ),
        key=lambda spend: (spend.amount, spend.name),
    )


def period_return(
    start_balance: int,
    flows: Sequence[tuple[dt.date, int]],
    gain: int,
    start: dt.date,
    end: dt.date,
) -> float | None:
    """The modified Dietz return of an account over `start`..`end`, both included.

    `flows` are the money put in (positive) or taken out (negative) on each date, `gain` what
    valuation added. Money counts from the start of the day it came in, so money put in late
    in the period counts for less of it. None when there
    was nothing invested to earn a return on.
    """
    days = (end - start).days + 1
    invested = start_balance + sum(
        amount * ((end - day).days + 1) / days for day, amount in flows if start <= day <= end
    )
    if invested <= 0:
        return None
    return gain / invested


def annualised(rate: float, days: int) -> float:
    """`rate` over `days` as a yearly rate; unchanged for a year or less."""
    if days <= DAYS_IN_YEAR or rate <= -1:
        return rate
    return (1 + rate) ** (DAYS_IN_YEAR / days) - 1


def period(
    store: Store,
    budget_id: str,
    rules: Rules,
    start: dt.date,
    end: dt.date,
    names: Mapping[str, str] | None = None,
) -> Period:
    """The period `start`..`end` (both included) of the counted accounts in `rules`.

    Blocking: it reads the store. `names` gives categories their current name.
    """
    lines = [
        line
        for line in store.lines(budget_id, since=start, until=end)
        if line.account_id in rules.on_budget
    ]
    by_month: dict[dt.date, list[Line]] = {month: [] for month in months_between(start, end)}
    for line in lines:
        by_month[month_start(line.date)].append(line)
    months = tuple(
        (month, total(flows_by_account(month_lines, rules).values()))
        for month, month_lines in by_month.items()
    )

    account_ids = list(rules.on_budget)
    day_before = start - dt.timedelta(days=1)
    balances = balances_at(store, budget_id, account_ids, [day_before, end])
    per_account = flows_by_account(lines, rules)
    moves: list[AccountMove] = []
    for account_id in account_ids:
        flows = per_account.get(account_id, Flows())
        start_balance, end_balance = balances[account_id]
        rate = None
        if flows.valuation:
            own = [
                (line.date, line.amount)
                for line in lines
                if line.account_id == account_id and rules.kind(line) != "valuation"
            ]
            rate = period_return(start_balance, own, flows.valuation, start, end)
        moves.append(AccountMove(account_id, start_balance, end_balance, flows, rate))
    moves.sort(key=lambda move: (-abs(move.change), move.account_id))

    return Period(
        start=start,
        end=end,
        flows=total(per_account.values()),
        start_worth=sum(move.start_balance for move in moves),
        end_worth=sum(move.end_balance for move in moves),
        months=months,
        accounts=tuple(moves),
        spending=tuple(spending_by_category(lines, rules, names)),
    )
