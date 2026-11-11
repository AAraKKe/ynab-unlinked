"""The Months and Movers tabs of Net worth, drawn from one `core.finance.Period`.

Months: four tiles (the change, how much of it was saved, what assets did, months up), the
monthly change chart and, under it, the period panel. With no month selected the panel shows
the whole range; clicking a month shows that month, clicking it again (or anywhere outside
the chart and the panel) goes back to the whole range.
Movers: every counted account's change over the range, what you put in or took out, what its
assets did and its return.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Collection
from typing import Any

from nicegui import run, ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.finance import Period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import closed_pill, glass_card, stat_tile
from ynab_unlinked.web.components.controls import pill_group
from ynab_unlinked.web.components.flow_chart import months_chart, months_options
from ynab_unlinked.web.components.history_chart import set_options
from ynab_unlinked.web.finances import RANGES
from ynab_unlinked.web.state import state
from ynab_unlinked.web.theme import KEEP_PROP, OUTSIDE_EVENT, OUTSIDE_PROP, Palette
from ynab_unlinked.web.views.networth import flows as words
from ynab_unlinked.web.views.networth.data import Snapshot, signed
from ynab_unlinked.web.views.networth.period_panel import period_panel


class PeriodTabs:
    """The Months or Movers tab of the period the view loaded, and the selected month."""

    def __init__(self) -> None:
        self.snapshot: Snapshot | None = None
        self.period: Period | None = None
        self.palette: Palette | None = None
        self.chart: ui.echart | None = None
        self.panel: ui.element | None = None
        self.selected: int | None = None
        self.month: Period | None = None

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
        if self.period is None or period.months != self.period.months:
            self.selected, self.month = None, None
        self.snapshot, self.period, self.palette = snapshot, period, palette
        self.chart = self.panel = None
        with ui.element("div").classes("yul-nwm-head"):
            ui.label(words.period_title(period.start, period.end)).classes("yul-h2 yul-grow")
            pill_group({key: key for key in RANGES}, range_key, on_range, marker="range").mark(
                "ranges"
            )
        if tab != "months":
            movers_tab(period, words.account_names(snapshot), self._closed(), formatter)
            return
        with ui.element("div").classes("yul-nwm-months").mark("months-tab") as months:
            # A click anywhere but on the chart or the panel of the month goes back to the range
            months.props(OUTSIDE_PROP).on(OUTSIDE_EVENT, self.clear)
            self.chart = months_tab(
                period,
                palette=palette,
                currency_format=config.budget.currency_format,
                formatter=formatter,
                on_month=self.pick,
                selected=self.selected,
            )
            self.chart.props(KEEP_PROP)
            self.panel = ui.element("div").props(KEEP_PROP)
        self._draw_panel()

    def _closed(self) -> set[str]:
        snapshot = self.snapshot
        if snapshot is None:
            return set()
        return {a.id for a in snapshot.history if snapshot.closed(a.id)}

    def _draw_panel(self) -> None:
        if self.panel is None or self.panel.is_deleted or self.snapshot is None:
            return
        if self.palette is None:
            return
        shown = self.month if self.month is not None else self.period
        if shown is None:
            return
        self.panel.clear()
        with self.panel:
            period_panel(
                shown,
                words.account_names(self.snapshot),
                self._closed(),
                state().require_formatter(),
                self.palette,
                selected=self.month is not None,
                on_clear=self.clear,
            )

    def _restyle_chart(self) -> None:
        chart, period, palette = self.chart, self.period, self.palette
        if chart is None or period is None or palette is None or chart.is_deleted:
            return
        config, _ = state().require()
        options = months_options(
            period.months, palette, config.budget.currency_format, self.selected
        )
        set_options(chart, options)

    def restyle(self, palette: Palette) -> None:
        self.palette = palette
        self._restyle_chart()
        self._draw_panel()

    async def pick(self, index: int) -> None:
        """A click on a month: show it, or the whole range again when it was the one shown."""
        snapshot, period = self.snapshot, self.period
        if snapshot is None or period is None or not 0 <= index < len(period.months):
            return
        wanted = words.next_selection(self.selected, index)
        if wanted is None:
            self.clear()
            return
        config, _ = state().require()
        start, end = words.month_bounds(period.months[wanted][0], dt.date.today())
        month = await run.io_bound(words.load_period, state().store, config, snapshot, start, end)
        if month is None or self.panel is None or self.panel.is_deleted:
            return
        self.selected, self.month = wanted, month
        self._restyle_chart()
        self._draw_panel()

    def clear(self) -> None:
        """Back to the whole range."""
        if self.selected is None:
            return
        self.selected, self.month = None, None
        self._restyle_chart()
        self._draw_panel()


def months_tab(
    period: Period,
    *,
    palette: Palette,
    currency_format: CurrencyFormat,
    formatter: Formatter,
    on_month: Callable[[int], Any],
    selected: int | None = None,
) -> ui.echart:
    """Draw the tiles and the chart card; returns the chart, which the view restyles."""
    flows = period.flows
    up, months = words.months_up(period)
    best = words.best_month(period)
    with ui.element("div").classes("yul-nw-tiles yul-stagger"):
        stat_tile(
            "Change",
            signed(formatter, flows.change),
            hint=f"from {formatter.format_amount_milli(period.start_worth)}",
        ).mark("tile-change")
        stat_tile(
            "From saving",
            signed(formatter, flows.saved),
            hint=words.share_of_change(flows.saved, flows) or "income minus spending",
        ).mark("tile-saved")
        stat_tile(
            "From assets",
            signed(formatter, flows.assets),
            hint=words.share_of_change(flows.assets, flows) or "markets, interest, sales",
        ).mark("tile-assets")
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
            ui.label(
                "click a month to see it; again, or anywhere else, for the whole range"
            ).classes("yul-faint yul-small")
        chart = months_chart(period.months, palette, currency_format, on_month, selected)
        chart.mark("months-chart")
        if any(month.other + month.transfers for _, month in period.months):
            ui.label(words.OTHER_NOTE).classes("yul-faint yul-small").mark("other-note")
    return chart


def movers_tab(
    period: Period, names: dict[str, str], closed: Collection[str], formatter: Formatter
) -> None:
    """One row per counted account, largest change first, with a bar around zero."""
    widest = words.spread(period.accounts) or 1
    with glass_card().classes("yul-nwm-card").mark("movers"):
        with ui.element("div").classes("yul-nwm-row head"):
            ui.label("Account")
            ui.label("Change")
            ui.label("Your money").classes("yul-nwm-r")
            ui.label("Assets").classes("yul-nwm-r")
            ui.label("Return").classes("yul-nwm-r").props["title"] = (
                "What the asset changes earned on the money in the account, per year over a "
                "range longer than one. Settings › Net worth picks the accounts."
            )
        for move in period.accounts:
            if not move.change and not move.start_balance and move.account_id in closed:
                continue  # closed before the range: nothing to show
            width = abs(move.change) / widest * 50
            up = move.change >= 0
            place = (
                f"left:50%;width:{width:.2f}%"
                if up
                else f"left:{50 - width:.2f}%;width:{width:.2f}%"
            )
            with ui.element("div").classes("yul-nwm-row").mark(f"mover-{move.account_id}"):
                with ui.element("div").classes("yul-nwm-name"):
                    ui.label(names.get(move.account_id, "Account"))
                    if move.account_id in closed:
                        closed_pill()
                with ui.element("div").classes("yul-nwm-change"):
                    with ui.element("div").classes("yul-nwm-dbar"):
                        ui.element("i").classes("up" if up else "down").style(place)
                    ui.label(signed(formatter, move.change)).classes("yul-num yul-small")
                ui.label(signed(formatter, move.own_money) if move.own_money else "—").classes(
                    "yul-num yul-nwm-r yul-muted"
                )
                assets = move.flows.assets
                ui.label(signed(formatter, assets) if assets else "—").classes(
                    "yul-num yul-nwm-r "
                    + ("yul-good" if assets > 0 else "yul-bad" if assets < 0 else "yul-faint")
                )
                ui.label(words.rate_text(move, period.days)).classes("yul-num yul-nwm-r")
    ui.label(
        "Your money is what you put in or took out: income, spending and transfers. Assets is "
        "what changed the account outside transfers: market moves, interest, sales recorded as "
        "an adjustment. Return weighs it by how long the money was in the account."
    ).classes("yul-faint yul-small").style("margin:8px 4px 0")
