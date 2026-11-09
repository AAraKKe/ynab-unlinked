"""The panel under the Months chart: where the change of the selected month, or of the whole
range when no month is selected, came from.

A sentence, the bridge from income to the net change, the accounts that moved most and why,
and where the money came in from and went to.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any

from nicegui import ui

from ynab_unlinked.core.finance import Period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import button, closed_pill
from ynab_unlinked.web.views.networth import flows as words
from ynab_unlinked.web.views.networth.data import signed

_TONES = {"income": "yul-good", "spending": "yul-bad"}


def _tone(amount: int) -> str:
    return "yul-good" if amount > 0 else "yul-bad" if amount < 0 else ""


def period_panel(
    period: Period,
    names: dict[str, str],
    closed: Collection[str],
    formatter: Formatter,
    *,
    selected: bool,
    on_clear: Callable[[], Any],
) -> None:
    """Draw the panel in the current context. `closed`: the accounts closed in YNAB, tagged.
    `selected`: it shows one month, with a button back to the whole range."""
    flows = period.flows
    with ui.element("div").classes("yul-card yul-nwp-panel").mark("period-panel"):
        with ui.element("div").classes("yul-row yul-nwp-head"):
            with ui.element("div").classes("yul-grow"):
                ui.label(words.period_title(period.start, period.end)).classes(
                    "yul-nwm-title"
                ).mark("period-title")
                ui.label(
                    f"{formatter.format_amount_milli(period.start_worth)} → "
                    f"{formatter.format_amount_milli(period.end_worth)}"
                ).classes("yul-faint yul-small")
            if selected:
                button(
                    "Whole range", kind="ghost", small=True, icon_name="x", on_click=on_clear
                ).mark("period-clear")
            ui.label(signed(formatter, flows.change)).classes(
                f"yul-nwp-figure yul-num {_tone(flows.change)}"
            )
        ui.label(words.headline(flows, formatter)).classes("yul-muted").mark("period-headline")

        with ui.element("div").classes("yul-nwp-cols"):
            with ui.element("div"):
                ui.label("Where the change came from").classes("yul-section")
                _bridge(period, formatter)
                ui.label("Accounts that moved most").classes("yul-section")
                moves = words.moved(period)
                if not moves:
                    ui.label("No account moved.").classes("yul-faint")
                for move in moves:
                    with ui.element("div").classes("yul-nwp-move").mark(f"moved-{move.account_id}"):
                        with ui.element("div").classes("yul-grow"):
                            with ui.element("div").classes("yul-nwm-name"):
                                ui.label(names.get(move.account_id, "Account"))
                                if move.account_id in closed:
                                    closed_pill()
                            ui.label(words.why(move, formatter)).classes("yul-faint yul-small")
                        ui.label(signed(formatter, move.change)).classes(
                            f"yul-num {_tone(move.change)}"
                        )
            with ui.element("div"):
                _amounts(
                    "Came in from",
                    [(income.name, income.amount) for income in period.income],
                    formatter,
                    marker="came-in",
                )
                _amounts(
                    "Spent most on",
                    [(spend.name, spend.amount) for spend in period.spending],
                    formatter,
                    marker="spent-on",
                )


def _amounts(title: str, rows: list[tuple[str, int]], formatter: Formatter, *, marker: str) -> None:
    ui.label(title).classes("yul-section")
    if not rows:
        ui.label("Nothing in this period.").classes("yul-faint yul-small")
    with ui.element("div").mark(marker):
        for name, amount in rows[: words.TOP_CATEGORIES]:
            with ui.element("div").classes("yul-nwp-move"):
                ui.label(name).classes("yul-grow")
                ui.label(formatter.format_amount_milli(amount)).classes("yul-num")


def _bridge(period: Period, formatter: Formatter) -> None:
    """Floating bars from zero: each step starts where the one before it ended."""
    steps = words.bridge(period.flows)
    running, ends = 0, [0]
    for step in steps[:-1]:
        running += step.amount
        ends.append(running)
    low, high = min(*ends, 0), max(*ends, 0)
    span = (high - low) or 1

    def left(value: int) -> float:
        return (value - low) / span * 100

    with ui.element("div").classes("yul-nwp-bridge").mark("bridge"):
        running = 0
        for step in steps:
            start, end = (
                (0, step.amount) if step.kind == "net" else (running, running + step.amount)
            )
            if step.kind != "net":
                running = end
            ui.label(step.label).classes("yul-nwp-step" + (" net" if step.kind == "net" else ""))
            with ui.element("div").classes("yul-nwp-track"):
                width = max(abs(end - start) / span * 100, 0.8)
                ui.element("i").classes(f"yul-nwp-bar {step.kind}").style(
                    f"left:{left(min(start, end)):.2f}%;width:{width:.2f}%"
                )
            ui.label(signed(formatter, step.amount)).classes(
                "yul-num yul-small " + _TONES.get(step.kind, "")
            ).mark(f"step-{step.kind}")
