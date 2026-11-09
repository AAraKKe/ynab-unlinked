"""The category drawer of Spending: one category's months, how they spread, and the numbers
behind its word.

The same right side dialog as Net worth's account drawer. Opened from a dot of the steady or
swingy chart or from a row of the categories table.
"""

from __future__ import annotations

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import button, pill
from ynab_unlinked.web.components.cashflow_chart import (
    DRAWER_HEIGHT,
    category_months_options,
    chart,
    histogram_options,
)
from ynab_unlinked.web.theme import Palette
from ynab_unlinked.web.views.spending import data


def category_drawer(
    trend: CategoryTrend,
    flow: CashFlow,
    *,
    palette: Palette,
    currency_format: CurrencyFormat,
    formatter: Formatter,
) -> None:
    """Open the drawer in the current context; it deletes itself once closed."""
    money = formatter.format_amount_milli
    numbers = data.stats(trend)
    word = data.word(trend)
    months = [month.month.strftime("%Y-%m") for month in flow.complete]
    with (
        ui.dialog().props("position=right full-height") as dialog,
        ui.element("div").classes("yul-card yul-nw-drawer").mark("category-drawer"),
    ):
        with ui.element("div").classes("yul-row"):
            with ui.element("div").classes("yul-grow"):
                ui.label(trend.name).classes("yul-h2")
                ui.label(f"{trend.group} · {len(months)} complete months").classes(
                    "yul-faint yul-small"
                )
            close = button(icon_name="x", kind="ghost", on_click=dialog.close)
            close.props["title"] = "Close"
        ui.label(f"{money(round(trend.mean))} a month").classes("yul-nw-drawer-figure yul-num")
        with ui.element("div").classes("yul-row").style("gap:8px"):
            if word is not None:
                pill(word.text, word.kind).mark("drawer-word")
                ui.label(f"moves {(trend.volatility.cv or 0) * 100:.0f}%").classes(
                    "yul-faint yul-small"
                )
            else:
                ui.label("Not enough months to say how it moves.").classes("yul-faint yul-small")
        if word is not None:
            ui.label(word.hint).classes("yul-muted yul-small")

        ui.label("Each month").classes("yul-section")
        chart(
            category_months_options(months, trend.spent, palette, currency_format, trend.mean),
            DRAWER_HEIGHT,
        ).mark("drawer-months")
        ui.label("dashed: its average over the range").classes("yul-faint yul-small")

        ui.label("How the months spread").classes("yul-section")
        life = trend.spent
        active = [index for index, value in enumerate(life) if value > 0]
        if active:
            life = life[active[0] : active[-1] + 1]
        bins = [(b.low, b.high, b.months) for b in data.histogram(life)]
        chart(histogram_options(bins, palette, currency_format), DRAWER_HEIGHT).mark(
            "drawer-histogram"
        )
        ui.label(
            "How many months fell in each slice, from its first month of spending to its last."
        ).classes("yul-faint yul-small")

        ui.label("The numbers").classes("yul-section")
        with ui.element("div").classes("yul-kv").mark("drawer-stats"):
            for key, value in (
                ("Average, first to last month", money(round(numbers.mean))),
                ("Median", money(round(numbers.median))),
                ("Lowest month", money(numbers.lowest)),
                ("Highest month", money(numbers.highest)),
                ("Spread (std dev)", money(round(numbers.spread))),
                ("Months it spent in", f"{numbers.active} of {numbers.months}"),
            ):
                ui.label(key).classes("k")
                ui.label(value).classes("yul-num")
        ui.label(
            "Measured from its first month of spending to its last in the range; the average a "
            "month at the top is over the whole range."
        ).classes("yul-faint yul-small")
    dialog.on_value_change(lambda e: None if e.value else dialog.delete())
    dialog.open()
