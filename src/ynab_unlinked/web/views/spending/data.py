"""What the Spending view shows, worked out without NiceGUI: the range, each category's row
and the words of its volatility."""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ynab_unlinked.config import LatestConfig
from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend
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
        "Quiet months and big ones: holidays, repairs. Moves over 75%: plan for these.",
    ),
    "lumpy": Word(
        "◆ lumpy",
        "acc",
        "Big charges every so often, each about the same: a yearly subscription, insurance. "
        "Swingy by the numbers, but predictable.",
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
