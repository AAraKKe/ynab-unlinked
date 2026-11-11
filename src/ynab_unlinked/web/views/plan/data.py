"""What the Plan view shows, worked out without NiceGUI.

The months the plan is measured over, what they measured (`core.plan.fit`), the knobs the
user turns and the plan they make, and the words of the tiles and of each knob. Everything is
plain Python over the store and the config, tested directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace

from ynab_unlinked.buckets import Bucket
from ynab_unlinked.config import LatestConfig, TrackedAccount
from ynab_unlinked.core.balances import AccountBalance, net_worth
from ynab_unlinked.core.finance import month_end, month_start, months_between
from ynab_unlinked.core.finance import period as read_period
from ynab_unlinked.core.history import balances_at
from ynab_unlinked.core.plan import (
    DEFAULT_RETURN,
    MIN_RETURN_MONTHS,
    RETURN_BAND,
    Assumptions,
    Fit,
    Goal,
    Position,
    Projection,
    date_after,
    fit,
    project,
    see,
)
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import Store, StoredAccount
from ynab_unlinked.text import plural
from ynab_unlinked.web import accounts as tracking
from ynab_unlinked.web import finances
from ynab_unlinked.web.categories import goal_category

WINDOWS: dict[str, int | None] = {"6M": 6, "1Y": 12, "3Y": 36, "All": None}
"""How many complete months the plan is measured over; All goes back to the first one."""
DEFAULT_WINDOW = "1Y"
MONEY = {"today": "Today's money", "future": "With inflation"}
GROUPINGS = {"total": "Total", "type": "By type"}
GOAL_MARGIN = 12
"""Months the goal's chart shows after the goal is reached."""
CHECK_MONTHS = 12
"""How far back the plan is checked against what happened: the plan of that day, for today."""
CHECK_MIN_MONTHS = 6
"""The fewest months that plan must have been measured over: fewer say too little to judge."""

MONEY_TITLE = "Today's money or with inflation"
MONEY_NOTE = (
    "With inflation is the figure your accounts will show on that day. Today's money takes "
    "the rise of prices out of it, so it says what that figure buys compared with now.",
    "Income and spending rise with prices either way. The goal is always shown as its "
    "category will read, since its target is a fixed amount.",
)
HOW_TITLE = "How the plan is worked out"
HOW_NOTE = (
    "Every month ahead earns and spends what a month did over the months measured. Of what "
    "is saved, what ended up in assets goes there: what you put into them less what you took "
    "out. The rest stays in the budget: it goes to savings and cash, and the goal takes its "
    "share of it.",
    "Assets grow at the return they had over the months measured when those cover three "
    "years, at 5% a year otherwise. The shaded range is the same plan with assets returning "
    "two points more or less a year.",
    "Move anything to see another future; the dashed line stays on what was measured.",
    "Under the chart, the plan of a year ago is checked against what happened since.",
)


@dataclass(frozen=True)
class Knob:
    """One figure of the plan the user can change, and the range its slider covers."""

    key: str
    label: str
    low: float
    high: float
    step: float


KNOBS: tuple[Knob, ...] = (
    Knob("income", "Income", -50, 50, 1),
    Knob("spending", "Spending", -50, 50, 1),
    Knob("net_assets", "Ends up in assets", -50, 100, 0.1),
    Knob("to_goal", "Goes to the goal", 0, 100, 1),
    Knob("assets_return", "Assets return", -5, 15, 0.1),
    Knob("savings_return", "Savings interest", 0, 8, 0.1),
    Knob("inflation", "Inflation", 0, 8, 0.1),
    Knob("years", "Years ahead", 1, 40, 1),
)
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Each month", ("income", "spending")),
    ("Assets", ("net_assets",)),
    ("The goal", ("to_goal",)),
    ("How far", ("years",)),
    ("Returns", ("assets_return", "savings_return", "inflation")),
)
RETURNS = "Returns"
"""The section that only shows when opened: figures set once, if ever."""
SWITCHES = {
    "goal_spent": "Its money is spent",
    "goal_to_assets": "Its share goes to assets",
}
"""What the plan does once the goal is reached, each off until the user says so: nothing in
a budget tells what a goal is for."""
RETURN_TITLE = "Where this return comes from"


