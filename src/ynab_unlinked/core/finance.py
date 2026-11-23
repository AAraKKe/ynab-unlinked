"""Where the money of a period came from and where it went, from the lines in the store.

Every line of a counted account (a transaction, or one line of a split) is one of:

- **income**: money in, other than a transfer, to an account on the budget, whatever its
  category. Refunds and reimbursements are income too: they raise income and spending alike.
- **spending**: money out, other than a transfer, of an account on the budget.
- **set aside**: money out of an account on the budget in a category marked "not spending"
  (money put away or moved to assets YNAB does not track).
- **assets**: what an asset changed by on its own, outside transfers: any line of a tracking
  account that is not a transfer (market moves, interest, a sale recorded as an adjustment),
  and the balance adjustments of the budget accounts whose return is followed
  (`Rules.returns`), such as the interest of a savings account.
- **transfers**: transfers with another counted account. They add up to zero over all of them.
- **outside**: starting balances, and transfers with accounts that are not counted.

Closed accounts count for the past, when they held money: a transfer from one is a transfer,
not money from outside.

So the change of net worth over a period is exactly the sum of the six, and each account's
change splits the same way.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields

from ynab_unlinked.core.history import balances_at
from ynab_unlinked.store import STARTING_BALANCE_PAYEE, Line, Store

RECONCILIATION_PAYEE = "Reconciliation Balance Adjustment"
"""The payee YNAB gives the adjustment a reconcile creates when the balance differs."""

DAYS_IN_YEAR = 365


@dataclass(frozen=True)
class Flows:
    """Milliunits, signed as they change net worth: spending and set aside are never positive."""

    income: int = 0
    spending: int = 0
    set_aside: int = 0
    assets: int = 0
    transfers: int = 0
    outside: int = 0

    @property
    def saved(self) -> int:
        """Income minus spending."""
        return self.income + self.spending

    @property
    def other(self) -> int:
        """What moved net worth besides saving and assets: set aside and outside."""
        return self.set_aside + self.outside

    @property
    def change(self) -> int:
        return self.saved + self.other + self.assets + self.transfers

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
    returns: frozenset[str] = frozenset()
    """Accounts whose return is followed. On a budget account, its balance adjustments are
    asset changes (interest, gains), not income or spending."""
    adjustment_payees: frozenset[str] = frozenset({RECONCILIATION_PAYEE})
    """The payees of balance adjustments: YNAB's and the one yul writes."""

    def kind(self, line: Line) -> str | None:
        """The `Flows` field the line adds to, None when its account is not counted."""
        on_budget = self.on_budget.get(line.account_id)
        if on_budget is None:
            return None
        if line.transfer_account_id is not None:
            return "transfers" if line.transfer_account_id in self.on_budget else "outside"
        if line.payee_name == STARTING_BALANCE_PAYEE:
            return "outside"
        if not on_budget or (
            line.account_id in self.returns and line.payee_name in self.adjustment_payees
        ):
            return "assets"
        if line.amount >= 0:
            return "income"
        return "set_aside" if line.category_id in self.not_spending else "spending"


@dataclass(frozen=True)
class CategorySpend:
    category_id: str | None
    name: str
    amount: int
    """Spent in the period, always negative: a refund is income and does not lower it."""


@dataclass(frozen=True)
class PayeeIncome:
    name: str
    amount: int


@dataclass(frozen=True)
class AccountMove:
    """How one counted account moved over the period."""

    account_id: str
    start_balance: int
    """At the end of the day before the period."""
    end_balance: int
    flows: Flows
    rate: float | None
    """Its time weighted return over the days of the period it held money (`period_return`),
    when it is followed and its assets moved; not annualised."""
    rate_days: int = 0
    """How many days `rate` is measured over: fewer than the period's when the account held
    no money for part of it (opened late, or emptied and filled again)."""

    @property
    def change(self) -> int:
        return self.end_balance - self.start_balance

    @property
    def own_money(self) -> int:
        """What moved it besides its asset changes: what you put in or took out."""
        return self.change - self.flows.assets


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
    breakdowns: tuple[Breakdown, ...] = field(default=())
    """Income, spending and assets, row by row and line by line (`breakdowns`)."""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def breakdown(self, kind: str) -> Breakdown:
        """The breakdown of `kind` (`income`, `spending` or `assets`); empty when it has none."""
        return next((b for b in self.breakdowns if b.kind == kind), Breakdown(kind, (), ()))


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


