"""The Spending view: three tiles, spending by group with how it moves, steady or swingy, a
legend of the four words, and every category.

Averages cover the complete months of the range. A group (its row, or the dropdown above the
table) and a word of the legend filter the chart and the table; a filtered table lists every
category that passes. A dot of the chart or a row of the table shows the category in the
chart's place (`detail.category_detail`) until its back arrow or a new filter; a new range
updates it.
"""

from __future__ import annotations

import datetime as dt
from functools import partial

from nicegui import PageArguments, events, run, ui

from ynab_unlinked.core.cashflow import CashFlow, CategoryTrend
from ynab_unlinked.web import shell, theme
from ynab_unlinked.web.components import (
    button,
    clickable,
    empty_state,
    glass_card,
    info_button,
    pill,
    set_class,
    stat_tile,
)
from ynab_unlinked.web.components.cashflow_chart import SCATTER_HEIGHT, chart, volatility_options
from ynab_unlinked.web.components.controls import pill_group
from ynab_unlinked.web.finances import RANGES, period_title
from ynab_unlinked.web.ranges import save_range, saved_range
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.spending import data
from ynab_unlinked.web.views.spending.detail import category_detail
from ynab_unlinked.web.wording import VERSUS_YNAB, VERSUS_YNAB_TITLE

ALL_GROUPS = "__all__"


def _word_key(marker: str) -> None:
    """The colour of each word: the key of By group's mix bars and of the scatter's dots."""
    with ui.element("div").classes("yul-sp-key").mark(marker):
        for label in (*data.ORDER, data.UNRATED):
            with ui.element("span"):
                ui.element("i").classes(f"mix-{label}")
                word = data.WORDS.get(label)
                ui.label(word.text.split(" ", 1)[1] if word else "not enough months")