@dataclass(frozen=True)
class Knobs:
    """Where every slider stands. Percentages, as the sliders show them; income and spending
    are changes from what was measured."""

    income: float = 0
    spending: float = 0
    net_assets: float = 0
    """What ends up in assets, as a share of what comes in; negative when they give back."""
    to_goal: float = 0
    assets_return: float = 0
    savings_return: float = 0
    inflation: float = 2
    years: float = 10
    goal_spent: bool = False
    goal_to_assets: bool = False

    def changed(self, other: Knobs) -> bool:
        """Whether the plan is another one than `other`'s: inflation and how far it looks
        are how a plan is read, not what it is."""
        return replace(self, inflation=other.inflation, years=other.years) != other


def _on_slider(knob: Knob, value: float) -> float:
    """`value` on the knob's slider: inside its range, on one of its steps."""
    steps = round((min(max(value, knob.low), knob.high) - knob.low) / knob.step)
    return round(knob.low + steps * knob.step, 4)


def mark(knob: Knob, value: float, high: float | None = None) -> float:
    """Where `value` sits along the knob's slider, from 0 to 100. `high`: where the slider
    ends when that is not the knob's own end."""
    high = knob.high if high is None else high
    if high <= knob.low:
        return 0
    return (min(max(value, knob.low), high) - knob.low) / (high - knob.low) * 100


def ceiling(found: Fit, knobs: Knobs) -> float:
    """The most that can end up in assets, as a share of what comes in: all that is saved,
    with income and spending where their sliders stand. The assets' slider ends there."""
    base = found.assumptions
    income = base.income * (1 + knobs.income / 100)
    saving = income - base.spending * (1 + knobs.spending / 100)
    return max(saving, 0) / income * 100 if income > 0 else 0


def _under_ceiling(found: Fit, knobs: Knobs) -> Knobs:
    return replace(knobs, net_assets=min(knobs.net_assets, ceiling(found, knobs)))


def measured(found: Fit) -> Knobs:
    """The sliders at what the months measured, each on its own scale.

    Inside the slider's range but not on one of its steps: a page that says "measured 300"
    starts at 300, not at the nearest step. A slider snaps to its steps once it is moved.
    """
    base = found.assumptions
    start = Knobs()
    raw: dict[str, float] = {
        "income": start.income,
        "spending": start.spending,
        "net_assets": (base.to_assets - (base.from_assets / base.income if base.income else 0))
        * 100,
        "to_goal": base.to_goal * 100,
        "assets_return": base.assets_return * 100,
        "savings_return": base.savings_return * 100,
        "inflation": base.inflation * 100,
        "years": start.years,
    }
    knobs = replace(
        start, **{knob.key: min(max(raw[knob.key], knob.low), knob.high) for knob in KNOBS}
    )
    # More went into assets than was saved when savings were moved there: not every month
    return _under_ceiling(found, knobs)


def with_changes(start: Knobs, changes: Mapping[str, object]) -> Knobs:
    """`start` with the sliders the user moved and the switches they flipped (`changes`, by
    key); anything else in it, a slider that is not a number or a switch that is not on or
    off, is ignored."""
    known = {knob.key: knob for knob in KNOBS}
    values: dict[str, float | bool] = {
        key: _on_slider(known[key], float(value))
        for key, value in changes.items()
        if key in known and isinstance(value, int | float) and not isinstance(value, bool)
    }
    values |= {
        key: value for key, value in changes.items() if key in SWITCHES and isinstance(value, bool)
    }
    return replace(start, **values)


def moved(knobs: Knobs, start: Knobs) -> dict[str, float | bool]:
    """The sliders and switches that stand somewhere else than `start`'s."""
    return {
        f.name: getattr(knobs, f.name)
        for f in fields(knobs)
        if getattr(knobs, f.name) != getattr(start, f.name)
    }


