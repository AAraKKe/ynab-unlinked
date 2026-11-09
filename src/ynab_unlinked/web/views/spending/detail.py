"""One category in the place of the steady or swingy chart: its months, how they spread, and
the numbers behind its word.

It slides in over the chart from the right; the back arrow brings the chart back. Everything
is over the category's life in the range (its first month of spending to its last), which the
line under its name spells out, so changing the range updates it in place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import button, pill
from ynab_unlinked.web.components.cashflow_chart import (
    DETAIL_HEIGHT,
    HISTOGRAM_HEIGHT,
    category_months_options,
    chart,
    histogram_options,
)
from ynab_unlinked.web.theme import Palette
from ynab_unlinked.web.views.spending import data


def category_detail(
    trend: CategoryTrend,
    flow: CashFlow,
    *,
    palette: Palette,
    currency_format: CurrencyFormat,
    formatter: Formatter,
    on_back: Callable[[], Any],
) -> None:
    """Draw the detail in the current context (the chart's card)."""
    money = formatter.format_amount_milli
    life = data.life(trend, flow)
    numbers = data.stats(life.spent)
    word = data.word(trend)
    with ui.element("div").classes("yul-sp-detail").mark("category-detail"):
        with ui.element("div").classes("yul-row").style("gap:8px;align-items:flex-start"):
            back = button(icon_name="arrow-left", kind="ghost", small=True, on_click=on_back)
            back.props["title"] = "Back to steady or swingy"
            back.mark("detail-back")
            with ui.element("div").classes("yul-grow"):
                ui.label(trend.name).classes("yul-nwm-title")
                ui.label(f"{trend.group} · {life.title}").classes("yul-faint yul-small").mark(
                    "detail-months"
                )
            ui.label(f"{money(round(numbers.mean))} a month").classes("yul-nwp-figure yul-num")
        with ui.element("div").classes("yul-row").style("gap:8px;margin-top:6px"):
            if word is not None:
                pill(word.text, word.kind).mark("detail-word")
                ui.label(f"moves {(trend.volatility.cv or 0) * 100:.0f}%").classes(
                    "yul-faint yul-small yul-nowrap"
                )
            else:
                ui.label("Not enough months to say how it moves.").classes("yul-faint yul-small")
        if word is not None:
            ui.label(word.hint).classes("yul-muted yul-small").style("margin-top:4px")

        ui.label("Each month").classes("yul-section")
        keys = [month.strftime("%Y-%m") for month in life.months]
        chart(
            category_months_options(keys, life.spent, palette, currency_format, numbers.mean),
            DETAIL_HEIGHT,
        ).mark("detail-chart")

        with ui.element("div").classes("yul-sp-numbers").mark("detail-stats"):
            for key, value in (
                ("Average", money(round(numbers.mean))),
                ("Median", money(round(numbers.median))),
                ("Lowest month", money(numbers.lowest)),
                ("Highest month", money(numbers.highest)),
                ("Spread", money(round(numbers.spread))),
            ):
                with ui.element("div"):
                    ui.label(key).classes("yul-faint yul-small")
                    ui.label(value).classes("yul-num")

        ui.label("How the months spread").classes("yul-section")
        bins = [(b.low, b.high, b.months) for b in data.histogram(life.spent)]
        chart(histogram_options(bins, palette, currency_format), HISTOGRAM_HEIGHT).mark(
            "detail-histogram"
        )
