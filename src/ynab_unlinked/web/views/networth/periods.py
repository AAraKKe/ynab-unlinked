"""The Months and Movers tabs of Net worth, drawn from one `core.finance.Period`.

`PeriodTabs` draws the tab the view is on, opens the period drawer and restyles the chart.

Months: four tiles (the change, how much of it was saved, what valuation did, months up) and
the monthly change chart; clicking a month or the change tile opens the period drawer.
Movers: every counted account's change over the range, what you put in or took out, what
valuation did and its return.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.finance import Period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import clickable, glass_card, stat_tile
from ynab_unlinked.web.components.controls import pill_group
from ynab_unlinked.web.components.flow_chart import months_chart, months_options
from ynab_unlinked.web.components.history_chart import set_options
from ynab_unlinked.web.state import state
from ynab_unlinked.web.theme import Palette
from ynab_unlinked.web.views.networth import flows as words
from ynab_unlinked.web.views.networth.data import RANGES, Snapshot, signed
from ynab_unlinked.web.views.networth.period_drawer import period_drawer


class PeriodTabs:
    """The Months or Movers tab of the period the view loaded, inside the view's `root`."""

    def __init__(self, root: ui.element) -> None:
        self.root = root
        self.snapshot: Snapshot | None = None
        self.period: Period | None = None
        self.chart: ui.echart | None = None

    def draw(
        self,
        tab: str,
        snapshot: Snapshot,
        period: Period,
        range_key: str,
        on_range: Callable[[str], Any],
        palette: Palette,
    ) -> None:
        """Draw `tab` (`months` or `movers`) in the current context."""
        config, _ = state().require()
        formatter = state().require_formatter()
        self.snapshot, self.period, self.chart = snapshot, period, None
        with ui.element("div").classes("yul-nwm-head"):
            ui.label(words.period_title(period.start, period.end)).classes("yul-h2 yul-grow")
            pill_group({key: key for key in RANGES}, range_key, on_range, marker="range").mark(
                "ranges"
            )
        if tab == "months":
            self.chart = months_tab(
                period,
                palette=palette,
                currency_format=config.budget.currency_format,
                formatter=formatter,
                on_month=self.open_month,
                on_period=self.open_period,
            )
        else:
            movers_tab(period, self._names(), formatter)

    def restyle(self, palette: Palette) -> None:
        chart, period = self.chart, self.period
        if chart is not None and period is not None and not chart.is_deleted:
            config, _ = state().require()
            set_options(
                chart, months_options(period.months, palette, config.budget.currency_format)
            )

    def _names(self) -> dict[str, str]:
        snapshot = self.snapshot
        return {} if snapshot is None else {a.id: snapshot.name(a) for a in snapshot.tracked}

    def open_period(self) -> None:
        if self.period is None:
            return
        with self.root:
            period_drawer(self.period, self._names(), state().require_formatter())

    async def open_month(self, index: int) -> None:
        snapshot, shown = self.snapshot, self.period
        if snapshot is None or shown is None or not 0 <= index < len(shown.months):
            return
        config, _ = state().require()
        start, end = words.month_bounds(shown.months[index][0], dt.date.today())
        month = await run.io_bound(words.load_period, state().store, config, snapshot, start, end)
        if month is None or self.root.is_deleted:
            return
        with self.root:
            period_drawer(month, self._names(), state().require_formatter())


def months_tab(
    period: Period,
    *,
    palette: Palette,
    currency_format: CurrencyFormat,
    formatter: Formatter,
    on_month: Callable[[int], Any],
    on_period: Callable[[], Any],
) -> ui.echart:
    """Draw the tab; returns its chart, which the view restyles when the theme changes."""
    flows = period.flows
    up, months = words.months_up(period)
    best = words.best_month(period)
    with ui.element("div").classes("yul-nw-tiles yul-stagger"):
        change = stat_tile(
            "Change",
            signed(formatter, flows.change),
            hint=f"from {formatter.format_amount_milli(period.start_worth)} · see why ›",
        ).mark("tile-change")
        clickable(change, on_period).classes("yul-nwm-click")
        stat_tile(
            "From saving",
            signed(formatter, flows.saved),
            hint=words.share_of_change(flows.saved, flows) or "income minus spending",
        ).mark("tile-saved")
        stat_tile(
            "From valuation",
            signed(formatter, flows.valuation),
            hint=words.share_of_change(flows.valuation, flows) or "markets, interest",
        ).mark("tile-valuation")
        stat_tile(
            "Months up",
            f"{up} of {months}",
            hint=None
            if best is None or best[1].change <= 0
            else f"best {best[0].strftime('%b')} {signed(formatter, best[1].change)}",
        ).mark("tile-months-up")
    with glass_card().classes("yul-nwm-card"):
        with ui.element("div").classes("yul-row"):
            ui.label("Monthly change").classes("yul-nwm-title yul-grow")
            ui.label("click a month to see why").classes("yul-faint yul-small")
        return months_chart(period.months, palette, currency_format, on_month).mark("months-chart")


def movers_tab(period: Period, names: dict[str, str], formatter: Formatter) -> None:
    """One row per counted account, largest change first, with a bar around zero."""
    widest = words.spread(period.accounts) or 1
    with glass_card().classes("yul-nwm-card").mark("movers"):
        with ui.element("div").classes("yul-nwm-row head"):
            ui.label("Account")
            ui.label("Change")
            ui.label("Your money").classes("yul-nwm-r")
            ui.label("Valuation").classes("yul-nwm-r")
            ui.label("Return").classes("yul-nwm-r").props["title"] = (
                "What valuation earned on the money in the account, per year over a range "
                "longer than one"
            )
        for move in period.accounts:
            width = abs(move.change) / widest * 50
            side = "up" if move.change >= 0 else "down"
            place = (
                f"left:50%;width:{width:.2f}%"
                if side == "up"
                else f"left:{50 - width:.2f}%;width:{width:.2f}%"
            )
            with ui.element("div").classes("yul-nwm-row").mark(f"mover-{move.account_id}"):
                ui.label(names.get(move.account_id, "Account")).classes("yul-nwm-name")
                with ui.element("div").classes("yul-nwm-change"):
                    with ui.element("div").classes("yul-nwm-dbar"):
                        ui.element("i").classes(side).style(place)
                    ui.label(signed(formatter, move.change)).classes("yul-num yul-small")
                ui.label(signed(formatter, move.own_money) if move.own_money else "—").classes(
                    "yul-num yul-nwm-r yul-muted"
                )
                valuation = move.flows.valuation
                ui.label(signed(formatter, valuation) if valuation else "—").classes(
                    "yul-num yul-nwm-r "
                    + ("yul-good" if valuation > 0 else "yul-bad" if valuation < 0 else "yul-faint")
                )
                ui.label(words.rate_text(move, period.days)).classes("yul-num yul-nwm-r")
    ui.label(
        "Your money is what you put in or took out: income, spending and transfers. Valuation "
        "is what the account did on its own. Return weighs valuation by how long the money "
        "was in the account."
    ).classes("yul-faint yul-small").style("margin:8px 4px 0")
