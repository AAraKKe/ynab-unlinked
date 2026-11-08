"""The tables of the Import view: a file's rows with their status and its file badge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from nicegui import ui

from ynab_unlinked.core.importing import ImportPlan, ImportRow, RowStatus
from ynab_unlinked.formatter import Formatter
from ynab_unlinked.models import Transaction
from ynab_unlinked.web.components import button, pill, set_class
from ynab_unlinked.web.views.import_.data import (
    LEFT_OUT_NOTE,
    file_color,
    unknown_matches_note,
)


def badge(suffix: str, *, small: bool = False) -> None:
    """The coloured tile with the file type ("XLSX"); `small` on the Review cards."""
    badge = ui.label((suffix or "?").upper()[:4]).classes("yul-imp-badge")
    badge.style(f"background:{file_color(suffix)}")
    if small:
        badge.classes(add="small")


@dataclass(frozen=True)
class RowActions:
    """What the Review step does when a row is left out or included; the Files step has none."""

    leave_out: Callable[[ImportRow], Awaitable[None]]
    include: Callable[[ImportRow], Awaitable[None]]


def plan_table(
    plan: ImportPlan, formatter: Formatter, key: int, actions: RowActions | None = None
) -> None:
    """Every row of the file `key` with its status; with `actions`, the control to change it.

    New rows are tagged, rows already in YNAB (by import id or through a match) dimmed and
    rows left out crossed out.
    """
    with ui.element("table").classes("yul-imp-table"):
        _header(actions is not None)
        for index, row in enumerate(plan.rows):
            status = row.status
            with ui.element("tr") as tr:
                _cells(row.transaction, formatter)
                with ui.element("td").classes("r"):
                    _status(status).mark(f"row-status-{key}-{index}")
                if actions is not None:
                    with ui.element("td").classes("r"):
                        _action(actions, row, status, f"{key}-{index}")
            set_class(tr, "dim", row.already_imported)
            set_class(tr, "out", status is RowStatus.EXCLUDED)
    if not plan.rows:
        return
    notes = ["Rows already in YNAB are matched by import id and are never sent twice."]
    if plan.with_status(RowStatus.MATCHED):
        notes.append(
            "Matched rows were matched in YNAB with a transaction you entered by hand: they are "
            "there too."
        )
    if (unknown := unknown_matches_note(plan)) is not None:
        notes.append(unknown)
    if actions is not None:
        notes.append(LEFT_OUT_NOTE)
    with ui.element("div").classes("yul-imp-notes"):
        for note in notes:
            ui.label(note).classes("yul-faint yul-small")


def _status(status: RowStatus) -> ui.label:
    match status:
        case RowStatus.NEW:
            return pill("new", "ok")
        case RowStatus.IN_YNAB:
            return ui.label("already in YNAB")
        case RowStatus.MATCHED:
            return ui.label("matched in YNAB")
        case RowStatus.EXCLUDED:
            return ui.label("left out")


def _action(actions: RowActions, row: ImportRow, status: RowStatus, marker: str) -> None:
    match status:
        case RowStatus.NEW:
            button(
                "Leave out", kind="ghost", small=True, on_click=lambda: actions.leave_out(row)
            ).mark(f"leave-out-{marker}")
        case RowStatus.EXCLUDED:
            button(
                "Include again", kind="ghost", small=True, on_click=lambda: actions.include(row)
            ).mark(f"include-{marker}")
        case RowStatus.IN_YNAB | RowStatus.MATCHED:
            pass


def transactions_table(transactions: Sequence[Transaction], formatter: Formatter) -> None:
    """The rows a file was read into, before YNAB was asked which are new."""
    with ui.element("table").classes("yul-imp-table"):
        _header()
        for transaction in transactions:
            with ui.element("tr"):
                _cells(transaction, formatter)
                with ui.element("td").classes("r"):
                    ui.label("…").classes("yul-faint")


def _header(actions: bool = False) -> None:
    with ui.element("tr"):
        for title, align in (("Date", ""), ("Payee", ""), ("Amount", "r"), ("Status", "r")):
            with ui.element("th").classes(align):
                ui.label(title)
        if actions:
            ui.element("th")


def _cells(transaction: Transaction, formatter: Formatter) -> None:
    with ui.element("td").classes("num"):
        ui.label(formatter.format_date(transaction.date))
    with ui.element("td"):
        ui.label(transaction.payee)
    with ui.element("td").classes("r num"):
        ui.label(formatter.format_amount(transaction.amount))