def assumptions(found: Fit, knobs: Knobs) -> Assumptions:
    """What a month looks like with the sliders at `knobs`.

    What stays in the budget is split between savings and cash as it was measured. The
    goal's share is of what stays, so any share of it fits whatever the assets take.
    """
    base = found.assumptions
    income = base.income * (1 + knobs.income / 100)
    return Assumptions(
        income=income,
        spending=base.spending * (1 + knobs.spending / 100),
        to_assets=max(knobs.net_assets, 0) / 100,
        from_assets=max(-knobs.net_assets, 0) / 100 * income,
        to_savings=base.to_savings,
        to_goal=knobs.to_goal / 100,
        assets_return=knobs.assets_return / 100,
        savings_return=knobs.savings_return / 100,
        inflation=knobs.inflation / 100,
        goal_spent=knobs.goal_spent,
        goal_to_assets=knobs.goal_to_assets,
    )


# ---- the page --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Past:
    """Net worth at the end of a month measured, debts taken off the cash they are paid from."""

    day: dt.date
    cash: int
    savings: int
    assets: int

    @property
    def total(self) -> int:
        return self.cash + self.savings + self.assets


@dataclass(frozen=True)
class Check:
    """The plan as it would have been made `CHECK_MONTHS` ago, against what happened."""

    since: dt.date
    """The last day it was measured up to."""
    until: dt.date
    """The day it is checked on: the end of the last complete month."""
    said: float
    """Net worth it said for `until`."""
    was: float

    @property
    def off(self) -> float | None:
        """How far what happened is from what it said, as a share of what it said."""
        return (self.was - self.said) / abs(self.said) if self.said else None


@dataclass(frozen=True)
class PlanPage:
    today: dt.date
    position: Position
    fit: Fit | None
    """None before the budget has a complete month."""
    goal: Goal | None
    past: tuple[Past, ...] = ()
    """The end of each month measured, oldest first."""
    goal_past: tuple[tuple[dt.date, int], ...] = ()
    """What the goal held at the end of each month measured the copy has."""
    check: Check | None = None
    """None when the budget does not go back far enough to check."""


def window_months(key: str, today: dt.date, earliest: dt.date) -> tuple[dt.date, dt.date] | None:
    """The complete months a window covers: the first day of the first, the last of the last.

    Never before the month of the first transaction, never the month still running. None when
    no month is complete yet.
    """
    end = month_start(today) - dt.timedelta(days=1)
    first = month_start(earliest)
    count = WINDOWS.get(key, WINDOWS[DEFAULT_WINDOW])
    start = first if count is None else max(month_start(date_after(today, -count)), first)
    return (start, end) if start <= end else None


def _worth(
    config: LatestConfig, accounts: Sequence[TrackedAccount], balances: Mapping[str, int]
) -> tuple[int, int, int]:
    """Cash, savings and assets of `accounts` at `balances`; debt nobody pays comes off cash."""
    worth = net_worth(
        [AccountBalance(a.id, a.name, a.bucket, balances.get(a.id, 0)) for a in accounts],
        tracking.effective_nettings(config),
    )
    by_bucket = worth.by_bucket()
    return (
        by_bucket[Bucket.CASH] + worth.unnetted,
        by_bucket[Bucket.SAVINGS],
        by_bucket[Bucket.ASSETS],
    )


