"""Where net worth goes from here: what the last months measured, carried forward.

`fit` says what a month looked like over a `core.finance.Period` of whole months: what came
in, what was spent, how much of the saving was put into assets and how much was taken out of
them, where the rest stayed (savings or cash), what assets and savings returned a year, and
how much the goal took. Those are the `Assumptions` the plan starts from; the user changes
any of them to see another future.

Money goes into assets and comes back out of them: shares that vest are pay that arrives
as an asset, and most of them are sold later, so the same money is counted going in and then
coming out. `see` reads both off the lines, and `Fit` keeps both to say what happened, but
the plan carries what is left of the two: a month puts into assets what ended up there, or
takes out what they gave back. So what ends up in assets is never more than was saved
unless the budget made up the rest.

A return is time weighted: each month's gain over what the bucket held that month, the
months compounded, so when money was put in does not change it. It is measured over the
months of the fit like everything else, but a year of a few shares says little about the
next ten: the plan starts from what assets returned only when the fit covers
`MIN_RETURN_MONTHS`, and from `DEFAULT_RETURN` otherwise.

`project` walks the assumptions forward a month at a time from today's `Position`:

- income and spending rise with inflation;
- savings and assets grow at their yearly return;
- assets take what ends up in them, a share of what came in, or give back what they
  were giving back;
- what stays in the budget goes to savings and cash, and the goal takes its share of it
  until it holds its target. A goal that is reached stays there, unless the plan is told
  what comes after: its money is spent (it leaves net worth the month after it is
  reached), and the share it took goes to assets from then on;
- a month that leaves the budget short takes the difference from cash, then savings, then
  assets, and from cash again (into the red) once all three are empty.

Every amount is in the money of its month (`Step.prices` says how much prices rose by then,
to read it in today's money). Money set aside in a category marked "not spending" is not
projected: the plan saves what is earned and not spent.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.core.finance import Period, Rules, month_end, month_start, months_between
from ynab_unlinked.core.history import balances_at
from ynab_unlinked.store import Store

WITHDRAWAL_RATE = 0.04
"""The share of net worth that can be spent a year without it running out: work is optional
once that pays for a year of spending (net worth 25 times it)."""
RETURN_BAND = 0.02
"""How far the asset return of the range around the plan is from the plan's, either way."""
DEFAULT_INFLATION = 0.02
"""Nothing in a budget measures it; the user changes it."""
DEFAULT_RETURN = 0.05
"""What assets return a year when the budget's own figure is not used."""
MIN_RETURN_MONTHS = 36
"""The fewest months of a fit for the return it measured to be the plan's."""
MONTH_CAP = 0.5
"""A month that moves a bucket by more than this share of what it held is not a return: it
is money brought in as a balance set by hand. It is left out of the bucket's return."""

_RETURNING = (Bucket.ASSETS, Bucket.SAVINGS)


@dataclass(frozen=True)
class Position:
    """Net worth today by bucket, debts taken off the cash they are paid from. Milliunits."""

    cash: float = 0
    savings: float = 0
    assets: float = 0

    @property
    def total(self) -> float:
        return self.cash + self.savings + self.assets


@dataclass(frozen=True)
class Goal:
    """The category whose target the plan follows."""

    name: str
    balance: int
    """What it holds now."""
    target: int
    target_date: dt.date | None = None
    """The day YNAB's target is for, when it has one."""


