"""The Spending view: three tiles, spending by group with how it moves, steady or swingy, a
legend of the four words, and every category.

Averages cover the complete months of the range. A group pill and a word of the legend filter
the chart and the table (a filtered table lists every category that passes). A dot of the
chart or a row of the table opens the category drawer.
"""

from __future__ import annotations

import datetime as dt
from functools import partial

from nicegui import events, run, ui

from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import (
    button,
    clickable,
    empty_state,
    glass_card,
    pill,
    set_class,
    stat_tile,
)
from ynab_unlinked.web.components.cashflow_chart import SCATTER_HEIGHT, chart, volatility_options
from ynab_unlinked.web.components.controls import pill_group
from ynab_unlinked.web.finances import RANGES, period_title
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.spending import data
from ynab_unlinked.web.views.spending.drawer import category_drawer

ALL_GROUPS = "__all__"


class SpendingView:
    def __init__(self) -> None:
        self.range = data.DEFAULT_RANGE
        self.all = False
        self.group: str | None = None
        self.label: str | None = None
        self.flow: CashFlow | None = None
        self.plotted: list[CategoryTrend] = []
        with ui.element("div").classes("yul-sp") as self.root:
            self.body = ui.element("div")

    async def render(self) -> None:
        config, _ = state().require()
        flow = await run.io_bound(data.load, state().store, config, self.range, dt.date.today())
        if flow is None or self.body.is_deleted:
            return
        self.flow = flow
        groups = {trend.group for trend in flow.categories}
        if self.group not in groups:
            self.group = None
        self._draw()

    async def set_range(self, key: str) -> None:
        self.range = key
        await self.render()

    def show_all(self) -> None:
        self.all = True
        self._draw()

    def set_group(self, key: str) -> None:
        self.group = None if key == ALL_GROUPS else key
        self._draw()

    def toggle_label(self, label: str) -> None:
        self.label = None if self.label == label else label
        self._draw()

    def open_category(self, trend: CategoryTrend) -> None:
        if self.flow is None:
            return
        config, _ = state().require()
        with self.root:
            category_drawer(
                trend,
                self.flow,
                palette=theme.palette(),
                currency_format=config.budget.currency_format,
                formatter=state().require_formatter(),
            )

    def _dot_clicked(self, event: events.GenericEventArguments) -> None:
        index = event.args.get("dataIndex")
        series = event.args.get("componentType") == "series"
        if series and isinstance(index, int) and 0 <= index < len(self.plotted):
            self.open_category(self.plotted[index])

    def _draw(self) -> None:
        flow = self.flow
        if flow is None:
            return
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
            self._tiles(flow)
            with ui.element("div").classes("yul-sp-split"):
                self._groups(flow)
                self._scatter(flow)
            self._legend()
            self._categories(flow)

    def _tiles(self, flow: CashFlow) -> None:
        money = state().require_formatter().format_amount_milli
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

    def _groups(self, flow: CashFlow) -> None:
        money = state().require_formatter().format_amount_milli
        with glass_card().classes("yul-nwm-card").mark("sp-groups"):
            with ui.element("div").classes("yul-row"):
                ui.label("By group").classes("yul-nwm-title yul-grow")
                ui.label("a month · share · click to filter").classes("yul-faint yul-small")
            with ui.element("div").classes("yul-sp-key").mark("sp-mix-key"):
                for label in (*data.ORDER, data.UNRATED):
                    with ui.element("span"):
                        ui.element("i").classes(f"mix-{label}")
                        word = data.WORDS.get(label)
                        ui.label(word.text.split(" ", 1)[1] if word else "not enough months")
            groups = flow.groups()
            widest = groups[0].mean if groups else 1
            for group in groups:
                row = ui.element("div").classes("yul-sp-group").mark(f"group-{group.name}")
                set_class(row, "on", group.name == self.group)
                clickable(row, partial(self.set_group, group.name))
                row.props["title"] = f"Show only {group.name}"
                with row:
                    with ui.element("div").classes("yul-hbar"):
                        ui.label(group.name).classes("yul-hbar-name")
                        with ui.element("div").classes("yul-hbar-track"):
                            ui.element("i").style(f"width:{group.mean / widest * 100:.1f}%")
                        ui.label(f"{money(round(group.mean))} · {group.share * 100:.0f}%").classes(
                            "yul-num yul-hbar-v"
                        )
                    mix = data.group_mix(flow, group.name)
                    with ui.element("div").classes("yul-sp-mix").mark(f"mix-{group.name}"):
                        for part in mix:
                            segment = ui.element("i").classes(f"mix-{part.label}")
                            segment.style(f"width:{part.share * 100:.2f}%")
                            word = data.WORDS.get(part.label)
                            name = word.text if word else "not enough months"
                            segment.props["title"] = f"{name}: {part.share * 100:.0f}%"

    def _scatter(self, flow: CashFlow) -> None:
        config, _ = state().require()
        shown = data.filtered(flow, self.group, self.label)
        self.plotted = data.plotted(shown)
        with glass_card().classes("yul-nwm-card"):
            with ui.element("div").classes("yul-row"):
                ui.label("Steady or swingy?").classes("yul-nwm-title yul-grow")
                ui.label("click a dot to see its months").classes("yul-faint yul-small")
            dots = chart(
                volatility_options(self.plotted, theme.palette(), config.budget.currency_format),
                SCATTER_HEIGHT,
            ).mark("sp-scatter")
            dots.on("componentClick", self._dot_clicked, ["componentType", "dataIndex"])
            ui.label(
                "Right is more a month, up is how much it moves. Top right: big and swingy, plan "
                "for these. Bottom right: your fixed costs."
            ).classes("yul-faint yul-small")

    def _legend(self) -> None:
        with glass_card().classes("yul-nwm-card yul-sp-legend").mark("sp-legend"):
            with ui.element("div").classes("yul-row"):
                ui.label("How it moves").classes("yul-nwm-title yul-grow")
                ui.label("click one to show only those").classes("yul-faint yul-small")
            with ui.element("div").classes("yul-sp-words"):
                for label in data.ORDER:
                    word = data.WORDS[label]
                    item = ui.element("div").classes("yul-sp-word").mark(f"word-{label}")
                    set_class(item, "on", label == self.label)
                    clickable(item, partial(self.toggle_label, label))
                    with item:
                        pill(word.text, word.kind)
                        ui.label(word.hint).classes("yul-muted yul-small")
            ui.label(
                "How much a category moves is its standard deviation over its average, from its "
                "first month of spending to its last (quiet months in between count as zero). A "
                "category needs six months in the range and three of its own for a word."
            ).classes("yul-faint yul-small")

    def _categories(self, flow: CashFlow) -> None:
        money = state().require_formatter().format_amount_milli
        trends = data.filtered(flow, self.group, self.label)
        filtering = self.group is not None or self.label is not None
        with glass_card().classes("yul-nwm-card").mark("sp-categories"):
            with ui.element("div").classes("yul-row"):
                ui.label("Categories").classes("yul-nwm-title yul-grow")
                ui.label("most spent first · click one to see its months").classes(
                    "yul-faint yul-small"
                )
            groups = {ALL_GROUPS: "All groups"} | {g.name: g.name for g in flow.groups()}
            pill_group(
                groups, self.group or ALL_GROUPS, self.set_group, marker="filter-group"
            ).mark("sp-group-filter")
            if self.label is not None:
                with ui.element("div").classes("yul-row").style("gap:8px;margin-top:8px"):
                    ui.label("Only").classes("yul-faint yul-small")
                    pill(data.WORDS[self.label].text, data.WORDS[self.label].kind)
                    button(
                        "Every kind",
                        kind="ghost",
                        small=True,
                        icon_name="x",
                        on_click=partial(self.toggle_label, self.label),
                    ).mark("sp-word-clear")
            with ui.element("div").classes("yul-sp-row head"):
                ui.label("Category")
                ui.label("A month").classes("yul-nwm-r")
                ui.label("Share").classes("yul-nwm-r")
                ui.label("Months")
                ui.label("How it moves")
            if not trends:
                ui.label("No category matches.").classes("yul-faint").mark("sp-no-match")
            shown = trends if self.all or filtering else trends[: data.SHOWN]
            for trend in shown:
                key = trend.category_id or "none"
                row = ui.element("div").classes("yul-sp-row click").mark(f"category-{key}")
                clickable(row, partial(self.open_category, trend))
                with row:
                    with ui.element("div").classes("yul-nwm-name"):
                        ui.label(trend.name)
                    ui.label(money(round(trend.mean))).classes("yul-num yul-nwm-r")
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
                            pill(word.text, word.kind).props["title"] = word.hint
                            cv = trend.volatility.cv or 0
                            ui.label(f"{cv:.2f}").classes("yul-faint yul-small yul-num")
                        else:
                            ui.label("not enough months").classes("yul-faint yul-small")
            if not filtering and not self.all and len(trends) > data.SHOWN:
                button(
                    f"Show all {len(trends)}", kind="ghost", small=True, on_click=self.show_all
                ).mark("sp-show-all")


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