def income_by_payee(lines: Iterable[Line], rules: Rules) -> list[PayeeIncome]:
    """What came in from each payee, most first. Income is counted by payee, not category."""
    amounts: dict[str, int] = {}
    for line in lines:
        if rules.kind(line) == "income":
            name = line.payee_name or "No payee"
            amounts[name] = amounts.get(name, 0) + line.amount
    return sorted(
        (PayeeIncome(name, amount) for name, amount in amounts.items()),
        key=lambda income: (-income.amount, income.name),
    )


BREAKDOWN_KINDS = ("income", "spending", "assets")
"""The kinds a breakdown lists, as `Flows` names them."""


@dataclass(frozen=True)
class Entry:
    """One line behind a breakdown, as a list of transactions shows it."""

    transaction_id: str
    date: dt.date
    payee: str
    account_id: str
    amount: int
    category: str | None
    group: str
    """The key of the `Group` it adds to."""


@dataclass(frozen=True)
class Group:
    """One row of a breakdown: a payee (income), a category (spending) or an account (assets)."""

    key: str
    """The payee's name, the category's id (`""` for none) or the account's id."""
    name: str
    """The payee, the category as it is named now; for assets the account's id, which the
    caller names."""
    amount: int
    count: int
    """How many lines add up to `amount`."""
    accounts: tuple[str, ...]
    """The accounts its lines are in, most money first."""


@dataclass(frozen=True)
class Breakdown:
    """Every line of one kind of a period, grouped. The groups and the lines add up to the
    `Flows` field of the same name exactly."""

    kind: str
    groups: tuple[Group, ...]
    """Income most first, spending most spent first, assets largest either way first."""
    entries: tuple[Entry, ...]
    """Newest first."""

    @property
    def total(self) -> int:
        return sum(group.amount for group in self.groups)

    def entries_of(self, key: str | None) -> list[Entry]:
        """The lines of one group, or of all of them when `key` is None."""
        return [e for e in self.entries if key is None or e.group == key]


def _group_key(kind: str, line: Line) -> str:
    if kind == "income":
        return line.payee_name or "No payee"
    if kind == "spending":
        return line.category_id or ""
    return line.account_id


def breakdowns(
    lines: Iterable[Line], rules: Rules, names: Mapping[str, str] | None = None
) -> tuple[Breakdown, ...]:
    """Income by payee, spending by category and assets by account, with the lines behind
    each row. `names` (category id to name) wins over a line's category name.

    Each line goes where `Rules.kind` puts it, so every breakdown adds up to its `Flows` field.
    Lines of no amount are left out: they move nothing.
    """
    names = names or {}
    found: dict[str, list[Entry]] = {kind: [] for kind in BREAKDOWN_KINDS}
    titles: dict[str, str] = {}
    for line in lines:
        kind = rules.kind(line)
        if kind not in found or not line.amount:
            continue
        key = _group_key(kind, line)
        if kind == "spending":
            titles.setdefault(key, names.get(key, line.category_name or "Uncategorized"))
        found[kind].append(
            Entry(
                line.transaction_id,
                line.date,
                line.payee_name or "No payee",
                line.account_id,
                line.amount,
                line.category_name,
                key,
            )
        )
    order = {
        "income": lambda group: (-group.amount, group.name),
        "spending": lambda group: (group.amount, group.name),
        "assets": lambda group: (-abs(group.amount), group.name),
    }
    result: list[Breakdown] = []
    for kind, entries in found.items():
        by_key: dict[str, list[Entry]] = {}
        for entry in entries:
            by_key.setdefault(entry.group, []).append(entry)
        groups: list[Group] = []
        for key, members in by_key.items():
            into: dict[str, int] = {}
            for entry in members:
                into[entry.account_id] = into.get(entry.account_id, 0) + abs(entry.amount)
            groups.append(
                Group(
                    key,
                    titles.get(key, key),
                    sum(entry.amount for entry in members),
                    len(members),
                    tuple(sorted(into, key=lambda account: (-into[account], account))),
                )
            )
        groups.sort(key=order[kind])
        newest = sorted(entries, key=lambda entry: entry.date, reverse=True)
        result.append(Breakdown(kind, tuple(groups), tuple(newest)))
    return tuple(result)


