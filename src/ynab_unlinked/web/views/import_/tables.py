"""The tables of the Import view: a file's rows (new or already in YNAB) and its file badge."""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from ynab_unlinked.core.importing import ImportPlan
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import Transaction
from ynab_unlinked.web.components import pill
from ynab_unlinked.web.views.import_.data import file_color


def badge(suffix: str, *, small: bool = False) -> None:
    """The coloured tile with the file type ("XLSX"); `small` on the Review cards."""
    badge = ui.label((suffix or "?").upper()[:4]).classes("yul-imp-badge")
    badge.style(f"background:{file_color(suffix)}")
    if small:
        badge.classes(add="small")


def plan_table(plan: ImportPlan, formatter: Formatter) -> None:
    """Every row of the plan: "new", or dimmed when it is already in YNAB."""
    with ui.element("table").classes("yul-imp-table"):
        _header()
        for row in plan.rows:
            with ui.element("tr") as tr:
                _cells(row.transaction, formatter)
                with ui.element("td").classes("r"):
                    if row.already_imported:
                        ui.label("already in YNAB")
                    else:
                        pill("new", "ok")
            if row.already_imported:
                tr.classes(add="dim")
    if plan.rows:
        ui.label("Rows already in YNAB are matched by import id and are never sent twice.").classes(
            "yul-faint yul-small"
        ).style("margin-top:6px")


def transactions_table(transactions: Sequence[Transaction], formatter: Formatter) -> None:
    """The rows a file was read into, before YNAB was asked which are new."""
    with ui.element("table").classes("yul-imp-table"):
        _header()
        for transaction in transactions:
            with ui.element("tr"):
                _cells(transaction, formatter)
                with ui.element("td").classes("r"):
                    ui.label("…").classes("yul-faint")


def _header() -> None:
    with ui.element("tr"):
        for title, align in (("Date", ""), ("Payee", ""), ("Amount", "r"), ("Status", "r")):
            with ui.element("th").classes(align):
                ui.label(title)


def _cells(transaction: Transaction, formatter: Formatter) -> None:
    with ui.element("td").classes("num"):
        ui.label(formatter.format_date(transaction.date))
    with ui.element("td"):
        ui.label(transaction.payee)
    with ui.element("td").classes("r num"):
        ui.label(formatter.format_amount(transaction.amount))
