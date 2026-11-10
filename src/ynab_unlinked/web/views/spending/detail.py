"""One category in the place of the steady or swingy chart: its months, how they spread, and
the numbers behind its word.

It slides in over the chart from the right; the back arrow brings the chart back. Everything
is over the category's life in the range (its first month of spending to its last); the range
itself is the page's, so changing it updates the detail in place. A lumpy category shows its
charges instead, over its history: what one costs, how often it comes, what to set aside.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend, rhythm
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
    """Draw the detail in the current context (the chart's card).

    A lumpy category is not spent "a month": its detail is about its charges (what one
    costs, how often it comes, what to set aside for it), over its history.
    """
    money = formatter.format_amount_milli
    word = data.word(trend)
    beat = rhythm(trend.past)
    lumpy = trend.volatility.label == "lumpy" and beat.set_aside is not None
    life = data.charges(trend, flow) if lumpy else data.life(trend, flow)
    numbers = data.stats(life.spent)
    with ui.element("div").classes("yul-sp-detail").mark("category-detail"):
        with ui.element("div").classes("yul-row").style("gap:8px;align-items:flex-start"):
            back = button(icon_name="arrow-left", kind="ghost", small=True, on_click=on_back)
            back.props["title"] = "Back to steady or swingy"
            back.mark("detail-back")
            ui.label(f"{trend.group} / {trend.name}").classes("yul-nwm-title yul-grow").mark(
                "detail-title"
            )
            figure = (
                f"{money(round(beat.charge))} a charge"
                if lumpy
                else f"{money(round(numbers.mean))} a month"
            )
            ui.label(figure).classes("yul-nwp-figure yul-num").mark("detail-figure")
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
        if lumpy and beat.every and beat.set_aside:
            with ui.element("div").classes("yul-sp-aside").mark("detail-set-aside"):
                ui.label(f"About {data.every_text(beat.every)}.")
                ui.label(f"Set aside {money(round(beat.set_aside))} a month").classes("yul-num")
                ui.label("to have it ready.")

        ui.label("Each charge" if lumpy else "Each month").classes("yul-section")
        keys = [month.strftime("%Y-%m") for month in life.months]
        # The dashed line of a lumpy category is what to set aside: its month by month cost
        average = beat.set_aside if lumpy and beat.set_aside else numbers.mean
        chart(
            category_months_options(
                keys,
                life.spent,
                palette,
                currency_format,
                average,
                line="Set aside a month" if lumpy else "Average",
            ),
            DETAIL_HEIGHT,
        ).mark("detail-chart")

        if lumpy and beat.every and beat.set_aside:
            paid = [m for m, v in zip(life.months, life.spent, strict=True) if v > 0]
            last = paid[-1]
            rows = (
                ("A charge", money(round(beat.charge))),
                ("Charges", str(beat.charges)),
                ("Comes", data.every_text(beat.every)),
                ("Set aside", f"{money(round(beat.set_aside))} a month"),
                ("Last one", f"{last:%b %Y}"),
            )
        else:
            rows = (
                ("Average", money(round(numbers.mean))),
                ("Median", money(round(numbers.median))),
                ("Lowest month", money(numbers.lowest)),
                ("Highest month", money(numbers.highest)),
                ("Spread", money(round(numbers.spread))),
            )
        with ui.element("div").classes("yul-sp-numbers").mark("detail-stats"):
            for key, value in rows:
                with ui.element("div"):
                    ui.label(key).classes("yul-faint yul-small")
                    ui.label(value).classes("yul-num")

        if lumpy:  # months of nothing and a few charges: there is no spread to show
            return
        ui.label("How the months spread").classes("yul-section")
        bins = [(b.low, b.high, b.months) for b in data.histogram(life.spent)]
        chart(histogram_options(bins, palette, currency_format), HISTOGRAM_HEIGHT).mark(
            "detail-histogram"
        )