@dataclass(frozen=True)
class Return:
    rate: float
    """Not annualised."""
    days: int
    """The days it is measured over: the ones the account held money."""


def period_return(
    start_balance: int,
    flows: Sequence[tuple[dt.date, int]],
    gains: Sequence[tuple[dt.date, int]],
    start: dt.date,
    end: dt.date,
) -> Return | None:
    """The time weighted return of an account over `start`..`end`, both included.

    `flows` are the money put in (positive) or taken out (negative) on each date, `gains` what
    the asset changes added on each date. Each day's gain is measured against what the account
    held that morning plus the money that came in that day (money taken out leaves after the
    gain), and the days are compounded. Days it held nothing are left out, so emptying an
    account and filling it again later does not break it. A gain written down after the money
    left (the account below zero) belongs to the money it last held. A gain on an empty
    account (shares recorded as they arrive) earns nothing: it is what fills it. None when it
    never held money.
    """
    into: dict[dt.date, int] = {}
    out: dict[dt.date, int] = {}
    gained: dict[dt.date, int] = {}
    for day, amount in flows:
        if start <= day <= end:
            side = into if amount > 0 else out
            side[day] = side.get(day, 0) + amount
    for day, amount in gains:
        if start <= day <= end:
            gained[day] = gained.get(day, 0) + amount
    growth, days, balance = 1.0, 0, start_balance
    last_base = max(start_balance, 0)
    held_since: dt.date | None = start if start_balance > 0 else None
    for day in sorted(into.keys() | out.keys() | gained.keys()):
        gain = gained.get(day, 0)
        base = balance + into.get(day, 0)
        if base > 0:
            last_base = base
            growth *= max(0.0, 1 + gain / base)
        elif base < 0 and gain and last_base:
            growth *= max(0.0, 1 + gain / last_base)
        after = base + out.get(day, 0) + gain
        # Days are counted between the moments it starts and stops holding money
        if held_since is None and (base > 0 or after > 0):
            held_since = day
        if held_since is not None and after <= 0:
            days += (day - held_since).days + 1
            held_since = None
        balance = after
    if held_since is not None:
        days += (end - held_since).days + 1
    if days == 0:
        return None
    return Return(growth - 1, days)


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
        measured = None
        if account_id in rules.returns and flows.assets:
            own: list[tuple[dt.date, int]] = []
            gains: list[tuple[dt.date, int]] = []
            for line in lines:
                if line.account_id == account_id:
                    kind = rules.kind(line)
                    (gains if kind == "assets" else own).append((line.date, line.amount))
            measured = period_return(start_balance, own, gains, start, end)
        moves.append(
            AccountMove(
                account_id,
                start_balance,
                end_balance,
                flows,
                measured.rate if measured else None,
                measured.days if measured else 0,
            )
        )
    moves.sort(key=lambda move: (-abs(move.change), move.account_id))

    return Period(
        start=start,
        end=end,
        flows=total(per_account.values()),
        start_worth=sum(move.start_balance for move in moves),
        end_worth=sum(move.end_balance for move in moves),
        months=months,
        accounts=tuple(moves),
        breakdowns=breakdowns(lines, rules, names),
    )
