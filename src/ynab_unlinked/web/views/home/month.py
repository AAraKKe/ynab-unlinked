"""Home's side cards about the running month: the pulse and where the money went."""

from __future__ import annotations

from functools import partial
from urllib.parse import urlencode

from nicegui import ui

from ynab_unlinked.web import shell
from ynab_unlinked.web.components import clickable, glass_card, icon
from ynab_unlinked.web.state import state
from ynab_unlinked.web.views.home.pulse import (
    MonthPulse,
    pace_line,
    rate_text,
    runway_text,
)


def card_head(title: str, link: str | None = None, path: str | None = None) -> None:
    """A card's title, with a quiet link to the page that has the rest on the right."""
    with ui.element("div").classes("yul-card-head"):
        ui.label(title).classes("yul-card-title")
        if link is not None and path is not None:
            with ui.element("a").classes("yul-card-link") as go:
                ui.label(link)
                icon("arrow-right", 14)
            clickable(go, lambda: ui.navigate.to(path), role="link")


def _figure(label: str, value: str) -> None:
    with ui.element("div").classes("yul-month-fig"):
        ui.label(label).classes("yul-muted yul-small")
        ui.label(value).classes("yul-month-k yul-num")


def month_card(pulse: MonthPulse) -> None:
    """Income, spending and what is left of the month so far, against a usual month."""
    money = state().require_formatter().format_amount_milli
    with glass_card().classes("yul-month").mark("month-pulse"):
        with ui.element("div").classes("yul-card-head"):
            ui.label(f"{pulse.month:%B}").classes("yul-card-title")
            ui.label(f"day {pulse.day} of {pulse.days}").classes("yul-faint yul-small")
        with ui.element("div").classes("yul-month-figs"):
            _figure("Income", money(pulse.income))
            _figure("Spending", money(pulse.spending))
            # No green or red: before payday a month is behind without anything being wrong
            saved = pulse.saved
            _figure("Net so far", ("+" if saved > 0 else "") + money(saved))
        share = pulse.spent_share
        if share is not None:
            with ui.element("div").classes("yul-pace") as bar:
                fill = ui.element("i").style(f"width:{min(share, 1) * 100:.1f}%")
                if share > 1:
                    fill.classes(add="over")
                ui.element("b").style(f"left:{pulse.elapsed * 100:.1f}%")
            bar.props["title"] = (
                f"A usual month spends {money(round(pulse.usual_spending))}. "
                "The mark is how far into the month today is."
            )
        ui.label(pace_line(pulse)).classes("yul-muted yul-small").mark("month-pace")
        with ui.element("div").classes("yul-month-foot") as foot:
            with ui.element("div"):
                ui.label("Savings rate").classes("yul-faint yul-small")
                ui.label(rate_text(pulse.savings_rate)).classes("yul-month-s yul-num").mark(
                    "month-rate"
                )
            with ui.element("div"):
                ui.label("Cash runway").classes("yul-faint yul-small")
                ui.label(runway_text(pulse.runway)).classes("yul-month-s yul-num").mark(
                    "month-runway"
                )
            with ui.element("span").classes("yul-card-link"):
                ui.label("Cash flow")
                icon("arrow-right", 14)
        foot.props["title"] = f"Over the last {pulse.months} complete months"
        clickable(foot, lambda: ui.navigate.to(shell.CASHFLOW_PATH), role="link")


def top_card(pulse: MonthPulse) -> None:
    """The categories that took most this month, each against its usual month."""
    money = state().require_formatter().format_amount_milli
    widest = max(max(item.spent, item.usual) for item in pulse.top)
    with glass_card().mark("month-top"):
        card_head("Where it went", "Spending", shell.SPENDING_PATH)
        for item in pulse.top:
            with ui.element("div").classes("yul-hbar yul-top-row") as row:
                ui.label(item.name).classes("yul-hbar-name")
                with ui.element("div").classes("yul-hbar-track"):
                    ui.element("i").style(f"width:{item.spent / widest * 100:.1f}%")
                    if item.usual > 0:
                        ui.element("b").style(f"left:{item.usual / widest * 100:.1f}%")
                ui.label(money(item.spent)).classes("yul-num yul-hbar-v")
            if item.usual > 0:
                row.props["title"] = f"Usually {money(round(item.usual))} a month"
            if item.category_id is not None:
                path = f"{shell.SPENDING_PATH}?{urlencode({'category': item.category_id})}"
                clickable(row, partial(ui.navigate.to, path), role="link").mark(
                    f"month-top-{item.category_id}"
                )
        ui.label("The mark is its usual month.").classes("yul-faint yul-small yul-top-note")
