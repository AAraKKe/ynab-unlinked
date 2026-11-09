"""The Spending view: three tiles, spending by group, steady or swingy, and every category.

Averages cover the complete months of the range. Each category row has its average a month,
its share, a sparkline of its months and its volatility word (`core.cashflow.volatility`).
"""

from __future__ import annotations

import datetime as dt

from nicegui import run, ui

from ynab_unlinked.core.cashflow import CashFlow
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import button, empty_state, glass_card, pill, stat_tile
from ynab_unlinked.web.components.cashflow_chart import SCATTER_HEIGHT, chart, volatility_options
from ynab_unlinked.web.components.controls import pill_group
from ynab_unlinked.web.finances import RANGES, period_title
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.spending import data


class SpendingView:
    def __init__(self) -> None:
        self.range = data.DEFAULT_RANGE
        self.all = False
        self.flow: CashFlow | None = None
        self.body = ui.element("div").classes("yul-sp")

    async def render(self) -> None:
        config, _ = state().require()
        flow = await run.io_bound(data.load, state().store, config, self.range, dt.date.today())
        if flow is None or self.body.is_deleted:
            return
        self.flow = flow
        self._draw()

    async def set_range(self, key: str) -> None:
        self.range = key
        await self.render()

    def show_all(self) -> None:
        self.all = True
        self._draw()

    def _draw(self) -> None:
        flow = self.flow
        if flow is None:
            return
        config, _ = state().require()
        formatter = state().require_formatter()
        money = formatter.format_amount_milli
        self.body.clear()
        with self.body:
            with ui.element("div").classes("yul-nwm-head"):
                ui.label(period_title(flow.start, flow.end)).classes("yul-h2 yul-grow")
                pill_group({key: key for key in RANGES}, self.range, self.set_range, marker="range")
            if not flow.complete or not flow.categories:
                empty_state(
                    "Spending needs one complete month. Pick a longer range.",
                    icon_name="spending",
                ).mark("sp-empty")
                return

            core = flow.core_spending()
            with ui.element("div").classes("yul-sp-tiles yul-stagger"):
                stat_tile("Spending a month", money(round(flow.mean_spending))).mark("sp-total")
                stat_tile("Core", money(round(core)), hint="steady and variable categories").mark(
                    "sp-core"
                )
                stat_tile(
                    "One-offs",
                    money(round(max(flow.mean_spending - core, 0))),
                    hint="spiky and lumpy ones, and the rest",
                ).mark("sp-one-offs")

            with ui.element("div").classes("yul-sp-split"):
                with glass_card().classes("yul-nwm-card").mark("sp-groups"):
                    with ui.element("div").classes("yul-row"):
                        ui.label("By group").classes("yul-nwm-title yul-grow")
                        ui.label("a month · share").classes("yul-faint yul-small")
                    groups = flow.groups()
                    widest = groups[0].mean if groups else 1
                    for group in groups:
                        with ui.element("div").classes("yul-hbar").mark(f"group-{group.name}"):
                            ui.label(group.name).classes("yul-hbar-name")
                            with ui.element("div").classes("yul-hbar-track"):
                                ui.element("i").style(f"width:{group.mean / widest * 100:.1f}%")
                            ui.label(
                                f"{money(round(group.mean))} · {group.share * 100:.0f}%"
                            ).classes("yul-num yul-hbar-v")
                with glass_card().classes("yul-nwm-card"):
                    ui.label("Steady or swingy?").classes("yul-nwm-title")
                    chart(
                        volatility_options(
                            flow.categories, theme.palette(), config.budget.currency_format
                        ),
                        SCATTER_HEIGHT,
                    ).mark("sp-scatter")
                    ui.label(
                        "Right is more a month, up is how much it moves. Top right: big and "
                        "swingy, plan for these. Bottom right: your fixed costs."
                    ).classes("yul-faint yul-small")

            with glass_card().classes("yul-nwm-card").mark("sp-categories"):
                with ui.element("div").classes("yul-row"):
                    ui.label("Categories").classes("yul-nwm-title yul-grow")
                    ui.label("most spent first").classes("yul-faint yul-small")
                with ui.element("div").classes("yul-sp-row head"):
                    ui.label("Category")
                    ui.label("A month").classes("yul-nwm-r")
                    ui.label("Share").classes("yul-nwm-r")
                    ui.label("Months")
                    ui.label("How it moves")
                shown = flow.categories if self.all else flow.categories[: data.SHOWN]
                for trend in shown:
                    key = trend.category_id or "none"
                    with ui.element("div").classes("yul-sp-row").mark(f"category-{key}"):
                        with ui.element("div").classes("yul-nwm-name"):
                            ui.label(trend.name)
                        ui.label(money(round(trend.volatility.mean))).classes("yul-num yul-nwm-r")
                        ui.label(f"{data.share(trend, flow) * 100:.0f}%").classes(
                            "yul-num yul-nwm-r yul-muted"
                        )
                        ui.html(
                            f'<svg width="{data.SPARK_WIDTH}" height="{data.SPARK_HEIGHT}" '
                            'class="yul-sp-spark" aria-hidden="true"><polyline points="'
                            f'{data.spark(trend.spent)}"/></svg>',
                            sanitize=False,
                        )
                        with ui.element("div").classes("yul-row").style("gap:6px"):
                            if (word := data.word(trend)) is not None:
                                tag = pill(
                                    word.text, word.kind if word.kind != "default" else "default"
                                )
                                tag.props["title"] = word.hint
                                cv = trend.volatility.cv or 0
                                ui.label(f"{cv:.2f}").classes("yul-faint yul-small yul-num")
                            else:
                                ui.label("not enough months").classes("yul-faint yul-small")
                if not self.all and len(flow.categories) > data.SHOWN:
                    button(
                        f"Show all {len(flow.categories)}",
                        kind="ghost",
                        small=True,
                        on_click=self.show_all,
                    ).mark("sp-show-all")
            ui.label(
                "How it moves: steady is about the same every month, variable moves around its "
                "average, spiky has quiet months and big ones, lumpy has big charges every so "
                "often of about the same amount (a yearly subscription). The number is the "
                "standard deviation over the average; empty months count as zero."
            ).classes("yul-faint yul-small").style("margin:8px 4px 0")


@shell.view(
    shell.SPENDING_PATH,
    key="spending",
    title="Spending",
    subtitle="Where the money goes, and how steady it is",
    icon="spending",
    order=42,
    group="Finances",
)
async def spending_view() -> None:
    await SpendingView().render()