@dataclass(frozen=True)
class Assumptions:
    """What a month looks like from here on. Amounts in milliunits a month, rates a year,
    shares between 0 and 1."""

    income: float = 0
    spending: float = 0
    to_assets: float = 0
    """The share of what comes in that ends up in assets."""
    from_assets: float = 0
    """What assets give back a month, at today's prices. One of the two is zero as measured:
    assets either took money over the months or gave it back."""
    to_savings: float = 0
    """The share of what stays in the budget that goes to savings; the rest stays in cash."""
    to_goal: float = 0
    """The share of what stays in the budget that the goal's category takes."""
    assets_return: float = 0
    savings_return: float = 0
    inflation: float = DEFAULT_INFLATION
    goal_spent: bool = False
    """The goal's money leaves net worth the month after it is reached: it was saved to be
    spent."""
    goal_to_assets: bool = False
    """Once the goal is reached, the share it took goes to assets."""

    @property
    def saving(self) -> float:
        return self.income - self.spending

    @property
    def savings_rate(self) -> float | None:
        return self.saving / self.income if self.income > 0 else None

    @property
    def into_assets(self) -> float:
        """What a month puts into assets."""
        return self.income * self.to_assets

    @property
    def stays(self) -> float:
        """What a month leaves in the budget: what is saved, less what is put into assets,
        plus what is taken out of them. Money in assets is not in the budget for the goal's
        category to hold, so the goal's share is of this. Negative when more goes to assets
        than is saved and comes back."""
        return self.saving - self.into_assets + self.from_assets


@dataclass(frozen=True)
class BucketMonth:
    """One month of a bucket, for its return."""

    start: float
    """What it held at the end of the month before."""
    own: float
    """Money put in, less money taken out."""
    gain: float
    """What its assets did on their own."""


@dataclass(frozen=True)
class Return:
    rate: float
    """A year, time weighted."""
    years: float
    """How long it was measured over."""


@dataclass(frozen=True)
class Seen:
    """What the lines say that a `Period` does not."""

    put_in: float = 0
    """Moved into assets from the other buckets over the months of the fit."""
    taken_out: float = 0
    """Moved out of assets to the other buckets over them. Positive."""
    assets: tuple[BucketMonth, ...] = ()
    """Each month of the fit, oldest first."""
    savings: tuple[BucketMonth, ...] = ()


@dataclass(frozen=True)
class Fit:
    """What the months `start`..`end` measured."""

    start: dt.date
    end: dt.date
    months: int
    assumptions: Assumptions
    assets_return: Return | None
    """None when no asset moved on its own."""
    savings_return: Return | None
    goal_pace: float | None
    """What the goal grew by a month; None without a goal or without its past balances."""
    put_in: float = 0
    """What went into assets a month."""
    taken_out: float = 0
    """What came out of assets a month."""

    @property
    def trusts_return(self) -> bool:
        """Whether the plan starts from what assets returned: they moved on their own, over
        enough months to say something."""
        return self.assets_return is not None and self.months >= MIN_RETURN_MONTHS


@dataclass(frozen=True)
class Step:
    """The plan `month` months from now, in the money of that month."""

    month: int
    cash: float
    savings: float
    assets: float
    prices: float
    """How many times today's prices: divide an amount by it for today's money."""
    goal: float | None = None
    """What the goal holds; None without a goal, and once its money was spent."""

    @property
    def total(self) -> float:
        return self.cash + self.savings + self.assets


@dataclass(frozen=True)
class Projection:
    steps: tuple[Step, ...]
    """`steps[0]` is today."""
    goal_month: int | None
    """Months until the goal holds its target; 0 when it already does, None when it does not
    get there (or there is no goal)."""
    free_month: int | None
    """Months until `WITHDRAWAL_RATE` of net worth pays for a year of spending."""

    @property
    def end(self) -> Step:
        return self.steps[-1]


def date_after(day: dt.date, months: int) -> dt.date:
    """The same day `months` months later, the month's last when it is shorter."""
    index = day.year * 12 + day.month - 1 + months
    year, month = index // 12, index % 12 + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def yearly_return(months: Sequence[BucketMonth]) -> Return | None:
    """The time weighted return of a bucket a year.

    Each month returns its gain over what it held (the start and half the money put in);
    the months are compounded and brought to a year. A month that held nothing, or moved by
    more than `MONTH_CAP`, is left out. None when nothing moved on its own.
    """
    growth, counted = 1.0, 0
    for month in months:
        held = month.start + month.own / 2
        if held <= 0 or abs(month.gain) > held * MONTH_CAP:
            continue
        growth *= 1 + month.gain / held
        counted += 1
    if not counted or growth == 1:
        return None
    return Return(growth ** (12 / counted) - 1, counted / 12)


