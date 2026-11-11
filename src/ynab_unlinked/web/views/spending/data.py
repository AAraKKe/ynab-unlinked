"""What the Spending view shows, worked out without NiceGUI: the range, each category's row
and the words of its volatility."""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend, rhythm
from ynab_unlinked.store import Store
from ynab_unlinked.web import finances

DEFAULT_RANGE = "1Y"
SHOWN = 20
"""Categories listed before "Show all"."""
SPARK_WIDTH = 72
SPARK_HEIGHT = 22

PillKind = Literal["default", "ok", "warn", "acc"]
"""The kinds of `components.pill`."""


@dataclass(frozen=True)
class Word:
    text: str
    kind: PillKind
    """The pill kind: `ok` steady, `default` variable, `warn` spiky, `acc` lumpy."""
    hint: str


WORDS = {
    "steady": Word(
        "● steady", "ok", "About the same every month: rent, a gym, a phone plan. Moves under 25%."
    ),
    "variable": Word(
        "◐ variable",
        "default",
        "Moves around its average, like groceries or eating out. Moves 25% to 75%.",
    ),
    "spiky": Word(
        "▲ spiky",
        "warn",
        "It keeps coming, and some months are far bigger than the rest: gifts, clothes. "
        "Moves over 75%: plan for the big ones.",
    ),
    "lumpy": Word(
        "◆ lumpy",
        "acc",
        "Nothing most months, then an expense: a yearly subscription, insurance, a repair, "
        "a holiday. Moves over 75%, with an expense in fewer than 2 months of 5.",
    ),
}


def load(store: Store, config: LatestConfig, range_key: str, today: dt.date) -> CashFlow:
    """Read the range. Blocking: run it through `run.io_bound`."""
    first = finances.earliest(store, config.budget.id, today)
    start, end = finances.months_range(range_key, today, first)
    return finances.load_cash_flow(store, config, start, end)


def word(trend: CategoryTrend) -> Word | None:
    label = trend.volatility.label
    return None if label is None else WORDS[label]


def spark(values: Sequence[int]) -> str:
    """The points of a sparkline of `values`, `SPARK_WIDTH` by `SPARK_HEIGHT`."""
    if not values:
        return ""
    top = max(max(values), 1)
    step = SPARK_WIDTH / max(len(values) - 1, 1)
    return " ".join(
        f"{index * step:.1f},{SPARK_HEIGHT - 2 - value / top * (SPARK_HEIGHT - 4):.1f}"
        for index, value in enumerate(values)
    )


def share(trend: CategoryTrend, flow: CashFlow) -> float:
    whole = sum(t.mean for t in flow.categories)
    return trend.mean / whole if whole else 0


ORDER = ("steady", "variable", "spiky", "lumpy")
"""The words in the order the legend, the filters and the group mix list them."""
UNRATED = "unrated"
"""The mix's part of categories without enough months for a word."""
BINS = 6


def matches(trend: CategoryTrend, group: str | None, label: str | None) -> bool:
    """Whether a category passes the group and the "how it moves" filters (None: any)."""
    return (group is None or trend.group == group) and (
        label is None or trend.volatility.label == label
    )


def filtered(flow: CashFlow, group: str | None, label: str | None) -> list[CategoryTrend]:
    return [trend for trend in flow.categories if matches(trend, group, label)]


@dataclass(frozen=True)
class MixPart:
    label: str
    """A word of `ORDER`, or `UNRATED`."""
    share: float
    """Of the group's spending a month."""


def group_mix(flow: CashFlow, group: str) -> list[MixPart]:
    """How a group's spending splits by how its categories move, in `ORDER`, unrated last."""
    totals: dict[str, float] = {}
    for trend in flow.categories:
        if trend.group == group:
            key = trend.volatility.label or UNRATED
            totals[key] = totals.get(key, 0) + trend.mean
    whole = sum(totals.values())
    return [
        MixPart(key, totals[key] / whole) for key in (*ORDER, UNRATED) if whole and totals.get(key)
    ]


def plotted(trends: Sequence[CategoryTrend]) -> list[CategoryTrend]:
    """The categories the steady or swingy chart draws, in its order: a click gives an index."""
    return [t for t in trends if t.volatility.cv is not None and t.mean >= 1000]


@dataclass(frozen=True)
class Bin:
    low: int
    high: int
    months: int


def histogram(values: Sequence[int], bins: int = BINS) -> list[Bin]:
    """How many months fell in each of `bins` equal slices from the lowest month to the highest."""
    if not values:
        return []
    low, high = min(values), max(values)
    if low == high:
        return [Bin(low, high, len(values))]
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        counts[min(int((value - low) / width), bins - 1)] += 1
    return [
        Bin(round(low + i * width), round(low + (i + 1) * width), count)
        for i, count in enumerate(counts)
    ]


@dataclass(frozen=True)
class Life:
    """A category's months from its first spending to its last in the range: what its detail
    shows and its word is worked out on."""

    months: tuple[dt.date, ...]
    spent: tuple[int, ...]


def life(trend: CategoryTrend, flow: CashFlow) -> Life:
    months = [month.month for month in flow.measured]
    active = [index for index, value in enumerate(trend.spent) if value > 0]
    if not active:
        return Life(tuple(months), trend.spent)
    first, last = active[0], active[-1] + 1
    return Life(tuple(months[first:last]), trend.spent[first:last])


