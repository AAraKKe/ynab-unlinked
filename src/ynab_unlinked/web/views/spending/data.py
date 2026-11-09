"""What the Spending view shows, worked out without NiceGUI: the range, each category's row
and the words of its volatility."""

from __future__ import annotations

import datetime as dt
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
    "steady": Word("● steady", "ok", "About the same every month"),
    "variable": Word("◐ variable", "default", "Moves around its average"),
    "spiky": Word("▲ spiky", "warn", "Quiet months and big ones: plan for these"),
    "lumpy": Word("◆ lumpy", "acc", "Big charges every so often, each about the same"),
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