def see(
    store: Store,
    budget_id: str,
    rules: Rules,
    buckets: Mapping[str, Bucket],
    start: dt.date,
    end: dt.date,
) -> Seen:
    """Read what `fit` needs off the lines of `start` (a month's first day) to `end`: money
    in and out of assets, and each month of assets and savings.

    Only transfers with another bucket count as put in or taken out: moving money between
    two assets is neither. Blocking: it reads the store.
    """
    months = months_between(start, end)
    position = {month: index for index, month in enumerate(months)}
    accounts = [account for account, bucket in buckets.items() if bucket in _RETURNING]
    ends = [start - dt.timedelta(days=1), *(month_end(month) for month in months)]
    balances = balances_at(store, budget_id, accounts, ends)
    own = {bucket: [0.0] * len(months) for bucket in _RETURNING}
    gain = {bucket: [0.0] * len(months) for bucket in _RETURNING}
    put_in = taken_out = 0.0
    for line in store.lines(budget_id, since=start, until=end):
        bucket = buckets.get(line.account_id)
        if bucket is None or bucket not in own or (kind := rules.kind(line)) is None:
            continue
        index = position[month_start(line.date)]
        (gain if kind == "assets" else own)[bucket][index] += line.amount
        if (
            bucket is Bucket.ASSETS
            and kind == "transfers"
            and buckets.get(line.transfer_account_id or "") is not Bucket.ASSETS
        ):
            if line.amount > 0:
                put_in += line.amount
            else:
                taken_out -= line.amount

    def of(bucket: Bucket) -> tuple[BucketMonth, ...]:
        mine = [account for account in accounts if buckets[account] is bucket]
        return tuple(
            BucketMonth(
                sum(balances[account][index] for account in mine),
                own[bucket][index],
                gain[bucket][index],
            )
            for index in range(len(months))
        )

    return Seen(put_in, taken_out, of(Bucket.ASSETS), of(Bucket.SAVINGS))


def goal_pace(balances: Mapping[dt.date, int], months: Sequence[dt.date]) -> float | None:
    """What a category grew by a month over `months` (first days, oldest first).

    `balances` is what it held at the end of each month. Measured from the end of the month
    before `months`, or from the first month it has a balance for; None when it has none
    for the last month, or for no other.
    """
    if not months or (last := balances.get(months[-1])) is None:
        return None
    before = date_after(months[0], -1)
    for span, anchor in zip(range(len(months), 0, -1), [before, *months[:-1]], strict=True):
        if anchor in balances:
            return (last - balances[anchor]) / span
    return None


def fit(
    period: Period,
    buckets: Mapping[str, Bucket],
    goal_balances: Mapping[dt.date, int] | None = None,
    seen: Seen | None = None,
) -> Fit:
    """Read the assumptions off `period`, whole months of the accounts in `buckets`.

    What ends up in assets is what was put into them less what was taken out: over what
    came in when they took money, as an amount when they gave it back. What stays in the budget
    goes to savings and cash as the money that stayed in each did (a bucket that was drawn
    from takes none; debt is paid from cash, so its money counts as cash). The goal's share
    is what it grew by over what stays in the budget.
    """
    seen = seen or Seen()
    months = max(len(period.months), 1)
    stayed = {Bucket.CASH: 0.0, Bucket.SAVINGS: 0.0}
    for move in period.accounts:
        bucket = buckets.get(move.account_id)
        home = Bucket.CASH if bucket is Bucket.DEBT else bucket
        if home is not None and home in stayed:
            flows = move.flows
            stayed[home] += flows.saved + flows.set_aside + flows.transfers
    in_savings, in_cash = max(stayed[Bucket.SAVINGS], 0), max(stayed[Bucket.CASH], 0)

    income = period.flows.income / months
    spending = -period.flows.spending / months
    put_in, taken_out = seen.put_in / months, seen.taken_out / months
    assets_return = yearly_return(seen.assets)
    savings_return = yearly_return(seen.savings)
    measured = Assumptions(
        income=income,
        spending=spending,
        to_assets=min(max((put_in - taken_out) / income, 0), 1) if income > 0 else 0,
        from_assets=max(taken_out - put_in, 0),
        to_savings=in_savings / (in_savings + in_cash) if in_savings + in_cash else 0,
        assets_return=assets_return.rate
        if assets_return is not None and len(period.months) >= MIN_RETURN_MONTHS
        else DEFAULT_RETURN,
        savings_return=0 if savings_return is None else savings_return.rate,
    )
    pace = goal_pace(goal_balances or {}, [month for month, _ in period.months])
    stays = measured.stays
    return Fit(
        start=period.start,
        end=period.end,
        months=len(period.months),
        assumptions=replace(
            measured, to_goal=min(max(pace / stays, 0), 1) if pace and stays > 0 else 0
        ),
        assets_return=assets_return,
        savings_return=savings_return,
        goal_pace=pace,
        put_in=put_in,
        taken_out=taken_out,
    )