@dataclass(frozen=True)
class _Budget:
    """What every reading of the store for the plan needs."""

    store: Store
    config: LatestConfig
    stored: Sequence[StoredAccount]
    history: Sequence[TrackedAccount]
    earliest: dt.date

    def measure(
        self, start: dt.date, end: dt.date, held: Mapping[dt.date, int] | None = None
    ) -> Fit:
        """What the months `start`..`end` measured."""
        budget_id = self.config.budget.id
        rules = finances.rules(self.config, self.stored)
        buckets = {account.id: account.bucket for account in self.history}
        period = read_period(self.store, budget_id, rules, start, end)
        seen = see(self.store, budget_id, rules, buckets, start, end)
        return fit(period, buckets, held, seen)

    def worth(self, days: Sequence[dt.date]) -> list[tuple[int, int, int]]:
        """Cash, savings and assets at the end of each of `days`, which must be sorted."""
        balances = balances_at(
            self.store, self.config.budget.id, [a.id for a in self.history], days
        )
        return [
            _worth(self.config, self.history, {a.id: balances[a.id][index] for a in self.history})
            for index in range(len(days))
        ]

    def check(self, window: str, today: dt.date) -> Check | None:
        """The plan of `CHECK_MONTHS` ago with the same months measured, for the end of the
        last complete month. Nothing later than that day is read to make it."""
        months = window_months(window, date_after(today, -CHECK_MONTHS), self.earliest)
        if months is None:
            return None
        start, since = months
        until = month_start(today) - dt.timedelta(days=1)
        found = self.measure(start, since)
        if found.months < CHECK_MIN_MONTHS:
            return None
        then, now = self.worth([since, until])
        said = project(Position(*then), found.assumptions, CHECK_MONTHS)
        return Check(since, until, said.end.total, sum(now))


def load(store: Store, config: LatestConfig, window: str, today: dt.date) -> PlanPage:
    """Read what the plan starts from. Blocking: run it through `run.io_bound`."""
    budget_id = config.budget.id
    stored = store.accounts(budget_id)
    counted = tracking.effective_accounts(config, stored)
    cash, savings, assets = _worth(config, counted, {a.id: a.balance for a in stored})
    position = Position(cash, savings, assets)

    category = goal_category(store.categories(budget_id), config.finances.goal_category_id)
    goal = None
    held: dict[dt.date, int] = {}
    if category is not None:
        goal = Goal(
            category.name, category.balance, category.goal_target or 0, category.goal_target_date
        )
        held = store.category_balances(budget_id, category.id)

    earliest = finances.earliest(store, budget_id, today)
    months = window_months(window, today, earliest)
    if months is None:
        return PlanPage(today, position, None, goal)
    start, end = months
    budget = _Budget(store, config, stored, tracking.history_accounts(config, stored), earliest)
    ends = [month_end(month) for month in months_between(start, end)]
    return PlanPage(
        today=today,
        position=position,
        fit=budget.measure(start, end, held),
        goal=goal,
        past=tuple(Past(day, *worth) for day, worth in zip(ends, budget.worth(ends), strict=True)),
        goal_past=tuple(
            (month_end(month), held[month]) for month in months_between(start, end) if month in held
        ),
        check=budget.check(window, today),
    )


# ---- the plan --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """The plan of the sliders, the one of what was measured, and the range around the first."""

    knobs: Knobs
    start: Knobs
    """The sliders as measured."""
    yours: Assumptions
    usual: Assumptions
    plan: Projection
    measured: Projection
    """The same years and inflation with everything else as measured."""
    low: Projection
    high: Projection

    @property
    def changed(self) -> bool:
        return self.knobs.changed(self.start)


def build(page: PlanPage, found: Fit, changes: Mapping[str, object]) -> Plan:
    """The plan with the sliders the user moved (`changes`); the rest as measured."""
    start = measured(found)
    knobs = _under_ceiling(found, with_changes(start, changes))
    yours = assumptions(found, knobs)
    usual = assumptions(found, replace(start, inflation=knobs.inflation, years=knobs.years))
    months = round(knobs.years) * 12

    def run(what: Assumptions) -> Projection:
        return project(page.position, what, months, page.goal)

    return Plan(
        knobs=knobs,
        start=start,
        yours=yours,
        usual=usual,
        plan=run(yours),
        measured=run(usual),
        low=run(replace(yours, assets_return=yours.assets_return - RETURN_BAND)),
        high=run(replace(yours, assets_return=yours.assets_return + RETURN_BAND)),
    )


def worth(projection: Projection, real: bool) -> list[float]:
    """Net worth at each step, in today's money when `real`."""
    return [step.total / step.prices if real else step.total for step in projection.steps]


