"""The account drawer of Net worth: one account's balance over the range and its last rows.

A `ui.dialog` on the right, full height (a `ui.drawer` cannot live inside `ui.sub_pages`).
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from ynab_unlinked.config.models.v2 import CurrencyFormat
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.store import StoredTransaction
from ynab_unlinked.web.components import button
from ynab_unlinked.web.components.history_chart import ChartSeries, history_chart
from ynab_unlinked.web.theme import Palette


def account_drawer(
    *,
    name: str,
    caption: str,
    balance: str,
    since: str,
    series: Sequence[ChartSeries],
    palette: Palette,
    currency_format: CurrencyFormat,
    formatter: Formatter,
    transactions: Sequence[StoredTransaction],
) -> ui.echart:
    """Open the drawer in the current context; it deletes itself once closed.

    Returns its chart, which the view restyles when the theme changes.
    """
    with (
        ui.dialog().props("position=right full-height") as dialog,
        ui.element("div").classes("yul-card yul-nw-drawer").mark("nw-drawer"),
    ):
        with ui.element("div").classes("yul-row"):
            with ui.element("div").classes("yul-grow"):
                ui.label(name).classes("yul-h2")
                ui.label(caption).classes("yul-faint yul-small")
            close = button(icon_name="x", kind="ghost", on_click=dialog.close)
            close.props["title"] = "Close"
        ui.label(balance).classes("yul-nw-drawer-figure yul-num")
        ui.label(since).classes("yul-faint yul-small")
        chart = (
            history_chart(series, palette, currency_format, height=220)
            .classes("yul-nw-chart")
            .mark("drawer-chart")
        )
        ui.label("Last transactions").classes("yul-section")
        if not transactions:
            ui.label("No transactions in the local copy yet.").classes("yul-faint")
        with ui.element("div").classes("yul-nw-tx-list"):
            for transaction in transactions:
                _transaction_row(formatter, transaction)
    dialog.on_value_change(lambda e: None if e.value else dialog.delete())
    dialog.open()
    return chart


def _transaction_row(formatter: Formatter, transaction: StoredTransaction) -> None:
    with ui.element("div").classes("yul-nw-tx").mark("drawer-tx"):
        ui.label(f"{transaction.date.day} {transaction.date:%b %y}").classes("yul-faint yul-num")
        with ui.element("div").classes("yul-grow"):
            ui.label(transaction.payee_name or "—")
            if transaction.memo:
                ui.label(transaction.memo).classes("yul-faint yul-small yul-nw-memo")
        amount = ui.label(formatter.format_amount_milli(transaction.amount))
        amount.classes("yul-num yul-nw-tx-amount")


__all__ = ["account_drawer"]