def _monthly(yearly: float) -> float:
    """The growth factor of a month at a yearly rate."""
    return max(1 + yearly, 0) ** (1 / 12)


def project(
    position: Position, assumptions: Assumptions, months: int, goal: Goal | None = None
) -> Projection:
    """`months` months from `position`, a `Step` for each and one for today."""
    cash, savings, assets = position.cash, position.savings, position.assets
    held = None if goal is None else float(goal.balance)
    assets_growth = _monthly(assumptions.assets_return)
    savings_growth = _monthly(assumptions.savings_return)

    def free(total: float, spending: float) -> bool:
        return spending > 0 and total * WITHDRAWAL_RATE >= spending * 12

    steps = [Step(0, cash, savings, assets, 1.0, held)]
    goal_month = 0 if goal is not None and goal.balance >= goal.target else None
    free_month = 0 if free(position.total, assumptions.spending) else None
    for month in range(1, months + 1):
        prices = (1 + assumptions.inflation) ** (month / 12)
        spending = assumptions.spending * prices
        saved = assumptions.income * prices - spending
        if assumptions.goal_spent and goal is not None and held is not None and held >= goal.target:
            # Reached the month before (or already, today): it was put away to be spent. Out
            # of savings first, where such money is kept
            from_savings = min(max(savings, 0), held)
            from_cash = min(max(cash, 0), held - from_savings)
            from_assets = min(max(assets, 0), held - from_savings - from_cash)
            savings -= from_savings
            assets -= from_assets
            cash -= held - from_savings - from_assets
            held = None
        savings *= savings_growth
        assets *= assets_growth
        put_in = assumptions.income * prices * assumptions.to_assets
        # Nothing comes out of assets that are not there
        taken_out = min(assumptions.from_assets * prices, max(assets + put_in, 0))
        assets += put_in - taken_out
        stays = saved - put_in + taken_out
        # What a goal that was reached before this month would have taken
        freed = goal is not None and (held is None or held >= goal.target)
        if stays >= 0:
            if freed and assumptions.goal_to_assets:
                assets += stays * assumptions.to_goal
                stays -= stays * assumptions.to_goal
            savings += stays * assumptions.to_savings
            cash += stays * (1 - assumptions.to_savings)
            if held is not None and goal is not None and held < goal.target:
                held = min(held + stays * assumptions.to_goal, goal.target)
        else:
            short = -stays
            from_cash = min(max(cash, 0), short)
            from_savings = min(max(savings, 0), short - from_cash)
            from_assets = min(max(assets, 0), short - from_cash - from_savings)
            savings -= from_savings
            assets -= from_assets
            # What the three could not cover is owed: cash goes into the red
            cash -= short - from_savings - from_assets
        if goal is not None and goal_month is None and held is not None and held >= goal.target:
            goal_month = month
        step = Step(month, cash, savings, assets, prices, held)
        steps.append(step)
        if free_month is None and free(step.total, spending):
            free_month = month
    return Projection(tuple(steps), goal_month, free_month)