@dataclass(frozen=True)
class Timeline:
    """The days the charts draw: the end of each month measured, today, then the same day of
    every month ahead."""

    days: tuple[dt.date, ...]
    lead: int
    """How many of them are before today."""

    def behind(self, values: Sequence[float | None]) -> list[float | None]:
        """A series that ends today: `values` for the days before and for today."""
        return [*values, *[None] * (len(self.days) - len(values))]

    def ahead(self, values: Sequence[float | None]) -> list[float | None]:
        """A series that starts today: `values` for today and every day after."""
        return [*[None] * self.lead, *values][: len(self.days)]

    def until(self, months: int) -> Timeline:
        """The same days, no further than `months` months ahead."""
        return Timeline(self.days[: self.lead + months + 1], self.lead)


def timeline(page: PlanPage, projection: Projection) -> Timeline:
    ahead = [date_after(page.today, step.month) for step in projection.steps]
    return Timeline((*(past.day for past in page.past), *ahead), len(page.past))


def by_type(page: PlanPage, projection: Projection, real: bool) -> dict[Bucket, list[float | None]]:
    """Assets, savings and cash on every day of the timeline, what was and what the plan says."""
    names = {Bucket.ASSETS: "assets", Bucket.SAVINGS: "savings", Bucket.CASH: "cash"}
    return {
        bucket: [
            *(getattr(past, name) for past in page.past),
            *(getattr(step, name) / (step.prices if real else 1) for step in projection.steps),
        ]
        for bucket, name in names.items()
    }


def goal_so_far(page: PlanPage) -> list[float | None]:
    """What the goal held on each day before today (None where the copy has no figure), and
    what it holds today."""
    held = dict(page.goal_past)
    today = None if page.goal is None else page.goal.balance
    return [*(held.get(past.day) for past in page.past), today]


def goal_ahead(projection: Projection) -> list[float | None]:
    return [step.goal for step in projection.steps]


def goal_months(plan: Plan) -> int:
    """How many months ahead the goal's chart looks: `GOAL_MARGIN` past the month the goal is
    reached (the later one, when the plan is drawn against what was measured), so a goal two
    years away is not a flat line across ten. All of the plan when it does not get there."""
    months = len(plan.plan.steps) - 1
    reached = [plan.plan.goal_month, *([plan.measured.goal_month] if plan.changed else [])]
    known = [month for month in reached if month is not None]
    if len(known) < len(reached):
        return months
    return min(months, max(known) + GOAL_MARGIN)


# ---- words -----------------------------------------------------------------------------------


def when(page: PlanPage, months: int | None) -> str | None:
    """`now`, `Mar 2029`, or None when the plan does not get there."""
    if months is None:
        return None
    return "now" if months == 0 else date_after(page.today, months).strftime("%b %Y")


def signed(formatter: Formatter, amount: float) -> str:
    text = formatter.format_amount_milli(round(amount))
    return f"+{text}" if amount > 0 else text


def percent(value: float, digits: int = 0) -> str:
    return f"{value:.{digits}f}%".replace("-", "−")


def years_text(years: float) -> str:
    return plural(round(years), "year")


def knob_value(key: str, plan: Plan, formatter: Formatter) -> str:
    """What stands next to a slider: its value, and the amount it makes where it is a share."""
    knobs, yours = plan.knobs, plan.yours
    money = formatter.format_amount_milli
    value = getattr(knobs, key)
    match key:
        case "income" | "spending":
            amount = money(round(yours.income if key == "income" else yours.spending))
            return f"{amount} · {value:+.0f}%".replace("-", "−") if value else amount
        case "net_assets":
            net = yours.into_assets - yours.from_assets
            if net < 0 or yours.saving <= 0:
                return money(round(net))
            return f"{money(round(net))} · {percent(net / yours.saving * 100)}"
        case "to_goal":
            return f"{percent(value)} · {money(round(max(yours.stays, 0) * yours.to_goal))}"
        case "years":
            return years_text(value)
        case _:
            return percent(value, 1)


