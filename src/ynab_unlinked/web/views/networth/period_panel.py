"""The panel under the Months chart: where the change of the selected month, or of the whole
range when no month is selected, came from.

The waterfall from income to the net change is the panel's menu: Income, Spending or Growth,
picked on a bar or on the row of buttons under it, fills the area below with its breakdown on
the left (every payee, category or account) and the transactions behind it on the right,
newest first. A row of the breakdown narrows the transactions to it. The range and its change
are in the tiles above, so only a picked month is named, next to the way back.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from nicegui import ui

from ynab_unlinked.core.finance import Breakdown, Period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import amount, button, clickable, explain_button, set_class
from ynab_unlinked.web.components import share_bar as draw_share_bar
from ynab_unlinked.web.components.flow_chart import bridge_chart, bridge_options, step_colour
from ynab_unlinked.web.components.history_chart import set_options
from ynab_unlinked.web.state import state
from ynab_unlinked.web.theme import Palette
from ynab_unlinked.web.views.networth import flows as words
from ynab_unlinked.web.views.networth import terms
from ynab_unlinked.web.views.networth.data import signed
from ynab_unlinked.web.views.networth.terms_story import show_terms
from ynab_unlinked.web.wording import short_date

_TONES = {"income": "yul-good", "spending": "yul-bad"}
ONE_COLUMN = 860
"""The width under which the breakdown and its transactions are one column (`yul.css`)."""


class PeriodPanel:
    """The panel of one period. The term picked outlives it (the caller keeps it across months);
    the row narrowing the transactions and how many are shown do not."""

    def __init__(
        self,
        period: Period,
        names: dict[str, str],
        formatter: Formatter,
        palette: Palette,
        *,
        term: str,
        on_term: Callable[[str], Any],
        selected: bool,
        on_clear: Callable[[], Any],
    ) -> None:
        self.period, self.names, self.formatter, self.palette = period, names, formatter, palette
        self.term = term if term in words.TERMS else words.DEFAULT_TERM
        self.on_term, self.selected, self.on_clear = on_term, selected, on_clear
        self.key: str | None = None
        self.shown = words.PAGE
        self.moves = {move.account_id: move for move in period.accounts}
        self.chart: ui.echart | None = None
        self.term_buttons: dict[str, ui.element] = {}
        self.below: ui.element | None = None
        self.list_box: ui.element | None = None

    def draw(self) -> None:
        """Draw the panel in the current context."""
        with ui.element("div").classes("yul-card yul-nwp-panel").mark("period-panel"):
            # The tiles and the chart already say the range and its change: only a month
            # picked needs naming, with the way back to the whole range
            with ui.element("div").classes("yul-row yul-nwp-head"):
                with ui.element("div").classes("yul-row yul-info-row yul-grow"):
                    ui.label("Where the change came from").classes("yul-section")
                    explain_button(terms.TERMS_TITLE, self.explain, marker="terms-info")
                if self.selected:
                    ui.label(words.period_title(self.period.start, self.period.end)).classes(
                        "yul-small"
                    ).mark("period-title")
                    button(
                        "Whole range",
                        kind="ghost",
                        small=True,
                        icon_name="x",
                        on_click=self.on_clear,
                    ).mark("period-clear")
            self._bridge()
            with ui.element("div").classes("yul-nwp-terms").mark("terms") as group:
                group.props["role"] = "group"
                group.props["aria-label"] = "What the panel lists"
                for kind, label in words.TERMS.items():
                    with ui.element("button").classes("yul-nwp-term") as pick:
                        ui.element("span").classes("yul-swatch").style(
                            f"background:{step_colour(kind, self.palette)}"
                        )
                        ui.label(label)
                    pick.props["type"] = "button"
                    pick.on("click", lambda _, kind=kind: self.pick(kind))
                    pick.mark(f"term-{kind}")
                    self.term_buttons[kind] = pick
            self.below = ui.element("div").classes("yul-nwp-below")
        self._mark_term()
        self._draw_below()

    async def explain(self) -> None:
        config, _ = state().require()
        await show_terms(self.formatter, config.budget.currency_format)

    def _bridge(self) -> None:
        """The waterfall, and its values as text for screen readers."""
        config, _ = state().require()
        steps = words.bridge(self.period.flows)
        values = [signed(self.formatter, step.amount) for step in steps]
        self.chart = bridge_chart(
            [(step.label, step.amount, step.kind) for step in steps],
            values,
            self.palette,
            config.budget.currency_format,
            selected=self.term,
            on_pick=self.pick,
        ).mark("bridge")
        with ui.element("div").classes("yul-nwp-steps"):
            for step, value in zip(steps, values, strict=True):
                with ui.element("span").classes(
                    "yul-nwp-step" + (" net" if step.kind == "net" else "")
                ):
                    ui.label(step.label)
                    ui.label(value).classes("yul-num " + _TONES.get(step.kind, "")).mark(
                        f"step-{step.kind}"
                    )

    def pick(self, kind: str) -> None:
        """Show another term's breakdown, all its transactions."""
        if kind not in words.TERMS or kind == self.term:
            return
        self.term, self.key, self.shown = kind, None, words.PAGE
        self.on_term(kind)
        self._mark_term()
        if self.chart is not None and not self.chart.is_deleted:
            config, _ = state().require()
            steps = words.bridge(self.period.flows)
            set_options(
                self.chart,
                bridge_options(
                    [(step.label, step.amount, step.kind) for step in steps],
                    [signed(self.formatter, step.amount) for step in steps],
                    self.palette,
                    config.budget.currency_format,
                    self.term,
                ),
            )
        self._draw_below()

    def _mark_term(self) -> None:
        for kind, element in self.term_buttons.items():
            set_class(element, "on", kind == self.term)
            element.props["aria-pressed"] = "true" if kind == self.term else "false"
            element.update()

    def narrow(self, key: str | None) -> None:
        """Show the transactions of one row, or of all of them again. In one column they are
        under every row, so the page goes down to them."""
        self.key = None if key == self.key else key
        self.shown = words.PAGE
        self._draw_below()
        if self.key is not None and self.list_box is not None:
            ui.run_javascript(
                f"if (innerWidth <= {ONE_COLUMN}) getHtmlElement({self.list_box.id})"
                "?.scrollIntoView({block: 'start', behavior:"
                " matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'})"
            )

    def more(self) -> None:
        breakdown = self.period.breakdown(self.term)
        self.shown += words.more_count(self.shown, len(breakdown.entries_of(self.key)))
        self._draw_list(breakdown)

    def _draw_below(self) -> None:
        if self.below is None or self.below.is_deleted:
            return
        breakdown = self.period.breakdown(self.term)
        self.below.clear()
        with self.below:
            if not breakdown.groups:
                ui.label(words.empty_text(self.term)).classes("yul-faint yul-small").mark(
                    "breakdown-empty"
                )
                return
            with ui.element("div").classes("yul-nwp-cols"):
                with ui.element("div").mark("breakdown"):
                    with ui.element("div").classes("yul-nwp-colhead"):
                        ui.label(words.BY[self.term]).classes("yul-grow")
                        ui.label(signed(self.formatter, breakdown.total)).classes(
                            "yul-num yul-nwp-total"
                        ).mark("breakdown-total")
                    self._draw_rows(breakdown)
                self.list_box = ui.element("div").mark("transactions")
        self._draw_list(breakdown)

    def _draw_rows(self, breakdown: Breakdown) -> None:
        colour = step_colour(self.term, self.palette)
        for index, group in enumerate(breakdown.groups):
            with ui.element("div").classes("yul-nwp-row") as row:
                with ui.element("div").classes("yul-row yul-nwp-row-top"):
                    with ui.element("div").classes("yul-grow yul-nwp-name"):
                        ui.label(words.row_name(self.term, group, self.names))
                        subtitle = words.row_subtitle(
                            self.term, group, self.names, self.moves, self.period.days
                        )
                        if subtitle:
                            ui.label(subtitle).classes("yul-faint yul-small")
                    ui.label(signed(self.formatter, group.amount)).classes("yul-num")
                draw_share_bar(words.share(group, breakdown), colour)
                ui.label(words.row_caption(self.term, group, breakdown)).classes(
                    "yul-faint yul-small"
                )
            set_class(row, "on", group.key == self.key)
            row.props["aria-pressed"] = "true" if group.key == self.key else "false"
            clickable(row, lambda _, key=group.key: self.narrow(key))
            row.mark(f"breakdown-row-{index}")

    def _draw_list(self, breakdown: Breakdown) -> None:
        box = self.list_box
        if box is None or box.is_deleted:
            return
        entries = breakdown.entries_of(self.key)
        today = dt.date.today()
        box.clear()
        with box:
            with ui.element("div").classes("yul-nwp-colhead"):
                ui.label(words.list_head(self.term, breakdown, self.key)).mark("tx-head")
                if self.key is not None:
                    group = next(g for g in breakdown.groups if g.key == self.key)
                    ui.label(f"· {words.row_name(self.term, group, self.names)}").classes(
                        "yul-grow yul-nwp-narrowed"
                    )
                    all_link = ui.element("button").classes("yul-link").mark("tx-all")
                    all_link.props["type"] = "button"
                    with all_link:
                        ui.label("all")
                    all_link.on("click", lambda: self.narrow(None))
            for entry in entries[: self.shown]:
                with ui.element("div").classes("yul-nwp-tx").mark("tx-row"):
                    ui.label(short_date(entry.date, today)).classes("yul-faint yul-small")
                    with ui.element("div").classes("yul-nwp-tx-who"):
                        ui.label(entry.payee)
                        ui.label(self.names.get(entry.account_id, "Account")).classes(
                            "yul-faint yul-small"
                        )
                    amount(entry.amount / 1000, self.formatter)
            if left := words.more_count(self.shown, len(entries)):
                button(f"Show {left} more", kind="ghost", small=True, on_click=self.more).mark(
                    "tx-more"
                )
