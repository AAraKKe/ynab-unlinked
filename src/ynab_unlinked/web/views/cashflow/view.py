"""The Cash flow view: four tiles, income against spending, the savings rate, income sources.

Averages and rates cover the complete months of the range; the month still running is in the
chart, faded. Everything is read from the store (`data.load`).
"""

from __future__ import annotations

import datetime as dt

from nicegui import run, ui

from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import empty_state, glass_card, info_button, stat_tile
from ynab_unlinked.web.components.cashflow_chart import (
    FLOW_HEIGHT,
    RATE_HEIGHT,
    chart,
    income_spending_options,
    rate_options,
)
from ynab_unlinked.web.components.controls import pill_group
from ynab_unlinked.web.finances import RANGES, period_title
from ynab_unlinked.web.ranges import save_range, saved_range
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.cashflow import data
from ynab_unlinked.web.wording import VERSUS_YNAB, VERSUS_YNAB_TITLE


class CashFlowView:
    def __init__(self) -> None:
        self.range = saved_range(data.DEFAULT_RANGE)
        self.body = ui.element("div").classes("yul-cf")
        shell.on_refresh(self.body, self.render)

    async def render(self) -> None:
        config, _ = state().require()
        page = await run.io_bound(data.load, state().store, config, self.range, dt.date.today())
        if self.body.is_deleted:
            return
        self.body.clear()
        with self.body:
            self._draw(page)

    async def set_range(self, key: str) -> None:
        self.range = key
        save_range(key)
        await self.render()

    def _draw(self, page: data.CashFlowPage) -> None:
        config, _ = state().require()
        formatter = state().require_formatter()
        palette = theme.palette()
        flow = page.flow
        money = formatter.format_amount_milli
        with ui.element("div").classes("yul-nwm-head"):
            with ui.element("div").classes("yul-row yul-info-row yul-grow"):
                ui.label(period_title(flow.start, flow.end)).classes("yul-h2")
                info_button(VERSUS_YNAB_TITLE, VERSUS_YNAB, marker="cf-info")
            pill_group({key: key for key in RANGES}, self.range, self.set_range, marker="range")
        if not flow.complete:
            empty_state(
                "Cash flow needs one complete month. Pick a longer range.", icon_name="cashflow"
            ).mark("cf-empty")
            return

        with ui.element("div").classes("yul-nw-tiles yul-stagger"):
            stat_tile(
                "Income a month",
                money(round(flow.mean_income)),
                hint=f"median {money(round(flow.median_income))}",
            ).mark("cf-income")
            stat_tile(
                "Spending a month",
                money(round(flow.mean_spending)),
                hint=data.spending_hint(page, formatter),
            ).mark("cf-spending")
            stat_tile(
                "Savings rate",
                data.percent(flow.savings_rate),
                hint=data.rate_change(page) or "saved over earned",
            ).mark("cf-rate")
            stat_tile(
                "Cash runway",
                data.runway_text(page),
                hint="cash and savings over core spending",
            ).mark("cf-runway")
        ui.label(f"Averages over {data.complete_note(flow)}.").classes("yul-faint yul-small")

        with glass_card().classes("yul-nwm-card"):
            ui.label("Income and spending").classes("yul-nwm-title")
            chart(
                income_spending_options(flow.months, palette, config.budget.currency_format),
                FLOW_HEIGHT,
            ).mark("cf-chart")
        with glass_card().classes("yul-nwm-card"):
            ui.label("Savings rate").classes("yul-nwm-title")
            chart(rate_options(flow.months, palette, flow.savings_rate), RATE_HEIGHT).mark(
                "cf-rate-chart"
            )
        with glass_card().classes("yul-nwm-card").mark("cf-sources"):
            with ui.element("div").classes("yul-row"):
                ui.label("Came in from").classes("yul-nwm-title yul-grow")
                ui.label("by payee, the whole range").classes("yul-faint yul-small")
            top = flow.income[: data.TOP_PAYEES]
            widest = top[0].amount if top else 1
            for income in top:
                with ui.element("div").classes("yul-hbar"):
                    ui.label(income.name).classes("yul-hbar-name")
                    with ui.element("div").classes("yul-hbar-track"):
                        ui.element("i").style(f"width:{income.amount / widest * 100:.1f}%")
                    ui.label(money(income.amount)).classes("yul-num yul-hbar-v")


@shell.view(
    shell.CASHFLOW_PATH,
    key="cashflow",
    title="Cash flow",
    subtitle="What comes in, what goes out, what stays",
    icon="cashflow",
    order=41,
    group="Finances",
)
async def cashflow_view() -> None:
    await CashFlowView().render()