def _span(years: float) -> str:
    """`11 months`, `1 year`, `4.9 years`."""
    months = round(years * 12)
    if months < 12:
        return plural(months, "month")
    return "1 year" if months == 12 else f"{years:.1f} years"


def return_note(found: Fit) -> tuple[str, ...]:
    """Behind the "i" of the assets' return: where the figure comes from."""
    default = percent(DEFAULT_RETURN * 100)
    span = _span(found.months / 12)
    measured = found.assets_return
    if measured is None:
        return (
            f"{default} a year is a default: none of your assets moved on its own over the "
            f"{span} measured. A balance you update by hand counts as a move.",
        )
    rate = percent(measured.rate * 100, 1)
    if not found.trusts_return:
        least = plural(MIN_RETURN_MONTHS // 12, "year")
        return (
            f"{default} a year is a default. A return needs at least {least} to say "
            f"something, and the months measured cover {span}.",
            f"Over them your assets returned {rate} a year. Pick 3Y or All under Measured "
            "over to start from your own return.",
        )
    knob = next(knob for knob in KNOBS if knob.key == "assets_return")
    lines = [
        f"Your assets returned {rate} a year over the {span} measured: what they gained on "
        "their own each month, over what they held."
    ]
    if not knob.low <= measured.rate * 100 <= knob.high:
        edge = knob.high if measured.rate * 100 > knob.high else knob.low
        lines.append(f"The slider ends at {percent(edge)}, so the plan starts there.")
    return tuple(lines)


def returns_summary(plan: Plan) -> str:
    """What the folded section holds, so it need not be opened to know."""
    knobs = plan.knobs
    return f"assets {percent(knobs.assets_return, 1)} · inflation {percent(knobs.inflation, 1)}"


def knob_hint(key: str, page: PlanPage, found: Fit, plan: Plan, formatter: Formatter) -> str:
    """The line under a slider: what the months measured, so a change is read against it."""
    money = formatter.format_amount_milli
    base = found.assumptions
    match key:
        case "income":
            return f"measured {money(round(base.income))} a month"
        case "spending":
            return f"measured {money(round(base.spending))} a month"
        case "net_assets":
            measured = f"measured {money(round(found.put_in))}"
            if found.taken_out:
                measured += f" in, {money(round(found.taken_out))} out"
            if plan.yours.from_assets:
                return f"assets give back · {measured} a month"
            return f"of what you save · {measured} a month"
        case "to_goal":
            left = f"of the {money(round(max(plan.yours.stays, 0)))} left in the budget"
            if found.goal_pace is None:
                return f"{left} · not measured yet: its past months come with the next sync"
            return f"{left} · measured {money(round(found.goal_pace))} a month"
        case "assets_return":
            if found.trusts_return:
                return f"measured over the last {_span(found.months / 12)}"
            return "a default: too little measured"
        case "savings_return":
            if found.savings_return is None:
                return "not followed: its interest counts as income"
            return f"measured over the last {_span(found.months / 12)}"
        case "inflation":
            return "raises income and spending alike"
        case _:
            return f"until {date_after(page.today, round(plan.knobs.years) * 12):%b %Y}"


def stays_note(plan: Plan, formatter: Formatter) -> str:
    """Under the assets' slider: what is saved, less what ends up in assets, is what the
    budget keeps a month, the amount the goal's share is of."""
    yours = plan.yours
    money = formatter.format_amount_milli
    if yours.from_assets:
        assets = f"+ {money(round(yours.from_assets))} out of assets"
    else:
        assets = f"− {money(round(yours.into_assets))} into assets"
    left = (
        f"Left in the budget: {money(round(yours.saving))} saved {assets} "
        f"= {money(round(yours.stays))} a month"
    )
    return f"{left}, made up from cash" if round(yours.stays) < 0 else left


def after_summary(plan: Plan) -> str:
    """What the folded "Once reached" holds, so it need not be opened to know."""
    knobs = plan.knobs
    parts = [
        *(["spent"] if knobs.goal_spent else []),
        *(["share to assets"] if knobs.goal_to_assets else []),
    ]
    return " · ".join(parts) or "nothing changes"


def after_note(page: PlanPage, plan: Plan, formatter: Formatter) -> str:
    """Under the two switches: what they do to this plan, in its own figures."""
    goal, knobs, yours = page.goal, plan.knobs, plan.yours
    if goal is None:
        return ""
    reached = when(page, plan.plan.goal_month)
    if reached is None:
        return f"Not reached in {years_text(knobs.years)}: nothing happens yet."
    money = formatter.format_amount_milli
    moment = "Now that it is reached" if reached == "now" else f"Once it is reached in {reached}"
    share = money(round(max(yours.stays, 0) * yours.to_goal))
    spent = f"{money(max(goal.target, goal.balance))} leaves net worth"
    invested = f"{share} a month goes to assets"
    if knobs.goal_spent and knobs.goal_to_assets:
        return f"{moment}: {spent}, and {invested}."
    if knobs.goal_spent:
        return f"{moment}: {spent}. Its share stays in savings and cash."
    if knobs.goal_to_assets:
        return f"{moment}: {invested}. Its money stays where it is."
    return "Its money stays where it is, and its share stays in savings and cash."


def check_note(check: Check, formatter: Formatter) -> str:
    """How the plan of a year ago did: what it said for the last complete month, and what
    that month was."""
    money = formatter.format_amount_milli
    off = check.off
    if off is None or abs(off) < 0.005:
        verdict = "about that"
    else:
        verdict = f"{percent(abs(off) * 100, 1)} {'more' if off > 0 else 'less'}"
    return (
        f"Checked against your past: measured up to {check.since:%b %Y}, this plan said "
        f"{money(round(check.said))} for {check.until:%b %Y}. It was {money(round(check.was))}, "
        f"{verdict}."
    )


def measured_note(found: Fit) -> str:
    """`12 complete months, Nov 2025 – Oct 2026`."""
    span = finances.period_title(found.start, found.end)
    return f"{found.months} complete {'month' if found.months == 1 else 'months'}, {span}"


def end_hint(page: PlanPage, plan: Plan, real: bool, formatter: Formatter) -> str:
    """Under the net worth at the end: how far from the measured plan, else today's figure."""
    if plan.changed:
        difference = worth(plan.plan, real)[-1] - worth(plan.measured, real)[-1]
        if round(difference):
            return f"{signed(formatter, difference)} against what was measured"
    return f"{formatter.format_amount_milli(round(page.position.total))} today"


def saving_hint(plan: Plan) -> str:
    rate = plan.yours.savings_rate
    if rate is None:
        return "nothing comes in"
    if plan.yours.saving < 0:
        return "more goes out than comes in"
    return f"{percent(rate * 100)} of what comes in"


def goal_value(page: PlanPage, plan: Plan) -> str:
    """When the goal holds its target: `Mar 2029`, `reached`, or how far the plan looks."""
    if page.goal is None:
        return "—"
    reached = when(page, plan.plan.goal_month)
    if reached is None:
        return f"not in {years_text(plan.knobs.years)}"
    return "reached" if reached == "now" else reached


def goal_hint(page: PlanPage, plan: Plan, formatter: Formatter) -> str:
    """The goal and its target; against YNAB's date when the target has one."""
    goal = page.goal
    if goal is None:
        return "add a balance target to a category in YNAB"
    text = f"{goal.name} · {formatter.format_amount_milli(goal.target)}"
    months = plan.plan.goal_month
    if goal.target_date is None or not months:
        return text
    wanted = (goal.target_date.year - page.today.year) * 12 + (
        goal.target_date.month - page.today.month
    )
    if months == wanted:
        return f"{text} · on its date"
    late = months - wanted
    return f"{text} · {plural(abs(late), 'month')} {'late' if late > 0 else 'early'}"


def free_value(page: PlanPage, plan: Plan) -> str:
    reached = when(page, plan.plan.free_month)
    return f"not in {years_text(plan.knobs.years)}" if reached is None else reached