class SpendingView:
    def __init__(self, category: str | None = None) -> None:
        self.range = saved_range(data.DEFAULT_RANGE)
        self.all = False
        self.group: str | None = None
        self.label: str | None = None
        self.flow: CashFlow | None = None
        self.plotted: list[CategoryTrend] = []
        self.detail: str | None = category
        """The category shown in the chart's place, by id ("none" for uncategorized). A
        `?category=` link opens the page on one."""
        self.side: ui.element | None = None
        # What a filter changes, redrawn alone so the page keeps its height and its scroll
        self.group_rows: dict[str, ui.element] = {}
        self.word_items: dict[str, ui.element] = {}
        self.group_select: ui.select | None = None
        self.table: ui.element | None = None
        with ui.element("div").classes("yul-sp") as self.root:
            self.body = ui.element("div")
        shell.on_refresh(self.root, self.render)

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
        save_range(key)
        await self.render()

    def show_all(self) -> None:
        self.all = True
        self._draw_table()

    def set_group(self, key: str | None) -> None:
        group = None if key in (None, ALL_GROUPS) else key
        if group == self.group:
            return
        self.group = group
        self._filters_changed()

    def toggle_group(self, name: str) -> None:
        """A click on a group row: filter by it, or stop filtering when it already does."""
        self.set_group(None if self.group == name else name)

    def toggle_label(self, label: str) -> None:
        self.label = None if self.label == label else label
        self._filters_changed()

    def _filters_changed(self) -> None:
        """Mark the chosen group and word, and redraw the chart and the table; nothing else
        moves. A category in the chart's place gives it back: the click asked for the dots of
        the new filter."""
        for name, row in self.group_rows.items():
            on = name == self.group
            set_class(row, "on", on)
            row.props["title"] = "Show every group again" if on else f"Show only {name}"
        for label, item in self.word_items.items():
            set_class(item, "on", label == self.label)
        if self.group_select is not None and self.group_select.value != (self.group or ALL_GROUPS):
            self.group_select.value = self.group or ALL_GROUPS
        self.detail = None
        self._draw_side()
        self._draw_table()

    def open_category(self, trend: CategoryTrend, *, scroll: bool = False) -> None:
        self.detail = trend.category_id or "none"
        self._draw_side()
        if scroll and self.side is not None:
            ui.run_javascript(
                f"getHtmlElement({self.side.id})?.scrollIntoView({{behavior: 'smooth', block: 'center'}})"
            )

    def close_category(self) -> None:
        self.detail = None
        self._draw_side()

    def _shown(self) -> CategoryTrend | None:
        if self.flow is None or self.detail is None:
            return None
        return next(
            (t for t in self.flow.categories if (t.category_id or "none") == self.detail), None
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
                with ui.element("div").classes("yul-row yul-info-row yul-grow"):
                    ui.label(period_title(flow.start, flow.end)).classes("yul-h2")
                    info_button(VERSUS_YNAB_TITLE, VERSUS_YNAB, marker="sp-info")
                pill_group({key: key for key in RANGES}, self.range, self.set_range, marker="range")
            if not flow.categories:
                empty_state(
                    "Nothing was spent in this range. Pick a longer one.", icon_name="spending"
                ).mark("sp-empty")
                return
            if flow.running_only:
                ui.label(
                    "This month so far. What each category is comes from its history."
                ).classes("yul-muted yul-small yul-sp-so-far").mark("sp-so-far")
            self._tiles(flow)
            with ui.element("div").classes("yul-sp-split"):
                self._groups(flow)
                self.side = glass_card().classes("yul-nwm-card yul-sp-side")
            self._draw_side()
            self._legend()
            self._categories(flow)

    def _tiles(self, flow: CashFlow) -> None:
        money = state().require_formatter().format_amount_milli
        core = flow.core_spending()
        with ui.element("div").classes("yul-sp-tiles yul-stagger"):
            title = "Spent so far" if flow.running_only else "Spending a month"
            stat_tile(title, money(round(flow.mean_spending))).mark("sp-total")
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
            ui.label("By group").classes("yul-nwm-title")
            _word_key("sp-mix-key")
            with ui.element("div").classes("yul-sp-gbar head"):
                ui.label("Group")
                ui.label("")
                ui.label("A month").classes("yul-nwm-r")
                ui.label("Share").classes("yul-nwm-r")
            groups = flow.groups()
            widest = groups[0].mean if groups else 1
            self.group_rows = {}
            for group in groups:
                row = ui.element("div").classes("yul-sp-group").mark(f"group-{group.name}")
                self.group_rows[group.name] = row
                on = group.name == self.group
                set_class(row, "on", on)
                clickable(row, partial(self.toggle_group, group.name))
                row.props["title"] = "Show every group again" if on else f"Show only {group.name}"
                with row:
                    with ui.element("div").classes("yul-sp-gbar"):
                        ui.label(group.name).classes("yul-hbar-name")
                        with ui.element("div").classes("yul-hbar-track"):
                            ui.element("i").style(f"width:{group.mean / widest * 100:.1f}%")
                        ui.label(money(round(group.mean))).classes("yul-num yul-nwm-r")
                        ui.label(f"{group.share * 100:.0f}%").classes("yul-num yul-nwm-r yul-muted")
                    mix = data.group_mix(flow, group.name)
                    with ui.element("div").classes("yul-sp-mix").mark(f"mix-{group.name}"):
                        for part in mix:
                            segment = ui.element("i").classes(f"mix-{part.label}")
                            segment.style(f"width:{part.share * 100:.2f}%")
                            word = data.WORDS.get(part.label)
                            name = word.text if word else "not enough months"
                            segment.props["title"] = f"{name}: {part.share * 100:.0f}%"

    def _draw_side(self) -> None:
        """The steady or swingy chart, or the category it shows in its place."""
        flow, side = self.flow, self.side
        if flow is None or side is None or side.is_deleted:
            return
        config, _ = state().require()
        side.clear()
        with side:
            if (trend := self._shown()) is not None:
                category_detail(
                    trend,
                    flow,
                    palette=theme.palette(),
                    currency_format=config.budget.currency_format,
                    formatter=state().require_formatter(),
                    on_back=self.close_category,
                )
                return
            self.detail = None
            self._scatter(flow)

    def _scatter(self, flow: CashFlow) -> None:
        config, _ = state().require()
        shown = data.filtered(flow, self.group, self.label)
        self.plotted = data.plotted(shown)
        with ui.element("div"):
            with ui.element("div").classes("yul-row"):
                ui.label("Steady or swingy?").classes("yul-nwm-title yul-grow")
                ui.label("click a dot to see its months").classes("yul-faint yul-small")
            # The dots are in the colours of the words, as the bars of By group are
            _word_key("sp-dot-key")
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
            self.word_items = {}
            with ui.element("div").classes("yul-sp-words"):
                for label in data.ORDER:
                    word = data.WORDS[label]
                    item = ui.element("div").classes("yul-sp-word").mark(f"word-{label}")
                    self.word_items[label] = item
                    set_class(item, "on", label == self.label)
                    clickable(item, partial(self.toggle_label, label))
                    with item:
                        pill(word.text, word.kind)
                        ui.label(word.hint).classes("yul-muted yul-small")
            ui.label(
                "How much a category moves is its standard deviation over its average, from its "
                "first month of spending to its last (quiet months in between count as zero). "
                "The word comes from up to three years of history, whatever range is shown, so a "
                "yearly charge is lumpy even when you look at one month. A category needs six "
                "months of history and three of its own for a word."
            ).classes("yul-faint yul-small")

    def _categories(self, flow: CashFlow) -> None:
        with glass_card().classes("yul-nwm-card").mark("sp-categories"):
            with ui.element("div").classes("yul-row"):
                ui.label("Categories").classes("yul-nwm-title yul-grow")
                ui.label("most spent first · click one to see its months").classes(
                    "yul-faint yul-small"
                )
            groups = {ALL_GROUPS: "All groups"} | {g.name: g.name for g in flow.groups()}
            self.group_select = (
                ui.select(
                    groups,
                    value=self.group or ALL_GROUPS,
                    on_change=lambda e: self.set_group(e.value),
                )
                .props("outlined dense options-dense")
                .classes("yul-sp-filter")
                .mark("sp-group-filter")
            )
            self.table = ui.element("div")
        self._draw_table()

    def _draw_table(self) -> None:
        flow, table = self.flow, self.table
        if flow is None or table is None or table.is_deleted:
            return
        money = state().require_formatter().format_amount_milli
        trends = data.filtered(flow, self.group, self.label)
        filtering = self.group is not None or self.label is not None
        table.clear()
        with table:
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
                clickable(row, partial(self.open_category, trend, scroll=True))
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
async def spending_view(args: PageArguments) -> None:
    await SpendingView(args.query_parameters.get("category")).render()
