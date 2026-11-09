"""The period drawer of Net worth: where the change of one month, or of the whole range, came from.

The same right side dialog as the account drawer: a sentence, the bridge from income to the net
change, the accounts that moved most and why, and the categories that spent most.
"""

from __future__ import annotations

from nicegui import ui

from ynab_unlinked.core.finance import Period
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.web.components import button
from ynab_unlinked.web.views.networth import flows as words
from ynab_unlinked.web.views.networth.data import signed

_TONES = {"income": "yul-good", "spending": "yul-bad"}


def period_drawer(period: Period, names: dict[str, str], formatter: Formatter) -> None:
    """Open the drawer in the current context; it deletes itself once closed.

    `names` gives each counted account its name.
    """
    flows = period.flows
    with (
        ui.dialog().props("position=right full-height") as dialog,
        ui.element("div").classes("yul-card yul-nw-drawer").mark("period-drawer"),
    ):
        with ui.element("div").classes("yul-row"):
            with ui.element("div").classes("yul-grow"):
                ui.label(words.period_title(period.start, period.end)).classes("yul-h2")
                ui.label(
                    f"{formatter.format_amount_milli(period.start_worth)} → "
                    f"{formatter.format_amount_milli(period.end_worth)}"
                ).classes("yul-faint yul-small")
            close = button(icon_name="x", kind="ghost", on_click=dialog.close)
            close.props["title"] = "Close"
        change = ui.label(signed(formatter, flows.change)).classes("yul-nw-drawer-figure yul-num")
        change.classes("yul-good" if flows.change > 0 else "yul-bad" if flows.change < 0 else "")
        ui.label(words.headline(flows, formatter)).classes("yul-muted").mark("period-headline")

        ui.label("Where the change came from").classes("yul-section")
        _bridge(period, formatter)

        moves = words.moved(period)
        ui.label("Accounts that moved most").classes("yul-section")
        if not moves:
            ui.label("No account moved.").classes("yul-faint")
        with ui.element("div").classes("yul-nw-tx-list"):
            for move in moves:
                with ui.element("div").classes("yul-nwp-move").mark(f"moved-{move.account_id}"):
                    with ui.element("div").classes("yul-grow"):
                        ui.label(names.get(move.account_id, "Account"))
                        ui.label(words.why(move, formatter)).classes("yul-faint yul-small")
                    amount = ui.label(signed(formatter, move.change)).classes("yul-num")
                    amount.classes(
                        "yul-good" if move.change > 0 else "yul-bad" if move.change < 0 else ""
                    )

        spent = period.spending[: words.TOP_CATEGORIES]
        if spent:
            ui.label("Spent most on").classes("yul-section")
            with ui.element("div").classes("yul-nw-tx-list"):
                for spend in spent:
                    with ui.element("div").classes("yul-nwp-move"):
                        ui.label(spend.name).classes("yul-grow")
                        ui.label(formatter.format_amount_milli(spend.amount)).classes("yul-num")
    dialog.on_value_change(lambda e: None if e.value else dialog.delete())
    dialog.open()


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
                ui.element("i").classes(f"yul-nwp-bar {step.kind}").style(
                    f"left:{left(min(start, end)):.2f}%;width:{max(abs(end - start) / span * 100, 0.8):.2f}%"
                )
            ui.label(signed(formatter, step.amount)).classes(
                "yul-num yul-small " + _TONES.get(step.kind, "")
            ).mark(f"step-{step.kind}")