def charges(trend: CategoryTrend, flow: CashFlow) -> Life:
    """A category's history from its first spending to now: the months it spent in and the
    quiet ones between and after them, whatever range the page shows."""
    active = [index for index, value in enumerate(trend.past) if value > 0]
    if not active:
        return life(trend, flow)
    return Life(tuple(flow.history[active[0] :]), trend.past[active[0] :])


def every_text(every: float) -> str:
    """How often a charge comes, in words: `once a year`, `every 3 months`."""
    months = max(round(every), 1)
    return {
        1: "every month",
        6: "twice a year",
        12: "once a year",
        24: "every two years",
    }.get(months, f"every {months} months")


@dataclass(frozen=True)
class Stats:
    mean: float
    median: float
    lowest: int
    highest: int
    spread: float
    """Standard deviation."""


def stats(spent: Sequence[int]) -> Stats:
    """The numbers behind a category's word, over the months given (its life)."""
    return Stats(
        mean=statistics.fmean(spent) if spent else 0,
        median=statistics.median(spent) if spent else 0,
        lowest=min(spent, default=0),
        highest=max(spent, default=0),
        spread=statistics.pstdev(spent) if spent else 0,
    )


# ---- what a category's detail says, by what the category is -----------------------------------


@dataclass(frozen=True)
class Story:
    """A category's detail in words and numbers. What "how much" means depends on what the
    category is: a month for one spent every month, a charge for a lumpy one whose charges
    are about the same, the biggest month for any other lumpy one and for a spiky one, the
    one purchase for one bought once."""

    figure: str
    """The headline: `288.94€ a month`, `170.99€ a charge`, `up to 6,753.00€ a month`."""
    guide: tuple[str, str, str] | None
    """How it comes, what to set aside (shown strong), and what for. None without enough
    months to say."""
    section: str
    life: Life
    """The months the chart draws: the range's for a category spent every month, its history
    since the first charge for one spent every so often."""
    line: str
    """The name of the chart's dashed line, drawn at `line_value`."""
    line_value: float
    rows: tuple[tuple[str, str], ...]
    histogram: bool


def _month(month: dt.date) -> str:
    return f"{month:%b %Y}"


def _last_spent(shown: Life) -> str:
    paid = [month for month, value in zip(shown.months, shown.spent, strict=True) if value > 0]
    return _month(paid[-1]) if paid else "—"


def story(trend: CategoryTrend, flow: CashFlow, money: Callable[[int], str]) -> Story:
    """Tell `trend` the way its word asks for. `money` formats milliunits."""
    label = trend.volatility.label
    beat = rhythm(trend.past)
    since = charges(trend, flow)
    ranged = life(trend, flow)
    numbers = stats(ranged.spent)
    every_month = (
        ("Average", money(round(numbers.mean))),
        ("Median", money(round(numbers.median))),
        ("Lowest month", money(numbers.lowest)),
        ("Highest month", money(numbers.highest)),
        ("Spread", money(round(numbers.spread))),
    )
    month_figure = f"{money(round(numbers.mean))} a month"

    if label == "lumpy" and beat.alike and beat.every and beat.set_aside:
        aside = money(round(beat.set_aside))
        return Story(
            figure=f"{money(round(beat.charge))} a charge",
            guide=(
                f"About {every_text(beat.every)}.",
                f"Set aside {aside} a month",
                "to have it ready.",
            ),
            section="Each charge",
            life=since,
            line="Set aside a month",
            line_value=beat.set_aside,
            rows=(
                ("A charge", money(round(beat.charge))),
                ("Charges", str(beat.charges)),
                ("Comes", every_text(beat.every)),
                ("Set aside", aside),
                ("Last one", _last_spent(since)),
            ),
            histogram=False,
        )
    if label in ("lumpy", "spiky") and since.spent:
        months, total = len(since.spent), sum(since.spent)
        aside = total / months
        return Story(
            figure=f"up to {money(max(since.spent))} a month",
            guide=(
                f"Spent in {beat.charges} of the last {months} months.",
                f"Set aside {money(round(aside))} a month",
                "to cover months like these.",
            ),
            section="Each month",
            life=since,
            line="Set aside a month",
            line_value=aside,
            rows=(
                ("Biggest month", money(max(since.spent))),
                ("Months spent in", f"{beat.charges} of {months}"),
                ("In all", money(total)),
                ("Set aside", money(round(aside))),
                ("Last one", _last_spent(since)),
            ),
            histogram=False,
        )
    if label == "steady":
        guide = (
            "About the same every month.",
            f"Set aside {money(round(numbers.mean))} a month",
            "and it is covered.",
        )
    elif label == "variable":
        guide = (
            f"Between {money(numbers.lowest)} and {money(numbers.highest)} a month.",
            f"Set aside {money(round(numbers.mean))} a month",
            "to cover it over time.",
        )
    elif beat.charges == 1:
        # Bought once: neither a month nor something to plan for
        return Story(
            figure=f"{money(round(beat.charge))} once",
            guide=(f"Spent once, in {_last_spent(since)}.", "", "Nothing to plan for yet."),
            section="Each month",
            life=ranged,
            line="Average",
            line_value=numbers.mean,
            rows=every_month,
            histogram=False,
        )
    else:
        guide = None
    return Story(
        figure=month_figure,
        guide=guide,
        section="Each month",
        life=ranged,
        line="Average",
        line_value=numbers.mean,
        rows=every_month,
        histogram=len(ranged.spent) > 1,
    )
